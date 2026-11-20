import math

from app import backtest as bt
from app import robust
from tests.test_backtest import bars_from, cfg

DAY = 86400


def _trades(pnls, start=0, step=DAY):
    return [{"side": "long", "units": 1, "entry_time": start + i * step, "exit_time": start + i * step + 3600,
             "pnl": p, "costs": 0, "swap": 0} for i, p in enumerate(pnls)]


def test_cut_index_holds_back_the_last_part():
    assert robust.cut_index(100, 30) == 70
    assert robust.cut_index(100, 0) == 100
    assert robust.cut_index(3, 50) == 1


def test_split_reports_each_part_on_its_own():
    trades = _trades([100] * 7 + [-50] * 3)
    acct, equity = 10_000.0, [(0, 10_000.0)]
    for t in trades:
        acct += t["pnl"]
        equity.append((t["exit_time"], acct))
    sp = robust.split(trades, equity, 10_000, 7 * DAY)
    assert sp["development"]["trades"] == 7 and sp["development"]["net_profit"] == 700
    assert sp["held_back"]["trades"] == 3 and sp["held_back"]["net_profit"] == -150
    assert sp["held_back"]["starting_capital"] == 10_700
    assert sp["held_back"]["avg_trade_return_pct"] < 0 < sp["development"]["avg_trade_return_pct"]


def test_monte_carlo_is_repeatable_and_sees_luck():
    steady = robust.monte_carlo([0.01] * 50)
    assert steady["loss_chance_pct"] == 0 and math.isclose(steady["return_p50"], (1.01 ** 50 - 1) * 100, rel_tol=1e-3)
    coin = robust.monte_carlo([0.02, -0.02] * 25)
    assert 20 < coin["loss_chance_pct"] < 80  # a coin flip with no edge loses about half the time
    assert coin == robust.monte_carlo([0.02, -0.02] * 25)
    assert coin["drawdown_p95"] <= coin["drawdown_p50"] <= 0
    assert robust.monte_carlo([0.01]) is None


def test_few_trades_are_not_enough_evidence():
    r = robust.assess(_trades([100, 120, 90, 80, 110]), 10_000, None)
    assert r["level"] == "thin"
    assert {c["key"]: c["status"] for c in r["checks"]}["trades"] == "fail"


def test_a_strategy_that_fails_on_held_back_data_is_weak():
    pnls = [100, -40] * 40 + [-60, 20] * 20  # good for 80 trades, then loses
    trades = _trades(pnls)
    acct, equity = 10_000.0, [(0, 10_000.0)]
    for t in trades:
        acct += t["pnl"]
        equity.append((t["exit_time"], acct))
    sp = robust.split(trades, equity, 10_000, 80 * DAY)
    r = robust.assess(trades, 10_000, sp)
    checks = {c["key"]: c["status"] for c in r["checks"]}
    assert checks["held_back"] == "fail" and r["level"] == "weak"


def test_a_steady_edge_with_many_trades_is_strong():
    pnls = [60, -30, 50, -20] * 40
    trades = _trades(pnls)
    acct, equity = 10_000.0, [(0, 10_000.0)]
    for t in trades:
        acct += t["pnl"]
        equity.append((t["exit_time"], acct))
    sp = robust.split(trades, equity, 10_000, 112 * DAY)
    r = robust.assess(trades, 10_000, sp)
    assert r["level"] == "strong", r["checks"]


def test_backtest_reports_split_and_trust_checks_only_when_asked():
    closes = [100 + 5 * math.sin(i / 6) for i in range(400)]
    bars = bars_from(closes)
    plain = bt.run(cfg(realistic_fills=False), bars)
    assert "split" not in plain and "robustness" not in plain
    rep = bt.run(cfg(realistic_fills=False), bars, checks=True)
    assert rep["split"]["cut"] == bars[280]["t"]
    assert rep["split"]["development"]["trades"] + rep["split"]["held_back"]["trades"] == rep["stats"]["trades"]
    assert rep["robustness"]["level"] in robust.LEVELS
    none = bt.run(cfg(realistic_fills=False, holdout_pct=0), bars, checks=True)
    assert none["split"] is None and "held_back" not in {c["key"] for c in none["robustness"]["checks"]}
