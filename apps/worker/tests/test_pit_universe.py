"""Point-in-time research universe (research/pit_universe.py): listing-date control, coverage, backfill files."""

import json
from datetime import date

import numpy as np

from dhandrishti.models import Bars
from dhandrishti.research import index_membership as M
from dhandrishti.research import pit_universe as P


def _history():
    periods = [(date(2026, 3, 30), frozenset({"A", "NEW"})), (date(2025, 1, 1), frozenset({"A", "OLD"}))]
    return M.History(date(2026, 10, 8), date(2025, 1, 1), periods, [], 0)


def test_member_before_first_trading_day_is_reported_unless_untestable():
    h = M.History(date(2026, 10, 8), date(2025, 1, 1), [(date(2025, 1, 1), frozenset({"A", "IPO", "OLD"}))], [], 0)
    first = {"A": date(2012, 1, 2), "IPO": date(2025, 6, 24), "OLD": date(2012, 1, 2)}
    assert P.listing_conflicts(h, first, data_start=date(2012, 1, 2)) == ["IPO: member from 2025-01-01 but first "
                                                                         "traded 2025-06-24"]


def test_first_member_day_and_coverage_in_member_days():
    h = _history()
    assert P.first_member_day(h) == {"A": date(2025, 1, 1), "OLD": date(2025, 1, 1), "NEW": date(2026, 3, 30)}
    share, missing = P.coverage(h, {"A", "NEW"}, end=date(2026, 3, 30))   # OLD unpriced for its whole membership
    assert missing == {"OLD": (date(2026, 3, 30) - date(2025, 1, 1)).days} and share == 0.5


def test_backfill_round_trip_reads_only_accepted_series(tmp_path):
    b = Bars(["2025-01-01", "2025-01-02"], np.array([1.0, 2.0]), np.array([1.5, 2.5]), np.array([0.5, 1.5]),
             np.array([1.2, 2.2]), np.array([100.0, 200.0]))
    P.save_backfill(tmp_path, "OLD", b)
    P.save_backfill(tmp_path, "LATE", b)
    (tmp_path / "manifest.json").write_text(json.dumps({"symbols": {"OLD": {"status": "ok"},
                                                                    "LATE": {"status": "history_starts_too_late"}}}))
    got = P.load_backfill(tmp_path)
    assert list(got) == ["OLD"] and got["OLD"].dates == b.dates and np.array_equal(got["OLD"].close, b.close)
    assert P.load_backfill(tmp_path / "absent") == {}
