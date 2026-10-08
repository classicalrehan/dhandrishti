"""Raw metrics for Valuation (SPEC §5). Valuation is always read relative to
sector peers and the stock's own history — never as "low PE is good"."""

import math
from dataclasses import replace

from .models import Fundamentals

Metrics = dict[str, float | bool | None]


def relative(value: float | None, ref: float | None) -> float | None:
    """value/ref, with non-positive value (e.g. loss-making PE) mapped to +inf."""
    if value is None or ref is None or ref <= 0:
        return None
    return math.inf if value <= 0 else value / ref


def valuation_metrics(
    f: Fundamentals | None, sector_median_pe: float | None, sector_median_pb: float | None
) -> Metrics:
    if f is None:
        return {}
    peg = f.peg
    return {
        "pe_vs_sector": relative(f.pe, sector_median_pe),
        "pe_vs_history": relative(f.pe, f.pe_median_5y),
        "peg": None if peg is None else (math.inf if peg <= 0 else peg),
        "pb_vs_sector": relative(f.pb, sector_median_pb),
        "dividend_yield": f.dividend_yield,
    }


def reprice(f: Fundamentals | None, close: float) -> Fundamentals | None:
    """Recompute price-dependent valuation from the scoring day's close (SPEC §5.2).

    Only when the snapshot carries per-share data (real filings). Otherwise the stored values are
    used as-is, which keeps MOCK data and the golden fixtures unchanged.
    """
    if f is None or f.eps_ttm is None or close <= 0:
        return f
    pe = close / f.eps_ttm if f.eps_ttm != 0 else None
    peg = None
    if pe is not None and f.eps_cagr_3y is not None and f.eps_cagr_3y != 0:
        peg = pe / f.eps_cagr_3y
    return replace(
        f,
        pe=pe,
        peg=peg,
        pb=close / f.book_value_per_share if f.book_value_per_share else None,
        dividend_yield=(f.dps_ttm / close * 100) if f.dps_ttm is not None else f.dividend_yield,
        market_cap_cr=close * f.shares_outstanding_cr if f.shares_outstanding_cr else f.market_cap_cr,
    )
