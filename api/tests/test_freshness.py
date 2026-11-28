"""Every market's prices stay current: recent prices first, refreshes in parallel and from where the feed got
to, old markets refreshed when opened, and network trouble never hiding a market."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import db, ingest, instruments

UTC = timezone.utc
XLE = instruments.get("XLEUSUSD")


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    for name in ("_ready", "_loading", "_busy"):
        monkeypatch.setattr(ingest, name, set())
    for name in ("_touched", "_refreshed", "_tried"):
        monkeypatch.setattr(ingest, name, {})


def bar(sym, ts, price=90.0):
    ingest.upsert([ingest.Bar(ts, price, price, price, price)], "1h", sym)


def test_first_load_fetches_recent_prices_first_then_history(client, monkeypatch):
    calls = []
    monkeypatch.setattr(ingest, "load", lambda source, start, end, inst: calls.append((start, end)) or 5)
    monkeypatch.setattr(ingest, "_load_fine_safely", lambda source, inst: None)
    ingest.update("dukascopy", XLE)
    start, end = calls[0]
    assert len(calls) == 1 and end - start == timedelta(days=ingest.RECENT_DAYS)
    assert datetime.now(UTC) - end < timedelta(minutes=1)
    assert db.get_meta(ingest._key("history_since", XLE)) is None  # older years still to come
    # The history filler then walks back from the oldest stored hour, a year at a time.
    oldest = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=30)
    bar(XLE.symbol, oldest)
    monkeypatch.setattr(ingest, "active_symbols", lambda: {XLE.symbol})
    calls.clear()
    ingest.extend_all("dukascopy")
    assert calls and calls[0][1] == oldest and all(a[0] == b[1] for a, b in zip(calls, calls[1:]))
    assert db.get_meta(ingest._key("history_since", XLE)) == ingest._history_start("dukascopy", XLE).isoformat()


def test_refresh_starts_where_the_feed_got_to(client, monkeypatch):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    bar(XLE.symbol, now)  # a live quote wrote this hour
    db.set_meta(ingest._key("price_source", XLE), "dukascopy")
    db.set_meta(ingest._key("hourly_dukascopy_done", XLE), (now - timedelta(hours=1)).isoformat())
    calls = []
    monkeypatch.setattr(ingest, "load", lambda source, start, end, inst: calls.append(start) or 1)
    monkeypatch.setattr(ingest, "_load_fine_safely", lambda source, inst: None)
    ingest.update("dukascopy", XLE)
    assert calls == [now - timedelta(hours=2)]
    assert not ingest.is_stale(XLE)


def test_hourly_fetch_reads_only_the_hours_asked_for(monkeypatch):
    urls = []
    monkeypatch.setattr(ingest, "duka_point", lambda client, inst: 1000.0)
    monkeypatch.setattr(ingest, "_get", lambda client, url: urls.append(url) or None)
    now = datetime.now(UTC)
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    list(ingest.dukascopy_hourly(start, now, XLE))
    ticks = [u for u in urls if u.endswith("h_ticks.bi5")]
    assert 1 <= len(ticks) <= 2  # the two completed hours, not every hour since midnight
    assert len(urls) <= 3


def test_network_trouble_never_hides_a_market(client, monkeypatch):
    def down(source, inst):
        raise ingest.FeedError("giving up on https://datafeed.dukascopy.com/...")

    monkeypatch.setattr(ingest, "update", down)
    assert ingest.ensure(XLE, background=False) == "on_demand"
    assert not ingest.is_unavailable(XLE)
    syms = {m["symbol"] for m in client.get("/prices/markets").json()["markets"]}
    assert XLE.symbol in syms

    def missing(source, inst):
        raise ingest.NotCarried("No recent prices")

    monkeypatch.setattr(ingest, "update", missing)
    monkeypatch.setattr(ingest, "_tried", {})
    assert ingest.ensure(XLE, background=False) == "unavailable"


def test_opening_a_market_with_old_prices_refreshes_it(client, monkeypatch):
    bar(XLE.symbol, datetime.now(UTC) - timedelta(days=20))
    done = []
    monkeypatch.setattr(ingest, "update", lambda source, inst: done.append(inst.symbol) or ingest._refreshed.update({inst.symbol: time.time()}))
    assert ingest.ensure(XLE, background=False) == "ready" and done == [XLE.symbol]
    assert ingest.ensure(XLE, background=False) == "ready" and done == [XLE.symbol]  # fresh now


def test_updates_run_several_markets_at_once(client, monkeypatch):
    threads = set()
    monkeypatch.setattr(ingest.config, "UPDATE_WORKERS", 4)

    def slow(source, inst):
        threads.add(threading.current_thread().name)
        time.sleep(0.05)
        return 1

    monkeypatch.setattr(ingest, "update", slow)
    t0 = time.monotonic()
    n = ingest.update_all("sample")
    assert n == len(instruments.CORE) and len(threads) > 1
    assert time.monotonic() - t0 < 0.05 * len(instruments.CORE)
    # A market being loaded by someone opening it is left to that load.
    ingest._busy.add("XAUUSD")
    assert ingest.update_all("sample") == len(instruments.CORE) - 1


def test_old_unavailable_marks_are_cleared_once(client):
    db.set_meta("unavailable_reset", "")  # the client fixture's startup ran on a truncated table
    ingest.mark_unavailable(XLE)
    assert ingest.clear_old_unavailable_marks() == 1 and not ingest.is_unavailable(XLE)
    ingest.mark_unavailable(XLE)
    assert ingest.clear_old_unavailable_marks() == 0 and ingest.is_unavailable(XLE)  # only once


def test_health_shows_fetch_errors(client, monkeypatch):
    def down(source, inst):
        raise ingest.FeedError("giving up on https://datafeed.dukascopy.com/x")

    monkeypatch.setattr(ingest, "update", down)
    ingest.update_all("dukascopy")
    h = client.get("/prices/health").json()
    assert "FeedError" in h["errors"]["XAUUSD"]["error"] and h["last_run"]["markets"] == len(instruments.CORE)


class FakeClient:
    def __init__(self, codes):
        self.codes, self.calls = list(codes), 0

    def get(self, url):
        import httpx
        self.calls += 1
        code = self.codes.pop(0)
        return httpx.Response(code, headers={"Retry-After": "0"}, content=b"", request=httpx.Request("GET", url))


def test_feed_push_back_pauses_and_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ingest.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(ingest, "_feed_pause", 0.0)
    monkeypatch.setattr(ingest, "_feed_strikes", 0)
    c = FakeClient([429, 503, 200])
    assert ingest._get(c, "https://datafeed.dukascopy.com/x") == b"" and c.calls == 3
    assert ingest._feed_strikes == 0  # a success resets the pause
    c = FakeClient([429] * ingest.ATTEMPTS)
    with pytest.raises(ingest.FeedError, match="HTTP 429"):
        ingest._get(c, "https://datafeed.dukascopy.com/y")
    assert ingest._feed_pause > time.monotonic()  # every download waits out the push-back
    assert ingest._feed_last["why"].startswith("HTTP 429") and ingest._feed_last["url"].endswith("/y")
    monkeypatch.setattr(ingest, "_feed_pause", 0.0)
    monkeypatch.setattr(ingest, "_feed_strikes", 0)
    assert ingest._get(FakeClient([404]), "https://datafeed.dukascopy.com/z") is None


def yahoo_answer(start, n, step, price, gmtoffset=0):
    ts = [int((start + timedelta(seconds=step * i)).timestamp()) for i in range(n)]
    closes = [price + i * 0.01 * price / 100 for i in range(n)]
    return {"meta": {"gmtoffset": gmtoffset}, "timestamp": ts,
            "indicators": {"quote": [{"open": closes, "high": [c * 1.001 for c in closes],
                                      "low": [c * 0.999 for c in closes], "close": closes, "volume": [1] * n}]}}


def test_yahoo_symbols_cover_the_catalog():
    from app import yahoo
    assert yahoo.symbol(instruments.get("PGUSUSD")) == "PG"
    assert yahoo.symbol(instruments.get("EURUSD")) == "EURUSD=X"
    assert yahoo.symbol(instruments.get("COPPERCMDUSD")) == "HG=F"
    assert yahoo.symbol(instruments.get("USA500IDXUSD")) == "^GSPC"
    assert yahoo.symbol(instruments.get("LNKUSD")) == "LINK-USD"
    assert yahoo.symbol(instruments.get("DIESELCMDUSD")) is None
    missing = [i.symbol for i in instruments.ALL if yahoo.symbol(i) is None]
    assert len(missing) <= 3, missing
    assert yahoo.scale_for(550, 5.5) == 0.01 and yahoo.scale_for(165, 165) == 1.0


def test_backup_source_fills_a_market_the_main_feed_refuses(client, monkeypatch):
    from app import yahoo
    wheat = instruments.get("WHEATCMDUSX")
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    calls = []

    def fake_get(sym, params):
        calls.append((sym, params["interval"]))
        start = datetime.fromtimestamp(params["period1"], UTC)
        if params["interval"] == "60m":
            return yahoo_answer(now - timedelta(hours=48), 48, 3600, 550.0)  # cents a bushel
        if params["interval"] == "1d":
            return yahoo_answer(start, 5, 86400, 540.0)
        return yahoo_answer(now - timedelta(minutes=30), 30, 60, 551.0)

    def refused(source, inst):
        raise ingest.FeedError("giving up on https://datafeed.dukascopy.com/x (HTTP 503)")

    monkeypatch.setattr(ingest.config, "BACKUP_SOURCE", "yahoo")
    monkeypatch.setattr(yahoo, "_get", fake_get)
    monkeypatch.setattr(ingest, "update", refused)
    monkeypatch.setattr(ingest, "_feed_strikes", 0)
    assert ingest.ensure(wheat, background=False) == "ready"
    assert ("ZW=F", "60m") in calls
    with db.conn() as c:
        last = c.execute("SELECT close FROM candles WHERE symbol = %s AND tf = '1h' ORDER BY ts DESC LIMIT 1",
                         (wheat.symbol,)).fetchone()["close"]
        daily = c.execute("SELECT count(*) AS n FROM candles WHERE symbol = %s AND tf = '1d'", (wheat.symbol,)).fetchone()["n"]
    assert 5 < last < 6  # cents turned into dollars, the market's own scale
    assert daily >= 2 and not ingest.is_unavailable(wheat)
    # While the main feed refuses everything, markets go straight to the backup.
    monkeypatch.setattr(ingest, "_feed_strikes", 5)
    monkeypatch.setattr(ingest, "update", lambda s, i: pytest.fail("main feed tried while it is down"))
    calls.clear()
    ingest.fetch_market("dukascopy", wheat)
    assert calls and calls[0][0] == "ZW=F"


def test_backup_off_keeps_the_main_feeds_error(client, monkeypatch):
    monkeypatch.setattr(ingest.config, "BACKUP_SOURCE", "")
    monkeypatch.setattr(ingest, "update", lambda s, i: (_ for _ in ()).throw(ingest.FeedError("down")))
    with pytest.raises(ingest.FeedError):
        ingest.fetch_market("dukascopy", XLE)
