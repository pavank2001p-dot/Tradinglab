"""Trade scenarios: the range of outcomes a market's own past daily moves make possible for a
trade opened now, on any market in app.instruments (gold by default).

This is a simulation, not a forecast. Each simulated path strings together real trading days
drawn at random from the lookback period (a bootstrap): the day's close-to-close move and how
far its high and low reached. By default the average daily move is removed first, so the
simulation takes no view on direction; it only shows how far and how often the market has moved.
Crypto trades every day, so its paths step through weekends too.
"""

import bisect
import hashlib
import math
import random
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

from . import config, db
from . import instruments as ins
from .auth import UserOut, current_user
from .risk import profile_of

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

PATHS = 2000
PCTS = (5, 25, 50, 75, 95)
CHECKPOINTS = (("1 week", 7), ("1 month", 30), ("3 months", 91), ("6 months", 182), ("1 year", 365))


class ScenarioIn(BaseModel):
    symbol: str = Field(config.SYMBOL, description="Market to simulate (see /prices/markets)")
    side: Literal["long", "short"] = "long"
    entry: float | None = Field(None, gt=0, description="Entry price; the latest price if left out")
    units: float = Field(1, gt=0, le=1_000_000_000, description="Units of the market (ounces, shares, currency units...)")
    stop: float | None = Field(None, gt=0)
    target: float | None = Field(None, gt=0)
    horizon_days: int = Field(30, ge=1, le=365, description="Calendar days to hold at most")
    lookback_years: int = Field(10, ge=1, le=20)
    with_trend: bool = Field(False, description="Keep the past average daily move instead of removing it")
    capital: float = Field(10_000, gt=0, le=100_000_000)
    spread: float | None = Field(None, ge=0, le=100_000, description="Price units; the market's typical spread if left out")
    swap_long: float | None = Field(None, ge=-10_000, le=10_000, description=(
        "USD per unit per night held long; the market's financing rate if left out"))
    swap_short: float | None = Field(None, ge=-10_000, le=10_000)

    @property
    def market(self) -> ins.Instrument:
        return ins.get(self.symbol)

    @model_validator(mode="after")
    def _check(self):
        try:
            m = ins.get(self.symbol)
        except KeyError:
            raise ValueError(f"Unknown market {self.symbol}")
        self.symbol = m.symbol
        if self.spread is None:
            self.spread = m.spread
        if self.entry is None:
            return self
        below, above = ("stop", "target") if self.side == "long" else ("target", "stop")
        lo, hi = getattr(self, below), getattr(self, above)
        if lo is not None and lo >= self.entry:
            raise ValueError(f"For a {self.side} trade the {below} must be below the entry price")
        if hi is not None and hi <= self.entry:
            raise ValueError(f"For a {self.side} trade the {above} must be above the entry price")
        return self


def trading_days(start: date, horizon_days: int, weekends: bool = False) -> list[date]:
    """Weekdays after start (every day for markets that trade at weekends), up to and including start + horizon_days."""
    out, d, end = [], start, start + timedelta(days=horizon_days)
    while d < end:
        d += timedelta(days=1)
        if weekends or d.weekday() < 5:
            out.append(d)
    return out or [start + timedelta(days=1)]


def day_moves(bars: list[dict]) -> list[tuple[float, float, float]]:
    """(close, high, low) of each day as log moves from the previous close."""
    out = []
    for prev, b in zip(bars, bars[1:]):
        pc = prev["c"]
        if pc > 0 and b["l"] > 0:
            out.append((math.log(b["c"] / pc), math.log(max(b["h"], b["c"]) / pc), math.log(min(b["l"], b["c"]) / pc)))
    return out


def _pct(sorted_xs: list[float], p: float) -> float:
    if not sorted_xs:
        return float("nan")
    k = (len(sorted_xs) - 1) * p / 100
    f = math.floor(k)
    c = min(f + 1, len(sorted_xs) - 1)
    return sorted_xs[f] + (sorted_xs[c] - sorted_xs[f]) * (k - f)


def simulate(cfg: ScenarioIn, moves: list[tuple[float, float, float]], start: date, paths: int = PATHS,
             seed: int = 0) -> dict:
    if len(moves) < 60:
        raise ValueError("Not enough daily price history to simulate (need at least 60 days)")
    entry = cfg.entry
    assert entry is not None
    mk = cfg.market
    dec = mk.decimals
    drift = 0.0 if cfg.with_trend else sum(m[0] for m in moves) / len(moves)
    days = trading_days(start, cfg.horizon_days, mk.weekends)
    n = len(days)
    rng = random.Random(seed)
    side = 1 if cfg.side == "long" else -1
    sp, u = cfg.spread, cfg.units
    fixed = cfg.swap_long if side == 1 else cfg.swap_short
    # Financing per unit per night: a fixed value if given, else the market's rate on the entry price.
    swap = fixed if fixed is not None else mk.swap_per_unit("long" if side == 1 else "short", entry)
    # Stored prices are bids: a long pays the spread on entry, a short on exit.
    fill = entry + sp if side == 1 else entry

    closes = [[0.0] * paths for _ in range(n)]  # closes[day][path]
    pnls, held, exits = [], [], {"target": 0, "stop": 0, "open": 0}
    for j in range(paths):
        lp, done = 0.0, False
        for i in range(n):
            rc, rh, rl = moves[rng.randrange(len(moves))]
            hi, lo = math.exp(lp + rh - drift) * entry, math.exp(lp + rl - drift) * entry
            lp += rc - drift
            px = math.exp(lp) * entry
            closes[i][j] = px
            if done:
                continue
            exit_px = reason = None
            if side == 1:
                if cfg.stop is not None and lo <= cfg.stop:
                    exit_px, reason = cfg.stop, "stop"  # if both could trigger, assume the stop hit first
                elif cfg.target is not None and hi >= cfg.target:
                    exit_px, reason = cfg.target, "target"
            else:  # shorts buy back at the ask (bid + spread)
                if cfg.stop is not None and hi + sp >= cfg.stop:
                    exit_px, reason = cfg.stop - sp, "stop"
                elif cfg.target is not None and lo + sp <= cfg.target:
                    exit_px, reason = cfg.target - sp, "target"
            if reason is None and i == n - 1:
                exit_px, reason = px, "open"
            if reason:
                out = exit_px if side == 1 else exit_px + sp
                pnls.append((out - fill) * u * side * mk.usd(out) + swap * u * (i + 1))
                held.append(i + 1)
                exits[reason] += 1
                done = True

    bands = []
    for i, d in enumerate(days):
        s = sorted(closes[i])
        bands.append({"t": int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()),
                      **{f"p{p}": round(_pct(s, p), dec) for p in PCTS}})

    checkpoints = []
    for label, cal in CHECKPOINTS:
        if cal > cfg.horizon_days:
            break
        i = bisect.bisect_right(days, start + timedelta(days=cal)) - 1
        if i < 0:
            continue
        s = sorted(closes[i])
        checkpoints.append({
            "label": label,
            "t": bands[i]["t"],
            **{f"p{p}": round(_pct(s, p), dec) for p in PCTS},
            "above_entry_pct": round(sum(x > entry for x in s) / paths * 100, 1),
        })

    ps = sorted(pnls)
    lo_p, hi_p = ps[0], ps[-1]
    bins = 24
    width = (hi_p - lo_p) / bins or 1
    hist = [0] * bins
    for x in ps:
        hist[min(int((x - lo_p) / width), bins - 1)] += 1

    loss_at_stop = None
    if cfg.stop is not None:
        # A long sells at the stop; a short buys back at it (the ask), so the spread is already inside.
        loss_at_stop = round(abs(cfg.stop - fill) * u * mk.usd(cfg.stop), 2)

    daily_sd = math.sqrt(sum((m[0] - drift) ** 2 for m in moves) / len(moves))
    yd = mk.year_days
    return {
        "symbol": mk.symbol,
        "entry": round(entry, dec),
        "side": cfg.side,
        "trading_days": n,
        "paths": paths,
        "bands": bands,
        "checkpoints": checkpoints,
        "outcomes": {k: round(v / paths * 100, 1) for k, v in exits.items()},
        "median_days_held": _pct(sorted(held), 50),
        "pnl": {
            **{f"p{p}": round(_pct(ps, p), 2) for p in PCTS},
            "mean": round(sum(ps) / len(ps), 2),
            "profit_pct": round(sum(x > 0 for x in ps) / len(ps) * 100, 1),
            "histogram": [{"from": round(lo_p + k * width, 2), "to": round(lo_p + (k + 1) * width, 2), "count": c}
                          for k, c in enumerate(hist)],
        },
        "loss_at_stop": loss_at_stop,
        "loss_at_stop_pct": None if loss_at_stop is None else round(loss_at_stop / cfg.capital * 100, 2),
        "position_value": round(entry * u * mk.usd(entry), 2),
        "leverage": round(entry * u * mk.usd(entry) / cfg.capital, 2),
        "history": {
            "days": len(moves),
            "yearly_volatility_pct": round(daily_sd * math.sqrt(yd) * 100, 1),
            "trend_removed": not cfg.with_trend,
            "avg_yearly_move_pct": round((math.exp(sum(m[0] for m in moves) / len(moves) * yd) - 1) * 100, 1),
        },
    }


def load_daily(lookback_years: int, symbol: str = config.SYMBOL) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=365 * lookback_years + 7)
    with db.conn() as c:
        return c.execute(
            "SELECT extract(epoch FROM ts)::bigint AS t, open AS o, high AS h, low AS l, close AS c FROM candles "
            "WHERE symbol = %s AND tf = '1d' AND ts >= %s ORDER BY ts",
            (symbol, since),
        ).fetchall()


def latest_price(symbol: str = config.SYMBOL) -> float | None:
    """The latest hourly close, or the latest daily one for a market loaded with daily bars only."""
    with db.conn() as c:
        row = c.execute("SELECT close FROM candles WHERE symbol = %s AND tf IN ('1h', '1d') ORDER BY ts DESC, tf DESC LIMIT 1",
                        (symbol,)).fetchone()
    return row["close"] if row else None


def run(cfg: ScenarioIn, user_id: int | None = None) -> dict:
    if cfg.entry is None:
        price = latest_price(cfg.symbol)
        if price is None:
            raise ValueError(f"No {cfg.market.name} prices yet")
        cfg = ScenarioIn(**{**cfg.model_dump(), "entry": cfg.market.round(price)})  # re-validates stop and target
    bars = load_daily(cfg.lookback_years, cfg.symbol)
    recent = [{"t": b["t"], "c": b["c"]} for b in bars[-90:]]
    seed = int(hashlib.sha256(cfg.model_dump_json().encode()).hexdigest()[:8], 16)
    start = datetime.fromtimestamp(bars[-1]["t"], timezone.utc).date() if bars else date.today()
    out = simulate(cfg, day_moves(bars), max(start, date.today()), seed=seed)
    out["recent"] = recent
    out["history"]["from"] = bars[0]["t"] if bars else None
    m = cfg.market
    fixed = cfg.swap_long if cfg.side == "long" else cfg.swap_short
    out["market"] = {"symbol": m.symbol, "name": m.name, "decimals": m.decimals, "unit": m.unit, "spread": cfg.spread,
                     "swap_per_night": round(fixed if fixed is not None else m.swap_per_unit(cfg.side, cfg.entry), 6)}
    if user_id is not None:
        p = profile_of(user_id)
        if p:
            out["profile"] = {k: p[k] for k in ("profile", "label", "max_risk_per_trade_pct", "max_leverage")}
    return out


@router.post("")
def scenario(cfg: ScenarioIn, user: UserOut = Depends(current_user)):
    try:
        return run(cfg, user.id)
    except ValidationError as e:  # the stop or target is on the wrong side of the latest price
        raise HTTPException(422, e.errors()[0]["msg"].removeprefix("Value error, "))
    except ValueError as e:
        raise HTTPException(422, str(e))
