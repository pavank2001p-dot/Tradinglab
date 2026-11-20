"""Daily Candle: one real moment from a market's history each day, the same for everyone.

The market rotates day by day (gold, forex, indices, oil, crypto...) and is revealed with the answer.

The chart stops at an hour where the next twelve hours moved a lot. The date and the price level are
hidden (prices are shown relative to the last close, which is 100), so nobody can look the answer up.
The player picks buy, sell or wait; only then does the server send the next twelve hours, the real date
and how everyone else chose. One go a day. Signed-in plays are kept for the streak and the crowd split;
signed-out plays are only answered.

Nothing here predicts prices or is advice; it is practice on history."""

import hashlib
import random
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from . import config, db, prices
from . import instruments as ins
from .auth import UserOut, current_user

router = APIRouter(prefix="/daily", tags=["daily"])

TF = "1h"
CONTEXT = 72          # hours shown before the moment
HORIZON = 12          # hours revealed after the choice
WAIT_BAND = 0.2       # a move smaller than this (in %) means waiting was the right call
TRIES = 40            # candidate moments looked at when the day's moment is chosen
FIRST_DAY = date(2026, 11, 1)
# Markets the Daily Candle rotates through. US stocks are left out: their six-and-a-half-hour sessions can't
# hold a twelve-hour reveal.
ROTATION = ("XAUUSD", "EURUSD", "USA500IDXUSD", "BTCUSD", "LIGHTCMDUSD", "GBPUSD", "USATECHIDXUSD", "XAGUSD",
            "ETHUSD", "USA30IDXUSD", "AUDUSD", "BRENTCMDUSD")

Choice = Literal["buy", "sell", "wait"]


def maybe_user(gl_session: str | None = Cookie(default=None)) -> UserOut | None:
    if not gl_session:
        return None
    try:
        return current_user(gl_session)
    except HTTPException:
        return None


def today() -> date:
    return datetime.now(timezone.utc).date()


def number(day: date) -> int:
    return (day - FIRST_DAY).days + 1


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def normalize(bars: list[dict], base: float) -> list[dict]:
    """Prices as a level where `base` is 100, so the chart shows shape without giving away the year."""
    return [{k: round(b[k] / base * 100, 4) for k in ("o", "h", "l", "c")} for b in bars]


def verdict(base: float, future: list[dict]) -> dict:
    """What the next hours did, and which of buy, sell or wait fitted them best."""
    end = future[-1]["c"]
    move = (end / base - 1) * 100
    high = (max(b["h"] for b in future) / base - 1) * 100
    low = (min(b["l"] for b in future) / base - 1) * 100
    best = "wait" if abs(move) < WAIT_BAND else ("buy" if move > 0 else "sell")
    return {"end_price": end, "move_pct": round(move, 3), "high_pct": round(high, 3), "low_pct": round(low, 3), "best": best}


def outcome(choice: str, v: dict) -> dict:
    """A $1,000 position in the chosen direction, held to the end, and the worst it got along the way."""
    if choice == "wait":
        return {"right": v["best"] == "wait", "pnl_1000": 0.0, "against_pct": 0.0}
    sign = 1 if choice == "buy" else -1
    against = -v["low_pct"] if choice == "buy" else v["high_pct"]
    return {"right": v["best"] == choice, "pnl_1000": round(sign * v["move_pct"] * 10, 2),
            "against_pct": round(max(against, 0.0), 3)}


def streak(days: list[date], now: date) -> int:
    """Days in a row played, ending today or yesterday."""
    have = set(days)
    d = now if now in have else now - timedelta(days=1)
    n = 0
    while d in have:
        n += 1
        d -= timedelta(days=1)
    return n


def drama(context: list[dict], future: list[dict]) -> float:
    """How big the next hours' move was, measured in typical hourly ranges, so quiet years can still win."""
    ranges = sorted(b["h"] - b["l"] for b in context)
    typical = ranges[len(ranges) // 2] or 1e-9
    return abs(future[-1]["c"] - context[-1]["c"]) / typical


# ---------------------------------------------------------------------------
# Choosing the day's moment
# ---------------------------------------------------------------------------

def _window(t: int, symbol: str = config.SYMBOL) -> tuple[list[dict], list[dict]]:
    context = prices.candles(tf=TF, start=None, end=t + 3600, limit=CONTEXT, symbol=symbol)["bars"]
    future = prices.candles(tf=TF, start=t + 3600, end=t + 3600 * 40, limit=HORIZON, symbol=symbol)["bars"]
    return context, future


def market_of(day: date) -> list[str]:
    """The day's market first, then the rest of the rotation to fall back on (only enabled markets)."""
    pool = [s for s in ROTATION if s in ins.BY_SYMBOL] or [config.SYMBOL]
    k = (day - FIRST_DAY).days % len(pool)
    return pool[k:] + pool[:k]


def _usable(t: int, context: list[dict], future: list[dict]) -> bool:
    return (len(context) == CONTEXT and len(future) == HORIZON and context[-1]["t"] == t
            and future[-1]["t"] - t <= 3600 * (HORIZON + 4))  # no weekend inside the reveal


def pick(day: date, symbol: str = config.SYMBOL) -> int | None:
    """The hour whose next twelve hours moved most, out of TRIES seeded guesses across the hourly history."""
    m = ins.BY_SYMBOL.get(symbol, ins.GOLD)
    with db.conn() as c:
        r = c.execute("SELECT min(ts) AS a, max(ts) AS b FROM candles WHERE symbol = %s AND tf = %s",
                      (m.symbol, TF)).fetchone()
    if not r or r["a"] is None:
        return None
    first = int(r["a"].timestamp()) + 3600 * (CONTEXT + 24)
    last = int(r["b"].timestamp()) - 86400 * 30   # nothing recent enough to remember
    if last <= first:
        last = int(r["b"].timestamp()) - 3600 * (HORIZON + 4)
    if last <= first:
        return None
    rnd = random.Random(int(hashlib.sha256(f"daily-candle-{day.isoformat()}".encode()).hexdigest(), 16))
    best, best_score = None, -1.0
    for _ in range(TRIES):
        t = rnd.randrange(first, last) // 3600 * 3600
        d = datetime.fromtimestamp(t, tz=timezone.utc)
        if (d.weekday() >= 5 and not m.weekends) or not 1 <= d.hour <= 18:
            continue
        context, future = _window(t, m.symbol)
        if not _usable(t, context, future):
            continue
        s = drama(context, future)
        if s > best_score:
            best, best_score = t, s
    return best


def moment(day: date) -> tuple[int, str]:
    """The day's frozen hour and its market, chosen once and stored."""
    with db.conn() as c:
        row = c.execute("SELECT frozen_ts, symbol FROM daily_candles WHERE day = %s", (day,)).fetchone()
    if row:
        return row["frozen_ts"], row["symbol"]
    t, symbol = None, config.SYMBOL
    for symbol in market_of(day):
        t = pick(day, symbol)
        if t is not None:
            break
    if t is None:
        raise HTTPException(503, "There isn't enough price history for a Daily Candle yet")
    with db.conn() as c:
        row = c.execute(
            "INSERT INTO daily_candles (day, symbol, frozen_ts) VALUES (%s, %s, %s) "
            "ON CONFLICT (day) DO UPDATE SET day = EXCLUDED.day RETURNING frozen_ts, symbol",
            (day, symbol, t),
        ).fetchone()
    return row["frozen_ts"], row["symbol"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _crowd(c, day: date) -> dict:
    rows = c.execute("SELECT choice, count(*) AS n FROM daily_candle_plays WHERE day = %s GROUP BY choice",
                     (day,)).fetchall()
    out = {"buy": 0, "sell": 0, "wait": 0}
    for r in rows:
        out[r["choice"]] = r["n"]
    out["total"] = sum(out.values())
    return out


def _record(c, user_id: int) -> dict:
    rows = c.execute(
        "SELECT day, choice, correct FROM daily_candle_plays WHERE user_id = %s ORDER BY day DESC LIMIT 400",
        (user_id,),
    ).fetchall()
    return {"streak": streak([r["day"] for r in rows], today()), "played": len(rows),
            "right": sum(1 for r in rows if r["correct"])}


def _result(day: date, t: int, symbol: str, choice: str, user: UserOut | None) -> dict:
    context, future = _window(t, symbol)
    base = context[-1]["c"]
    v = verdict(base, future)
    m = ins.BY_SYMBOL.get(symbol) or next((i for i in ins.ALL if i.symbol == symbol), ins.GOLD)
    res = {"choice": choice, **outcome(choice, v), **v, "price": base, "at": t,
           "future": normalize(future, base), "symbol": m.symbol, "market": m.name, "decimals": m.decimals}
    with db.conn() as c:
        res["crowd"] = _crowd(c, day)
        res["you"] = _record(c, user.id) if user else None
    return res


@router.get("")
def get_daily(user: UserOut | None = Depends(maybe_user)):
    day = today()
    t, symbol = moment(day)
    context, _ = _window(t, symbol)
    played = None
    if user:
        with db.conn() as c:
            row = c.execute("SELECT choice FROM daily_candle_plays WHERE user_id = %s AND day = %s",
                            (user.id, day)).fetchone()
        if row:
            played = _result(day, t, symbol, row["choice"], user)
    return {"day": day.isoformat(), "number": number(day), "tf": TF, "horizon": HORIZON,
            "bars": normalize(context, context[-1]["c"]), "played": played}


class PlayIn(BaseModel):
    choice: Choice


@router.post("")
def play(body: PlayIn, user: UserOut | None = Depends(maybe_user)):
    """Answers today's moment. A signed-in player's first answer is kept; asking again returns that one."""
    day = today()
    t, symbol = moment(day)
    choice = body.choice
    if user:
        context, future = _window(t, symbol)
        right = outcome(choice, verdict(context[-1]["c"], future))["right"]
        with db.conn() as c:
            c.execute("INSERT INTO daily_candle_plays (user_id, day, choice, correct) VALUES (%s, %s, %s, %s) "
                      "ON CONFLICT (user_id, day) DO NOTHING", (user.id, day, choice, right))
            choice = c.execute("SELECT choice FROM daily_candle_plays WHERE user_id = %s AND day = %s",
                               (user.id, day)).fetchone()["choice"]
    return _result(day, t, symbol, choice, user)
