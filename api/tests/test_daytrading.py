"""Day trading in the backtester (intraday candles, session hours, flat by the close, daily limits) and the
price history behind it (longer minute history for a few markets, older hourly history for every market)."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import backtest as bt
from app import config, db, ingest, planner
from app import instruments as ins

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
T0 = int(datetime(2024, 1, 8, 14, tzinfo=UTC).timestamp())  # Monday 09:00 New York


def bars_from(closes, step=3600, start=T0):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append({"t": start + i * step, "o": prev, "h": max(prev, c) + 0.5, "l": min(prev, c) - 0.5, "c": c})
        prev = c
    return out


def cfg(**kw):
    base = dict(strategy="buy_and_hold", tf="1h", direction="long_only", capital=10_000, units=1, spread=0.0,
                swap_long=-1.0, swap_short=0, slippage=0, realistic_fills=False)
    base.update(kw)
    return bt.BacktestIn(**base)


def ny(t: int) -> datetime:
    return datetime.fromtimestamp(t, NY)


def test_day_trade_closes_before_the_rollover_and_pays_no_swap():
    rep = bt.run(cfg(day_trade=True), bars_from([100 + i * 0.1 for i in range(60)]))
    trades = rep["trades"]
    assert len(trades) >= 3
    for t in trades[:-1]:
        assert t["exit_reason"] == "session_end"
        assert ny(t["exit_time"]).hour == 16  # the last hourly candle before 17:00 New York
        assert t["swap"] == 0
    assert rep["days"]["traded"] == len(trades)
    held = bt.run(cfg(), bars_from([100 + i * 0.1 for i in range(60)]))
    assert held["trades"][0]["swap"] < 0  # the same trade held overnight pays swap


def test_new_york_session_opens_only_inside_its_hours_and_closes_after():
    rep = bt.run(cfg(session="new_york", day_trade=True), bars_from([100.0] * 72))
    assert rep["trades"]
    for t in rep["trades"]:
        o = ny(t["entry_time"])
        assert (o.hour, o.minute) >= (9, 30) and o.hour < 16
        if t["exit_reason"] != "end_of_test":
            assert t["exit_reason"] == "session_end" and ny(t["exit_time"]).hour == 16


def test_session_without_day_trade_holds_but_only_opens_in_hours():
    rep = bt.run(cfg(session="london"), bars_from([100.0] * 30, start=T0 + 12 * 3600))  # starts 02:00 London
    t = rep["trades"][0]
    assert datetime.fromtimestamp(t["entry_time"], ZoneInfo("Europe/London")).hour == 8
    assert t["exit_reason"] == "end_of_test"


def test_custom_hours_can_run_past_midnight():
    w = bt.session_window(cfg(session="custom", session_start="22:00", session_end="02:00", session_tz="UTC"))
    at = lambda h: int(datetime(2024, 1, 8, h, tzinfo=UTC).timestamp())  # noqa: E731
    assert bt.in_session(at(23), w) and bt.in_session(at(1), w)
    assert not bt.in_session(at(2), w) and not bt.in_session(at(12), w)


def test_max_trades_per_day(monkeypatch):
    monkeypatch.setattr(bt, "signals", lambda *a: [1, 0] * 40)
    bars = bars_from([100.0] * 80)
    free = bt.run(cfg(), bars)["trades"]
    capped = bt.run(cfg(max_trades_per_day=2), bars)["trades"]
    per_day: dict = {}
    for t in capped:
        d = bt.trading_date(t["entry_time"])
        per_day[d] = per_day.get(d, 0) + 1
    assert max(per_day.values()) == 2 and len(capped) < len(free)


def test_daily_loss_limit_closes_and_stops_for_the_day():
    # Falls 1 a bar for the first day (09:00 to 16:00 New York), then rises.
    closes = [100 - i for i in range(8)] + [93 + i * 0.5 for i in range(30)]
    rep = bt.run(cfg(units=100, daily_loss_limit_pct=2), bars_from(closes))
    first = rep["trades"][0]
    assert first["exit_reason"] == "daily_loss_limit"
    assert first["pnl"] <= -200
    second = rep["trades"][1]
    assert bt.trading_date(second["entry_time"]) > bt.trading_date(first["exit_time"])  # nothing more that day


def test_validation_of_day_trading_options():
    with pytest.raises(ValidationError, match="intraday"):
        cfg(tf="1d", day_trade=True)
    with pytest.raises(ValidationError, match="start and an end"):
        cfg(session="custom")
    with pytest.raises(ValidationError, match="HH:MM"):
        cfg(session="custom", session_start="9", session_end="10:00")
    assert cfg(session="asia", session_start="01:00").session_start is None


def test_five_minute_candles_are_built_from_minute_bars(client):
    start = datetime(2024, 1, 8, 14, tzinfo=UTC)
    ingest.upsert([ingest.Bar(start + timedelta(minutes=i), 100 + i, 100.5 + i, 99.5 + i, 100.2 + i) for i in range(10)], "1m")
    bars = bt.load_bars("5m", date(2024, 1, 8), None)
    assert [b["t"] for b in bars] == [int(start.timestamp()), int(start.timestamp()) + 300]
    assert bars[0]["o"] == 100 and bars[0]["c"] == 104.2 and bars[0]["h"] == 104.5 and bars[0]["l"] == 99.5


def test_intraday_backtest_through_the_api(client):
    client.post("/auth/signup", json={"email": "day@example.com", "password": "longpassword1"})
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    ingest.upsert([ingest.Bar(now - timedelta(minutes=600 - i), 100 + (i % 37) * 0.1, 100.3 + (i % 37) * 0.1,
                              99.8 + (i % 37) * 0.1, 100.1 + (i % 37) * 0.1) for i in range(600)], "1m")
    r = client.post("/backtests", json={"strategy": "ma_cross", "params": {"fast": 3, "slow": 8}, "tf": "15m",
                                        "start": (now - timedelta(days=2)).date().isoformat(), "day_trade": True,
                                        "max_trades_per_day": 3})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stats"]["bars"] in (40, 41) and "days" in body
    assert all(t["swap"] == 0 for t in body["trades"])
    assert client.post("/backtests", json={"strategy": "ma_cross", "tf": "1d", "day_trade": True}).status_code == 422


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_day_trading_markets_keep_more_minute_bars(monkeypatch):
    monkeypatch.setattr(config, "MINUTE_DAYS", 60)
    monkeypatch.setattr(config, "MARKET_MINUTE_DAYS", 14)
    monkeypatch.setattr(config, "INTRADAY_DAYS", 180)
    monkeypatch.setattr(config, "INTRADAY_SYMBOLS", {"EURUSD"})
    assert ingest.minute_days(ins.get("EURUSD")) == 180
    assert ingest.minute_days(ins.get("GBPUSD")) == 14
    assert ingest.minute_days(ins.GOLD) == 60


def test_a_longer_minute_window_fetches_the_older_part_once(client, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "INTRADAY_SYMBOLS", set())
    monkeypatch.setattr(config, "MINUTE_DAYS", 10)
    monkeypatch.setattr(ingest, "dukascopy_minutes", lambda s, e, i=None: calls.append((s, e)) or iter([]))
    monkeypatch.setattr(ingest, "dukascopy_seconds", lambda s, e, i=None: iter([]))
    ingest.load_fine("dukascopy")
    assert len(calls) == 1
    # Gold becomes a day-trading market: the next run fetches the 50 older days, then only new hours.
    monkeypatch.setattr(config, "INTRADAY_SYMBOLS", {"XAUUSD"})
    monkeypatch.setattr(config, "INTRADAY_DAYS", 60)
    calls.clear()
    ingest.load_fine("dukascopy")
    assert len(calls) == 2
    older = calls[0]
    assert 59 <= (datetime.now(UTC) - older[0]).days <= 60 and 9 <= (datetime.now(UTC) - older[1]).days <= 10
    calls.clear()
    ingest.load_fine("dukascopy")
    assert len(calls) == 1  # remembered


def test_extend_history_walks_back_a_year_at_a_time_until_the_feed_runs_out(client, monkeypatch):
    eur = ins.get("EURUSD")
    monkeypatch.setattr(config, "MARKET_HISTORY_SINCE", date(2003, 5, 1))
    ingest.upsert([ingest.Bar(datetime(2015, 1, 5, tzinfo=UTC), 1, 1, 1, 1)], symbol=eur.symbol)
    calls = []

    def fake_load(source, start, end, inst=None):
        calls.append(start)
        return 100 if start.year >= 2012 else 0  # the feed has nothing before 2012

    monkeypatch.setattr(ingest, "load", fake_load)
    assert ingest.extend_history("dukascopy", eur) == 300
    assert [c.year for c in calls] == [2014, 2013, 2012, 2011]
    assert ingest.extend_history("dukascopy", eur) == 0 and len(calls) == 4  # remembered


def test_market_list_shows_how_far_back_prices_go(client):
    ingest.backfill("sample", date.today() - timedelta(days=20))
    m = {x["symbol"]: x for x in client.get("/prices/markets").json()["markets"]}
    gold = m[ins.GOLD.symbol]
    assert gold["history_from"] and date.fromisoformat(gold["history_from"]) <= date.today() - timedelta(days=18)
    assert gold["minutes_from"]


def test_strategy_finder_says_when_a_market_has_less_history_than_asked(client):
    ingest.backfill("sample", date.today() - timedelta(days=4 * 365))
    with pytest.raises(HTTPException) as e:
        planner._window("1d", 10, ins.GOLD.symbol)
    assert "only go back to" in e.value.detail and "Pick 3 years or fewer" in e.value.detail
    bars, ins_, outs = planner._window("1d", 3, ins.GOLD.symbol)
    assert len(bars) > 300
    with db.conn():
        pass
