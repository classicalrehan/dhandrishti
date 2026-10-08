"""Technical indicators (SPEC §3).

Series functions take 1-D float arrays and return arrays of the same length,
with NaN where there is not enough history. Implementations are explicit loops
or cumulative sums so the recursion matches the spec exactly (pandas' ewm
seeding differs from Wilder's).
"""

import math

import numpy as np

Array = np.ndarray

LOOKBACK = {"d1": 1, "w1": 5, "m1": 21, "m3": 63, "m6": 126, "y1": 252}


def _nan(n: int) -> Array:
    return np.full(n, np.nan)


def last(a: Array) -> float | None:
    if len(a) == 0:
        return None
    v = float(a[-1])
    return None if math.isnan(v) else v


def sma(x: Array, n: int) -> Array:
    out = _nan(len(x))
    if len(x) < n:
        return out
    c = np.cumsum(np.insert(np.asarray(x, dtype=float), 0, 0.0))
    out[n - 1 :] = (c[n:] - c[:-n]) / n
    return out


def ema(x: Array, n: int) -> Array:
    out = _nan(len(x))
    if len(x) < n:
        return out
    k = 2.0 / (n + 1)
    prev = float(np.mean(x[:n]))
    out[n - 1] = prev
    for i in range(n, len(x)):
        prev = float(x[i]) * k + prev * (1 - k)
        out[i] = prev
    return out


def wilder(x: Array, n: int, start: int = 0) -> Array:
    """Wilder smoothing: seed = simple mean of x[start:start+n], then (prev*(n-1)+x)/n."""
    out = _nan(len(x))
    if len(x) < start + n:
        return out
    prev = float(np.mean(x[start : start + n]))
    out[start + n - 1] = prev
    for i in range(start + n, len(x)):
        prev = (prev * (n - 1) + float(x[i])) / n
        out[i] = prev
    return out


def rsi(close: Array, n: int = 14) -> Array:
    out = _nan(len(close))
    if len(close) <= n:
        return out
    d = np.diff(close)
    gain = float(np.clip(d[:n], 0, None).sum()) / n
    loss = float(np.clip(-d[:n], 0, None).sum()) / n

    def value(g: float, l: float) -> float:
        return 100.0 if l == 0 else 100.0 - 100.0 / (1 + g / l)

    out[n] = value(gain, loss)
    for i in range(n + 1, len(close)):
        di = float(d[i - 1])
        gain = (gain * (n - 1) + max(di, 0.0)) / n
        loss = (loss * (n - 1) + max(-di, 0.0)) / n
        out[i] = value(gain, loss)
    return out


def macd(close: Array, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Array, Array, Array]:
    line = ema(close, fast) - ema(close, slow)
    sig = _nan(len(close))
    valid = np.flatnonzero(~np.isnan(line))
    if len(valid):
        s = int(valid[0])
        sig[s:] = ema(line[s:], signal)
    return line, sig, line - sig


def true_range(high: Array, low: Array, close: Array) -> Array:
    tr = high - low
    if len(close) > 1:
        pc = close[:-1]
        tr[1:] = np.maximum.reduce([high[1:] - low[1:], np.abs(high[1:] - pc), np.abs(low[1:] - pc)])
    return tr


def atr(high: Array, low: Array, close: Array, n: int = 14) -> Array:
    return wilder(true_range(high, low, close), n, start=1)


def adx(high: Array, low: Array, close: Array, n: int = 14) -> tuple[Array, Array, Array]:
    size = len(close)
    up = np.zeros(size)
    down = np.zeros(size)
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    up[1:] = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    down[1:] = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s = wilder(true_range(high, low, close), n, start=1)
    p_s = wilder(up, n, start=1)
    m_s = wilder(down, n, start=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(tr_s > 0, 100 * p_s / tr_s, np.nan)
        minus_di = np.where(tr_s > 0, 100 * m_s / tr_s, np.nan)
        di_sum = plus_di + minus_di
        dx = np.where(di_sum > 0, 100 * np.abs(plus_di - minus_di) / di_sum, 0.0)
    adx_out = _nan(size)
    valid = np.flatnonzero(~np.isnan(plus_di))
    if len(valid):
        s = int(valid[0])
        adx_out[s:] = wilder(dx[s:], n)
    return adx_out, plus_di, minus_di


def rolling_std(x: Array, n: int) -> Array:
    """Population standard deviation over a sliding window."""
    out = _nan(len(x))
    for i in range(n - 1, len(x)):
        out[i] = float(np.std(x[i - n + 1 : i + 1]))
    return out


def bollinger(close: Array, n: int = 20, mult: float = 2.0) -> tuple[Array, Array, Array]:
    mid = sma(close, n)
    sd = rolling_std(close, n)
    return mid, mid + mult * sd, mid - mult * sd


def pct_return(close: Array, lookback: int) -> float | None:
    if len(close) <= lookback:
        return None
    start = float(close[-1 - lookback])
    return None if start == 0 else (float(close[-1]) / start - 1) * 100


def daily_returns(close: Array) -> Array:
    return close[1:] / close[:-1] - 1


def annualized_volatility(close: Array, n: int = 60) -> float | None:
    r = daily_returns(close)[-n:]
    if len(r) < n:
        return None
    return float(np.std(r, ddof=1)) * math.sqrt(252) * 100


def max_drawdown(close: Array) -> float | None:
    if len(close) < 2:
        return None
    peak = np.maximum.accumulate(close)
    return float(np.min(close / peak - 1)) * 100


def slope_pct(series: Array, lookback: int) -> float | None:
    if len(series) <= lookback:
        return None
    end, start = float(series[-1]), float(series[-1 - lookback])
    if math.isnan(end) or math.isnan(start) or start == 0:
        return None
    return (end / start - 1) * 100
