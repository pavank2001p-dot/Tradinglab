"""Realistic fills: spreads widen and stops slip at the times they do at a real broker.

Two moments matter most:
- High-impact releases (CPI, payrolls, central bank decisions, from the events table) of the economies a
  market depends on (US releases for every market, plus euro-area ones for EUR/USD or the DAX, Japanese ones
  for USD/JPY or the Nikkei, and so on; see Instrument.currencies): from a few minutes before to a
  quarter of an hour after, the spread is several times its usual size and stop orders fill a little past
  their price, because the market jumps instead of trading through every level.
- The daily rollover at 17:00 New York time, when liquidity thins out and spreads widen for a few minutes.
  Markets that trade all week (crypto) or only in exchange hours (US stocks) have no rollover.

The paper account uses this by default (it can be turned off in account settings); the backtester uses it when
`realistic_fills` is set. Gaps through a stop already fill at the next price, as before."""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db
from . import instruments as ins

NY = ZoneInfo("America/New_York")
NEWS_BEFORE = timedelta(minutes=5)
NEWS_AFTER = timedelta(minutes=15)
NEWS_SPREAD_X = 4.0      # spread multiple around a high-impact release
NEWS_SLIP_X = 1.0        # extra slippage on stop fills, in multiples of the usual spread
ROLLOVER_SPREAD_X = 3.0  # spread multiple around 17:00 New York
ROLLOVER_FROM, ROLLOVER_TO = (16, 55), (17, 15)  # New York clock times
CACHE_SECONDS = 300


def _has_rollover(inst: ins.Instrument) -> bool:
    return inst.hours == "fx"


def in_rollover(t: datetime) -> bool:
    ny = t.astimezone(NY)
    hm = (ny.hour, ny.minute)
    return ROLLOVER_FROM <= hm < ROLLOVER_TO


@dataclass
class Conditions:
    """High-impact release times over a span, and the spread and slippage they imply at any moment."""
    events: list[datetime] = field(default_factory=list)
    on: bool = True
    countries: list[str] = field(default_factory=list)  # each event's currency code; empty means "matters to all"

    def _times(self, inst: ins.Instrument | None) -> list[datetime]:
        if inst is None or not self.countries:
            return self.events
        mine = inst.currencies
        return [e for e, c in zip(self.events, self.countries) if c in mine]

    def near_news(self, t: datetime, inst: ins.Instrument | None = None) -> bool:
        return self.on and any(e - NEWS_BEFORE <= t <= e + NEWS_AFTER for e in self._times(inst))

    def why(self, inst: ins.Instrument, t: datetime) -> str | None:
        if not self.on:
            return None
        if self.near_news(t, inst):
            return "news"
        if _has_rollover(inst) and in_rollover(t):
            return "rollover"
        return None

    def spread(self, inst: ins.Instrument, t: datetime) -> float:
        w = self.why(inst, t)
        return inst.spread * (NEWS_SPREAD_X if w == "news" else ROLLOVER_SPREAD_X if w == "rollover" else 1.0)

    def slip(self, inst: ins.Instrument, t: datetime) -> float:
        """How much further than its price a stop order or stop loss fills at time t."""
        return inst.spread * NEWS_SLIP_X if self.near_news(t, inst) else 0.0

    def news_between(self, a: datetime, b: datetime, inst: ins.Instrument | None = None) -> bool:
        """Whether a release falls inside [a, b), for coarse bars such as hourly and daily ones."""
        return self.on and any(a - NEWS_BEFORE <= e < b + NEWS_AFTER for e in self._times(inst))


def load(c, start: datetime, end: datetime) -> Conditions:
    rows = c.execute("SELECT ts, country FROM events WHERE impact = 'High' AND ts BETWEEN %s AND %s ORDER BY ts",
                     (start - NEWS_AFTER, end + NEWS_BEFORE)).fetchall()
    return Conditions([r["ts"] for r in rows], countries=[r["country"] or "USD" for r in rows])


_cache: tuple[float, Conditions] | None = None


def now() -> Conditions:
    """Conditions around the present moment, cached for a few minutes (the calendar changes rarely)."""
    global _cache
    if _cache and time.time() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    t = datetime.now(timezone.utc)
    with db.conn() as c:
        cond = load(c, t - timedelta(days=1), t + timedelta(days=1))
    _cache = (time.time(), cond)
    return cond


def clear_cache() -> None:
    global _cache
    _cache = None
