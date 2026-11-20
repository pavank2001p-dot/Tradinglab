import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import calendar, config, news, risk

UTC = timezone.utc


def test_relevance_and_markets():
    assert news.relevance("Gold hits record as dollar slides") == 2
    assert news.relevance("Fed's Powell signals rate cuts later this year") == 1
    assert news.relevance("Apple unveils new iPhone") == 2
    assert news.relevance("Local council approves new park") == 0
    syms, secs = news.classify_text("Goldman Sachs earnings beat")
    assert syms == ["GSUSUSD"] and "stocks:Financials" in secs  # word boundary: Goldman, not gold
    assert news.classify_text("Oil jumps as OPEC+ cuts output")[0] == ["LIGHTCMDUSD", "BRENTCMDUSD"]
    assert news.classify_text("Yen weakens as BoJ holds")[0] == ["USDJPY"]
    assert news.classify_text("Bank stocks rally after stress test") == ([], ["indices", "stocks", "stocks:Financials"])
    assert news.classify_text("Nifty and Sensex hit records")[0][0] == "INDIDXUSD"
    assert news.classify_text("Analysts upgrade the stock", related="NVDA")[0] == ["NVDAUSUSD"]
    assert news.classify_text("an apple a day")[0] == []  # company names are case-sensitive


class FakeClient:
    def __init__(self, payload, stop="end_turn"):
        self.calls = []
        outer = self

        class Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return SimpleNamespace(stop_reason=stop, stop_details=None,
                                       content=[SimpleNamespace(type="text", text=json.dumps(payload))])

        self.beta = SimpleNamespace(messages=Messages())


def test_classify_sends_schema_and_filters_unknown_ids():
    fake = FakeClient({"items": [
        {"id": 1, "impact": "bullish", "reason": "Rate cuts lower the cost of holding gold."},
        {"id": 99, "impact": "bearish", "reason": "Not one of ours."},
    ]})
    out = news.classify(fake, [{"id": 1, "headline": "Fed signals cuts", "summary": ""}])
    assert out == [{"id": 1, "impact": "bullish", "reason": "Rate cuts lower the cost of holding gold."}]
    kw = fake.calls[0]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]


def test_classify_handles_refusal():
    assert news.classify(FakeClient({}, stop="refusal"), [{"id": 1, "headline": "x", "summary": ""}]) == []


def test_news_store_tag_and_list(client, monkeypatch):
    now = datetime.now(UTC)
    items = [
        {"source": "finnhub", "external_id": str(i), "headline": h, "summary": "", "url": "https://example.com",
         "publisher": "Reuters", "published_at": now - timedelta(minutes=i), "relevance": news.relevance(h)}
        for i, h in enumerate(["Gold climbs to record", "US CPI hotter than expected"])
    ]
    assert news.store(items) == 2
    assert news.store(items) == 0  # duplicates ignored

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    fake = FakeClient({"items": [{"id": 1, "impact": "bullish", "reason": "Momentum."},
                                 {"id": 2, "impact": "bearish", "reason": "Rates may stay high."}]})
    monkeypatch.setattr(news.anthropic, "Anthropic", lambda api_key: fake)
    assert news.tag_pending() == 2

    body = client.get("/news").json()
    assert [i["impact"] for i in body["items"]] == ["bullish", "bearish"]
    assert body["items"][0]["focus"] == "XAUUSD" and body["items"][0]["focus_name"] == "Gold"
    assert body["items"][1]["focus"] == "USA500IDXUSD"  # macro news is tagged for US stocks
    # The market said which market each tag is for.
    assert "market: Gold (XAU/USD)" in fake.calls[0]["messages"][0]["content"]
    assert len(client.get("/news", params={"gold_only": True}).json()["items"]) == 1
    assert len(client.get("/news", params={"sector": "macro"}).json()["items"]) == 1


def test_news_by_market_and_sector(client):
    now = datetime.now(UTC)
    heads = ["Gold climbs to record", "Bank stocks rally after stress test", "JPMorgan beats estimates",
             "Oil slides as inventories build", "Bitcoin tops $100,000"]
    news.store([{"source": "finnhub", "external_id": str(i), "headline": h, "summary": "", "url": "", "publisher": "X",
                 "published_at": now - timedelta(minutes=i), "relevance": news.relevance(h)} for i, h in enumerate(heads)])
    get = lambda **p: [i["headline"] for i in client.get("/news", params=p).json()["items"]]  # noqa: E731
    assert get(symbol="JPMUSUSD") == ["Bank stocks rally after stress test", "JPMorgan beats estimates"]
    assert get(sector="stocks:Financials") == ["Bank stocks rally after stress test", "JPMorgan beats estimates"]
    assert get(sector="energy") == ["Oil slides as inventories build"]
    assert get(symbol="BTCUSD") == ["Bitcoin tops $100,000"]
    assert get(sector="crypto") == ["Bitcoin tops $100,000"]


def test_old_gold_headlines_get_markets(client):
    from app import db
    with db.conn() as c:
        c.execute("INSERT INTO news (source, external_id, headline, published_at, relevance, impact, reason) "
                  "VALUES ('finnhub', 'old', 'Fed holds rates', now(), 1, 'bullish', 'Lower rates help gold.')")
    assert news.backfill_markets() == 1
    item = client.get("/news", params={"symbol": "XAUUSD"}).json()["items"][0]
    assert item["focus"] == "XAUUSD" and "XAUUSD" in item["symbols"]


def test_calendar_seed_feed_and_list(client, monkeypatch):
    soon = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    feed = [
        {"title": "CPI m/m", "country": "USD", "date": soon.isoformat(), "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
        {"title": "German ZEW", "country": "EUR", "date": soon.isoformat(), "impact": "High"},
        {"title": "Crude Oil Inventories", "country": "USD", "date": soon.isoformat(), "impact": "Low"},
    ]

    class Resp:
        def raise_for_status(self): ...
        def json(self): return feed

    monkeypatch.setattr(calendar.httpx, "get", lambda *a, **k: Resp())
    assert calendar.update() == 2  # US and euro-area releases; low-impact ones are left out
    events = client.get("/calendar", params={"days": 30}).json()
    cpi = next(e for e in events if e["title"] == "CPI m/m")
    assert cpi["forecast"] == "0.3%" and "inflation" in cpi["why"].lower()
    # Each market sees the US calendar plus its own economies: EUR/USD and the DAX get the German release.
    titles = lambda s: {e["title"] for e in client.get("/calendar", params={"days": 30, "symbol": s}).json()}  # noqa: E731
    assert "German ZEW" in titles("EURUSD") and "German ZEW" in titles("DEUIDXEUR")
    assert "German ZEW" not in titles("USDJPY") and "CPI m/m" in titles("USDJPY")
    with __import__("app.db", fromlist=["conn"]).conn() as c:
        assert c.execute("SELECT count(*) AS n FROM events WHERE title = 'FOMC rate decision'").fetchone()["n"] == 8


def test_risk_quiz(client):
    q = client.get("/risk/quiz").json()["questions"]
    assert client.post("/risk/profile", json={"answers": {}}).status_code == 401
    client.post("/auth/signup", json={"email": "r@example.com", "password": "longenough"})
    assert client.get("/risk/profile").status_code == 404
    assert client.post("/risk/profile", json={"answers": {q[0]["key"]: 1}}).status_code == 422

    cautious = client.post("/risk/profile", json={"answers": {x["key"]: 0 for x in q}}).json()
    assert cautious["profile"] == "conservative" and cautious["max_risk_per_trade_pct"] == 0.5
    middle = client.post("/risk/profile", json={"answers": {x["key"]: (1 if i % 2 else 2) for i, x in enumerate(q)}}).json()
    assert middle["profile"] == "moderate"
    bold = client.post("/risk/profile", json={"answers": {x["key"]: 3 for x in q}}).json()
    assert bold["profile"] == "aggressive"
    assert client.get("/risk/profile").json()["profile"] == "aggressive"


def test_risk_thresholds():
    assert risk.place(0) == "conservative"
    assert risk.place(risk.MAX_SCORE) == "aggressive"


def test_risk_breakdown_and_old_profiles(client):
    from app import db, risk

    client.post("/auth/signup", json={"email": "b@example.com", "password": "longenough"})
    quiz = client.get("/risk/quiz").json()
    assert len(quiz["questions"]) >= 16 and set(quiz["categories"]) == {q["category"] for q in quiz["questions"]}
    answers = {q["key"]: (3 if q["category"] == "behaviour" else 0) for q in quiz["questions"]}
    p = client.post("/risk/profile", json={"answers": answers}).json()
    pct = {b["key"]: b["pct"] for b in p["breakdown"]}
    assert pct["behaviour"] == 100 and pct["experience"] == 0 and p["complete"]
    assert p["max_score"] == 3 * len(quiz["questions"])

    # A profile saved with the original eight questions still loads, scored out of those.
    old = {k: 1 for k in ("experience", "goal", "drawdown", "loss_limit", "money", "horizon", "leverage", "stops")}
    with db.conn() as c:
        c.execute("UPDATE risk_profiles SET answers = %s, score = 8, profile = 'conservative'",
                  (__import__("psycopg").types.json.Jsonb(old),))
    got = client.get("/risk/profile").json()
    assert got["max_score"] == 24 and not got["complete"] and got["profile"] == "conservative"
    assert risk.place(8) == "conservative"
