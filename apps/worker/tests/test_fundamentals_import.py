import math
from datetime import date, timedelta

import pytest

from dhandrishti.ingestion.fundamentals_import import (
    ImportError_,
    build_snapshots,
    parse_quarterly,
    parse_shareholding,
)
from dhandrishti.models import Fundamentals
from dhandrishti.valuation import reprice

HEADER = "symbol,period_end,published_on,revenue,operating_profit,net_profit,eps,interest,equity,debt,cfo,capex,dps,shares_cr\n"
QUARTER_ENDS = ["03-31", "06-30", "09-30", "12-31"]


def quarter_rows(symbol="TESTCO", n=16, start_year=2022):
    """Revenue grows 2% a quarter; margins fixed; cash flow reported half-yearly (Sep, Mar)."""
    rows = []
    for i in range(n):
        y, q = start_year + (i + 1) // 4, (i + 1) % 4
        period = f"{y}-{QUARTER_ENDS[q]}"
        published = (date.fromisoformat(period) + timedelta(days=45)).isoformat()
        rev = 1000 * 1.02 ** i
        half = QUARTER_ENDS[q] in ("03-31", "09-30")
        rows.append(",".join(str(x) for x in (
            symbol, period, published, round(rev, 6), round(rev * 0.2, 6), round(rev * 0.1, 6),
            round(rev * 0.1 / 10, 6), 5, 2000 + 10 * i, 400,
            round(rev * 0.2, 6) if half else "", 50 if half else "", 2 if QUARTER_ENDS[q] == "06-30" else "", 10)))
    return rows


@pytest.fixture()
def quarterly_csv(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text(HEADER + "\n".join(quarter_rows()) + "\n")
    return p


@pytest.fixture()
def holdings_csv(tmp_path):
    p = tmp_path / "sh.csv"
    p.write_text("symbol,period_end,published_on,promoter_pct,promoter_pledged_pct,fii_pct,dii_pct\n"
                 "TESTCO,2025-09-30,2025-10-21,55.5,4.0,20.0,12.5\n")
    return p


def closes(price=500.0):
    return lambda sym, d: price


def test_derived_metrics_match_hand_calculation(quarterly_csv, holdings_csv):
    snaps = build_snapshots(parse_quarterly(quarterly_csv), parse_shareholding(holdings_csv), closes())["TESTCO"]
    f = snaps[-1]
    g = (1.02 ** 4 - 1) * 100  # TTM growth when every quarter grows 2%
    assert f.revenue_growth_yoy == pytest.approx(g, abs=0.01)
    assert f.profit_growth_yoy == pytest.approx(g, abs=0.01)
    assert f.eps_growth_yoy == pytest.approx(g, abs=0.01)
    assert f.eps_cagr_3y == pytest.approx(g, abs=0.01)  # 12 quarters at 2% = 3 years at 8.24%
    assert f.operating_margin == pytest.approx(20.0) and f.net_margin == pytest.approx(10.0)
    ttm_np = sum(1000 * 1.02 ** i * 0.1 for i in range(12, 16))
    assert f.roe == pytest.approx(ttm_np / ((2150 + 2110) / 2) * 100, abs=0.01)
    assert f.debt_to_equity == pytest.approx(400 / 2150, abs=0.001)
    assert f.interest_coverage == pytest.approx(ttm_np * 2 / 20, abs=0.01)
    assert f.positive_eps_quarters_8 == 8 and len(f.quarterly_eps) == 12
    assert f.eps_ttm == pytest.approx(ttm_np / 10, abs=1e-3)
    assert f.book_value_per_share == pytest.approx(215.0)
    assert f.dps_ttm == pytest.approx(2.0) and f.dividend_yield == pytest.approx(0.4)
    assert f.cfo_to_pat is not None and f.free_cash_flow_cr is not None  # half-yearly cash flow accepted
    assert f.promoter_holding == 55.5 and f.promoter_pledge == 4.0 and f.institutional_holding == 32.5
    assert f.pe == pytest.approx(500 / f.eps_ttm, abs=0.01)
    assert f.pe_median_5y is not None


def test_snapshots_are_point_in_time(quarterly_csv):
    snaps = build_snapshots(parse_quarterly(quarterly_csv), {}, closes())["TESTCO"]
    eighth = snaps[7]
    assert eighth.as_of == quarter_rows()[7].split(",")[2]
    assert eighth.eps_cagr_3y is None  # only 8 quarters were public then
    assert eighth.revenue_growth_yoy is not None
    assert [s.as_of for s in snaps] == sorted(s.as_of for s in snaps)
    assert len({s.as_of for s in snaps}) == 16


def test_too_little_history_gives_nulls_not_guesses(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text(HEADER + "\n".join(quarter_rows(n=3)) + "\n")
    f = build_snapshots(parse_quarterly(p), {}, closes())["TESTCO"][-1]
    assert f.revenue_growth_yoy is None and f.operating_margin is None and f.eps_ttm is None and f.pe is None


@pytest.mark.parametrize("content, message", [
    ("symbol,period_end,published_on,revenue\nX,2025-03-31,2025-05-01,1\n", "missing required columns"),
    (HEADER.strip() + ",mystery\n", "unknown columns"),
    (HEADER + "TESTCO,2025-03-31,2025-03-01,1,1,1,1,,,,,,,\n", "before period_end"),
    (HEADER + "TESTCO,2025-03-31,2025-05-01,1,1,1,1,,,,,,,\nTESTCO,2025-03-31,2025-05-02,1,1,1,1,,,,,,,\n", "duplicate"),
    (HEADER + "NOPE,2025-03-31,2025-05-01,1,1,1,1,,,,,,,\n", "unknown symbol NOPE"),
    (HEADER + "TESTCO,2025-03-31,2025-05-01,,1,1,1,,,,,,,\n", "required"),
])
def test_validation_errors_are_specific(tmp_path, content, message):
    p = tmp_path / "bad.csv"
    p.write_text(content)
    with pytest.raises(ImportError_, match=message):
        parse_quarterly(p, known={"TESTCO"})


def test_valuation_is_repriced_from_the_scoring_day_close():
    f = Fundamentals(as_of="2026-08-14", pe=10.0, pb=1.0, eps_ttm=50.0, book_value_per_share=250.0,
                     dps_ttm=10.0, shares_outstanding_cr=2.0, eps_cagr_3y=20.0)
    r = reprice(f, 1000.0)
    assert (r.pe, r.pb, r.dividend_yield, r.market_cap_cr, r.peg) == (20.0, 4.0, 1.0, 2000.0, 1.0)
    assert reprice(Fundamentals(pe=12.0), 1000.0).pe == 12.0  # no per-share data (mock): unchanged
    loss = reprice(Fundamentals(eps_ttm=-5.0), 100.0)
    assert loss.pe < 0  # loss-making stays loss-making (scores as "not meaningful")
