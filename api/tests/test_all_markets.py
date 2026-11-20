"""Every lab tool runs on any market, not only gold: scenarios, the builder, the agent, replay, sessions,
the weekly challenge, the strategy finder, alerts, the Daily Candle, Stay or Bail and the assistant's tools."""

import math
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from app import agent, assistant, daily, db, ingest, instruments, practice, scenarios
from app.live import feed, feed_of

UTC = timezone.utc
EUR = instruments.get("EURUSD")
BTC = instruments.get("BTCUSD")
SPX = instruments.get("USA500IDXUSD")

RULES = {"name": "Cross", "long_entry": [{"left": {"ind": "sma", "n": 5}, "op": "crosses_above", "right": {"ind": "sma", "n": 20}}],
         "long_exit": [], "short_entry": [{"left": {"ind": "sma", "n": 5}, "op": "crosses_below", "right": {"ind": "sma", "n": 20}}],
         "short_exit": []}


def signup(client, email="markets@example.com"):
    assert client.post("/auth/signup", json={"email": email, "password": "longenough"}).status_code == 201


@pytest.fixture(autouse=True)
def no_live_feed(monkeypatch):
    for f in (feed, feed_of("BTCUSD"), feed_of("EURUSD"), feed_of("USA500IDXUSD")):
        if f is not None:
            monkeypatch.setattr(f, "price", None)
            monkeypatch.setattr(f, "t", None)


def walk(n: int, start: float, vol: float, seed: int = 1, drift: float = 0.0) -> list[float]:
    rnd, px, out = random.Random(seed), start, []
    for _ in range(n):
        px *= math.exp(rnd.gauss(drift, vol))
        out.append(px)
    return out


def put(symbol: str, tf: str, start: datetime, prices: list[float], step: timedelta, wiggle: float = 0.002):
    bars, prev = [], prices[0]
    for i, p in enumerate(prices):
        bars.append(ingest.Bar(start + step * i, prev, max(prev, p) * (1 + wiggle), min(prev, p) * (1 - wiggle), p))
        prev = p
    ingest.upsert(bars, tf, symbol)


def daily_bars(symbol: str, prices: list[float]):
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=len(prices))
    put(symbol, "1d", start, prices, timedelta(days=1))


def hourly_bars(symbol: str, prices: list[float], end: datetime | None = None) -> datetime:
    end = (end or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    put(symbol, "1h", end - timedelta(hours=len(prices)), prices, timedelta(hours=1), wiggle=0.0002)
    last = prices[-1]
    ingest.upsert([ingest.Bar(datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=1), last, last, last, last)],
                  "1m", symbol)
    return end


def test_market_specs_are_published(client):
    m = {x["symbol"]: x for x in client.get("/prices/markets").json()["markets"]}
    assert m["EURUSD"]["tick"] == 0.00001 and m["EURUSD"]["tick_value"] == 1.0  # $1 per point per 100,000-unit lot
    assert m["XAUUSD"]["tick"] == 0.01 and m["XAUUSD"]["tick_value"] == 1.0     # 1 cent on 100 oz
    assert m["BTCUSD"]["weekends"] and not m["AAPLUSUSD"]["weekends"]
    assert EUR.units_text(10_000) == "10,000 units" and instruments.GOLD.units_text(1) == "1 oz"
    assert BTC.year_days == 365 and EUR.year_days == 252


def test_scenarios_on_forex_and_crypto(client):
    signup(client)
    daily_bars("EURUSD", walk(800, 1.1, 0.005))
    r = client.post("/scenarios", json={"symbol": "EURUSD", "units": 10_000, "horizon_days": 30, "lookback_years": 2})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["symbol"] == "EURUSD" and out["market"]["spread"] == EUR.spread and 0.5 < out["entry"] < 2
    assert out["entry"] == round(out["entry"], 5) and out["market"]["decimals"] == 5
    # A stop below a 1.1 entry is fine for EUR/USD, though it would be nonsense for gold.
    stop = round(out["entry"] - 0.01, 5)
    r = client.post("/scenarios", json={"symbol": "EURUSD", "units": 10_000, "stop": stop, "lookback_years": 2})
    assert r.status_code == 200 and r.json()["loss_at_stop"] > 0
    # Crypto trades every day, so its paths step through weekends.
    assert len(scenarios.trading_days(date(2026, 11, 6), 7, weekends=True)) == 7
    daily_bars("BTCUSD", walk(800, 90_000, 0.03, seed=2))
    btc = client.post("/scenarios", json={"symbol": "BTCUSD", "units": 0.1, "horizon_days": 7, "lookback_years": 2}).json()
    assert btc["trading_days"] == 7 and btc["market"]["swap_per_night"] < 0
    assert client.post("/scenarios", json={"symbol": "NOPE"}).status_code == 422


def test_builder_preview_and_sweep_on_an_index(client):
    signup(client)
    daily_bars("USA500IDXUSD", walk(900, 5000, 0.01, seed=4, drift=0.0005))
    r = client.post("/custom-strategies/preview", json={"symbol": "USA500IDXUSD", "rules": RULES, "years": 2})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["symbol"] == "USA500IDXUSD" and out["candles"][-1]["c"] > 1000 and out["stats"]["trades"] > 0
    sw = client.post("/custom-strategies/sweep", json={"symbol": "USA500IDXUSD", "rules": RULES, "years": 2,
                                                         "lane": "long_entry", "index": 0, "side": "left", "field": "n",
                                                         "values": [3, 5, 8]})
    assert sw.status_code == 200, sw.text
    assert len(sw.json()) == 3
    # Gold has no prices here, so the same rules on gold have nothing to test.
    assert client.post("/custom-strategies/preview", json={"rules": RULES, "years": 2}).status_code == 422


def test_agent_tests_and_trades_another_market(client):
    signup(client)
    daily_bars("EURUSD", walk(900, 1.1, 0.006, seed=5))
    r = client.post("/agent/past", json={"symbol": "EURUSD", "strategy": "ma_cross",
                                         "params": {"fast": 5, "slow": 20, "ema": 0}, "years": 2})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["symbol"] == "EURUSD"

    up = [1.10 + i * 0.0004 for i in range(80)]
    hourly_bars("EURUSD", up)
    s = client.post("/agent/start", json={"symbol": "EURUSD", "strategy": "ma_cross", "params": {"fast": 5, "slow": 20, "ema": 0},
                                          "tf": "1h", "stop_loss_pct": 1, "size_pct": 100})
    assert s.status_code == 200, s.text
    pos = client.get("/paper?symbol=EURUSD").json()["positions"]
    assert len(pos) == 1 and pos[0]["symbol"] == "EURUSD" and pos[0]["side"] == "long"
    assert pos[0]["stop_loss"] == round((up[-1] + EUR.spread) * 0.99, 5)
    log = client.get("/agent").json()["log"]
    assert any("Euro / US dollar" in e["message"] and "units" in e["message"] for e in log)


def test_replay_sessions_and_challenge_on_other_markets(client, monkeypatch):
    signup(client)
    t0 = datetime(2025, 3, 3, tzinfo=UTC)  # a Monday
    put("BTCUSD", "1h", t0 - timedelta(days=10), walk(24 * 40, 90_000, 0.004, seed=6), timedelta(hours=1))
    put("BTCUSD", "1d", t0 - timedelta(days=60), walk(70, 90_000, 0.02, seed=7), timedelta(days=1))

    r = client.get("/practice/replay", params={"tf": "1h", "day": "2025-03-03", "symbol": "BTCUSD"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["symbol"] == "BTCUSD" and rep["leverage"] == BTC.max_leverage and rep["bars"][0]["c"] > 10_000
    # Bitcoin's cap is 1:10, tighter than the replay's 1:20.
    big = {"side": "long", "units": 1.5, "entry_bar": 0, "exit_bar": 3}
    settle = {"tf": "1h", "start": rep["start"], "end": rep["end"], "symbol": "BTCUSD", "trades": [big]}
    assert client.post("/practice/replay/settle", json=settle).status_code == 422
    settle["trades"] = [{**big, "units": 0.5}]
    assert client.post("/practice/replay/settle", json=settle).json()["trades"] == 1

    s = client.post("/practice/sessions", json={"symbol": "BTCUSD", "tf": "1h", "start": "2025-03-03", "end": "2025-03-10"})
    assert s.status_code == 201, s.text
    s = s.json()
    assert s["symbol"] == "BTCUSD" and len(s["bars"]) == 24 * 7 and s["leverage"] == 10
    assert s["htf"]["context"][-1]["c"] > 10_000
    fin = client.post(f"/practice/sessions/{s['id']}/finish", json={"trades": [
        {"side": "short", "units": 0.2, "entry_bar": 2, "exit_bar": 30}]}).json()
    assert fin["finished"] and fin["symbol"] == "BTCUSD"
    assert client.post("/practice/sessions", json={"symbol": "NOPE", "tf": "1h"}).status_code == 404

    # The weekly challenge rotates through markets that have prices.
    assert practice.challenge_market("2026-W47") in practice.CHALLENGE_MARKETS
    with db.conn() as c:
        assert practice.challenge_market("2026-W47", c) == "BTCUSD"  # the only market with hourly prices here


def test_alerts_on_another_market(client):
    signup(client)
    ingest.upsert([ingest.Bar(datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=2), 1.1, 1.1, 1.1, 1.1)],
                  "1m", "EURUSD")
    a = client.post("/practice/alerts", json={"symbol": "EURUSD", "price": 1.10250})
    assert a.status_code == 201, a.text
    assert a.json()["symbol"] == "EURUSD" and a.json()["direction"] == "above" and a.json()["price"] == 1.1025
    ingest.upsert([ingest.Bar(datetime.now(UTC).replace(second=0, microsecond=0), 1.1, 1.103, 1.1, 1.102)], "1m", "EURUSD")
    hit = client.post("/practice/alerts/check").json()["triggered"]
    assert [h["symbol"] for h in hit] == ["EURUSD"]


def test_daily_candle_rotates_markets(client):
    pool = daily.market_of(date(2026, 11, 2))
    assert pool[0] != daily.market_of(date(2026, 11, 1))[0] and set(pool) <= set(daily.ROTATION)
    hours_n = 24 * 120
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours_n)
    put("ETHUSD", "1h", start, walk(hours_n, 3000, 0.01, seed=9), timedelta(hours=1))
    r = client.get("/daily")
    assert r.status_code == 200, r.text
    played = client.post("/daily", json={"choice": "buy"}).json()
    assert played["symbol"] == "ETHUSD" and played["market"] == "Ethereum"


def test_stay_or_bail_and_assistant_tools_take_a_symbol(client):
    signup(client)
    closes = [100 * (0.97 ** i) for i in range(14)] + [70 + i for i in range(40)]
    bars = []
    for i, cl in enumerate(closes):
        y, m = 2015 + (i // 12), i % 12 + 1
        bars.append(ingest.Bar(datetime(y, m, 15, tzinfo=UTC), cl, cl, cl, cl))
    ingest.upsert(bars, "1d", "USA500IDXUSD")
    sob = client.get("/risk/stay-or-bail", params={"symbol": "USA500IDXUSD"}).json()
    assert sob["name"] == "S&P 500" and sob["episodes"] and sob["episodes"][0]["worst_pct"] < -10

    daily_bars("BTCUSD", walk(500, 90_000, 0.03, seed=11))
    hourly_bars("BTCUSD", walk(30, 90_000, 0.003, seed=12))
    out = assistant.t_price_summary({"symbol": "BTCUSD"}, 1)
    assert out["symbol"] == "BTCUSD" and out["price"] > 1000
    t = assistant.t_test_rules({"rules": RULES, "symbol": "BTCUSD", "years": 1}, 1)
    assert t["settings"]["symbol"] == "BTCUSD"
    content, is_error = assistant.call_tool("price_summary", {"symbol": "NOPE"}, 1)
    assert is_error and "Unknown market" in content
