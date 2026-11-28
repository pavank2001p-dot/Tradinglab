"""Backup price source: Yahoo Finance's public chart data (no key).

Used only when the main feed (Dukascopy) refuses a download or doesn't carry a market (see
app.ingest.fetch_market). It covers stocks, ETFs, currency pairs, indices, commodity futures and crypto.
Limits: hourly bars for the last 730 days, minute bars for the last 7 days, daily bars for decades.

Prices are matched to each market's scale: commodity futures are often quoted in cents (wheat at 550
for $5.50) and are divided by the power of ten that brings them nearest the market's stored or rough price.
Commodities and indices come from futures or the cash index rather than Dukascopy's CFDs, so their level
can differ slightly from the main feed (futures carry a premium); when the main feed comes back, its bars
replace these.

Unofficial: Yahoo can change or limit this endpoint without notice, and its terms restrict commercial use.
Set BACKUP_SOURCE= (empty) to turn it off.
"""

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import config, db
from .instruments import Instrument

log = logging.getLogger("yahoo")
UTC = timezone.utc
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; tradinglab/1.0)", "Accept": "application/json"}

# Our symbol -> Yahoo symbol, for everything that isn't a plain US stock, ETF, currency pair or coin.
SPECIAL = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "XPTCMDUSD": "PL=F", "XPDCMDUSD": "PA=F", "COPPERCMDUSD": "HG=F",
    "LIGHTCMDUSD": "CL=F", "BRENTCMDUSD": "BZ=F", "GASCMDUSD": "NG=F",
    "WHEATCMDUSX": "ZW=F", "SOYBEANCMDUSX": "ZS=F", "COFFEECMDUSX": "KC=F", "COCOACMDUSD": "CC=F",
    "COTTONCMDUSX": "CT=F", "OJUICECMDUSX": "OJ=F",
    "USA500IDXUSD": "^GSPC", "USATECHIDXUSD": "^NDX", "USA30IDXUSD": "^DJI", "USSC2000IDXUSD": "^RUT",
    "DEUIDXEUR": "^GDAXI", "GBRIDXGBP": "^FTSE", "FRAIDXEUR": "^FCHI", "EUSIDXEUR": "^STOXX50E",
    "ESPIDXEUR": "^IBEX", "NLDIDXEUR": "^AEX", "CHEIDXCHF": "^SSMI", "JPNIDXJPY": "^N225",
    "HKGIDXHKD": "^HSI", "AUSIDXAUD": "^AXJO", "INDIDXUSD": "^NSEI",
    "UNIUSD": "UNI7083-USD",
}
# No close match on Yahoo: gas oil and sugar are quoted per tonne in London (Yahoo has New York contracts in
# other units), and the China A50 index has no reliable free series.
NONE = {"DIESELCMDUSD", "SUGARCMDUSD", "CHIIDXUSD"}

_gate = threading.Lock()
_next = 0.0
_pause = 0.0
MIN_GAP = 0.5


def symbol(inst: Instrument) -> str | None:
    """The Yahoo symbol for a market, or None when Yahoo has no close match."""
    if inst.symbol in NONE:
        return None
    if inst.symbol in SPECIAL:
        return SPECIAL[inst.symbol]
    if inst.asset_class in ("stocks", "etfs"):
        return inst.symbol.removesuffix("USUSD").replace(".", "-")
    if inst.asset_class == "forex":
        return f"{inst.symbol}=X"
    if inst.asset_class == "crypto":
        if inst.live.startswith("BINANCE:") and inst.live.endswith("USDT"):
            return inst.live.removeprefix("BINANCE:").removesuffix("USDT") + "-USD"
        return inst.symbol.removesuffix("USD") + "-USD"
    return None


class YahooError(RuntimeError):
    pass


def _get(sym: str, params: dict) -> dict:
    """One chart request, at most one at a time and MIN_GAP apart, pausing everyone when Yahoo throttles."""
    global _next, _pause
    for attempt in range(4):
        with _gate:
            wait = max(_next, _pause) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                r = httpx.get(CHART.format(symbol=sym), params=params, headers=HEADERS, timeout=20,
                              follow_redirects=True)
            except httpx.HTTPError as e:
                _next = time.monotonic() + MIN_GAP * 2 ** attempt
                log.warning("yahoo %s: %s", sym, e)
                continue
            _next = time.monotonic() + MIN_GAP
        if r.status_code == 429 or r.status_code >= 500:
            _pause = time.monotonic() + min(60.0, 5.0 * 2 ** attempt)
            log.warning("yahoo %s: HTTP %s", sym, r.status_code)
            continue
        if r.status_code == 404:
            raise YahooError(f"Yahoo has no {sym}")
        r.raise_for_status()
        chart = r.json().get("chart") or {}
        if chart.get("error"):
            raise YahooError(f"Yahoo {sym}: {chart['error'].get('description') or chart['error']}")
        res = (chart.get("result") or [None])[0]
        if not res:
            raise YahooError(f"Yahoo {sym}: empty answer")
        return res
    raise YahooError(f"Yahoo {sym}: gave up after retries")


def bars(sym: str, interval: str, start: datetime, end: datetime):
    """Bars for [start, end) as app.ingest.Bar, oldest first, unscaled."""
    from .ingest import Bar
    res = _get(sym, {"interval": interval, "period1": int(start.timestamp()), "period2": int(end.timestamp()),
                     "includePrePost": "false"})
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    offset = int((res.get("meta") or {}).get("gmtoffset") or 0)
    out = []
    for i, t in enumerate(ts):
        o, h, lo, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        if None in (o, h, lo, c) or not c > 0:
            continue
        v = (q.get("volume") or [0] * len(ts))[i] or 0
        when = datetime.fromtimestamp(t, UTC)
        if interval == "1d":  # stamped like our daily bars: the trading date, at midnight UTC
            d = datetime.fromtimestamp(t + offset, UTC).date()
            when = datetime(d.year, d.month, d.day, tzinfo=UTC)
        elif interval == "60m":  # stock and index hours start at :30 there; ours are on the hour
            when = when.replace(minute=0, second=0, microsecond=0)
        out.append(Bar(when, float(o), float(max(h, o, c)), float(min(lo, o, c)),
                       float(c), float(v)))
    # Merge bars that land on the same slot (a half-hour bar floored into the hour before it).
    merged: dict[datetime, Bar] = {}
    for b in out:
        m = merged.get(b.ts)
        if m is None:
            merged[b.ts] = b
        else:
            m.high, m.low, m.close, m.volume = max(m.high, b.high), min(m.low, b.low), b.close, m.volume + b.volume
    return list(merged.values())


def _stored_close(inst: Instrument) -> float | None:
    with db.conn() as c:
        row = c.execute("SELECT close FROM candles WHERE symbol = %s AND tf = '1h' ORDER BY ts DESC LIMIT 1",
                        (inst.symbol,)).fetchone()
    return row["close"] if row else None


def scale_for(raw: float, ref: float) -> float:
    """The power of ten that brings a Yahoo price nearest the reference (1, 0.01 for cents...)."""
    if raw <= 0 or ref <= 0:
        return 1.0
    return 10.0 ** round(math.log10(ref / raw))


def _scaled(bs, k: float, decimals: int):
    if k == 1.0:
        return bs
    from .ingest import Bar
    r = lambda x: round(x * k, decimals + 2)  # noqa: E731
    return [Bar(b.ts, r(b.open), r(b.high), r(b.low), r(b.close), b.volume) for b in bs]


def update(inst: Instrument) -> int:
    """Bring one market up to date from Yahoo: hourly bars from the newest stored hour (or the last 730 days
    for a market with none), daily bars before that, and minute bars for the last few days."""
    from . import ingest
    sym = symbol(inst)
    if not sym:
        raise YahooError(f"no Yahoo symbol for {inst.symbol}")
    now = datetime.now(UTC)
    last = ingest._last_hour(inst)
    h_start = max(last - timedelta(days=1), now - timedelta(days=729)) if last else now - timedelta(days=729)
    hourly = bars(sym, "60m", h_start, now)
    if not hourly:
        raise YahooError(f"Yahoo {sym}: no recent prices")
    ref = _stored_close(inst) or inst.ref_price
    k = scale_for(hourly[-1].close, ref)
    # Only completed hours: the main feed's rule, and the live feed fills the hour in progress.
    hour_now = now.replace(minute=0, second=0, microsecond=0)
    n = ingest.upsert(_scaled([b for b in hourly if b.ts < hour_now], k, inst.decimals), "1h", inst.symbol)
    if not last:
        # A market with nothing stored: daily bars before the hourly ones, as far back as Yahoo goes.
        first_hour = hourly[0].ts
        daily = [b for b in bars(sym, "1d", datetime(2003, 5, 1, tzinfo=UTC), first_hour) if b.ts < first_hour]
        ingest.upsert(_scaled(daily, k, inst.decimals), "1d", inst.symbol)
    ingest.rebuild_daily(h_start, inst)
    days = min(7, ingest.minute_days(inst))
    if days > 0:
        try:
            minute = bars(sym, "1m", now - timedelta(days=days), now)
            minute = [b for b in minute if b.ts < now.replace(second=0, microsecond=0)]
            ingest.upsert(_scaled(minute, k, inst.decimals), "1m", inst.symbol)
            with db.conn() as c:
                c.execute("DELETE FROM candles WHERE symbol = %s AND tf = '1m' AND ts < %s",
                          (inst.symbol, now - timedelta(days=ingest.minute_days(inst))))
        except (YahooError, httpx.HTTPError) as e:
            log.warning("%s minute bars from Yahoo failed: %s", inst.symbol, e)
    db.set_meta(f"backup_updated_at:{inst.symbol}", now.isoformat(timespec="seconds"))
    log.info("%s: %d hourly bars from Yahoo (%s, x%g)", inst.symbol, n, sym, k)
    return n


def enabled() -> bool:
    return config.BACKUP_SOURCE == "yahoo"
