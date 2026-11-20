"""How far a backtest result can be trusted to carry over to the real market.

A strategy tuned on past prices can look great just because it was fitted to that one stretch of history.
Three checks guard against that:

- Held-back data: the last part of the test (30% by default) is reported on its own. Tuning tools only see
  the part before it, so it is data the strategy was never shaped on. A real edge should still show there.
- Trade count: a handful of trades can't tell skill from luck. 30 is the bare minimum, 100+ is solid.
- Monte Carlo: the test's own trades are redrawn in random order (with repeats) many times, to see how
  often the same edge would still have lost money and how deep the drawdowns could have gone.

Signals only ever use past prices, so the indicators simply run on through the cut; nothing from the
held-back part leaks into the development part.
"""

import random

from .report import build_report

DEFAULT_HOLDOUT_PCT = 30.0
MIN_TRADES, GOOD_TRADES = 30, 100
MIN_HELD_TRADES = 10
MC_PATHS, MC_BUDGET, MC_MIN_PATHS = 1000, 300_000, 200
MC_SEED = 7

LEVELS = {
    "strong": "Strong evidence",
    "fair": "Some evidence",
    "weak": "Weak evidence",
    "thin": "Not enough trades",
}


def cut_index(n_bars: int, holdout_pct: float) -> int:
    """Index of the first held-back bar (n_bars when nothing is held back)."""
    if holdout_pct <= 0:
        return n_bars
    return max(1, min(n_bars - 1, int(n_bars * (1 - holdout_pct / 100))))


def trade_returns(trades: list[dict], capital: float) -> list[tuple[int, float]]:
    """(entry time, return on the account) of each closed trade, in the order they closed. Cash only moves
    when a trade closes, so the account before a trade is the capital plus every earlier trade's P&L."""
    closed = sorted((t for t in trades if t.get("exit_time") is not None), key=lambda t: t["exit_time"])
    out, acct = [], capital
    for t in closed:
        out.append((t["entry_time"], t["pnl"] / acct if acct > 0 else 0.0))
        acct += t["pnl"]
    return out


def split(trades: list[dict], equity: list[tuple[int, float]], capital: float, cut_t: int) -> dict:
    """Stats for the development part (before cut_t) and the held-back part (from cut_t), each as if it were
    its own test. A trade belongs to the part it was opened in."""
    dev_eq = [p for p in equity if p[0] < cut_t] or equity[:1]
    held_cap = dev_eq[-1][1]
    held_eq = [(cut_t, held_cap)] + [p for p in equity if p[0] >= cut_t]
    dev_tr = [t for t in trades if t["entry_time"] < cut_t]
    held_tr = [t for t in trades if t["entry_time"] >= cut_t]
    rets = trade_returns(trades, capital)
    out = {"cut": cut_t}
    for key, tr, eq, cap in (("development", dev_tr, dev_eq, capital), ("held_back", held_tr, held_eq, held_cap)):
        st = build_report(tr, eq, cap)["stats"] if cap > 0 else {"trades": len(tr)}
        part = [r for t, r in rets if (t < cut_t) == (key == "development")]
        st["avg_trade_return_pct"] = round(sum(part) / len(part) * 100, 4) if part else None
        out[key] = st
    return out


def monte_carlo(returns: list[float], paths: int | None = None, seed: int = MC_SEED) -> dict | None:
    """Redraw the trades' returns at random, with repeats, and compound them. Returns percentiles of the
    final return and the deepest drawdown, and how often a path ended below where it started."""
    n = len(returns)
    if n < 2:
        return None
    paths = paths or max(MC_MIN_PATHS, min(MC_PATHS, MC_BUDGET // n))
    rng = random.Random(seed)
    finals, dds = [], []
    for _ in range(paths):
        v = peak = 1.0
        worst = 0.0
        for r in rng.choices(returns, k=n):
            v *= max(1 + r, 0.0)
            peak = max(peak, v)
            worst = min(worst, v / peak - 1)
            if v <= 0:
                break
        finals.append((v - 1) * 100)
        dds.append(worst * 100)
    finals.sort()
    dds.sort()  # most negative first

    def pct(xs: list[float], p: float) -> float:
        return round(xs[min(len(xs) - 1, int(p / 100 * len(xs)))], 2)

    return {
        "paths": paths,
        "return_p5": pct(finals, 5), "return_p50": pct(finals, 50), "return_p95": pct(finals, 95),
        "drawdown_p50": pct(dds, 50), "drawdown_p95": pct(dds, 5),  # 1 path in 20 was at least this deep
        "loss_chance_pct": round(sum(1 for f in finals if f < 0) / paths * 100, 1),
    }


def _check(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def assess(trades: list[dict], capital: float, sp: dict | None) -> dict:
    """The trust level and the checks behind it. `sp` is the result of split(), or None if nothing was
    held back."""
    rets = trade_returns(trades, capital)
    n = len(rets)
    checks = []

    if n >= GOOD_TRADES:
        checks.append(_check("trades", "Number of trades", "pass", f"{n} trades: enough to judge the edge."))
    elif n >= MIN_TRADES:
        checks.append(_check("trades", "Number of trades", "warn",
                             f"{n} trades: a start, but 100 or more would make the result much more reliable. "
                             "Try a longer period or hourly candles."))
    else:
        checks.append(_check("trades", "Number of trades", "fail",
                             f"Only {n} trade{'' if n == 1 else 's'}: too few to tell skill from luck. "
                             "Use a longer period or hourly candles to get at least 30."))

    if sp is not None:
        dev, held = sp["development"], sp["held_back"]
        h_n, h_avg, d_avg = held.get("trades", 0), held.get("avg_trade_return_pct"), dev.get("avg_trade_return_pct")
        if h_n < MIN_HELD_TRADES:
            checks.append(_check("held_back", "Held-back data", "warn",
                                 f"Only {h_n} trade{'' if h_n == 1 else 's'} in the held-back part, too few to confirm "
                                 "the result on data the strategy wasn't tuned on."))
        elif (held.get("net_profit") or 0) <= 0:
            checks.append(_check("held_back", "Held-back data", "fail",
                                 f"Lost money on the held-back part ({held.get('total_return_pct')}% over {h_n} trades). "
                                 "The edge may only exist in the data it was tuned on."))
        elif d_avg and d_avg > 0 and h_avg is not None and h_avg < d_avg * 0.5:
            checks.append(_check("held_back", "Held-back data", "warn",
                                 f"Still profitable on the held-back part, but each trade made {h_avg:.2f}% against "
                                 f"{d_avg:.2f}% before it. Expect weaker results live than in the full test."))
        else:
            checks.append(_check("held_back", "Held-back data", "pass",
                                 f"Profitable on the held-back part too ({held.get('total_return_pct')}% over {h_n} trades)."))

    mc = monte_carlo([r for _, r in rets])
    if mc:
        lc = mc["loss_chance_pct"]
        dd = f" 1 in 20 runs fell {abs(mc['drawdown_p95']):.0f}% or more from a peak."
        if lc <= 5:
            checks.append(_check("monte_carlo", "Luck test", "pass",
                                 f"Reshuffled {mc['paths']} times, the same trades lost money in {lc}% of runs.{dd}"))
        elif lc <= 25:
            checks.append(_check("monte_carlo", "Luck test", "warn",
                                 f"Reshuffled {mc['paths']} times, the same trades lost money in {lc}% of runs.{dd}"))
        else:
            checks.append(_check("monte_carlo", "Luck test", "fail",
                                 f"Reshuffled {mc['paths']} times, the same trades lost money in {lc}% of runs: "
                                 f"the profit could easily be luck.{dd}"))

    statuses = {c["key"]: c["status"] for c in checks}
    if statuses.get("trades") == "fail":
        level = "thin"
    elif "fail" in statuses.values():
        level = "weak"
    elif "warn" in statuses.values():
        level = "fair"
    else:
        level = "strong"
    return {"level": level, "label": LEVELS[level], "checks": checks, "monte_carlo": mc}
