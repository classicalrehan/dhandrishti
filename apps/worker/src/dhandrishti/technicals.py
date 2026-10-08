"""Per-security technical snapshot (SPEC §3)."""

from dataclasses import asdict, dataclass

import numpy as np

from . import indicators as ind
from .models import Bars

L = ind.LOOKBACK


@dataclass
class Technicals:
    close: float
    prev_close: float | None
    change: float | None
    change_pct: float | None
    sma20: float | None
    sma50: float | None
    sma100: float | None
    sma200: float | None
    ema20: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    adx14: float | None
    plus_di: float | None
    minus_di: float | None
    atr14: float | None
    atr_pct: float | None
    bb_upper: float | None
    bb_lower: float | None
    high_52w: float | None
    low_52w: float | None
    dist_from_52w_high: float | None
    dist_from_sma50: float | None
    dist_from_sma200: float | None
    sma200_slope_20d: float | None
    volume: float
    volume_sma20: float | None
    volume_sma50: float | None
    relative_volume: float | None
    avg_traded_value_cr: float | None
    up_down_volume_ratio: float | None
    ret_1d: float | None
    ret_1w: float | None
    ret_1m: float | None
    ret_3m: float | None
    ret_6m: float | None
    ret_1y: float | None
    rs_nifty_1m: float | None
    rs_nifty_3m: float | None
    rs_nifty_6m: float | None
    volatility_60d: float | None
    max_drawdown_1y: float | None
    gap_moves_60d: int
    trend: str
    bars: int

    def to_dict(self) -> dict:
        return asdict(self)


def classify_trend(close: float, sma50: float | None, sma200: float | None,
                   slope: float | None, adx14: float | None) -> str:
    if sma50 is None or sma200 is None:
        return "SIDEWAYS"
    strong = (adx14 or 0) >= 25
    rising = (slope or 0) > 0
    if close > sma50 > sma200:
        return "STRONG_UPTREND" if strong and rising else "UPTREND"
    if close < sma50 < sma200:
        return "STRONG_DOWNTREND" if strong and not rising else "DOWNTREND"
    return "SIDEWAYS"


def _pct_from(close: float, ref: float | None) -> float | None:
    return None if ref is None or ref == 0 else (close / ref - 1) * 100


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def compute_technicals(bars: Bars, benchmark: Bars | None = None) -> Technicals:
    if len(bars) == 0:
        raise ValueError("compute_technicals: no bars")
    c, h, lo, v = bars.close, bars.high, bars.low, bars.volume
    close = float(c[-1])
    prev = float(c[-2]) if len(c) > 1 else None

    s50 = ind.sma(c, 50)
    s200 = ind.sma(c, 200)
    m_line, m_sig, m_hist = ind.macd(c)
    adx_s, pdi, mdi = ind.adx(h, lo, c)
    atr14 = ind.last(ind.atr(h, lo, c))
    _, bb_u, bb_l = ind.bollinger(c)
    v20 = ind.last(ind.sma(v, 20))

    year_h, year_l = h[-L["y1"]:], lo[-L["y1"]:]
    high_52w = float(year_h.max()) if len(year_h) >= 200 else None
    low_52w = float(year_l.min()) if len(year_l) >= 200 else None

    atv = None
    if len(c) >= 20:
        atv = float(np.mean(c[-20:] * v[-20:] / 1e7))

    o = bars.open[-61:]
    pc = c[-61:]
    gaps = int(np.sum(np.abs(o[1:] / pc[:-1] - 1) > 0.04)) if len(pc) > 1 else 0

    ud = None
    if len(c) > 50:
        chg = np.diff(c[-51:])
        vol = v[-50:]
        down_v = float(vol[chg < 0].sum())
        if down_v > 0:
            ud = float(vol[chg > 0].sum()) / down_v

    rets = {k: ind.pct_return(c, n) for k, n in L.items()}
    bench = {k: (ind.pct_return(benchmark.close, L[k]) if benchmark is not None else None)
             for k in ("m1", "m3", "m6")}

    sma50, sma200 = ind.last(s50), ind.last(s200)
    slope = ind.slope_pct(s200, 20)
    adx14 = ind.last(adx_s)

    return Technicals(
        close=close,
        prev_close=prev,
        change=None if prev is None else close - prev,
        change_pct=None if prev is None else (close / prev - 1) * 100,
        sma20=ind.last(ind.sma(c, 20)),
        sma50=sma50,
        sma100=ind.last(ind.sma(c, 100)),
        sma200=sma200,
        ema20=ind.last(ind.ema(c, 20)),
        rsi14=ind.last(ind.rsi(c)),
        macd=ind.last(m_line),
        macd_signal=ind.last(m_sig),
        macd_hist=ind.last(m_hist),
        adx14=adx14,
        plus_di=ind.last(pdi),
        minus_di=ind.last(mdi),
        atr14=atr14,
        atr_pct=None if atr14 is None else atr14 / close * 100,
        bb_upper=ind.last(bb_u),
        bb_lower=ind.last(bb_l),
        high_52w=high_52w,
        low_52w=low_52w,
        dist_from_52w_high=_pct_from(close, high_52w),
        dist_from_sma50=_pct_from(close, sma50),
        dist_from_sma200=_pct_from(close, sma200),
        sma200_slope_20d=slope,
        volume=float(v[-1]),
        volume_sma20=v20,
        volume_sma50=ind.last(ind.sma(v, 50)),
        relative_volume=None if not v20 else float(v[-1]) / v20,
        avg_traded_value_cr=atv,
        up_down_volume_ratio=ud,
        ret_1d=rets["d1"],
        ret_1w=rets["w1"],
        ret_1m=rets["m1"],
        ret_3m=rets["m3"],
        ret_6m=rets["m6"],
        ret_1y=rets["y1"],
        rs_nifty_1m=_diff(rets["m1"], bench["m1"]),
        rs_nifty_3m=_diff(rets["m3"], bench["m3"]),
        rs_nifty_6m=_diff(rets["m6"], bench["m6"]),
        volatility_60d=ind.annualized_volatility(c, 60),
        max_drawdown_1y=ind.max_drawdown(c[-L["y1"]:]),
        gap_moves_60d=gaps,
        trend=classify_trend(close, sma50, sma200, slope, adx14),
        bars=len(c),
    )


SERIES_COLUMNS = ("sma20", "sma50", "sma200", "ema20", "rsi14", "macd", "macd_signal", "macd_hist",
                  "bb_upper", "bb_lower")


def indicator_series(bars: Bars) -> dict[str, np.ndarray]:
    """Full aligned indicator series for chart overlays (NaN during warm-up)."""
    c = bars.close
    m_line, m_sig, m_hist = ind.macd(c)
    _, bb_u, bb_l = ind.bollinger(c)
    return {
        "sma20": ind.sma(c, 20),
        "sma50": ind.sma(c, 50),
        "sma200": ind.sma(c, 200),
        "ema20": ind.ema(c, 20),
        "rsi14": ind.rsi(c),
        "macd": m_line,
        "macd_signal": m_sig,
        "macd_hist": m_hist,
        "bb_upper": bb_u,
        "bb_lower": bb_l,
    }
