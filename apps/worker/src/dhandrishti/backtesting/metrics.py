"""Performance statistics for equity curves. Pure functions over daily values."""

import math

import numpy as np

TRADING_DAYS = 252


def daily_returns(values: np.ndarray) -> np.ndarray:
    return values[1:] / values[:-1] - 1


def cagr(values: np.ndarray, dates: list[str]) -> float | None:
    if len(values) < 2:
        return None
    from datetime import date
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    return None if years <= 0 else ((values[-1] / values[0]) ** (1 / years) - 1) * 100


def drawdown_series(values: np.ndarray) -> np.ndarray:
    return (values / np.maximum.accumulate(values) - 1) * 100


def max_drawdown(values: np.ndarray, dates: list[str]) -> dict:
    dd = drawdown_series(values)
    trough = int(np.argmin(dd))
    peak = int(np.argmax(values[: trough + 1]))
    return {"pct": float(dd[trough]), "peak": dates[peak], "trough": dates[trough]}


def summary(values: np.ndarray, dates: list[str], rf_annual: float) -> dict:
    r = daily_returns(values)
    vol = float(np.std(r, ddof=1)) * math.sqrt(TRADING_DAYS) * 100 if len(r) > 1 else None
    excess = r - rf_annual / TRADING_DAYS
    sd = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    downside = r[r < 0]
    dsd = float(np.sqrt(np.mean(downside**2))) if len(downside) else 0.0
    mdd = max_drawdown(values, dates)
    c = cagr(values, dates)
    return {
        "total_return_pct": float((values[-1] / values[0] - 1) * 100),
        "cagr_pct": c,
        "volatility_pct": vol,
        "sharpe": None if sd == 0 else float(np.mean(excess) / sd * math.sqrt(TRADING_DAYS)),
        "sortino": None if dsd == 0 else float(np.mean(excess) / dsd * math.sqrt(TRADING_DAYS)),
        "max_drawdown_pct": mdd["pct"],
        "max_drawdown_peak": mdd["peak"],
        "max_drawdown_trough": mdd["trough"],
        "calmar": None if not c or mdd["pct"] == 0 else float(c / abs(mdd["pct"])),
    }


def relative(strategy: np.ndarray, bench: np.ndarray) -> dict:
    rs, rb = daily_returns(strategy), daily_returns(bench)
    active = rs - rb
    te = float(np.std(active, ddof=1)) * math.sqrt(TRADING_DAYS) if len(active) > 1 else None
    var_b = float(np.var(rb, ddof=1)) if len(rb) > 1 else 0.0
    return {
        "beta": None if var_b == 0 else float(np.cov(rs, rb, ddof=1)[0, 1] / var_b),
        "tracking_error_pct": None if te is None else te * 100,
        "information_ratio": None if not te else float(np.mean(active) * TRADING_DAYS / te),
    }


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Rank correlation (average ranks for ties)."""
    if len(a) < 3:
        return None
    import pandas as pd
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])
