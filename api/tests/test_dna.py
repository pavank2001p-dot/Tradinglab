"""Trader DNA scores and the rulebook remix of a user's paper trades against each challenge plan."""

from datetime import timedelta

from app import dna
from tests.test_coach import NOW, no_live_feed, trade, uid  # noqa: F401
from tests.test_paper import signup

RULES = {"targets": [10.0], "daily_loss_pct": 5.0, "max_loss_pct": 10.0, "min_days": 2}


def test_run_passes_fails_and_waits():
    assert dna.run([[0.06], [0.05]], RULES)[:2] == ("pass", 2)
    assert dna.run([[0.11]], RULES)[0] == "open"                       # target hit on day 1, two days needed
    assert dna.run([[-0.03], [-0.06]], RULES)[0] == "daily"
    assert dna.run([[-0.04], [-0.04], [-0.04]], RULES)[0] == "overall"
    assert dna.run([[0.01]], RULES)[0] == "open"


def test_remix_is_repeatable_and_counts_every_run():
    days = [[0.03], [-0.02], [0.04], [-0.01], [0.05], [0.02]]
    a, b = dna.remix(days, RULES, runs=200), dna.remix(days, RULES, runs=200)
    assert a == b and round(sum(a["odds"].values())) == 100
    assert a["actual"] == "pass" and len(a["paths"]) == dna.PATHS


def test_needs_a_few_trades(client):
    signup(client)
    r = client.get("/prop/dna").json()
    assert r["ready"] is False and r["needed"] == dna.MIN_TRADES


def test_dna_scores_and_plans(client):
    signup(client)
    u = uid(client)
    t0 = NOW - timedelta(days=10)
    for d in range(6):
        trade(u, t0 + timedelta(days=d), t0 + timedelta(days=d, minutes=30), 40 if d % 2 else -20)
    trade(u, t0 + timedelta(days=6), t0 + timedelta(days=6, hours=1), -300, units=30)      # oversized
    r = client.get("/prop/dna").json()
    assert r["ready"] and r["trades"] == 7
    s = {x["key"]: x for x in r["scores"]}
    assert s["stops"]["score"] == 100 and s["sizing"]["score"] == round(600 / 7, 1)
    assert s["payoff"]["score"] == round(min((40 / ((20 * 3 + 300) / 4)) / 2, 1) * 100, 1)
    assert {p["plan"] for p in r["plans"]} == {"starter", "two_step", "one_step"}
    assert all(round(sum(p["odds"].values())) == 100 for p in r["plans"])
