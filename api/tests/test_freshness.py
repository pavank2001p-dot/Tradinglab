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
