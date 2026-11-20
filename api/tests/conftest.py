import os

os.environ.setdefault("DATABASE_URL", "postgresql://gold:gold@localhost:5432/gold_test")
os.environ["EMAIL_PROVIDER"] = "console"
# Day-trading markets keep months of minute bars; tests that need that set it themselves.
os.environ.setdefault("INTRADAY_SYMBOLS", "")

import pytest
from fastapi.testclient import TestClient

from app import db, fills, fx
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        with db.conn() as conn:
            conn.execute("TRUNCATE users, user_activity, page_views, auth_tokens, candles, price_alerts, challenges, challenge_entries, user_prefs, meta, backtests, trades, news, events, risk_profiles, assistant_questions, paper_accounts, paper_orders, paper_positions, trade_reviews, lesson_progress, prop_challenges, daily_candles, daily_candle_plays, record_entries, record_reports RESTART IDENTITY CASCADE")
        yield c


@pytest.fixture(autouse=True)
def no_rollover(monkeypatch):
    """Keep fills independent of the time of day the tests run; tests of the rollover turn it back on."""
    monkeypatch.setattr(fills, "in_rollover", lambda t: False)
    fills.clear_cache()
    yield
    fills.clear_cache()


@pytest.fixture(autouse=True)
def fixed_fx(monkeypatch):
    """Exchange rates are the built-in rough ones, so converting P&L of non-dollar markets is deterministic."""
    fx.clear_cache()
    monkeypatch.setattr(fx, "_cache", {"at": 1e18, "rates": None, "as_of": None})
    yield
    fx.clear_cache()
