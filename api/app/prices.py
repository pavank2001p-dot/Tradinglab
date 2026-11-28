from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from . import config, db, ingest
from . import instruments as ins

router = APIRouter(prefix="/prices", tags=["prices"])

MAX_BARS = 5000


def market(symbol: str | None, load: bool = True) -> ins.Instrument:
    """The instrument for a request's symbol, or a 404 naming it. Opening a market that isn't loaded yet
    starts loading it (see app.ingest.ensure)."""
    try:
        inst = ins.get(symbol)
    except KeyError:
        raise HTTPException(404, f"Unknown market {symbol}. See /prices/markets for the list.")
    if load:
        ingest.ensure(inst)
    return inst


@router.get("/markets")
def markets():
    """Every market on offer, by asset class in display order, with its rules, latest price and status:
    ready, loading (its history is being fetched for the first time) or on_demand (loads when opened).
    Markets the price feed doesn't carry are left out."""
    syms = [i.symbol for i in ins.ENABLED]
    with db.conn() as c:
        rows = c.execute(
            """SELECT s.symbol, l.close, l.ts FROM unnest(%s::text[]) AS s(symbol)
               CROSS JOIN LATERAL (SELECT close, ts FROM candles WHERE symbol = s.symbol AND tf = '1h'
                                   ORDER BY ts DESC LIMIT 1) l""", (syms,)).fetchall()
        # How far back each market's prices go: the first daily bar, and the first minute bar (day trading).
        firsts = c.execute(
            """SELECT s.symbol, (SELECT min(ts) FROM candles WHERE symbol = s.symbol AND tf = '1d') AS d,
                      (SELECT min(ts) FROM candles WHERE symbol = s.symbol AND tf = '1m') AS m
               FROM unnest(%s::text[]) AS s(symbol)""", (syms,)).fetchall()
    last = {r["symbol"]: r for r in rows}
    first = {r["symbol"]: r for r in firsts}
    gone = ingest.unavailable_symbols()
    out = []
    for i in ins.ENABLED:
        r = last.get(i.symbol)
        if i.symbol in gone and not r:
            continue
        status = "ready" if r else "loading" if i.symbol in ingest._loading else "on_demand"
        out.append({**i.public(), "price": r["close"] if r else None,
                    "as_of": int(r["ts"].timestamp()) if r else None,
                    "has_seconds": i.symbol in config.SECOND_SYMBOLS,
                    "has_history": i.symbol == ins.GOLD.symbol, "status": status,
                    "history_from": _day(first.get(i.symbol, {}).get("d")),
                    "minutes_from": _day(first.get(i.symbol, {}).get("m"))})
    return {"default": ins.DEFAULT, "classes": ins.CLASSES, "markets": out}


def _day(ts: datetime | None) -> str | None:
    return ts.date().isoformat() if ts else None


@router.post("/open")
def open_market(symbol: str):
    """Called when someone picks a market: loads its prices if this is the first time. Returns its status."""
    inst = market(symbol, load=False)
    return {"symbol": inst.symbol, "status": ingest.ensure(inst)}


@router.get("/health")
def health():
    """How the price feed is doing, to diagnose markets that don't fill in: the scheduler's settings, the
    last update run, markets loading right now, markets marked as not carried, and each market's last fetch
    error. Holds no personal data."""
    with db.conn() as c:
        rows = c.execute("""SELECT symbol, max(ts) AS ts FROM candles WHERE tf = '1h' GROUP BY symbol""").fetchall()
    now = datetime.now(timezone.utc)
    newest = {r["symbol"]: round((now - r["ts"]).total_seconds() / 3600, 1) for r in rows}
    return {"scheduler": config.ENABLE_SCHEDULER, "source": config.PRICE_SOURCE, "backup": config.BACKUP_SOURCE or None,
            "interval_min": config.UPDATE_INTERVAL_MIN, "workers": config.UPDATE_WORKERS,
            "last_run": ingest._last_run or None,
            "feed_paused_seconds": max(0, round(ingest._feed_pause - __import__("time").monotonic())),
            "feed_pushbacks_in_a_row": ingest._feed_strikes,
            "feed_last_pushback": ingest._feed_last or None, "feed_last_success": ingest._feed_last_ok or None, "core": sorted(ins.CORE),
            "loading": sorted(ingest._loading), "unavailable": sorted(ingest.unavailable_symbols()),
            "errors": {k: {"at": a, "error": e} for k, (a, e) in sorted(ingest._errors.items())},
            "hours_since_newest_bar": dict(sorted(newest.items()))}


def _ts(v: int | None) -> datetime | None:
    return datetime.fromtimestamp(v, tz=timezone.utc) if v is not None else None


# Chart timeframe -> (stored timeframe it is built from, bucket). A bucket in seconds groups
# bars into fixed UTC slots; "week" and "month" group daily bars by calendar week and month.
TIMEFRAMES: dict[str, tuple[str, int | str | None]] = {
    "1s": ("1s", None), "5s": ("1s", 5), "15s": ("1s", 15), "30s": ("1s", 30),
    "1m": ("1m", None), "5m": ("1m", 300), "15m": ("1m", 900), "30m": ("1m", 1800),
    "1h": ("1h", None), "4h": ("1h", 14400),
    "1d": ("1d", None), "1w": ("1d", "week"), "1mo": ("1d", "month"),
}
Tf = Literal["1s", "5s", "15s", "30s", "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]


@router.get("/candles")
def candles(
    tf: Tf = "1h",
    start: int | None = Query(None, description="Unix seconds, inclusive"),
    end: int | None = Query(None, description="Unix seconds, exclusive"),
    limit: int = Query(1000, ge=1, le=MAX_BARS),
    symbol: str = config.SYMBOL,
):
    """Bars in ascending time order. With no start, returns the latest `limit` bars before `end`."""
    inst = market(symbol)
    base, bucket = TIMEFRAMES[tf]
    where = ["symbol = %s", "tf = %s"]
    args: list = [inst.symbol, base]
    if start is not None:
        where.append("ts >= %s")
        args.append(_ts(start))
    if end is not None:
        where.append("ts < %s")
        args.append(_ts(end))
    order = "ASC" if start is not None else "DESC"
    if bucket is None:
        sql = (
            "SELECT extract(epoch FROM ts)::bigint AS t, open AS o, high AS h, low AS l, close AS c, volume AS v "
            f"FROM candles WHERE {' AND '.join(where)} ORDER BY ts {order} LIMIT %s"
        )
    else:
        if isinstance(bucket, int):
            slot = f"to_timestamp(floor(extract(epoch FROM ts) / {bucket}) * {bucket})"
        else:
            slot = f"date_trunc('{bucket}', ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        sql = (
            f"SELECT extract(epoch FROM {slot})::bigint AS t, "
            "(array_agg(open ORDER BY ts))[1] AS o, max(high) AS h, min(low) AS l, "
            "(array_agg(close ORDER BY ts DESC))[1] AS c, sum(volume) AS v "
            f"FROM candles WHERE {' AND '.join(where)} GROUP BY 1 ORDER BY 1 {order} LIMIT %s"
        )
    with db.conn() as c:
        rows = c.execute(sql, (*args, limit)).fetchall()
        if tf == "1mo" and inst.symbol == ins.GOLD.symbol:
            rows = _with_history(c, rows, where, args, order, limit)
    if order == "DESC":
        rows.reverse()
    out = {"symbol": inst.symbol, "tf": tf, "bars": rows}
    if not rows:
        out["status"] = ingest.status(inst)  # "loading" while a market opened for the first time is fetched
    return out


def _with_history(c, rows: list[dict], where: list[str], args: list, order: str, limit: int) -> list[dict]:
    """Months before the first daily bar come from the stored monthly history (since 1833)."""
    first = c.execute("SELECT min(ts) AS t FROM candles WHERE symbol = %s AND tf = '1d'", (config.SYMBOL,)).fetchone()["t"]
    hist_where = [w for w in where if w != "tf = %s"] + ["tf = '1mo'"]
    hist_args = [a for i, a in enumerate(args) if i != 1]  # drop the tf argument
    if first is not None:
        hist_where.append("ts < date_trunc('month', %s AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'")
        hist_args.append(first)
    hist = c.execute(
        "SELECT extract(epoch FROM ts)::bigint AS t, open AS o, high AS h, low AS l, close AS c, volume AS v "
        f"FROM candles WHERE {' AND '.join(hist_where)} ORDER BY ts {order} LIMIT %s",
        (*hist_args, limit),
    ).fetchall()
    merged = sorted(rows + hist, key=lambda r: r["t"], reverse=order == "DESC")
    return merged[:limit]


@router.get("/summary")
def summary(symbol: str = config.SYMBOL):
    """Latest price, daily change, data coverage and where the data came from."""
    inst = market(symbol)
    with db.conn() as c:
        last = c.execute(
            "SELECT ts, close FROM candles WHERE symbol = %s AND tf = '1h' ORDER BY ts DESC LIMIT 1",
            (inst.symbol,),
        ).fetchone()
        span = c.execute(
            "SELECT min(ts) AS first, max(ts) AS last, count(*) AS n FROM candles WHERE symbol = %s AND tf = %s",
            (inst.symbol, "1h"),
        ).fetchone()
        monthly = c.execute("SELECT min(ts) AS first FROM candles WHERE symbol = %s AND tf = '1mo'",
                            (inst.symbol,)).fetchone()
        prev = None
        if last:
            prev = c.execute(
                """SELECT close FROM candles WHERE symbol = %s AND tf = '1h' AND ts <= %s - interval '24 hours'
                   ORDER BY ts DESC LIMIT 1""",
                (inst.symbol, last["ts"]),
            ).fetchone()
    key = (lambda k: k) if inst.symbol == ins.GOLD.symbol else (lambda k: f"{k}:{inst.symbol}")
    source = db.get_meta(key("price_source")) or "none"
    updated = db.get_meta(key("prices_updated_at"))
    if not last:
        return {"symbol": inst.symbol, "name": inst.name, "price": None, "source": source,
                "status": ingest.status(inst)}
    change = last["close"] - prev["close"] if prev else None
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "price": last["close"],
        "as_of": int(last["ts"].timestamp()),
        "change_24h": change,
        "change_24h_pct": (change / prev["close"] * 100) if prev else None,
        "first_bar": int(span["first"].timestamp()),
        "hourly_bars": span["n"],
        "first_month": int(monthly["first"].timestamp()) if monthly and monthly["first"] else None,
        "source": source,
        "updated_at": updated,
    }
