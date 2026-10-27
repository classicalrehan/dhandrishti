"""Entry-signal study (research/entry_signals.py): no look-ahead, correct event arithmetic, honest verdicts."""

from datetime import date, timedelta

import numpy as np
import pytest

from dhandrishti.models import Bars, MarketHistory, Security
from dhandrishti.research import entry_signals as E
from dhandrishti.research.factors import ROUND_TRIP_COST


def _dates(n, start=date(2015, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(close, volume=None, dates=None, opens=None, lows=None):
    c = np.asarray(close, float)
    return Bars(dates or _dates(len(c)), np.asarray(opens if opens is not None else c, float), c * 1.01,
                np.asarray(lows if lows is not None else c * 0.99, float), c,
                np.asarray(volume if volume is not None else np.full(len(c), 1000.0), float))


def test_signals_use_only_past_data():
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.02, 900)))
    vol = rng.uniform(500, 3000, 900)
    full = _bars(close, vol)
    whole = E.signals(full)
    for cut in (300, 451, 600, 777, 899):
        part = E.signals(Bars(full.dates[:cut + 1], full.open[:cut + 1], full.high[:cut + 1], full.low[:cut + 1],
                              full.close[:cut + 1], full.volume[:cut + 1]))
        for k in whole:
            assert np.array_equal(part[k], whole[k][:cut + 1]), (k, cut)   # adding the future changes nothing


def test_breakout_needs_a_new_55_day_high_and_volume():
    close = np.full(400, 100.0)
    close[:250] = np.linspace(50, 100, 250)          # rising, then flat above the 200-day average
    vol = np.full(400, 1000.0)
    close[350], vol[350] = 105.0, 1600.0             # new high with 1.6x volume
    close[370], vol[370] = 106.0, 1200.0             # new high, volume too low
    s = E.signals(_bars(close, vol))["breakout"]
    assert s[350] and not s[370] and s.sum() == 1


def test_continuation_and_cooldown():
    close = np.linspace(50, 150, 400)
    for k in (300, 310, 340):                        # dips below SMA20, recovers the next day
        close[k] = close[k] * 0.9
    s = E.signals(_bars(close))["continuation"]
    assert s[301] and not s[311] and s[341]          # 311 is within 20 sessions of 301: cooled down


def _history(prices: dict[str, Bars], nifty: Bars) -> MarketHistory:
    secs = [Security(s, s, "Test", False) for s in prices]
    return MarketHistory("2026-01-01", "EOD", secs, prices, {}, {}, nifty, nifty, nifty)


def test_event_arithmetic_entry_next_open_costs_control_and_exclusions():
    n = 30
    d = _dates(n)
    up = _bars(np.linspace(100, 129, n), dates=d, opens=np.linspace(100, 129, n) + 0.5)
    flat = _bars(np.full(n, 50.0), dates=d)
    jumpy_close = np.full(n, 80.0)
    jumpy_close[9:] = 200.0                                          # +150% in one day: unadjusted action?
    jumpy = _bars(jumpy_close, dates=d)
    nifty = _bars(np.full(n, 1000.0), dates=d, opens=np.linspace(1000, 1029, n))

    def fire(b):                                                     # signal on day 5 for every stock
        m = np.zeros(len(b.dates), bool)
        m[5] = True
        return {"test": m}

    res = E.run(_history({"UP": up, "FLAT": flat, "JUMPY": jumpy}, nifty), horizons=(5, 30), signal_fn=fire)
    ev = {(e.symbol, e.horizon): e for e in res.events}
    e = ev[("UP", 5)]
    entry, exit_ = up.open[6], up.open[11]                           # next open, open 5 sessions later
    assert e.gross == pytest.approx(exit_ / entry - 1) and e.net == pytest.approx(e.gross - ROUND_TRIP_COST)
    assert e.net_stress == pytest.approx(e.net - E.EXTRA_SLIPPAGE)
    control = np.mean([up.open[11] / up.open[6] - 1, 0.0])           # JUMPY's window is suspect: not in control
    assert e.excess == pytest.approx(e.gross - control)
    assert e.excess_nifty == pytest.approx(e.gross - (nifty.open[11] / nifty.open[6] - 1))
    assert e.mae == pytest.approx(min(up.low[6:11].min(), exit_) / entry - 1)
    assert ("JUMPY", 5) not in ev and res.excluded["suspect_price_jump"] == 1
    assert ("UP", 30) not in ev and res.excluded["window_beyond_data"] == 3


def test_summary_clusters_by_date_and_verdicts_need_both_later_periods():
    def ev(strategy, day, excess):
        return E.Event(strategy, "X", day, 20, excess, excess, excess, excess, excess, -0.05)
    good = [ev("a", f"{y}-0{m}-15", 0.02 + 0.001 * m) for y in (2020, 2021, 2024, 2025) for m in range(1, 10)]
    half = [ev("b", f"2020-0{m}-15", 0.03) for m in range(1, 10)] + \
           [ev("b", f"2024-0{m}-15", -0.01 + 0.004 * (m % 2)) for m in range(1, 10)]
    res = E.StudyResult(good + half)
    rows = E.summarize(res)
    v = E.verdict(rows)
    assert v[("a", 20)].startswith("CANDIDATE") and v[("b", 20)] == "NO DEMONSTRATED EDGE"
    all_a = next(r for r in rows if r["strategy"] == "a" and r["period"] == "all")
    assert all_a["events"] == 36 and all_a["dates"] == 36
    assert "| a | 20 | all | 36 |" in E.markdown(rows, res)


def test_point_in_time_universe_limits_signals_and_control_to_members_on_the_signal_day():
    n = 30
    d = _dates(n)
    up = _bars(np.linspace(100, 129, n), dates=d)
    down = _bars(np.linspace(100, 71, n), dates=d)
    flat = _bars(np.full(n, 50.0), dates=d)
    nifty = _bars(np.full(n, 1000.0), dates=d)

    def fire(b):
        m = np.zeros(len(b.dates), bool)
        m[[3, 5]] = True
        return {"test": m}

    def members(day):                         # DOWN joins on day 5; before day 3 nothing is known
        if day < d[3]:
            return None
        return frozenset({"UP", "FLAT"} | ({"DOWN"} if day >= d[5] else set()))

    res = E.run(_history({"UP": up, "DOWN": down, "FLAT": flat}, nifty), horizons=(5,), signal_fn=fire,
                members=members)
    ev = {(e.symbol, e.signal_date): e for e in res.events}
    assert ("DOWN", d[3]) not in ev and ("DOWN", d[5]) in ev and res.excluded["not_a_member"] == 1
    on3 = np.mean([up.open[9] / up.open[4] - 1, 0.0])                       # control on day 3: UP and FLAT only
    assert ev[("UP", d[3])].excess == pytest.approx(ev[("UP", d[3])].gross - on3)
    on5 = np.mean([up.open[11] / up.open[6] - 1, down.open[11] / down.open[6] - 1, 0.0])
    assert ev[("UP", d[5])].excess == pytest.approx(ev[("UP", d[5])].gross - on5)
    plain = E.run(_history({"UP": up, "DOWN": down, "FLAT": flat}, nifty), horizons=(5,), signal_fn=fire)
    assert len(plain.events) == 6 and "not_a_member" not in plain.excluded    # unchanged without a universe


def test_verdict_uses_the_given_later_periods():
    rows = [{"strategy": "a", "horizon": 20, "period": p, "events": 9, "t_nw": 2.5, "mean_excess": 0.01}
            for p in ("2021-2022", "2023-2026")]
    assert E.verdict(rows, ("2021-2022", "2023-2026"), "pit")[("a", 20)] == "CANDIDATE (consistent positive excess; pit)"
    assert E.verdict(rows)[("a", 20)] == "NO DEMONSTRATED EDGE"               # default periods absent
