"""Position-sizing study (research/position_sizing.py): exposure, stops, costs and common random draws."""

from datetime import date, timedelta

import numpy as np
import pytest

from dhandrishti.models import Bars, MarketHistory, Security
from dhandrishti.research import position_sizing as S
from dhandrishti.research.factors import ROUND_TRIP_COST


def _dates(n, start=date(2021, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(close, dates, opens=None):
    c = np.asarray(close, float)
    o = np.asarray(opens if opens is not None else c, float)
    return Bars(dates, o, np.maximum(o, c), np.minimum(o, c), c, np.full(len(c), 1000.0))


def _history(bars, dates):
    secs = [Security(s, s, "Test", False) for s in bars]
    nifty = _bars(np.full(len(dates), 1000.0), dates)
    return MarketHistory(dates[-1], "EOD", secs, bars, {}, {}, nifty, nifty, nifty)


def _setup():
    n = 400
    d = _dates(n)
    starts = S.quarter_starts(d)
    q0 = starts[1]                                   # leave history before the first quarter
    fall = np.full(n, 100.0)
    fall[q0 + 5:] = 80.0                              # -20% inside the first quarter, then flat
    opens = fall.copy()
    rng = np.random.default_rng(1)
    wiggle = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    bars = {"FALL": _bars(fall, d, opens), "FLAT": _bars(np.full(n, 50.0), d), "WIGGLE": _bars(wiggle, d)}
    members = lambda day: None if day < d[q0] else frozenset(bars)  # noqa: E731
    return S.prepare(_history(bars, d), members), d, q0


def test_stop_fills_at_next_open_and_holds_cash_until_the_rebalance():
    quarters, d, q0 = _setup()
    q = quarters[0]
    assert d[q.start - 1] == d[q0]                   # decision at the quarter's first session, entry next open
    i = q.symbols.index("FALL")
    assert q.rel[None][i][-1] == pytest.approx(0.80)
    stopped = q.rel[0.08][i]
    assert stopped[3] == pytest.approx(1.0) and np.allclose(stopped[4:], 0.80)   # breach close at day 3 -> fill 0.80
    assert len(quarters) >= 2


def test_exposure_scales_the_invested_part_and_costs_are_charged_on_it():
    quarters, _, _ = _setup()
    one = [quarters[0]]
    q = one[0]
    full = S.simulate(one, n=3, exposure=1.0, weighting="equal", stop=None, paths=1)
    half = S.simulate(one, n=3, exposure=0.5, weighting="equal", stop=None, paths=1)
    basket = q.rel[None].mean(axis=0)
    assert full[0] == pytest.approx((1 - ROUND_TRIP_COST) * basket)
    assert half[0] == pytest.approx((1 - 0.5 * ROUND_TRIP_COST) * (0.5 + 0.5 * basket))


def test_every_setting_sees_the_same_random_draws():
    quarters, _, _ = _setup()
    a = S.simulate(quarters, n=1, exposure=1.0, weighting="equal", stop=None, paths=20)
    b = S.simulate(quarters, n=1, exposure=0.5, weighting="equal", stop=None, paths=20)
    # with one stock and half the exposure, each path's return is exactly halved day by day: same picks
    ra, rb = np.diff(np.concatenate([np.ones((20, 1)), a], 1), axis=1), np.diff(np.concatenate([np.ones((20, 1)), b], 1), axis=1)
    assert np.sign(ra[:, 10:]).tolist() == np.sign(rb[:, 10:]).tolist()
    assert np.array_equal(S.simulate(quarters, 1, 1.0, "equal", None, 20), a)          # reproducible


def test_stats_and_verdict_rules():
    flat_then_drop = np.array([[1.0] * 9 + [0.75] * 3, [1.0] * 9 + [0.9] * 3])
    st = S.path_stats(flat_then_drop, days=252)
    assert st["breach_20"] == 0.5 and st["median_dd"] == pytest.approx(-0.175)
    rows = [
        {"n": 5, "exposure": 1.0, "weighting": "equal", "stop": None, "breach_20": 0.40, "median_annual": 0.15},
        {"n": 5, "exposure": 1.0, "weighting": "equal", "stop": 0.08, "breach_20": 0.30, "median_annual": 0.145},
        {"n": 5, "exposure": 0.6, "weighting": "equal", "stop": None, "breach_20": 0.08, "median_annual": 0.09},
        {"n": 5, "exposure": 0.6, "weighting": "equal", "stop": 0.08, "breach_20": 0.07, "median_annual": 0.05},
    ]
    v = S.verdict(rows)
    assert v["recommended"]["exposure"] == 0.6 and v["recommended"]["stop"] is None and v["acceptable"] == 2
    assert v["stop_helps"] == [(5, 1.0, "equal")]
