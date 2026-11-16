"""Trader DNA and rulebook remix: a scouting report built from the user's closed paper trades.

DNA: six behaviour scores from 0 to 100, each a plain share or ratio of the user's own trades:
- Stops: trades that had a stop and kept it where it was planned.
- Sizing: trades that risked no more than the profile's limit.
- Consistency: how steady the risk per trade was (100 when every trade risked the same share).
- Composure: trades after a loss that were neither a revenge trade nor oversized.
- Payoff: average win against average loss (100 at 2 to 1 or better).
- News care: trades not opened next to a high-impact release.

Rulebook remix: the same trades replayed against every challenge plan. Each trade's result is taken as a share
of the equity it was taken with, trades are grouped into the trading days they were opened on (17:00 New York
roll). The days are run once in their real order, then 1,000 times as HORIZON new days drawn at random from
the user's own days (with repeats), as if they kept trading the same way. A run passes phase 1 when the
balance reaches the target after the minimum number of days, and fails when one day's closed losses pass the
daily limit or the balance falls below the overall floor. Losses inside open trades are not seen, so real
challenges are somewhat harder than these odds.

Nothing here predicts prices or promises a result."""

import random
from statistics import mean, pstdev

from fastapi import APIRouter, Depends

from . import db
from .auth import UserOut, current_user
from .coach import _limit, tag_trades
from .prop import PLANS
from .report import trading_date

router = APIRouter(prefix="/prop", tags=["prop"])

MIN_TRADES = 5
RUNS = 1000
PATHS = 40          # sample paths returned for the fan chart
HORIZON = 60        # trading days in each simulated run


def _pct(n: float, d: float) -> float:
    return round(100 * n / d, 1) if d else 0.0


def scores(trades: list[dict], limit_pct: float) -> list[dict]:
    """Six behaviour scores, worst habits low. `trades` come from coach.tag_trades, oldest first."""
    n = len(trades)
    stops = sum(1 for t in trades if not {"no_stop", "stop_widened"} & set(t["tags"]))
    sized = sum(1 for t in trades if "oversized" not in t["tags"] and "no_stop" not in t["tags"])
    risks = [t["risk_pct"] for t in trades if t["risk_pct"]]
    consistency = 100 * max(0.0, 1 - pstdev(risks) / mean(risks)) if len(risks) >= 2 and mean(risks) > 0 else 0.0
    by_close = sorted(trades, key=lambda t: t["closed_at"])
    after_loss = []
    for t in trades:
        before = [q for q in by_close if q["closed_at"] <= t["opened_at"] and q is not t]
        if before and before[-1]["pnl"] < 0:
            after_loss.append(t)
    calm = sum(1 for t in after_loss if not {"revenge", "oversized"} & set(t["tags"]))
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [-t["pnl"] for t in trades if t["pnl"] < 0]
    ratio = (mean(wins) / mean(losses)) if wins and losses else (2.0 if wins else 0.0)
    news = sum(1 for t in trades if "red_folder" not in t["tags"])
    out = [
        ("stops", "Stops", _pct(stops, n), f"{stops} of {n} trades had a stop that stayed where it was planned."),
        ("sizing", "Sizing", _pct(sized, n), f"{sized} of {n} trades risked no more than your {limit_pct:g}% limit."),
        ("consistency", "Consistency", round(consistency, 1),
         "How steady your risk per trade was." if risks else "No trades with a stop, so risk can't be measured."),
        ("composure", "Composure", _pct(calm, len(after_loss)) if after_loss else 100.0,
         f"{calm} of {len(after_loss)} trades after a loss were calm: no revenge trade, no bigger size."
         if after_loss else "No losing trade has been followed by another yet."),
        ("payoff", "Payoff", round(min(ratio / 2, 1) * 100, 1), f"An average win is {ratio:.2f} times an average loss."),
        ("news", "News care", _pct(news, n), f"{news} of {n} trades were not opened next to a high-impact release."),
    ]
    return [{"key": k, "label": label, "score": s, "text": text} for k, label, s, text in out]


def day_returns(trades: list[dict], start_balance: float) -> list[list[float]]:
    """Each trading day as the list of its trades' results, as a share of the equity each was taken with."""
    equity = start_balance
    days: dict = {}
    for t in sorted(trades, key=lambda x: x["closed_at"]):
        r = t["pnl"] / equity if equity > 0 else 0.0
        equity += t["pnl"]
        days.setdefault(trading_date(int(t["opened_at"].timestamp())), []).append(r)
    return [days[k] for k in sorted(days)]


def run(days: list[list[float]], rules: dict) -> tuple[str, int, list[float]]:
    """One pass through the days: ('pass' | 'daily' | 'overall' | 'open', days used, balance after each day)."""
    target = 100 * (1 + rules["targets"][0] / 100)
    floor = 100 * (1 - rules["max_loss_pct"] / 100)
    daily = 100 * rules["daily_loss_pct"] / 100
    bal, path = 100.0, [100.0]
    for i, day in enumerate(days):
        start = bal
        for r in day:
            bal *= 1 + r
            if start - bal > daily:
                path.append(bal)
                return "daily", i + 1, path
            if bal < floor:
                path.append(bal)
                return "overall", i + 1, path
        path.append(bal)
        if bal >= target and i + 1 >= rules["min_days"]:
            return "pass", i + 1, path
    return "open", len(days), path


def remix(days: list[list[float]], rules: dict, runs: int = RUNS, seed: int = 7) -> dict:
    actual, used, path = run(days, rules)
    rnd = random.Random(seed)
    counts = {"pass": 0, "daily": 0, "overall": 0, "open": 0}
    paths = []
    for k in range(runs):
        res, _, p = run([rnd.choice(days) for _ in range(HORIZON)], rules)
        counts[res] += 1
        if k < PATHS:
            paths.append({"result": res, "path": [round(x, 2) for x in p]})
    return {"actual": actual, "actual_days": used, "actual_path": [round(x, 2) for x in path],
            "odds": {k: _pct(v, runs) for k, v in counts.items()}, "paths": paths}


def dna(user_id: int) -> dict:
    with db.conn() as c:
        trades = tag_trades(c, user_id)
        acct = c.execute("SELECT starting_balance FROM paper_accounts WHERE user_id = %s", (user_id,)).fetchone()
    limit = _limit(user_id)
    if len(trades) < MIN_TRADES:
        return {"ready": False, "trades": len(trades), "needed": MIN_TRADES, "scores": [], "plans": []}
    days = day_returns(trades, acct["starting_balance"] if acct else 10_000.0)
    plans = []
    for key, p in PLANS.items():
        rules = {k: p[k] for k in ("targets", "daily_loss_pct", "max_loss_pct", "min_days")}
        plans.append({"plan": key, "label": p["label"], "rules": rules, **remix(days, rules)})
    s = scores(trades, limit)
    weakest = min(s, key=lambda x: x["score"])
    return {"ready": True, "trades": len(trades), "days": len(days), "limit_pct": limit, "scores": s,
            "weakest": weakest["key"], "plans": plans}


@router.get("/dna")
def get_dna(user: UserOut = Depends(current_user)):
    """Behaviour scores from your paper trades, and how they would fare against each challenge plan."""
    return dna(user.id)
