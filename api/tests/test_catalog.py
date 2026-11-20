"""The wider catalog: markets in other currencies, markets loaded on first use, and the feed probe."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app import backtest, db, fills, fx, ingest, instruments, paper
from app.live import feed, feed_of

UTC = timezone.utc
JPY = instruments.get("USDJPY")
DAX = instruments.get("DEUIDXEUR")
EURJPY = instruments.get("EURJPY")


def signup(client, email="c@example.com"):
    assert client.post("/auth/signup", json={"email": email, "password": "longenough"}).status_code == 201


@pytest.fixture(autouse=True)
def no_live_feed(monkeypatch):
    for f in (feed, feed_of("USDJPY"), feed_of("EURUSD")):
        monkeypatch.setattr(f, "price", None)
        monkeypatch.setattr(f, "t", None)


def test_catalog_covers_every_class_and_sector():
    classes = {i.asset_class for i in instruments.ALL}
    assert classes == set(instruments.CLASSES)
    assert len({i.symbol for i in instruments.ALL}) == len(instruments.ALL) >= 150
    sectors = {i.group for i in instruments.ALL if i.asset_class == "stocks"}
    assert {"Technology", "Financials", "Healthcare", "Energy", "Industrials", "Consumer", "Staples",
            "Communication"} <= sectors
    assert all(i.group for i in instruments.ALL)
    for i in instruments.ALL:
        assert i.hours in ("fx", "us_stock", "eu", "in", "always"), i.symbol
        assert i.quote == "USD" or i.quote in fx.FALLBACK or i.base_usd, i.symbol
        assert i.spread > 0 and i.default_units > 0 and i.ref_price > 0
    assert instruments.GOLD.symbol in instruments.CORE


def test_money_in_other_currencies_is_converted_to_dollars():
    assert instruments.GOLD.usd() == 1.0
    # USD/JPY: a yen move converts at the pair's own price.
    assert JPY.base_usd and JPY.usd(150) == pytest.approx(1 / 150)
    # The DAX is in euros and EUR/JPY in yen: converted at the day's reference rate.
    assert DAX.usd() == pytest.approx(1 / fx.FALLBACK["EUR"])
    assert EURJPY.usd(160) == pytest.approx(1 / fx.FALLBACK["JPY"])
    # Financing is in dollars too.
    assert JPY.swap_per_unit("long", 150) == pytest.approx(150 * -2.0 / 100 / 365 / 150)
    assert JPY.public()["usd_rate"] is None and DAX.public()["usd_rate"] == pytest.approx(1 / 0.93, rel=1e-6)
    assert JPY.currencies == {"USD", "JPY"} and DAX.currencies == {"USD", "EUR"}
    assert instruments.get("INDIDXUSD").currencies == {"USD", "INR"}


def test_trading_hours_for_european_and_indian_sessions():
    wed = datetime(2026, 11, 11, tzinfo=UTC)
    assert DAX.is_open(wed.replace(hour=10)) and not DAX.is_open(wed.replace(hour=22))
    nifty = instruments.get("INDIDXUSD")
    assert nifty.is_open(wed.replace(hour=5)) and not nifty.is_open(wed.replace(hour=12))
    assert DAX.session_hours and not JPY.session_hours


def bar(symbol: str, minutes_from_now: float, o, h, l, c, tf="1m"):
    ts = (datetime.now(UTC) + timedelta(minutes=minutes_from_now)).replace(second=0, microsecond=0)
    with db.conn() as conn:
        conn.execute(
            """INSERT INTO candles (symbol, tf, ts, open, high, low, close) VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (symbol, tf, ts) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high,
               low = EXCLUDED.low, close = EXCLUDED.close""",
            (symbol, tf, ts, o, h, l, c))


def test_paper_pnl_in_yen_pair_is_in_dollars(client, monkeypatch):
    monkeypatch.setattr(fills, "now", lambda: fills.Conditions(on=False))
    if not JPY.is_open(datetime.now(UTC)):
        pytest.skip("forex is closed right now")
    signup(client)
    bar("USDJPY", -3, 150.0, 150.0, 150.0, 150.0)
    r = client.post("/paper/orders", json={"symbol": "USDJPY", "side": "long", "units": 100_000})
    assert r.status_code == 201, r.text
    entry = r.json()["position"]["entry_price"]
    bar("USDJPY", -2, 151.5, 151.5, 151.5, 151.5)
    pos = client.get("/paper", params={"symbol": "USDJPY"}).json()["positions"][0]
    # 100,000 units x (151.5 - entry) yen, at 151.5 yen a dollar, is about $990 on a 1.5 yen move.
    assert pos["pnl"] == pytest.approx((151.5 - entry) * 100_000 / 151.5, abs=1)
    assert 900 < pos["pnl"] < 1000
    # Margin is a dollar amount: 100,000 dollars of position at the account's 1:20.
    assert pos["margin"] == pytest.approx(100_000 / 20, rel=0.01)


def test_backtest_on_euro_index_reports_dollars(client):
    ingest.load("sample", datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), DAX)
    cfg = backtest.BacktestIn(strategy="ma_cross", symbol="DEUIDXEUR", start=date(2024, 1, 1), end=date(2025, 1, 1),
                              realistic_fills=False)
    rep = backtest.run(cfg, backtest.load_bars("1d", cfg.start, cfg.end, "DEUIDXEUR"))
    t = rep["trades"][0]
    gross = (t["exit_price"] - t["entry_price"]) * t["units"] * (1 if t["side"] == "long" else -1)
    assert t["pnl"] - t["swap"] == pytest.approx(gross / fx.FALLBACK["EUR"], abs=0.02)


def test_market_loads_on_first_use_and_list_shows_status(client, monkeypatch):
    monkeypatch.setattr(ingest.config, "PRICE_SOURCE", "sample")
    monkeypatch.setattr(ingest, "_ready", set())
    monkeypatch.setattr(ingest, "_touched", {})
    monkeypatch.setattr(ingest.config, "MARKET_HISTORY_SINCE", date.today() - timedelta(days=10))
    xle = instruments.get("XLEUSUSD")
    m = {x["symbol"]: x for x in client.get("/prices/markets").json()["markets"]}
    assert m["XLEUSUSD"]["status"] == "on_demand" and m["XLEUSUSD"]["group"] == "Sectors"
    assert m["XLEUSUSD"]["ticker"] == "XLE" and m["DEUIDXEUR"]["quote"] == "EUR"
    # Without the scheduler (tests, scripts) opening a market only notes it as in use.
    assert client.post("/prices/open", params={"symbol": "XLEUSUSD"}).json()["status"] == "on_demand"
    assert "XLEUSUSD" in ingest.active_symbols()
    assert ingest.ensure(xle, background=False) == "ready"
    m = {x["symbol"]: x for x in client.get("/prices/markets").json()["markets"]}
    assert m["XLEUSUSD"]["status"] == "ready" and m["XLEUSUSD"]["price"]
    # The updater keeps it fresh while in use, along with the core markets, and skips the rest.
    done = []
    monkeypatch.setattr(ingest, "update", lambda source, inst: done.append(inst.symbol) or 0)
    ingest.update_all("sample")
    assert "XLEUSUSD" in done and "XAUUSD" in done and "XLUUSUSD" not in done


def test_probe_hides_markets_the_feed_lacks(client, monkeypatch):
    def fake_point(_client, inst):
        if inst.symbol == "OJUICECMDUSX":
            raise RuntimeError("No recent prices")
        db.set_meta(ingest._key("duka_point", inst), "1000.0")
        return 1000.0

    monkeypatch.setattr(ingest, "duka_point", fake_point)
    out = ingest.probe("dukascopy")
    assert out["OJUICECMDUSX"] == "unavailable" and out["EURUSD"] == "ok"
    syms = {x["symbol"] for x in client.get("/prices/markets").json()["markets"]}
    assert "OJUICECMDUSX" not in syms and "EURUSD" in syms
    assert ingest.probe("dukascopy") == {}  # already checked: nothing fetched again


def test_live_quote_on_a_different_scale_is_ignored(client):
    f = feed_of("EURUSD")
    bar("EURUSD", -120, 1.1, 1.1, 1.1, 1.1, tf="1h")
    f.ref = None
    f.tick(110.0, datetime.now(UTC).timestamp())
    assert f.price is None
    f.tick(1.1002, datetime.now(UTC).timestamp())
    assert f.price == 1.1002


def test_news_spreads_follow_the_markets_own_economies():
    t = datetime(2026, 11, 11, 13, 30, tzinfo=UTC)
    cond = fills.Conditions([t], countries=["JPY"])
    assert cond.why(JPY, t) == "news" and cond.why(DAX, t) is None
    assert cond.why(instruments.GOLD, t) is None
    us = fills.Conditions([t], countries=["USD"])
    assert us.why(DAX, t) == "news" and us.why(JPY, t) == "news"


def test_trade_log_covers_every_market(client):
    from app import trades
    signup(client, "log@example.com")
    csv = ("Ticket,Open Time,Type,Volume,Symbol,Price,Close Time,Price,Commission,Swap,Profit\n"
           "1,2026.01.05 10:00,buy,0.1,XAUUSD.m,2000,2026.01.05 12:00,2010,0,0,100\n"
           "2,2026.01.06 10:00,sell,1,USDJPY.pro,150.00,2026.01.06 12:00,149.00,0,0,0\n"
           "3,2026.01.07 10:00,buy,2,#AAPL,200,2026.01.07 12:00,205,0,0,0\n"
           "4,2026.01.08 10:00,buy,1,XYZ,1,2026.01.08 12:00,2,0,0,0\n")
    body = client.post("/trades/import", files={"file": ("h.csv", csv)}).json()
    assert body["imported"] == 3 and "XYZ isn't a market" in body["skipped"][0]
    rows = {r["symbol"]: r for r in client.get("/trades").json()}
    assert rows["XAUUSD"]["units"] == 10 and rows["XAUUSD"]["pnl"] == 100
    # One standard lot of USD/JPY is 100,000 dollars; a 1-yen fall on a short makes 100,000 yen, at 149 yen a dollar.
    assert rows["USDJPY"]["units"] == 100_000 and rows["USDJPY"]["pnl"] == pytest.approx(100_000 / 149, abs=0.01)
    assert rows["AAPLUSUSD"]["pnl"] == 10
    assert trades.match_symbol("GER40").symbol == "DEUIDXEUR" and trades.match_symbol("BTCUSDT").symbol == "BTCUSD"
    r = client.post("/trades", json={"symbol": "EURUSD", "side": "long", "units": 10000, "open_time": "2026-01-01T10:00:00Z",
                                     "open_price": 1.1})
    assert r.status_code == 201 and r.json()["symbol"] == "EURUSD"


def test_commission_on_value_is_in_dollars():
    # A percentage commission is of the trade's value in dollars, whatever currency the market is quoted in.
    from dataclasses import replace
    dax = replace(DAX, commission_pct=0.1, commission_per_unit=0.0, commission_min=0.0)
    assert dax.commission(1, 18000) == pytest.approx(18000 * 0.001 / fx.FALLBACK["EUR"])
    jpy = replace(JPY, commission_pct=0.01, commission_per_unit=0.0, commission_min=0.0)
    assert jpy.commission(100_000, 150) == pytest.approx(100_000 * 0.0001)
    # Every class has cost defaults, so every new market gets them.
    assert all(i.asset_class in instruments.COSTS for i in instruments.ALL)
