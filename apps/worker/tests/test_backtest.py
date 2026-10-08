import copy
import json
from dataclasses import replace

import numpy as np
import pytest

from dhandrishti.backtesting import BacktestParams, rebalance_dates, run_backtest
from dhandrishti.backtesting import metrics as M
from dhandrishti.backtesting.engine import _Book
from dhandrishti.ingestion.fixtures import market_to_json
from dhandrishti.ingestion.mock import generate_market
from dhandrishti.ingestion.mock_history import generate_history

SHORT = BacktestParams(start="2025-09-01", end="2026-03-31", rebalance="quarterly", top_n=5)


@pytest.fixture(scope="module")
def history():
    return generate_history("2026-10-05")


@pytest.fixture(scope="module")
def short_result(history):
    return run_backtest(history, SHORT)


# ------------------------------------------------------------------ mock history

def test_history_keeps_golden_window_identical(history):
    assert market_to_json(history.market_at("2026-10-05", 300)) == market_to_json(generate_market("2026-10-05"))


def test_history_is_deterministic(history):
    again = generate_history("2026-10-05")
    assert again.nifty.close.tolist() == history.nifty.close.tolist()
    assert [f.as_of for f in again.fundamentals["HDFCBANK"]] == [f.as_of for f in history.fundamentals["HDFCBANK"]]


def test_fundamentals_snapshots_are_published_after_quarter_end(history):
    dates = [f.as_of for f in history.fundamentals["INFY"]]
    assert dates == sorted(dates)
    assert all(d[5:] in ("02-14", "05-30", "08-14", "11-14", "10-05") for d in dates)


def test_market_at_has_no_look_ahead(history):
    m = history.market_at("2024-06-28", 300)
    assert all(s.bars.dates[-1] <= "2024-06-28" for s in m.stocks)
    assert all(s.fundamentals is None or s.fundamentals.as_of <= "2024-06-28" for s in m.stocks)
    assert len(m.nifty) == 300


# ------------------------------------------------------------------ calendar

def test_rebalance_dates_are_period_ends_traded_next_session():
    cal = ["2026-01-29", "2026-01-30", "2026-02-02", "2026-02-27", "2026-03-02", "2026-03-31", "2026-04-01"]
    assert rebalance_dates(cal, "2026-01-01", "2026-04-01", "monthly") == [
        ("2026-01-30", "2026-02-02"), ("2026-02-27", "2026-03-02"), ("2026-03-31", "2026-04-01")]
    assert rebalance_dates(cal, "2026-01-01", "2026-04-01", "quarterly") == [("2026-03-31", "2026-04-01")]


# ------------------------------------------------------------------ engine

def test_requires_enough_history_before_first_signal(history):
    with pytest.raises(ValueError, match="sessions of history"):
        run_backtest(history, replace(SHORT, start="2022-10-01"))


def test_invalid_params_rejected(history):
    for bad in (replace(SHORT, rebalance="daily"), replace(SHORT, max_risk="TINY"), replace(SHORT, top_n=0)):
        with pytest.raises(ValueError):
            run_backtest(history, bad)


def test_trades_execute_the_session_after_the_signal(short_result):
    for p in short_result.periods:
        assert p["execution"] > p["signal"]
    assert short_result.dates[0] == short_result.periods[0]["execution"]


def test_picks_respect_top_n_and_risk_filter(short_result):
    for p in short_result.periods:
        assert len(p["picks"]) <= SHORT.top_n
    assert {h["risk_level"] for h in short_result.holdings} <= {"LOW", "MEDIUM"}


def test_look_ahead_canary(history):
    """Scrambling every price after a signal date must not change that signal's picks."""
    base = run_backtest(history, SHORT)
    signal = base.periods[0]["signal"]
    tampered = copy.deepcopy(history)
    rng = np.random.default_rng(0)
    for b in tampered.bars.values():
        future = np.array([d > signal for d in b.dates])
        factor = rng.uniform(0.2, 5.0, future.sum())
        for arr in (b.open, b.high, b.low, b.close):
            arr[future] = arr[future] * factor
    changed = run_backtest(tampered, SHORT)
    assert changed.periods[0]["picks"] == base.periods[0]["picks"]


def test_deterministic(history, short_result):
    again = run_backtest(history, SHORT)
    assert json.dumps(again.to_dict(), sort_keys=True) == json.dumps(short_result.to_dict(), sort_keys=True)


def test_costs_reduce_returns(history, short_result):
    free = run_backtest(history, replace(SHORT, buy_cost_bps=0, sell_cost_bps=0))
    assert free.strategy[-1] > short_result.strategy[-1]
    assert free.metrics["trading"]["total_costs"] == 0
    assert short_result.metrics["trading"]["total_costs"] > 0


def test_result_is_json_safe_and_complete(short_result):
    d = short_result.to_dict()
    json.dumps(d, allow_nan=False)
    assert d["data_provenance"] == "MOCK"
    for key in ("strategy", "nifty", "universe_ew", "vs_nifty", "vs_universe", "trading", "signal"):
        assert key in d["metrics"]
    assert len(d["metrics"]["signal"]["quantile_mean_returns_pct"]) == SHORT.quantiles
    assert all(-1 <= p["ic"] <= 1 for p in d["periods"] if p["ic"] is not None)
    # Capital is invested at the first execution open; the curve's first point is that day's close.
    assert d["equity"][0]["strategy"] == pytest.approx(SHORT.initial_capital, rel=0.05)


# ------------------------------------------------------------------ accounting

def test_book_equal_weights_and_costs():
    b = _Book(1000.0, buy_bps=100, sell_bps=0)  # 1% buy cost
    nav = b.rebalance(["A", "B"], {"A": 10.0, "B": 20.0})
    assert nav == pytest.approx(990.0)  # 1% of 1000 bought
    assert b.shares["A"] * 10 == pytest.approx(495.0) and b.shares["B"] * 20 == pytest.approx(495.0)
    assert b.mark({"A": 11.0, "B": 20.0}) == pytest.approx(990.0 + 49.5)
    assert b.turnover == [pytest.approx(0.5)]


def test_book_holds_cash_when_nothing_is_tradable():
    b = _Book(1000.0, buy_bps=0, sell_bps=0)
    b.rebalance(["A"], {"A": 10.0})
    b.rebalance(["Z"], {"A": 12.0})  # Z has no price: sell A, stay in cash
    assert b.shares == {} and b.cash == pytest.approx(1200.0)


def test_metrics_on_known_series():
    dates = ["2025-01-01", "2026-01-01"]
    assert M.cagr(np.array([100.0, 110.0]), dates) == pytest.approx(10.0, abs=0.05)
    mdd = M.max_drawdown(np.array([100.0, 120.0, 90.0, 130.0]), ["a", "b", "c", "d"])
    assert mdd == {"pct": pytest.approx(-25.0), "peak": "b", "trough": "c"}
    assert M.spearman(np.array([1.0, 2, 3, 4]), np.array([10.0, 20, 30, 40])) == pytest.approx(1.0)
