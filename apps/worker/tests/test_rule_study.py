"""Rule-study replays use the live paper engine; checked on MOCK history (machinery only)."""

from dataclasses import replace

import pytest

from dhandrishti.config import default_config
from dhandrishti.ingestion.mock_history import generate_history
from dhandrishti.jobs.rule_study import VARIANTS, report
from dhandrishti.research.replay import SignalCache, benchmarks, price_tables, replay
from dhandrishti.scoring import score_universe
from dhandrishti.trading.paper import PaperParams


@pytest.fixture(scope="module")
def setup():
    h = generate_history("2026-10-05")
    cfg = default_config()
    calls = []

    def score(hist, day):
        calls.append(day)
        r = score_universe(hist.market_at(day, 300), cfg)
        return r["stocks"], r["regime"]["regime"]

    days = [d for d in h.nifty.dates if "2026-04-01" <= d <= "2026-08-31"]
    return h, SignalCache(h, score), *price_tables(h), days, calls


def test_replay_trades_like_paper_and_scores_each_day_once(setup):
    h, signals, opens, closes, days, calls = setup
    a = replay("a", PaperParams(), days, signals, opens, closes)
    b = replay("b", PaperParams(), days, signals, opens, closes)
    assert a.equity[0] == 100_000 and a.trades >= 5 and a.charges > 0
    assert (a.equity == b.equity).all()  # deterministic
    assert len(calls) == len(set(calls))  # the cache shares scoring across variants
    assert a.invested_pct.max() > 90


def test_cash_in_bear_markets_never_holds_stock_when_every_signal_is_bearish(setup):
    h, _, opens, closes, days, _ = setup
    bearish = SignalCache(h, lambda hist, d: (score_universe(hist.market_at(d, 300))["stocks"], "BEARISH"))
    r = replay("bear", replace(PaperParams(), regime_slots={"BEARISH": 0}), days, bearish, opens, closes)
    assert r.trades == 0 and (r.equity == 100_000).all()


def test_benchmarks_and_report(setup):
    h, signals, opens, closes, days, _ = setup
    b = benchmarks(days, signals, h, opens, closes, 100_000)
    nifty = dict(zip(h.nifty.dates, h.nifty.close.tolist()))
    assert b["NIFTY 50"].equity[-1] == pytest.approx(100_000 * nifty[days[-1]] / nifty[days[0]])
    assert b["Equal-weight universe"].charges > 0
    rows = {"Baseline": replay("x", PaperParams(), days, signals, opens, closes).summary()}
    rows |= {k: v.summary() for k, v in b.items()}
    text = report({"Window": rows})
    assert "| Baseline |" in text and "*NIFTY 50*" in text


def test_variants_are_valid_and_distinct():
    for _, p in VARIANTS:
        p.validate()
    assert len({repr(p) for _, p in VARIANTS}) == len(VARIANTS)
