"""Load market prices into the candles table (every market in app.instruments).

    python -m app.ingest backfill [--source dukascopy|sample] [--since 2010-01-01] [--symbol XAUUSD]
    python -m app.ingest update   [--source dukascopy|sample]   (core markets plus those in use)
    python -m app.ingest probe                                   (which catalog markets the feed carries)

Core markets (instruments.CORE) are kept up to date all the time. Any other market is loaded the
first time someone opens it (ensure) and kept up to date while it is in use: opened in the last
ACTIVE_DAYS, or holding paper positions, orders, an agent or alerts. A market the feed turns out not
to carry is marked unavailable and left out of the market list (probe).

Long-run history: monthly prices since 1833 (bundled, public domain) are stored as '1mo' bars
and fill the monthly chart before the first daily bar. See load_monthly_history.

Hourly bars are the stored source of truth; daily bars are rebuilt from them so the
two timeframes always agree. Minute bars (last MINUTE_DAYS) and one-second bars (last
SECOND_DAYS) are kept for short-term charts; other timeframes are aggregated on request. A daily bar runs from 17:00 New York to 17:00 New York
(the usual forex/gold convention), stamped with the date it closes on.
"""

import argparse
import logging
import lzma
import math
import random
import struct
import threading
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from . import config, db
from .instruments import CORE, ENABLED, GOLD, Instrument, fit_point

log = logging.getLogger("ingest")
UTC = timezone.utc
NY = ZoneInfo("America/New_York")


class FeedError(RuntimeError):
    """The feed couldn't be reached (network trouble, rate limits). Says nothing about whether it carries a market."""


class NotCarried(RuntimeError):
    """The feed has no recent prices for a market: it doesn't carry it (see duka_point)."""


@dataclass
class Bar:
    ts: datetime  # open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


# ---------------------------------------------------------------------------
# Dukascopy (free historical feed, no API key)
# ---------------------------------------------------------------------------

DUKA_BASE = "https://datafeed.dukascopy.com/datafeed"
DUKA_POINT = 1000.0  # XAUUSD prices are stored as integers x 1000; other markets are checked, see duka_point
_CANDLE = struct.Struct(">IIIIIf")  # seconds offset, open, close, low, high, volume
_TICK = struct.Struct(">IIIff")  # ms offset, ask, bid, ask volume, bid volume


def _duka_url(*parts: str, symbol: str = config.SYMBOL) -> str:
    return "/".join([DUKA_BASE, symbol, *parts])


def _key(name: str, inst: Instrument) -> str:
    """Meta keys for gold keep their original names; other markets get their symbol appended."""
    return name if inst.symbol == GOLD.symbol else f"{name}:{inst.symbol}"


def duka_point(client: httpx.Client, inst: Instrument) -> float:
    """What the feed's integer prices are divided by for this market. The feed doesn't publish it,
    so it is worked out once from recent minute bars against the market's rough price, and saved."""
    if inst.symbol == GOLD.symbol:
        return DUKA_POINT
    key = _key("duka_point", inst)
    saved = db.get_meta(key)
    if saved:
        return float(saved)
    today = datetime.now(UTC).date()
    for back in range(1, 15):
        day = today - timedelta(days=back)
        y, m = _ym(day)
        raw = _get(client, _duka_url(y, m, f"{day.day:02d}", "BID_candles_min_1.bi5", symbol=inst.symbol))
        closes = sorted(c for _, _, c, _, _, v in _CANDLE.iter_unpack(raw or b"") if v > 0)
        if closes:
            point = fit_point(closes[len(closes) // 2], inst.ref_price)
            db.set_meta(key, repr(point))
            log.info("%s: feed prices are divided by %g", inst.symbol, point)
            return point
    raise NotCarried(f"No recent {inst.symbol} prices to check the feed's scale against")


def _ym(d: date) -> tuple[str, str]:
    # Dukascopy months are zero-based: January is "00".
    return f"{d.year}", f"{d.month - 1:02d}"


def _get(client: httpx.Client, url: str) -> bytes | None:
    """Fetch and decompress one .bi5 file. None when the file does not exist yet."""
    for attempt in range(4):
        try:
            r = client.get(url)
        except httpx.HTTPError as e:
            log.warning("fetch %s failed (%s), retrying", url, e)
            time.sleep(2**attempt)
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 500 or r.status_code == 429:
            time.sleep(2**attempt)
            continue
        r.raise_for_status()
        return lzma.decompress(r.content) if r.content else b""
    raise FeedError(f"giving up on {url}")


def parse_candles(raw: bytes, base: datetime, point: float = DUKA_POINT) -> list[Bar]:
    bars = []
    for off, o, c, lo, hi, vol in _CANDLE.iter_unpack(raw):
        if vol <= 0:  # Dukascopy pads closed-market periods with flat zero-volume bars
            continue
        bars.append(
            Bar(base + timedelta(seconds=off), o / point, hi / point, lo / point, c / point, vol)
        )
    return bars


def parse_ticks_to_bar(raw: bytes, hour: datetime, point: float = DUKA_POINT) -> Bar | None:
    bids = [(bid / point, bv) for _, _, bid, _, bv in _TICK.iter_unpack(raw)]
    if not bids:
        return None
    prices = [p for p, _ in bids]
    return Bar(hour, prices[0], max(prices), min(prices), prices[-1], sum(v for _, v in bids))


def parse_ticks_to_bars(raw: bytes, hour: datetime, step: int, point: float = DUKA_POINT) -> list[Bar]:
    """Bid ticks for one hour grouped into bars of `step` seconds."""
    out: dict[int, Bar] = {}
    for ms, _, bid, _, bv in _TICK.iter_unpack(raw):
        k = ms // 1000 // step * step
        p = bid / point
        cur = out.get(k)
        if cur is None:
            out[k] = Bar(hour + timedelta(seconds=k), p, p, p, p, bv)
        else:
            cur.high, cur.low, cur.close = max(cur.high, p), min(cur.low, p), p
            cur.volume += bv
    return [out[k] for k in sorted(out)]


def resample_hourly(bars: Iterable[Bar]) -> list[Bar]:
    out: dict[datetime, Bar] = {}
    for b in bars:
        h = b.ts.replace(minute=0, second=0, microsecond=0)
        cur = out.get(h)
        if cur is None:
            out[h] = Bar(h, b.open, b.high, b.low, b.close, b.volume)
        else:
            cur.high = max(cur.high, b.high)
            cur.low = min(cur.low, b.low)
            cur.close = b.close
            cur.volume += b.volume
    return [out[k] for k in sorted(out)]


def dukascopy_hourly(start: datetime, end: datetime, inst: Instrument = GOLD) -> Iterator[list[Bar]]:
    """Yield hourly bars in [start, end), one chunk per month or day.

    Finished months come from one monthly hour-candle file. The current month (or a
    month whose file is not published yet) is built from daily minute files, and
    today from hourly tick files, so the latest completed hour is always included.
    """
    now = datetime.now(UTC)
    today = now.date()
    headers = {"User-Agent": "goldlab-ingest/1.0"}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        point, sym = duka_point(client, inst), inst.symbol
        month = date(start.year, start.month, 1)
        while month <= end.date():
            nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            month_start = datetime(month.year, month.month, 1, tzinfo=UTC)
            raw = None
            if nxt <= today:
                raw = _get(client, _duka_url(*_ym(month), "BID_candles_hour_1.bi5", symbol=sym))
            if raw is not None:
                yield [b for b in parse_candles(raw, month_start, point) if start <= b.ts < end]
            elif nxt <= today - timedelta(days=7):
                pass  # a month long finished with no file: the feed has no data that far back
            else:
                day = max(month, start.date())
                while day < nxt and day <= min(today, end.date()):
                    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
                    y, m = _ym(day)
                    raw = None
                    if day < today:
                        raw = _get(client, _duka_url(y, m, f"{day.day:02d}", "BID_candles_min_1.bi5", symbol=sym))
                    if raw is not None:
                        bars = resample_hourly(parse_candles(raw, day_start, point))
                    else:  # today, or a day whose minute file isn't published yet: completed hours from tick files
                        bars = []
                        for hour in _hours(max(start, day_start), min(end, day_start + timedelta(days=1))):
                            raw = _get(client, _duka_url(y, m, f"{day.day:02d}", f"{hour.hour:02d}h_ticks.bi5", symbol=sym))
                            bar = parse_ticks_to_bar(raw, hour, point) if raw else None
                            if bar:
                                bars.append(bar)
                    yield [b for b in bars if start <= b.ts < end]
                    day += timedelta(days=1)
            log.info("dukascopy %s %s done", sym, month.isoformat()[:7])
            month = nxt


def _hours(start: datetime, end: datetime) -> Iterator[datetime]:
    """Completed hours in [start, end)."""
    h = start.replace(minute=0, second=0, microsecond=0)
    last = min(end, datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    while h < last:
        yield h
        h += timedelta(hours=1)


def dukascopy_minutes(start: datetime, end: datetime, inst: Instrument = GOLD) -> Iterator[list[Bar]]:
    """Minute bars in [start, end): a daily minute file for past days, hourly tick files for today."""
    today = datetime.now(UTC).date()
    headers = {"User-Agent": "goldlab-ingest/1.0"}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        point, sym = duka_point(client, inst), inst.symbol
        day = start.date()
        while day <= min(today, end.date()):
            day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            y, m = _ym(day)
            raw = None
            if day < today:
                raw = _get(client, _duka_url(y, m, f"{day.day:02d}", "BID_candles_min_1.bi5", symbol=sym))
            if raw is not None:
                bars = parse_candles(raw, day_start, point)
            else:  # today, or a day whose minute file isn't published yet
                bars = []
                for hour in _hours(max(start, day_start), min(end, day_start + timedelta(days=1))):
                    raw = _get(client, _duka_url(y, m, f"{day.day:02d}", f"{hour.hour:02d}h_ticks.bi5", symbol=sym))
                    bars += parse_ticks_to_bars(raw, hour, 60, point) if raw else []
            yield [b for b in bars if start <= b.ts < end]
            day += timedelta(days=1)


def dukascopy_seconds(start: datetime, end: datetime, inst: Instrument = GOLD) -> Iterator[list[Bar]]:
    """One-second bars from hourly tick files. The feed publishes each hour once it has ended."""
    headers = {"User-Agent": "goldlab-ingest/1.0"}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        point = duka_point(client, inst)
        for hour in _hours(start, end):
            y, m = _ym(hour.date())
            raw = _get(client, _duka_url(y, m, f"{hour.day:02d}", f"{hour.hour:02d}h_ticks.bi5", symbol=inst.symbol))
            if raw:
                yield [b for b in parse_ticks_to_bars(raw, hour, 1, point) if start <= b.ts < end]


# ---------------------------------------------------------------------------
# Sample data (offline demo): real monthly averages, synthetic hours in between
# ---------------------------------------------------------------------------

HOURLY_VOL = 0.0015  # roughly gold's typical hourly volatility


def market_open(ts: datetime) -> bool:
    """Gold trades Sunday 18:00 to Friday 17:00 New York time, with a daily 17:00-18:00 break."""
    return GOLD.is_open(ts)


def _digits(inst: Instrument) -> int:
    return max(3, inst.decimals + 1)


def _monthly_anchors() -> list[tuple[datetime, float]]:
    path = Path(__file__).parent / "data" / "gold_monthly.csv"
    rows = []
    for line in path.read_text().splitlines()[1:]:
        ym, price = line.split(",")
        y, m = map(int, ym.split("-"))
        # Treat each monthly average as the price in the middle of that month.
        rows.append((datetime(y, m, 15, tzinfo=UTC), float(price)))
    return rows


def _bar_from_walk(ts: datetime, open_: float, close: float, rng: random.Random, d: int = 3) -> Bar:
    wick = abs(rng.gauss(0, HOURLY_VOL * 0.6))
    hi = max(open_, close) * (1 + wick * rng.random())
    lo = min(open_, close) * (1 - wick * rng.random())
    return Bar(ts, round(open_, d), round(hi, d), round(lo, d), round(close, d), round(rng.uniform(50, 400), 1))


def sample_hourly(start: datetime, end: datetime, inst: Instrument = GOLD) -> Iterator[list[Bar]]:
    """Deterministic synthetic hours that pass through the real monthly averages of gold. Other
    markets reuse gold's path scaled to their own rough price, and their own trading hours: demo
    data only, never shown as real."""
    anchors = _monthly_anchors()
    if inst.symbol != GOLD.symbol:
        scale = inst.ref_price / anchors[-1][1]
        anchors = [(t, p * scale) for t, p in anchors]
    d = _digits(inst)
    for (t0, p0), (t1, p1) in zip(anchors, anchors[1:] + [(None, None)]):
        if t1 is None:  # past the last anchor: free random walk up to now
            t1 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        if t1 <= start or t0 >= end:
            continue
        rng = random.Random(int(t0.timestamp()))
        hours = [t0 + timedelta(hours=i) for i in range(int((t1 - t0).total_seconds() // 3600))]
        hours = [h for h in hours if inst.is_open(h)]
        if not hours:
            continue
        # Brownian bridge in log space from p0 to p1 (or a plain walk for the open-ended tail).
        steps = [rng.gauss(0, HOURLY_VOL) for _ in hours]
        drift = 0.0 if p1 is None else (math.log(p1 / p0) - sum(steps)) / len(steps)
        price, chunk = p0, []
        for h, s in zip(hours, steps):
            nxt = price * math.exp(s + drift)
            if start <= h < end:
                chunk.append(_bar_from_walk(h, price, nxt, rng, d))
            price = nxt
        yield chunk


def subdivide(bar: Bar, n: int, step: int, rng: random.Random, d: int = 3) -> list[Bar]:
    """Split one bar into n bars of `step` seconds along a random path from its open to its
    close, kept inside the bar's high and low."""
    scale = (bar.high - bar.low) / math.sqrt(n) * 0.6
    steps = [rng.gauss(0, scale) for _ in range(n)]
    pull = (sum(steps) - (bar.close - bar.open)) / n  # bridge: the path ends at the close
    path, x = [bar.open], bar.open
    for z in steps:
        x += z - pull
        path.append(min(max(x, bar.low), bar.high))
    path[-1] = bar.close
    out = []
    for i in range(n):
        o, c = path[i], path[i + 1]
        w = abs(rng.gauss(0, scale * 0.3))
        out.append(Bar(bar.ts + timedelta(seconds=i * step), round(o, d), round(min(max(o, c) + w, bar.high), d),
                       round(max(min(o, c) - w, bar.low), d), round(c, d), round(bar.volume / n, 2)))
    return out


def sample_fine(start: datetime, end: datetime, step: int, inst: Instrument = GOLD) -> Iterator[list[Bar]]:
    """Demo minute (step=60) or second (step=1) bars, split from the sample hours."""
    d = _digits(inst)
    for chunk in sample_hourly(start.replace(minute=0, second=0, microsecond=0), end, inst):
        out = []
        for h in chunk:
            rng = random.Random(int(h.ts.timestamp()) * 7 + step)
            minutes = subdivide(h, 60, 60, rng, d)
            out += minutes if step == 60 else [s for m in minutes for s in subdivide(m, 60, 1, rng, d)]
        yield [b for b in out if start <= b.ts < end]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Monthly history since 1833
# ---------------------------------------------------------------------------

HISTORY_CSV = Path(__file__).parent / "data" / "gold_history_monthly.csv"


def monthly_history() -> list[Bar]:
    """Monthly gold prices in USD per ounce since 1833, from the public-domain datahub.io
    "gold-prices" dataset: annual averages from Timothy Green's tables to 1959 (the same value
    for every month of a year), then World Bank monthly averages. Each month has one price, so a
    bar opens at the previous month's price and closes at this month's."""
    bars, prev = [], None
    for line in HISTORY_CSV.read_text().splitlines()[1:]:
        ym, price = line.split(",")
        y, m = map(int, ym.split("-"))
        p = float(price)
        o = prev if prev is not None else p
        bars.append(Bar(datetime(y, m, 1, tzinfo=UTC), o, max(o, p), min(o, p), p))
        prev = p
    return bars


def load_monthly_history() -> int:
    """Store the monthly history (idempotent; a few thousand rows)."""
    return upsert(monthly_history(), "1mo")


def upsert(bars: list[Bar], tf: str = "1h", symbol: str = config.SYMBOL) -> int:
    if not bars:
        return 0
    with db.conn() as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO candles (symbol, tf, ts, open, high, low, close, volume)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (symbol, tf, ts) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high,
                 low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume""",
            [(symbol, tf, b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars],
        )
    return len(bars)


# The trading day an hourly bar belongs to: 17:00 New York to 17:00 New York (forex, metals,
# energy, indices, stocks; US stocks close at 16:00 so their day is the calendar day), or
# midnight to midnight UTC for crypto, which never closes.
DAY_SQL = {
    "ny17": "((ts AT TIME ZONE 'America/New_York') + interval '7 hours')::date",
    "utc": "(ts AT TIME ZONE 'UTC')::date",
}


def rebuild_daily(since: datetime, inst: Instrument = GOLD) -> None:
    """Recompute daily bars from hourly ones, for trading days touching `since` onward."""
    with db.conn() as c:
        c.execute(
            f"""
            WITH h AS (
              SELECT ts, open, high, low, close, volume, {DAY_SQL[inst.day]} AS d
              FROM candles WHERE symbol = %(s)s AND tf = '1h' AND ts >= %(since)s - interval '2 days'
            )
            INSERT INTO candles (symbol, tf, ts, open, high, low, close, volume)
            SELECT %(s)s, '1d', d::timestamp AT TIME ZONE 'UTC',
                   (array_agg(open ORDER BY ts))[1], max(high), min(low),
                   (array_agg(close ORDER BY ts DESC))[1], sum(volume)
            FROM h GROUP BY d
            ON CONFLICT (symbol, tf, ts) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high,
              low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume
            """,
            {"s": inst.symbol, "since": since},
        )


def _last_hour(inst: Instrument = GOLD) -> datetime | None:
    with db.conn() as c:
        row = c.execute(
            "SELECT max(ts) AS ts FROM candles WHERE symbol = %s AND tf = '1h'", (inst.symbol,)
        ).fetchone()
    return row["ts"]


def _keeps_seconds(inst: Instrument) -> bool:
    return inst.symbol in config.SECOND_SYMBOLS


def minute_days(inst: Instrument) -> int:
    """How many days of minute bars a market keeps: more for the day-trading markets (INTRADAY_SYMBOLS)."""
    days = config.MINUTE_DAYS if inst.symbol == GOLD.symbol else min(config.MINUTE_DAYS, config.MARKET_MINUTE_DAYS)
    return max(days, config.INTRADAY_DAYS) if inst.symbol in config.INTRADAY_SYMBOLS else days


def load_fine(source: str, inst: Instrument = GOLD) -> int:
    """Bring minute and second bars up to date and drop those past their retention window."""
    now = datetime.now(UTC)
    total = 0
    for tf, days, step, fetch in (
        ("1m", minute_days(inst), 60, dukascopy_minutes),
        ("1s", config.SECOND_DAYS if _keeps_seconds(inst) else 0, 1, dukascopy_seconds),
    ):
        if days <= 0:
            continue
        floor = now - timedelta(days=days)
        fetch_range = (lambda a, b: fetch(a, b, inst)) if source == "dukascopy" else (lambda a, b: sample_fine(a, b, step, inst))
        # Track how far this feed has got separately from what is stored: live quotes also
        # write recent bars, and must not make this skip hours it hasn't fetched yet.
        key = _key(f"fine_{source}_{tf}", inst)
        done = db.get_meta(key)
        # The oldest day fetched. When the window has grown since (a market added to INTRADAY_SYMBOLS),
        # the older part is fetched once, so the bars run back to the new floor without a hole.
        from_key = _key(f"fine_from_{source}_{tf}", inst)
        fetched_from = db.get_meta(from_key)
        if done:
            oldest = datetime.fromisoformat(fetched_from) if fetched_from else _oldest(inst, tf) or now
            if oldest > floor + timedelta(days=1):
                for chunk in fetch_range(floor, oldest):
                    total += upsert(chunk, tf, inst.symbol)
        # Re-fetch the hour before too, in case the feed published it late.
        start = max(floor, datetime.fromisoformat(done) - timedelta(hours=1)) if done else floor
        for chunk in fetch_range(start, now):
            total += upsert(chunk, tf, inst.symbol)
        db.set_meta(key, now.replace(minute=0, second=0, microsecond=0).isoformat())
        if not fetched_from or datetime.fromisoformat(fetched_from) > floor:
            db.set_meta(from_key, floor.isoformat())
        with db.conn() as c:
            c.execute("DELETE FROM candles WHERE symbol = %s AND tf = %s AND ts < %s", (inst.symbol, tf, floor))
    return total


def _load_fine_safely(source: str, inst: Instrument = GOLD) -> None:
    # Short-timeframe data is a bonus; a feed hiccup there must not stop hourly updates.
    try:
        load_fine(source, inst)
    except Exception:
        log.exception("%s minute/second update failed", inst.symbol)


def load(source: str, start: datetime, end: datetime, inst: Instrument = GOLD) -> int:
    fetch = dukascopy_hourly if source == "dukascopy" else sample_hourly
    previous = db.get_meta(_key("price_source", inst))
    if previous and previous != source:
        # Never mix sources: replace demo data entirely once real data arrives (and vice versa).
        with db.conn() as c:
            c.execute("DELETE FROM candles WHERE symbol = %s AND tf <> '1mo'", (inst.symbol,))
    total = 0
    for chunk in fetch(start, end, inst):
        total += upsert(chunk, "1h", inst.symbol)
    rebuild_daily(start, inst)
    db.set_meta(_key("price_source", inst), source)
    db.set_meta(_key("prices_updated_at", inst), datetime.now(UTC).isoformat(timespec="seconds"))
    return total


def backfill(source: str, since: date, inst: Instrument = GOLD) -> int:
    start = datetime(since.year, since.month, since.day, tzinfo=UTC)
    n = load(source, start, datetime.now(UTC), inst)
    _load_fine_safely(source, inst)
    return n


def _oldest(inst: Instrument = GOLD, tf: str = "1h") -> datetime | None:
    with db.conn() as c:
        row = c.execute("SELECT min(ts) AS t FROM candles WHERE symbol = %s AND tf = %s", (inst.symbol, tf)).fetchone()
    return row["t"] if row else None


def extend_history(source: str, inst: Instrument = GOLD) -> int:
    """Once per market, fetch hourly history from its history start (HISTORY_SINCE for gold,
    MARKET_HISTORY_SINCE for the rest) up to the oldest stored hour, so markets first loaded from a later
    date reach back as far as the feed goes.

    It walks back a year at a time from the oldest stored hour, so a run cut short (a deploy) leaves no
    hole: the next run carries on from the new oldest hour. A year with no prices at all means the feed
    starts later than that, and ends the walk."""
    since = _history_start(source, inst)
    key = _key("history_since", inst)
    first = _oldest(inst)
    if source != "dukascopy" or first is None or db.get_meta(key) == since.isoformat():
        return 0
    start = datetime(since.year, since.month, since.day, tzinfo=UTC)
    n = 0
    end = first
    while end > start + timedelta(days=7):
        chunk_start = max(start, end - timedelta(days=366))
        got = load(source, chunk_start, end, inst)
        n += got
        if not got:
            break
        end = chunk_start
    db.set_meta(key, since.isoformat())
    log.info("%s: extended hourly history back to %s: %d bars", inst.symbol, since, n)
    return n


def _history_start(source: str, inst: Instrument) -> date:
    if inst.symbol != GOLD.symbol:
        return config.MARKET_HISTORY_SINCE
    return config.HISTORY_SINCE if source == "dukascopy" else date(2010, 1, 1)


RECENT_DAYS = 30  # a market's first load fetches this much first, so its chart is current within seconds


def update(source: str, inst: Instrument = GOLD) -> int:
    """Bring one market's hourly, minute and second bars up to now.

    A market with no prices yet (or prices from another source) gets the last RECENT_DAYS first; its older
    history is filled in afterwards, a year at a time, by extend_all. Fetching from 2003 forward first left
    a newly opened market showing years-old prices until its whole history had arrived. Demo data is
    generated in full right away (it is offline and quick)."""
    now = datetime.now(UTC)
    done_key = _key(f"hourly_{source}_done", inst)
    last = _last_hour(inst)
    if last is None or db.get_meta(_key("price_source", inst)) != source:
        if source != "dukascopy":
            n = backfill(source, _history_start(source, inst), inst)
        else:
            n = load(source, now - timedelta(days=RECENT_DAYS), now, inst)
            _load_fine_safely(source, inst)
        db.set_meta(done_key, now.replace(minute=0, second=0, microsecond=0).isoformat())
        _refreshed[inst.symbol] = time.time()
        return n
    # Re-fetch from the hour before the last one fetched (the feed can publish an hour late). Live quotes
    # also write the newest bars, so how far the feed got is tracked apart from what is stored.
    done = db.get_meta(done_key)
    start = datetime.fromisoformat(done) - timedelta(hours=1) if done else last - timedelta(days=1)
    start = min(start, last + timedelta(hours=1))
    n = load(source, start, now, inst)
    db.set_meta(done_key, now.replace(minute=0, second=0, microsecond=0).isoformat())
    _load_fine_safely(source, inst)
    _refreshed[inst.symbol] = time.time()
    return n


def _to_update() -> list[Instrument]:
    """The core markets and every market in use, core first (gold leads the catalog)."""
    active = active_symbols()
    core = [i for i in ENABLED if i.symbol in CORE]
    rest = [i for i in ENABLED if i.symbol not in CORE and i.symbol in active]
    return [i for i in core + rest if not is_unavailable(i)]


def _update_one(source: str, inst: Instrument) -> int:
    if not _claim(inst):  # being loaded or refreshed right now by someone opening it
        return 0
    try:
        n = update(source, inst)
        _ready.add(inst.symbol)
        _errors.pop(inst.symbol, None)
        return n
    except NotCarried as e:
        log.warning("%s: %s", inst.symbol, e)
        _note_error(inst, e)
        if not has_prices(inst):
            mark_unavailable(inst)
    except Exception as e:
        log.exception("%s price update failed", inst.symbol)
        _note_error(inst, e)
    finally:
        _release(inst)
    return 0


def _note_error(inst: Instrument, e: Exception) -> None:
    _errors[inst.symbol] = (datetime.now(UTC).isoformat(timespec="seconds"), f"{type(e).__name__}: {e}"[:300])


def update_all(source: str) -> int:
    """Refresh the core markets and every market in use, UPDATE_WORKERS at a time, so one slow market
    or a long list doesn't leave the others waiting. One market failing doesn't stop the others."""
    t0, todo = time.time(), _to_update()
    if config.UPDATE_WORKERS <= 1 or len(todo) <= 1:
        n = sum(_update_one(source, i) for i in todo)
    else:
        with ThreadPoolExecutor(config.UPDATE_WORKERS, thread_name_prefix="update") as pool:
            n = sum(pool.map(lambda i: _update_one(source, i), todo))
    _last_run.update(started=datetime.fromtimestamp(t0, UTC).isoformat(timespec="seconds"),
                     seconds=round(time.time() - t0, 1), markets=len(todo), bars=n)
    return n


def extend_all(source: str, budget_seconds: float = 600) -> int:
    """Fill in older history for markets that have only their recent prices so far (see update), one
    market at a time and for at most `budget_seconds`, so it never holds up the price updates."""
    if source != "dukascopy":
        return 0
    t0 = time.monotonic()
    total = 0
    for inst in _to_update():
        if time.monotonic() - t0 > budget_seconds:
            break
        if db.get_meta(_key("history_since", inst)) == _history_start(source, inst).isoformat():
            continue
        if not has_prices(inst) or inst.symbol in _loading:
            continue
        # Not claimed (see _claim): it fetches only years before the stored prices, so the market's
        # regular refresh carries on meanwhile.
        try:
            total += extend_history(source, inst)
        except Exception:
            log.exception("%s history extension failed", inst.symbol)
    return total


# ---------------------------------------------------------------------------
# Markets loaded on first use
# ---------------------------------------------------------------------------

ACTIVE_DAYS = config.ACTIVE_DAYS
UNAVAILABLE_RETRY_DAYS = 7
_ready: set[str] = set()      # markets known to have stored prices
_loading: set[str] = set()    # markets being loaded for the first time right now
_touched: dict[str, float] = {}  # when each market's last use was saved (saved at most hourly)
_refreshed: dict[str, float] = {}  # when this process last brought each market up to date
_tried: dict[str, float] = {}      # when opening a market last started a fetch (retried at most once a minute)
_errors: dict[str, tuple[str, str]] = {}  # each market's last fetch error: (when, what), for /prices/health
_last_run: dict[str, object] = {}  # the last update_all run: start, seconds, markets, bars
_busy: set[str] = set()       # markets being fetched right now (first load, refresh or history)
_lock = threading.Lock()


def _claim(inst: Instrument) -> bool:
    """Mark a market as being fetched; False when something else is fetching it already."""
    with _lock:
        if inst.symbol in _busy:
            return False
        _busy.add(inst.symbol)
        return True


def _release(inst: Instrument) -> None:
    with _lock:
        _busy.discard(inst.symbol)


def is_stale(inst: Instrument) -> bool:
    """Not brought up to date by this process in the last two update intervals. Markets nobody has
    opened for ACTIVE_DAYS drop out of the updates, so their stored prices can be weeks old."""
    return time.time() - _refreshed.get(inst.symbol, 0) > 2 * config.UPDATE_INTERVAL_MIN * 60


def active_symbols() -> set[str]:
    """Markets in use: opened in the last ACTIVE_DAYS, or with open paper positions, pending orders, a
    running agent or price alerts."""
    since = datetime.now(UTC) - timedelta(days=ACTIVE_DAYS)
    with db.conn() as c:
        rows = c.execute(
            """SELECT substr(key, 11) AS s FROM meta WHERE key LIKE 'wanted_at:%%' AND updated_at >= %s
               UNION SELECT symbol FROM paper_positions WHERE closed_at IS NULL
               UNION SELECT symbol FROM paper_orders WHERE status = 'pending'
               UNION SELECT config->>'symbol' FROM paper_agents WHERE status = 'running'
               UNION SELECT symbol FROM price_alerts""", (since,)).fetchall()
    return {r["s"] for r in rows if r["s"]}


def _touch(inst: Instrument) -> None:
    now = time.time()
    if now - _touched.get(inst.symbol, 0) < 3600:
        return
    _touched[inst.symbol] = now
    db.set_meta(f"wanted_at:{inst.symbol}", datetime.now(UTC).isoformat(timespec="seconds"))


def is_unavailable(inst: Instrument) -> bool:
    """Marked as missing from the feed within the last week (it is checked again after that)."""
    when = db.get_meta(f"unavailable:{inst.symbol}")
    return bool(when) and datetime.fromisoformat(when) > datetime.now(UTC) - timedelta(days=UNAVAILABLE_RETRY_DAYS)


def unavailable_symbols() -> set[str]:
    since = datetime.now(UTC) - timedelta(days=UNAVAILABLE_RETRY_DAYS)
    with db.conn() as c:
        rows = c.execute("SELECT substr(key, 13) AS s FROM meta WHERE key LIKE 'unavailable:%%' AND updated_at >= %s",
                         (since,)).fetchall()
    return {r["s"] for r in rows}


def has_prices(inst: Instrument) -> bool:
    if inst.symbol in _ready:
        return True
    with db.conn() as c:
        row = c.execute("SELECT 1 FROM candles WHERE symbol = %s AND tf = '1h' LIMIT 1", (inst.symbol,)).fetchone()
    if row:
        _ready.add(inst.symbol)
    return bool(row)


def status(inst: Instrument) -> str:
    """"ready", "loading" (first load running), "unavailable" (the feed doesn't carry it) or "on_demand"
    (loads when opened)."""
    if inst.symbol in _loading:
        return "loading"
    if has_prices(inst):
        return "ready"
    return "unavailable" if is_unavailable(inst) else "on_demand"


def ensure(inst: Instrument, background: bool | None = None) -> str:
    """Someone opened this market: note it as in use and make sure its prices are current. With no prices
    yet it starts the first load ("loading"); with old prices (it had dropped out of the updates) it starts
    a refresh and stays "ready" meanwhile. Fetching runs in a background thread when the scheduler is on
    (the server) and is left to the scheduler's next run otherwise; background=False fetches right here
    (scripts, tests)."""
    _touch(inst)
    st = status(inst)
    if st == "unavailable" or st == "loading":
        return st
    if st == "ready" and (inst.symbol in CORE or not is_stale(inst)):
        return st
    if background is None:
        if not config.ENABLE_SCHEDULER:
            return st
        background = True
    if time.time() - _tried.get(inst.symbol, 0) < 60 or not _claim(inst):
        return "loading" if inst.symbol in _loading else st
    _tried[inst.symbol] = time.time()
    if st == "on_demand":
        with _lock:
            _loading.add(inst.symbol)
    if background:
        threading.Thread(target=_first_load, args=(config.PRICE_SOURCE, inst), daemon=True,
                         name=f"load-{inst.symbol}").start()
        return "loading" if st == "on_demand" else st
    _first_load(config.PRICE_SOURCE, inst)
    return status(inst)


def _first_load(source: str, inst: Instrument) -> None:
    """Load (or refresh) one market that someone opened. The caller has claimed it (_claim)."""
    try:
        update(source, inst)
        if has_prices(inst):
            with db.conn() as c:
                c.execute("DELETE FROM meta WHERE key = %s", (f"unavailable:{inst.symbol}",))
        else:
            mark_unavailable(inst)
    except NotCarried as e:  # the feed has no recent prices for it (see duka_point)
        log.warning("%s: %s", inst.symbol, e)
        _note_error(inst, e)
        if not has_prices(inst):
            mark_unavailable(inst)
    except Exception as e:  # network trouble is not a verdict: it is tried again next time
        log.exception("%s load failed", inst.symbol)
        _note_error(inst, e)
    finally:
        _loading.discard(inst.symbol)
        _release(inst)


def clear_old_unavailable_marks() -> int:
    """Once: forget "not carried" marks made before network errors were told apart from missing markets.
    Back then a rate limit or a dropped connection hid a market for a week. Markets the feed really lacks
    are found again by the next probe."""
    if db.get_meta("unavailable_reset") == "v1":
        return 0
    with db.conn() as c:
        n = c.execute("DELETE FROM meta WHERE key LIKE 'unavailable:%%'").rowcount
    db.set_meta("unavailable_reset", "v1")
    if n:
        log.info("cleared %d old unavailable marks", n)
    return n


def mark_unavailable(inst: Instrument) -> None:
    db.set_meta(f"unavailable:{inst.symbol}", datetime.now(UTC).isoformat(timespec="seconds"))


def probe(source: str = "dukascopy") -> dict[str, str]:
    """Check once that the feed carries each catalog market, without loading its history: the scale check
    (duka_point) reads one recent day. Markets it doesn't carry are marked unavailable and left out of the
    list. Network errors leave a market as it was, to be checked next time."""
    out: dict[str, str] = {}
    if source != "dukascopy":
        return out
    headers = {"User-Agent": "goldlab-ingest/1.0"}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        for inst in ENABLED:
            if inst.symbol == GOLD.symbol or db.get_meta(_key("duka_point", inst)) or is_unavailable(inst):
                continue
            try:
                duka_point(client, inst)
                out[inst.symbol] = "ok"
            except NotCarried:
                mark_unavailable(inst)
                out[inst.symbol] = "unavailable"
            except Exception as e:  # noqa: BLE001 - a network hiccup is not a verdict
                log.warning("probe %s failed: %s", inst.symbol, e)
                out[inst.symbol] = "error"
    if out:
        log.info("probe: %s", ", ".join(f"{k} {v}" for k, v in sorted(out.items())))
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["backfill", "update", "probe"])
    p.add_argument("--source", choices=["dukascopy", "sample"], default=config.PRICE_SOURCE)
    p.add_argument("--since", type=date.fromisoformat, default=None)
    p.add_argument("--symbol", default=GOLD.symbol)
    a = p.parse_args()
    db.migrate()
    load_monthly_history()
    if a.command == "probe":
        res = probe(a.source)
        for k, v in sorted(res.items()):
            print(f"{k:16} {v}")
        db.close()
        return
    if a.command == "backfill":
        from .instruments import get
        inst = get(a.symbol)
        n = backfill(a.source, a.since or _history_start(a.source, inst), inst)
    else:
        n = update_all(a.source)
    log.info("%s: stored %d hourly bars from %s", a.command, n, a.source)
    db.close()


if __name__ == "__main__":
    main()
