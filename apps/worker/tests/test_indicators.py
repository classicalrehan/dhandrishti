import math

import numpy as np
import pytest

from dhandrishti import indicators as ind
from dhandrishti.technicals import classify_trend


def test_sma_warmup_and_values():
    out = ind.sma(np.array([1, 2, 3, 4, 5], dtype=float), 3)
    assert np.isnan(out[:2]).all()
    assert out[2:].tolist() == [2, 3, 4]


def test_ema_seed_and_convergence():
    e = ind.ema(np.array([2, 4, 6] + [8] * 9, dtype=float), 3)
    assert e[2] == 4
    assert e[-1] == pytest.approx(8, abs=0.05)


def test_rsi_extremes():
    up = np.arange(100, 130, dtype=float)
    down = np.arange(130, 100, -1, dtype=float)
    assert ind.rsi(up)[-1] == 100
    assert ind.rsi(down)[-1] < 1


def test_rsi_wilder_reference():
    # Wilder (1978) worked example as reproduced in common references: first RSI ≈ 70.53.
    closes = np.array([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
                       45.89, 46.03, 45.61, 46.28, 46.28])
    assert ind.rsi(closes, 14)[-1] == pytest.approx(70.53, abs=0.5)


def test_macd_positive_in_uptrend():
    up = 100 * 1.01 ** np.arange(80)
    line, sig, hist = ind.macd(up)
    assert line[-1] > 0 and not math.isnan(sig[-1])
    assert np.isnan(sig[25]) and not np.isnan(sig[25 + 8])  # signal starts 8 bars after MACD line


def test_atr_and_adx_on_linear_trend():
    i = np.arange(60, dtype=float)
    h, lo, c = 101 + i, 99 + i, 100 + i
    assert ind.atr(h, lo, c)[-1] == pytest.approx(2, abs=0.05)
    adx, pdi, mdi = ind.adx(h, lo, c)
    assert adx[-1] > 50 and pdi[-1] > mdi[-1]


def test_returns_and_risk_measures():
    assert ind.pct_return(np.array([100.0, 110.0]), 1) == pytest.approx(10)
    assert ind.pct_return(np.array([100.0]), 1) is None
    assert ind.max_drawdown(np.array([100.0, 120, 60, 90, 130])) == pytest.approx(-50)
    g = 100 * 1.001 ** np.arange(70)
    assert ind.annualized_volatility(g) == pytest.approx(0, abs=1e-9)


def test_bollinger_band_width():
    c = np.array([10.0] * 19 + [30.0])
    mid, up, lo = ind.bollinger(c)
    assert mid[-1] == pytest.approx(11)
    assert up[-1] - mid[-1] == pytest.approx(2 * np.std(c))


@pytest.mark.parametrize("args,expected", [
    ((120, 110, 100, 2, 30), "STRONG_UPTREND"),
    ((120, 110, 100, -1, 30), "UPTREND"),
    ((80, 90, 100, -1, 30), "STRONG_DOWNTREND"),
    ((80, 90, 100, 1, 30), "DOWNTREND"),
    ((105, 110, 100, 1, 30), "SIDEWAYS"),
    ((120, None, None, None, None), "SIDEWAYS"),
])
def test_classify_trend(args, expected):
    assert classify_trend(*args) == expected
