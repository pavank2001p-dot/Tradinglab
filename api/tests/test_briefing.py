"""Claude market briefing: facts from the site's data, a structured write-up, and no trading calls."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app import briefing, config, ingest
from tests.test_coach import trade, uid
from tests.test_paper import signup
from tests.test_week4 import ScriptedClient, block

REPORT = {
    "headline": "Gold sits near the top of its 60-day range with volatility above its yearly average.",
    "news": {"tone": "quiet", "summary": "No headlines in the last three days.", "points": []},
    "chart": {"summary": "Price is above its 50-day average.", "points": ["RSI is 61, which is neither stretched nor weak."]},
    "strategies": {"summary": "Trend followers held up better than mean reverters.", "held_up": ["Price vs moving average"],
                   "weak_points": ["RSI reversion lost money on the held-back part."]},
    "habits": {"summary": "Two trades, one without a stop.", "points": []},
    "watch": ["US CPI on 2026-11-26 at 13:30 UTC."],
    "limits": ["Past tests don't guarantee future results, and this doesn't say whether the price will rise or fall."],
}


def load_sample():
    ingest.load("sample", datetime.now(UTC) - timedelta(days=6 * 365), datetime.now(UTC))


def test_facts_cover_every_section(client):
    load_sample()
    signup(client)
    u = uid(client)
    t0 = datetime.now(UTC) - timedelta(days=3)
    trade(u, t0, t0 + timedelta(minutes=20), -10)
    trade(u, t0 + timedelta(hours=2), t0 + timedelta(hours=3), 4, stop=None)
    f = briefing.facts(u, "XAUUSD")
    assert f["market"]["symbol"] == "XAUUSD"
    assert f["price"]["data_source"] == "sample"
    ch = f["chart"]
    assert ch["sma200"] and ch["rsi14"] is not None and 0 <= ch["position_in_20d_range_pct"] <= 100
    strategies = {s["strategy"]: s for s in f["strategy_comparison"]["strategies"]}
    assert set(strategies) == set(briefing.COMPARE)
    assert "held_back_return_pct" in strategies["ma_cross"] and "trust" in strategies["ma_cross"]
    assert f["news"]["count"] == 0 and f["my_latest_backtest"] is None
    h = f["my_habits"]
    assert h["trades"] == 2 and h["tags"]["no_stop"]["trades"] == 1 and h["clean_trades"] == 1
    json.dumps(f, default=str)  # stored as JSON


def test_signal_check():
    assert briefing.signal_like(REPORT) is None  # "doesn't say whether the price will rise" is a denial
    assert briefing.signal_like({**REPORT, "headline": "Gold will rise from here."}) == "will rise"
    assert briefing.signal_like({**REPORT, "watch": ["This is a good time to add."]})
    assert briefing.signal_like({**REPORT, "chart": {"summary": "Price is likely to climb.", "points": []}})


def run(client, monkeypatch, report):
    load_sample()
    signup(client)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    fake = ScriptedClient([SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text=json.dumps(report))])])
    monkeypatch.setattr(briefing.anthropic, "Anthropic", lambda **kw: fake)
    r = client.post("/briefing?symbol=xauusd")
    assert r.status_code == 202
    return client.get(f"/briefing/{r.json()['id']}").json(), fake


def test_briefing_end_to_end(client, monkeypatch):
    got, fake = run(client, monkeypatch, REPORT)
    assert got["status"] == "done" and got["report"] == REPORT and got["note"] is None
    assert got["facts"]["market"]["symbol"] == "XAUUSD"
    assert got["label"].startswith("Analysis, not a signal")
    call = fake.calls[0]
    assert call["output_config"]["format"]["schema"] == briefing.SCHEMA and call["fallbacks"] == "default"
    assert "never tell the reader to buy" in call["system"]
    # Asking again within the hour reuses it instead of spending another briefing.
    again = client.post("/briefing?symbol=XAUUSD").json()
    assert again == {"id": got["id"], "status": "done", "reused": True}
    assert client.get("/briefing/status").json()["used_today"] == 1


def test_signal_like_briefing_is_withheld(client, monkeypatch):
    got, _ = run(client, monkeypatch, {**REPORT, "headline": "A buying opportunity: gold will rally."})
    assert got["status"] == "done" and got["report"] is None
    assert "held back" in got["note"] and got["facts"]["chart"]["sma20"]


def test_limits_and_errors(client, monkeypatch):
    signup(client)
    assert client.post("/briefing").status_code == 503  # no key
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    assert client.post("/briefing?symbol=NOPE").status_code == 404
    monkeypatch.setattr(config, "BRIEFING_DAILY_LIMIT", 1)
    monkeypatch.setattr(briefing, "process", lambda bid: None)  # stays pending
    first = client.post("/briefing?symbol=EURUSD").json()
    assert client.post("/briefing?symbol=XAUUSD").json()["id"] == first["id"]  # one at a time
    from app import db
    with db.conn() as c:
        c.execute("UPDATE briefings SET status = 'done'")
    assert client.post("/briefing?symbol=XAUUSD").status_code == 429
    assert client.get("/briefing/999").status_code == 404
