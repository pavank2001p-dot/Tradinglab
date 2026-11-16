"""Stay or Bail: the deepest twelve-month falls in gold's monthly history, without overlap."""

from datetime import datetime, timezone

from app import db, stayorbail


def test_pick_finds_the_deepest_separate_falls():
    closes = [100.0] * 120
    closes[30:42] = [90, 80, 70, 75, 80, 85, 90, 95, 100, 100, 100, 100]    # -30% from index 29
    closes[80:86] = [95, 90, 88, 90, 95, 100]                               # -12% from index 79
    starts = stayorbail.pick(closes, n=2)
    assert len(starts) == 2 and 22 <= starts[0] <= 29 and 70 <= starts[1] <= 79
    assert min(closes[starts[0]:starts[0] + 13]) == 70


def test_endpoint_returns_episodes(client):
    with db.conn() as c:
        rows = []
        for i in range(160):
            y, m = 1975 + i // 12, i % 12 + 1
            p = 100.0 - (30 if 40 <= i <= 46 else 0)
            rows.append(("XAUUSD", "1mo", datetime(y, m, 1, tzinfo=timezone.utc), p, p, p, p))
        c.cursor().executemany("INSERT INTO candles (symbol, tf, ts, open, high, low, close) VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
    r = client.get("/risk/stay-or-bail").json()["episodes"]
    assert r and r[0]["months"][0]["level"] == 100 and r[0]["worst_pct"] == -30.0
    assert len(r[0]["months"]) == stayorbail.WINDOW + stayorbail.AFTER + 1
