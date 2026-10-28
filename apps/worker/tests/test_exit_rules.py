"""Exit-rule study (research/exit_rules.py): triggers on closes, fills at the next open, same trades for every rule."""

from datetime import date, timedelta

import numpy as np
import pytest

from dhandrishti.models import Bars, MarketHistory, Security
from dhandrishti.research import exit_rules as X
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
    return Bars(dates, o, np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, c, np.full(len(c), 1000.0))


def _history(bars, dates):
    secs = [Security(s, s, "Test", False) for s in bars]
    nifty = _bars(np.full(len(dates), 1000.0), dates)
    return MarketHistory(dates[-1], "EOD", secs, bars, {}, {}, nifty, nifty, nifty)


def test_triggers_use_closes_and_the_first_breach():
    c = np.full(200, 100.0)
    c[105], c[106] = 91.0, 80.0                 # -9% then -20% after entry at index 100 (entry price 100)
    sma = np.full(200, 95.0)
    atr = np.full(200, 2.0)
    assert X._exit("stop8", 100, 100.0, c, sma, atr) == (105, "stop")
    assert X._exit("stop15", 100, 100.0, c, sma, atr) == (106, "stop")
    assert X._exit("sma50", 100, 100.0, c, sma, atr) == (105, "trend")
    assert X._exit("atr3", 100, 100.0, c, sma, atr) == (105, "stop")        # 100 - 3 x 2 = 94
    up = np.full(200, 100.0)
    up[110:] = 120.0
    up[130] = 101.0                             # trailing: 0.85 x 120 = 102
    assert X._exit("trail15", 100, 100.0, up, sma, atr) == (130, "stop")
    assert X._exit("tgt15_stop8", 100, 100.0, up, sma, atr) == (110, "target")
    flat = np.full(200, 100.0)
    assert X._exit("stop8", 100, 100.0, flat, sma, atr) == (100 + X.HOLD - 1, "time")


def test_run_fills_at_next_open_including_gaps_and_keeps_trades_identical_across_rules():
    n = 260
    d = _dates(n)
    close = np.full(n, 100.0)
    opens = np.full(n, 100.0)
    t = X.first_sessions(d)[3]                  # a cohort with history before it
    e = t + 1
    close[e + 2] = 90.0                         # breach on a close ...
    opens[e + 3] = 70.0                         # ... and a gap down at the next open: the fill is 70, not 92
    close[e + 3:] = 70.0
    bars = {"GAP": _bars(close, d, opens), "FLAT": _bars(np.full(n, 50.0), d)}

    def members(day):
        return None if day < d[t] else frozenset({"GAP", "FLAT"} if day == d[t] else {"FLAT"})

    res = X.run(_history(bars, d), members, rules=("time60", "stop8"))
    gap = {(tr.rule, tr.cohort): tr for tr in res.trades if tr.symbol == "GAP"}
    stop = gap[("stop8", d[t])]
    assert stop.net == pytest.approx(0.70 - 1 - ROUND_TRIP_COST) and stop.reason == "stop" and stop.held == 3
    assert gap[("time60", d[t])].reason == "time" and gap[("time60", d[t])].held == X.HOLD
    assert len(gap) == 2                        # GAP only traded in the cohort where it was a member
    pairs = {r: {(tr.symbol, tr.cohort) for tr in res.trades if tr.rule == r} for r in ("time60", "stop8")}
    assert pairs["time60"] == pairs["stop8"]
    assert res.excluded["membership_unknown"] == 3


def test_portfolio_holds_cash_after_an_exit_and_charges_costs_once():
    n = 200
    d = _dates(n)
    close = np.full(n, 100.0)
    t = X.first_sessions(d)[3]
    close[t + 3:] = 80.0                        # falls 20% and stays there
    bars = {"A": _bars(close, d)}
    one = {d[t]}
    res = X.run(_history(bars, d), lambda day: frozenset({"A"}) if day in one else frozenset(), rules=("time60", "stop8"))
    dates, r = res.curves["stop8"]
    eq = np.cumprod(1 + r)
    assert eq[-1] == pytest.approx(0.80 - ROUND_TRIP_COST)      # exit at the next open (80), costs once
    assert np.allclose(eq[3:], eq[-1])                          # flat cash after the exit
    _, base = res.curves["time60"]
    assert np.cumprod(1 + base)[-1] == pytest.approx(0.80 - ROUND_TRIP_COST)
    stats = X.curve_stats(dates, r, "0000", "9999")
    assert stats["max_drawdown"] == pytest.approx(0.80 - ROUND_TRIP_COST - 1)


def test_verdicts_need_both_periods_and_no_significant_return_cost():
    def row(rule, period, dd, diff=0.0, t=0.0):
        return {"rule": rule, "period": period, "max_drawdown": dd, "diff_vs_base": diff, "t_diff": t}
    base = [row("time60", p, -0.20) for p in ("all", "2021-2022", "2023-2026")]
    good = [row("a", "all", -0.15, -0.001, -0.5), row("a", "2021-2022", -0.16), row("a", "2023-2026", -0.15)]
    half = [row("b", "all", -0.15), row("b", "2021-2022", -0.19), row("b", "2023-2026", -0.10)]
    costly = [row("c", "all", -0.10, -0.01, -3.0), row("c", "2021-2022", -0.10, -0.01, -2.5),
              row("c", "2023-2026", -0.10, -0.01, -2.1)]
    v = X.verdict(base + good + half + costly)
    assert v["a"] == ["REDUCES DRAWDOWN"]
    assert v["b"] == ["NO DEMONSTRATED BENEFIT"]
    assert v["c"] == ["COSTS RETURN"]           # smaller drawdown bought with a significant return cost
