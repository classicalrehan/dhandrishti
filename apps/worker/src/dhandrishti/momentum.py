"""Raw metrics for Momentum and Technical Trend (SPEC §5)."""

from .technicals import Technicals

Metrics = dict[str, float | bool | None]


def momentum_metrics(t: Technicals) -> Metrics:
    accel = None if t.ret_1m is None or t.ret_3m is None else t.ret_1m - t.ret_3m / 3
    return {
        "ret_1m": t.ret_1m,
        "ret_3m": t.ret_3m,
        "ret_6m": t.ret_6m,
        "ret_1y": t.ret_1y,
        "rs_nifty_3m": t.rs_nifty_3m,
        "rs_nifty_6m": t.rs_nifty_6m,
        "up_down_volume_ratio": t.up_down_volume_ratio,
        "momentum_acceleration": accel,
    }


def trend_metrics(t: Technicals) -> Metrics:
    directional = None
    if t.adx14 is not None and t.plus_di is not None and t.minus_di is not None:
        directional = t.adx14 if t.plus_di > t.minus_di else 0.0
    return {
        "above_sma50": None if t.sma50 is None else t.close > t.sma50,
        "above_sma200": None if t.sma200 is None else t.close > t.sma200,
        "sma50_above_sma200": None if t.sma50 is None or t.sma200 is None else t.sma50 > t.sma200,
        "sma200_slope_20d": t.sma200_slope_20d,
        "directional_adx": directional,
        "rsi14": t.rsi14,
        "macd_hist_positive": None if t.macd_hist is None else t.macd_hist > 0,
        "dist_from_52w_high": t.dist_from_52w_high,
    }
