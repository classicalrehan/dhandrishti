"""Drawdown-control study (research/drawdown_control.py)."""

import numpy as np
import pytest

from dhandrishti.research import drawdown_control as D
from dhandrishti.research import position_sizing as S
from dhandrishti.research.factors import ROUND_TRIP_COST
from dhandrishti.research.position_sizing import Quarter


def _quarter(start, path):
    rel = np.array([path])
    return Quarter(start, start + len(path) - 1, ["A"], {None: rel, 0.08: rel}, np.array([0.01]))


def test_fixed_reproduces_the_position_sizing_baskets():
    rng = np.random.default_rng(3)
    qs, t = [], 1
    for _ in range(4):
        rel = np.exp(np.cumsum(rng.normal(0, 0.01, (6, 21)), axis=1))
        qs.append(Quarter(t, t + 20, list("ABCDEF"), {None: rel, 0.08: rel}, np.full(6, 0.01)))
        t += 20
    flags = np.ones(200, bool)
    baskets = D._baskets(qs, 3, paths=5, seed=7)
    for base in (0.6, 1.0):
        got = D.simulate(qs, baskets, "fixed", base, flags, flags)
        assert got == pytest.approx(S.simulate(qs, 3, base, "equal", None, paths=5, seed=7))


def test_drawdown_rule_halves_exposure_after_a_10pct_fall_and_restores_after_recovery():
    path = [1.0, 0.95, 0.88, 0.80, 0.80, 0.90, 1.0, 1.0]
    q = _quarter(1, path)
    flags = np.ones(50, bool)
    curve = D.simulate([q], [[np.array(path)]], "dd_half", 1.0, flags, flags)[0]
    cost = 1 - ROUND_TRIP_COST
    assert curve[2] == pytest.approx(cost * 0.88)                 # full exposure until the -12% close
    sold_cost = 0.5 * curve[2] * ROUND_TRIP_COST / 2               # sells half at that mark, half a round trip on it
    assert curve[3] == pytest.approx(curve[2] * (0.5 + 0.5 * 0.80 / 0.88) - sold_cost)   # only half falls further
    assert curve[3] > cost * 0.80                                 # less damage than staying fully invested


def test_trend_rule_is_in_cash_below_the_200_day_average_and_cash_does_not_move():
    path = [1.0, 0.9, 0.8, 0.7]
    q = _quarter(1, path)
    below = np.zeros(50, bool)
    curve = D.simulate([q], [[np.array(path)]], "trend200", 1.0, below, below)[0]
    assert np.allclose(curve, 1.0)                                # never invested, no costs
    half = D.simulate([q], [[np.array(path)]], "trend200_half", 1.0, below, below)[0]
    assert half[-1] == pytest.approx((1 - 0.5 * ROUND_TRIP_COST) * (0.5 + 0.5 * 0.7))


def test_cash_rule_re_enters_on_the_50_day_trend_and_resets_the_peak():
    path = [1.0, 0.85, 0.85, 0.85, 0.95]
    q = _quarter(1, path)
    above200 = np.ones(50, bool)
    above50 = np.zeros(50, bool)
    above50[3] = True                                             # trend turns up at session 3 (step 2)
    curve = D.simulate([q], [[np.array(path)]], "dd_cash_trend", 1.0, above200, above50)[0]
    # marks are recorded before that day's trade: the sale's cost shows at the next mark, then cash stays put
    assert curve[2] == pytest.approx(curve[1] * (1 - ROUND_TRIP_COST / 2))
    assert curve[4] > curve[3]                                    # back in, takes part in the rebound


def test_verdict_needs_both_periods():
    v = [{"rule": "a", "base": 0.8, "breach_20": 0.05, "median_annual": 0.10},
         {"rule": "b", "base": 0.8, "breach_20": 0.02, "median_annual": 0.12}]
    s = [{"rule": "a", "base": 0.8, "breach_20": 0.08}, {"rule": "b", "base": 0.8, "breach_20": 0.40}]
    out = D.verdict(v, s)
    assert out["passing"] == [("a", 0.8)] and out["recommended"]["rule"] == "a"
