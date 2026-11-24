"""Claude market briefing: an analysis of one market, written from the site's own data.

The site gathers the facts in code (price and chart readings, tagged news, the calendar, a set of backtests
re-checked on held-back data, and the user's own paper-trading habits) and Claude writes them up as a structured
briefing. Every number comes from those facts. The briefing explains; it never tells anyone to buy or sell and
never says where a price will go. A reply that reads like a signal is withheld and only the facts are shown.

Briefings run in the background and the page polls for them. A user's briefing for a market is reused for
BRIEFING_CACHE_MINUTES, and each user gets BRIEFING_DAILY_LIMIT new ones per UTC day.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from psycopg.types.json import Jsonb

from . import backtest, calendar, coach, config, db, news
from . import instruments as ins
from .assistant import failure_text, t_price_summary
from .auth import UserOut, current_user

log = logging.getLogger("briefing")
router = APIRouter(prefix="/briefing", tags=["briefing"])

LABEL = ("Analysis, not a signal. This briefing explains what the data shows; it doesn't predict prices or tell you "
         "to buy or sell. Past results don't guarantee future ones.")

# The strategies every briefing re-tests: trend followers and mean reverters, plus holding as the benchmark.
COMPARE = ("ma_cross", "ma_trend", "breakout", "macd", "rsi_reversion", "bollinger", "buy_and_hold")
COMPARE_YEARS = 5
NEWS_DAYS = 3
HABIT_DAYS = 90

# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def _sma(xs: list[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _rsi(xs: list[float], n: int = 14) -> float | None:
    if len(xs) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(xs[-n - 1:-1], xs[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    return round(100 - 100 / (1 + gains / losses), 1)


def _pct(a: float | None, b: float | None) -> float | None:
    return None if not a or b is None else round((b / a - 1) * 100, 2)


def chart_facts(symbol: str) -> dict:
    """Plain readings of the daily chart: where price sits against its averages and recent ranges, momentum and
    volatility. Readings, not forecasts."""
    start = date.today() - timedelta(days=420)
    bars = backtest.load_bars("1d", start, None, symbol)
    if len(bars) < 30:
        return {"error": "Not enough daily history for chart readings."}
    dec = ins.get(symbol).decimals
    closes = [b["c"] for b in bars]
    last = closes[-1]
    out: dict = {"last_close": round(last, dec), "as_of": datetime.fromtimestamp(bars[-1]["t"], timezone.utc).date().isoformat()}
    for n in (20, 50, 200):
        avg = _sma(closes, n)
        out[f"sma{n}"] = None if avg is None else round(avg, dec)
        out[f"vs_sma{n}_pct"] = _pct(avg, last)
    s20, s50, s200 = out["sma20"], out["sma50"], out["sma200"]
    if s50 and s200:
        out["averages_order"] = ("20 above 50 above 200" if s20 and s20 > s50 > s200 else
                                 "20 below 50 below 200" if s20 and s20 < s50 < s200 else "mixed")
    out["rsi14"] = _rsi(closes)
    tr = [max(b["h"], p["c"]) - min(b["l"], p["c"]) for p, b in zip(bars[:-1], bars[1:])]
    atr = sum(tr[-14:]) / min(len(tr), 14)
    out["atr14"] = round(atr, dec)
    out["atr14_pct_of_price"] = round(atr / last * 100, 2)
    year_tr = tr[-250:]
    out["atr_vs_1y_avg"] = round(atr / (sum(year_tr) / len(year_tr)), 2) if year_tr else None
    for n in (20, 60):
        recent = bars[-n:]
        hi, lo = max(b["h"] for b in recent), min(b["l"] for b in recent)
        out[f"high_{n}d"], out[f"low_{n}d"] = round(hi, dec), round(lo, dec)
        out[f"position_in_{n}d_range_pct"] = round((last - lo) / (hi - lo) * 100) if hi > lo else None
    out["return_5d_pct"] = _pct(closes[-6], last) if len(closes) > 5 else None
    out["return_20d_pct"] = _pct(closes[-21], last) if len(closes) > 20 else None
    return out


def news_facts(symbol: str) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=NEWS_DAYS)
    items = [r for r in news.list_(limit=40, symbol=symbol, sector=None)["items"] if r["published_at"] >= since][:15]
    tone = {k: sum(r["impact"] == k for r in items) for k in ("bullish", "bearish", "neutral")}
    return {"days": NEWS_DAYS, "count": len(items), "tagged": tone,
            "items": [{"published": r["published_at"].isoformat(timespec="minutes"), "headline": r["headline"],
                       "publisher": r["publisher"], "tagged_for": r["focus"], "impact": r["impact"],
                       "reason": r["reason"]} for r in items]}


def calendar_facts(symbol: str) -> list[dict]:
    rows = calendar.list_(days=7, past_days=0, symbol=symbol)
    return [{"time_utc": r["ts"].isoformat(timespec="minutes"), "country": r["country"], "event": r["title"],
             "impact": r["impact"]} for r in rows if r["impact"] == "High"][:10]


def _brief(stats: dict) -> dict:
    return {k: stats.get(k) for k in ("total_return_pct", "cagr_pct", "max_drawdown_pct", "trades", "win_rate_pct",
                                      "profit_factor", "time_in_market_pct")}


def backtest_facts(symbol: str) -> dict:
    """The same strategies re-tested on the last few years, with the last part held back as unseen data."""
    start = date.today() - timedelta(days=round(COMPARE_YEARS * 365.25))
    bars = backtest.load_bars("1d", start, None, symbol)
    if len(bars) < 200:
        return {"error": "Not enough daily history to compare strategies."}
    out, hold = [], None
    for key in COMPARE:
        cfg = backtest.BacktestIn(strategy=key, symbol=symbol, start=start, capital=10_000, size_pct=100)
        try:
            rep = backtest.run(cfg, bars, checks=True)
        except Exception:
            log.exception("briefing backtest %s on %s failed", key, symbol)
            continue
        hold = rep["stats"].get("buy_and_hold_pct")
        row = {"strategy": key, "label": backtest.label_of(key), "kind": backtest.kind_of(key), **_brief(rep["stats"])}
        if key != "buy_and_hold" and rep.get("split"):
            dev, held = rep["split"]["development"], rep["split"]["held_back"]
            row["earlier_part_return_pct"] = dev.get("total_return_pct")
            row["held_back_return_pct"] = held.get("total_return_pct")
            row["held_back_trades"] = held.get("trades")
            row["trust"] = rep["robustness"]["label"]
            row["failed_checks"] = [c["detail"] for c in rep["robustness"]["checks"] if c["status"] == "fail"][:3]
        out.append(row)
    return {"years": COMPARE_YEARS, "timeframe": "daily", "size": "whole account per trade, no leverage",
            "held_back_pct": backtest.robust.DEFAULT_HOLDOUT_PCT, "buy_and_hold_pct": hold,
            "strategies": out}


def my_backtest_facts(user_id: int, symbol: str) -> dict | None:
    """The user's most recent saved backtest on this market, so the briefing can point at its weak spots."""
    with db.conn() as c:
        r = c.execute(
            "SELECT id, created_at, params, stats, result -> 'robustness' AS robustness, result -> 'split' AS split "
            "FROM backtests WHERE user_id = %s AND coalesce(params ->> 'symbol', %s) = %s "
            "ORDER BY created_at DESC LIMIT 1", (user_id, config.SYMBOL, symbol)).fetchone()
    if not r:
        return None
    p = r["params"]
    rob = r["robustness"] or {}
    return {"id": r["id"], "saved": r["created_at"].date().isoformat(), "strategy": p.get("strategy"),
            "timeframe": p.get("tf"), "stop_loss_pct": p.get("stop_loss_pct"), "stats": _brief(r["stats"]),
            "buy_and_hold_pct": r["stats"].get("buy_and_hold_pct"), "trust": rob.get("label"),
            "checks": [{"check": c["label"], "status": c["status"], "detail": c["detail"]} for c in rob.get("checks", [])]}


def habit_facts(user_id: int, symbol: str) -> dict:
    """The user's closed paper trades in the last HABIT_DAYS, with the coach's mistake tags and what each cost."""
    since = datetime.now(timezone.utc) - timedelta(days=HABIT_DAYS)
    with db.conn() as c:
        trades = [t for t in coach.tag_trades(c, user_id) if t["closed_at"] >= since]
    if not trades:
        return {"trades": 0}
    tags = {}
    for k in coach.SEVERITY:
        hit = [t for t in trades if k in t["tags"]]
        if hit:
            tags[k] = {"label": coach.TAGS[k][0], "meaning": coach.TAGS[k][1], "trades": len(hit),
                       "net_pnl": round(sum(t["pnl"] for t in hit), 2)}
    clean = [t for t in trades if not t["tags"]]
    here = [t for t in trades if t["symbol"] == symbol]
    return {"days": HABIT_DAYS, "trades": len(trades), "net_pnl": round(sum(t["pnl"] for t in trades), 2),
            "clean_trades": len(clean), "clean_net_pnl": round(sum(t["pnl"] for t in clean), 2),
            "tags": tags, "on_this_market": {"trades": len(here), "net_pnl": round(sum(t["pnl"] for t in here), 2)}}


def facts(user_id: int, symbol: str) -> dict:
    m = ins.get(symbol)
    out = {"market": {"symbol": m.symbol, "name": m.name, "asset_class": ins.CLASSES.get(m.asset_class, m.asset_class)}}
    parts = {
        "price": lambda: t_price_summary({"symbol": symbol}, user_id),
        "chart": lambda: chart_facts(symbol),
        "news": lambda: news_facts(symbol),
        "calendar_next_7_days": lambda: calendar_facts(symbol),
        "strategy_comparison": lambda: backtest_facts(symbol),
        "my_latest_backtest": lambda: my_backtest_facts(user_id, symbol),
        "my_habits": lambda: habit_facts(user_id, symbol),
    }
    for key, fn in parts.items():
        try:
            out[key] = fn()
        except Exception:
            # One missing piece shouldn't sink the briefing; the write-up says what's missing.
            log.exception("briefing facts %s for %s failed", key, symbol)
            out[key] = {"error": "Not available right now."}
    return out


# ---------------------------------------------------------------------------
# The write-up
# ---------------------------------------------------------------------------

_SECTION = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "points"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "news": {"type": "object", "properties": {
            "tone": {"type": "string", "enum": ["mostly_positive", "mostly_negative", "mixed", "quiet"]},
            "summary": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
            "required": ["tone", "summary", "points"], "additionalProperties": False},
        "chart": _SECTION,
        "strategies": {"type": "object", "properties": {
            "summary": {"type": "string"},
            "held_up": {"type": "array", "items": {"type": "string"}},
            "weak_points": {"type": "array", "items": {"type": "string"}}},
            "required": ["summary", "held_up", "weak_points"], "additionalProperties": False},
        "habits": _SECTION,
        "watch": {"type": "array", "items": {"type": "string"}},
        "limits": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "news", "chart", "strategies", "habits", "watch", "limits"],
    "additionalProperties": False,
}

SYSTEM = """You write the market briefing on Trading Lab, an educational trading-analysis website. You are given facts about ONE market, gathered from the site's own data, and write a short briefing that helps a learner understand what the data shows. Trading Lab is an analysis site, not a trading or signal service.

Hard rules
- Use only numbers, dates and headlines in the facts. Never add prices, levels or events from memory.
- Never predict where the price will go, never say it is likely to rise or fall, never give targets, and never tell the reader to buy, sell, go long, go short, enter, exit or hold. Describe; don't call. "Price is 4% above its 200-day average" is fine; "this looks like a buying opportunity" is not.
- News tone is the share of headlines the site's tagger marked positive or negative for this market. Report it as a description of the headlines, not as a direction for the price.
- Strategy results are past tests. Say which held up on the held-back part and which didn't, and compare with simply holding the market. Never say a strategy will work.
- If a fact is missing or says error, say briefly that it isn't available. If price data_source is "sample", say these are demo prices.

What to write (plain English for beginners, short sentences, no markdown)
- headline: one neutral sentence on the state of the market (e.g. range, trend reading, volatility), no direction call.
- news: tone, a two-sentence summary of what the headlines are about, and up to 4 points naming the main stories with dates.
- chart: a two-sentence summary and 3 to 5 points: where price sits against its averages and recent ranges, what RSI and ATR say about momentum and volatility, and what each reading means for a learner (e.g. wider stops when volatility is high). Explain terms briefly.
- strategies: a summary, up to 3 held_up points and up to 4 weak_points. Weak points cover strategies that lost on held-back data, deep drawdowns, too few trades, and doing worse than holding. If my_latest_backtest is present, include its failed or warning checks as weak points, naming it as "your latest backtest".
- habits: if my_habits has trades, summarise them and give up to 3 points on the costliest tags with their counts and P&L, and how clean trades compared. Judge process, not profit. If there are no trades, say that the habit review starts once they close paper trades.
- watch: up to 4 things worth keeping an eye on, such as high-impact releases in the calendar (with time in UTC) and how far the recent range highs and lows are. Things to watch, not things to do.
- limits: 2 or 3 short points on what this briefing can't tell (for example that headlines are partial and that past tests don't guarantee future results)."""

# Phrases that read like a call. A briefing containing one is withheld and the facts are shown instead.
SIGNAL = re.compile(
    r"\b(you should (buy|sell|go long|go short|enter|exit|hold)|(buy|sell)(ing)? (opportunity|now)|"
    r"(good|great) (time|entry|moment) to|price target|target of|(is|are) (likely|expected|set|poised) to (rise|fall|climb|drop|rally|gain|decline)|"
    r"will (rise|fall|climb|drop|rally|go up|go down|break out)|we recommend|i recommend|recommend (buying|selling))\b",
    re.I)


NEGATED = re.compile(r"\b(not|never|no|n't|whether|cannot|can't|doesn't|won't)\b", re.I)


def _texts(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [t for x in v.values() for t in _texts(x)]
    if isinstance(v, list):
        return [t for x in v for t in _texts(x)]
    return []


def signal_like(report: dict) -> str | None:
    """The first call-like phrase in the briefing, skipping sentences that deny one ("this doesn't say whether
    the price will rise")."""
    for text in _texts(report):
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if (m := SIGNAL.search(sentence)) and not NEGATED.search(sentence):
                return m.group(0)
    return None


def write(client: anthropic.Anthropic, f: dict) -> dict | None:
    resp = client.beta.messages.create(
        model=config.BRIEFING_MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": "Write the briefing for this market.\n\n" + json.dumps(f, default=str)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("briefing stopped: %s", resp.stop_reason)
        return None
    try:
        return json.loads(next(b.text for b in resp.content if b.type == "text"))
    except (StopIteration, ValueError):
        return None


def process(bid: int) -> None:
    with db.conn() as c:
        row = c.execute("SELECT user_id, symbol FROM briefings WHERE id = %s", (bid,)).fetchone()
    status, report, note, f = "error", None, None, None
    try:
        f = facts(row["user_id"], row["symbol"])
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=3)
        report = write(client, f)
        if report is None:
            note = "Claude couldn't write this briefing. The facts it would have used are below."
        elif hit := signal_like(report):
            log.warning("briefing %s withheld: read like a signal (%r)", bid, hit)
            report, note = None, ("The write-up read too much like a trading call, so it was held back. "
                                  "The facts it would have used are below.")
        status = "done"
    except anthropic.APIError as e:
        log.error("briefing request failed (%s): %r", bid, e)
        note = failure_text(e)
    except Exception as e:
        log.exception("briefing failed (%s)", bid)
        note = failure_text(e)
    with db.conn() as c:
        c.execute("UPDATE briefings SET status = %s, facts = %s, report = %s, note = %s, finished_at = now() WHERE id = %s",
                  (status, Jsonb(f) if f else None, Jsonb(report) if report else None, note, bid))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _used_today(c, user_id: int) -> int:
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return c.execute("SELECT count(*) AS n FROM briefings WHERE user_id = %s AND created_at >= %s AND status <> 'error'",
                     (user_id, midnight)).fetchone()["n"]


def _out(row: dict) -> dict:
    return {**row, "label": LABEL}


@router.get("/status")
def status(user: UserOut = Depends(current_user)):
    with db.conn() as c:
        used = _used_today(c, user.id)
    return {"configured": bool(config.ANTHROPIC_API_KEY), "limit": config.BRIEFING_DAILY_LIMIT, "used_today": used,
            "remaining": max(config.BRIEFING_DAILY_LIMIT - used, 0), "label": LABEL}


@router.post("", status_code=202)
def create(tasks: BackgroundTasks, symbol: str = Query(config.SYMBOL, max_length=32), fresh: bool = False,
           user: UserOut = Depends(current_user)):
    """Start a briefing for a market, or return this user's recent one for it (unless fresh)."""
    m = ins.BY_SYMBOL.get(symbol.upper())
    if not m:
        raise HTTPException(404, "Unknown market")
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(503, "The Claude briefing isn't switched on yet")
    with db.conn() as c:
        c.execute("SELECT pg_advisory_xact_lock(%s)", (user.id,))
        c.execute("""UPDATE briefings SET status = 'error', note = 'Interrupted. Try again.', finished_at = now()
                     WHERE user_id = %s AND status = 'pending' AND created_at < now() - interval '5 minutes'""", (user.id,))
        pending = c.execute("SELECT id FROM briefings WHERE user_id = %s AND status = 'pending'", (user.id,)).fetchone()
        if pending:
            return {"id": pending["id"], "status": "pending"}
        if not fresh:
            recent = c.execute(
                "SELECT id FROM briefings WHERE user_id = %s AND symbol = %s AND status = 'done' "
                "AND created_at > now() - make_interval(mins => %s) ORDER BY created_at DESC LIMIT 1",
                (user.id, m.symbol, config.BRIEFING_CACHE_MINUTES)).fetchone()
            if recent:
                return {"id": recent["id"], "status": "done", "reused": True}
        if _used_today(c, user.id) >= config.BRIEFING_DAILY_LIMIT:
            raise HTTPException(429, f"You've used all {config.BRIEFING_DAILY_LIMIT} briefings for today. "
                                     "The limit resets at midnight UTC.")
        row = c.execute("INSERT INTO briefings (user_id, symbol) VALUES (%s, %s) RETURNING id", (user.id, m.symbol)).fetchone()
    tasks.add_task(process, row["id"])
    return {"id": row["id"], "status": "pending"}


@router.get("/{bid}")
def get(bid: int, user: UserOut = Depends(current_user)):
    with db.conn() as c:
        row = c.execute("SELECT id, symbol, status, report, facts, note, created_at, finished_at FROM briefings "
                        "WHERE id = %s AND user_id = %s", (bid, user.id)).fetchone()
    if not row:
        raise HTTPException(404, "Briefing not found")
    return _out(row)
