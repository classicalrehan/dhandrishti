"""Factor research machinery, checked on MOCK history (statistics, not market conclusions)."""

import numpy as np
import pandas as pd
import pytest

from dhandrishti.ingestion.mock_history import generate_history
from dhandrishti.jobs import factor_study as job
from dhandrishti.research import factors as F


@pytest.fixture(scope="module")
def history():
    return generate_history("2026-10-05")


@pytest.fixture(scope="module")
def panels(history):
    dates = F.sample_dates(history.nifty.dates, "2026-01-01", "2026-06-30", 10)
    return F.build_panel(history, dates, (5, 20))


def test_forward_returns_start_at_the_next_open(history, panels):
    panel, dpanel = panels
    cal = history.nifty.dates
    row = panel.iloc[0]
    i = cal.index(row["date"])
    b = history.bars[row["symbol"]]
    o = dict(zip(b.dates, b.open.tolist()))
    assert row["ret_5"] == pytest.approx(o[cal[i + 6]] / o[cal[i + 1]] - 1)
    n = dict(zip(cal, history.nifty.open.tolist()))
    assert dpanel.iloc[0]["nifty_5"] == pytest.approx(n[cal[i + 6]] / n[cal[i + 1]] - 1)


def test_factor_values_match_the_engine_on_that_date(history, panels):
    from dhandrishti.scoring import score_universe
    panel, _ = panels
    d = panel["date"].iloc[0]
    live = {s["symbol"]: s for s in score_universe(history.market_at(d, 300))["stocks"]}
    for _, r in panel[panel["date"] == d].iterrows():
        assert r["composite"] == live[r["symbol"]]["total_score"]
        assert r["f_momentum"] == live[r["symbol"]]["components"]["momentum"]["normalized_score"]


def test_ic_canaries():
    rng = np.random.default_rng(0)
    rows = []
    for d in range(30):
        ret = rng.normal(size=50)
        for i in range(50):
            rows.append({"date": f"2026-01-{d + 1:02d}", "symbol": f"S{i}", "ret_5": ret[i],
                         "oracle": ret[i], "noise": rng.normal(), "flat": 0.5})
    p = pd.DataFrame(rows)
    assert F.ic_summary(F.ic_by_date(p, "oracle", 5), 5, 5)["mean"] == pytest.approx(1.0)
    noise = F.ic_summary(F.ic_by_date(p, "noise", 5), 5, 5)
    assert abs(noise["mean"]) < 0.05 and abs(noise["t_nw"]) < 3
    assert F.ic_summary(F.ic_by_date(p, "flat", 5), 5, 5) == {"n_dates": 0}  # constant factor: no IC


def test_newey_west_widens_for_autocorrelated_ics():
    x = np.repeat(np.random.default_rng(1).normal(0.02, 0.05, 40), 5)  # each value repeated: overlap
    assert abs(F.newey_west_t(x, 4)) < abs(F.newey_west_t(x, 0))


def test_variants_buckets_stability_and_report(history, panels):
    panel, dpanel = panels
    p = F.with_groups(F.add_variants(panel))
    # shrinkage equals the engine score where every metric is present
    from dhandrishti.config import COMPONENT_ORDER
    full = p[[f"cov_{c}" for c in COMPONENT_ORDER]].min(axis=1) == 1
    assert full.any()
    assert p.loc[full, "composite_shrunk"].sub(p.loc[full, "composite"]).abs().max() < 0.06  # rounding only: 3-decimal parts x 100 points
    assert set(p["size_proxy"].dropna().unique()) <= {"low liquidity", "mid liquidity", "high liquidity"}
    b = F.bucket_study(p, dpanel, 20, 10)
    assert b["Top 5"]["periods"] >= 2 and "Decile 10" in b
    st = F.rank_stability(p, [10, 20], 10)
    assert -1 <= st["10 sessions"]["rank_corr"] <= 1
    table = F.factor_table(p, (5,), 10)
    assert table["f_fundamentals"][5]["rank_ic"]["n_dates"] > 0  # mock data has fundamentals
    assert table["composite"][5]["n_obs"] == p[["composite", "ret_5"]].dropna().shape[0]


def test_code_fingerprint_is_stable():
    assert job.code_fingerprint() == job.code_fingerprint()
