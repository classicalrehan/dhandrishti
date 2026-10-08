"""Raw metrics for Fundamental Quality and Earnings Growth (SPEC §5)."""

from .models import Fundamentals

Metrics = dict[str, float | bool | None]


def ttm_eps_growth(quarterly_eps: list[float] | None) -> float | None:
    if not quarterly_eps or len(quarterly_eps) < 8:
        return None
    recent, prior = sum(quarterly_eps[-4:]), sum(quarterly_eps[-8:-4])
    return None if prior <= 0 else (recent / prior - 1) * 100


def earnings_deteriorating(quarterly_eps: list[float] | None) -> bool | None:
    """True when each of the last two quarters is below the same quarter a year earlier."""
    if not quarterly_eps or len(quarterly_eps) < 6:
        return None
    q = quarterly_eps
    return q[-1] < q[-5] and q[-2] < q[-6]


def quality_metrics(f: Fundamentals | None, sector_median_op_margin: float | None) -> Metrics:
    if f is None:
        return {}
    op_vs = (
        None
        if f.operating_margin is None or sector_median_op_margin is None
        else f.operating_margin - sector_median_op_margin
    )
    return {
        "roe": f.roe,
        "roce": f.roce,
        "operating_margin_vs_sector": op_vs,
        "net_margin": f.net_margin,
        "debt_to_equity": f.debt_to_equity,
        "interest_coverage": f.interest_coverage,
        "cfo_to_pat": f.cfo_to_pat,
        "fcf_positive": None if f.free_cash_flow_cr is None else f.free_cash_flow_cr > 0,
        "promoter_pledge": f.promoter_pledge,
        "earnings_consistency": (
            None if f.positive_eps_quarters_8 is None else f.positive_eps_quarters_8 / 8
        ),
    }


def growth_metrics(f: Fundamentals | None) -> Metrics:
    if f is None:
        return {}
    return {
        "revenue_growth_yoy": f.revenue_growth_yoy,
        "profit_growth_yoy": f.profit_growth_yoy,
        "eps_growth_yoy": f.eps_growth_yoy,
        "eps_cagr_3y": f.eps_cagr_3y,
        "ttm_eps_growth": ttm_eps_growth(f.quarterly_eps),
    }
