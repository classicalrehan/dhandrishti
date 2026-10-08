import copy
import dataclasses
import json

import pytest

from dhandrishti.config import COMPONENT_ORDER
from dhandrishti.ingestion.fixtures import market_from_json, market_to_json
from dhandrishti.ingestion.mock import generate_market
from dhandrishti.models import Event, Fundamentals
from dhandrishti.risk import assess_risk, risk_level
from dhandrishti.scoring import score_component, score_universe
from dhandrishti.technicals import compute_technicals


@pytest.fixture(scope="module")
def market():
    return generate_market("2026-10-05")


@pytest.fixture(scope="module")
def result(market, cfg):
    return score_universe(market, cfg)


def by_symbol(result, sym):
    return next(s for s in result["stocks"] if s["symbol"] == sym)


# ------------------------------------------------------------ invariants

def test_total_equals_sum_of_components(result):
    for s in result["stocks"]:
        assert s["total_score"] == pytest.approx(sum(c["score"] for c in s["components"].values()), abs=0.05)
        assert 0 <= s["total_score"] <= 100


def test_component_scores_bounded_by_weight(result, cfg):
    for s in result["stocks"]:
        for k in COMPONENT_ORDER:
            c = s["components"][k]
            assert c["max"] == cfg["components"][k]["weight"]
            assert 0 <= c["score"] <= c["max"] + 1e-9
            assert 0 <= c["normalized_score"] <= 1


def test_ranks_are_dense_and_ordered(result):
    ranks = [s["rank"] for s in result["stocks"]]
    assert ranks == list(range(1, len(ranks) + 1))
    totals = [s["total_score"] for s in result["stocks"]]
    assert totals == sorted(totals, reverse=True)


def test_output_contract_fields(result):
    s = result["stocks"][0]
    for key in ("symbol", "as_of", "data_provenance", "config_version", "total_score", "max_score", "rank",
                "confidence", "data_coverage", "risk_level", "risk_flags", "key_reason",
                "top_positives", "top_negatives", "components"):
        assert key in s
    for c in s["components"].values():
        for key in ("score", "max", "weight", "normalized_score", "coverage", "raw_metrics",
                    "reasons", "data_timestamp"):
            assert key in c
    json.dumps(result, allow_nan=False)  # strictly JSON-serialisable (no NaN/Infinity)


def test_mock_data_is_labelled_mock(result):
    assert result["data_provenance"] == "MOCK"
    assert all(s["data_provenance"] == "MOCK" for s in result["stocks"])


def test_headline_reasons_exclude_aggregate_risk_metric(result):
    for s in result["stocks"]:
        assert all(p["metric"] != "risk_points" for p in s["top_positives"])


# ------------------------------------------------------------ determinism

def test_same_input_same_output(market, cfg):
    a = score_universe(market, cfg)
    b = score_universe(market_from_json(json.loads(json.dumps(market_to_json(market)))), cfg)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_mock_generator_is_deterministic():
    a = market_to_json(generate_market("2026-10-05"))
    b = market_to_json(generate_market("2026-10-05"))
    assert a == b


# ------------------------------------------------------------ configurability

def test_weights_come_from_config(market, cfg):
    alt = copy.deepcopy(cfg)
    alt["components"]["momentum"]["weight"] = 25
    alt["components"]["valuation"]["weight"] = 0
    r = score_universe(market, alt)
    s = r["stocks"][0]
    assert s["components"]["momentum"]["max"] == 25
    assert s["components"]["valuation"]["score"] == 0


# ------------------------------------------------------------ rules

def test_missing_component_gets_neutral_and_lowers_coverage(cfg):
    c = score_component("valuation", {}, cfg, is_financial=False, as_of="2026-10-05")
    assert c["normalized_score"] == cfg["missing_data_neutral"]
    assert c["coverage"] == 0
    assert "Data unavailable" in c["reasons"][0]["text"]


def test_financials_exclude_leverage_metrics(cfg):
    raw = {"roe": 15, "debt_to_equity": 9.0, "net_margin": 10, "cfo_to_pat": 1.0,
           "promoter_pledge": 0, "earnings_consistency": 1}
    fin = score_component("fundamentals", raw, cfg, is_financial=True, as_of="x")
    assert "debt_to_equity" not in fin["raw_metrics"]
    assert fin["coverage"] == 1.0
    non_fin = score_component("fundamentals", raw, cfg, is_financial=False, as_of="x")
    assert non_fin["coverage"] < 1.0
    assert non_fin["metric_scores"]["debt_to_equity"] == 0


def test_value_trap_guard_caps_cheap_low_quality(market, cfg):
    m = copy.deepcopy(market)
    stock = next(s for s in m.stocks if s.security.symbol == "TATASTEEL")
    f = stock.fundamentals
    f.pe, f.pe_median_5y, f.peg, f.pb, f.dividend_yield = 3.0, 10.0, 0.5, 0.3, 5.0
    f.eps_cagr_3y = -5.0
    s = by_symbol(score_universe(m, cfg), "TATASTEEL")
    v = s["components"]["valuation"]
    cap = cfg["components"]["valuation"]["value_trap_guard"]["cap"]
    assert v["normalized_score"] == pytest.approx(cap)
    assert any("not fully rewarded" in r["text"] for r in v["reasons"])


def test_loss_making_pe_scores_zero_and_flags(market, cfg):
    m = copy.deepcopy(market)
    stock = next(s for s in m.stocks if s.security.symbol == "DLF")
    stock.fundamentals.pe = -12.0
    s = by_symbol(score_universe(m, cfg), "DLF")
    v = s["components"]["valuation"]
    assert v["metric_scores"]["pe_vs_sector"] == 0
    assert v["raw_metrics"]["pe_vs_sector"] is None  # +inf is not representable in JSON
    assert any(f["code"] == "EXCESSIVE_VALUATION" for f in s["risk_flags"])


def _risk_for(market, cfg, symbol, *, fund=None, tech=None, events=None):
    stock = copy.deepcopy(next(s for s in market.stocks if s.security.symbol == symbol))
    if fund:
        for k, v in fund.items():
            setattr(stock.fundamentals, k, v)
    if events is not None:
        stock.events = events
    t = compute_technicals(stock.bars, market.nifty)
    if tech:
        t = dataclasses.replace(t, **tech)
    return assess_risk(stock, t, None, market.as_of, cfg)


def test_risk_flags_and_points(market, cfg):
    calm = dict(volatility_60d=20.0, max_drawdown_1y=-10.0, relative_volume=1.0,
                gap_moves_60d=0, dist_from_sma200=5.0, avg_traded_value_cr=500.0)
    flags = _risk_for(market, cfg, "LT",
                      fund=dict(debt_to_equity=2.5, promoter_pledge=30.0,
                                quarterly_eps=[1, 1, 1, 1, 2, 2, 0.5, 0.5]),
                      tech={**calm, "volatility_60d": 50.0, "relative_volume": 4.0}, events=[])
    codes = {f.code: f for f in flags}
    assert codes["DEBT_CONCERN"].severity == "EXTREME"
    assert codes["PROMOTER_PLEDGE"].severity == "EXTREME"
    assert codes["EARNINGS_DETERIORATION"].points == 2
    assert codes["EXTREME_VOLATILITY"].severity == "EXTREME"
    assert codes["UNUSUAL_VOLUME"].points == 1
    total = sum(f.points for f in flags)
    assert risk_level(total, cfg) == "VERY_HIGH"


def test_financials_skip_debt_flag_and_events_are_info(market, cfg):
    calm = dict(volatility_60d=20.0, max_drawdown_1y=-10.0, relative_volume=1.0,
                gap_moves_60d=0, dist_from_sma200=5.0, avg_traded_value_cr=500.0)
    flags = _risk_for(market, cfg, "HDFCBANK", fund=dict(debt_to_equity=8.0, promoter_pledge=0.0),
                      tech=calm, events=[Event(date="2026-10-09", type="EARNINGS", title="Q2 results")])
    assert [f.code for f in flags] == ["UPCOMING_EARNINGS"]
    assert flags[0].points == 0


@pytest.mark.parametrize("points,level", [(0, "LOW"), (1, "LOW"), (2, "MEDIUM"), (3, "MEDIUM"),
                                          (4, "HIGH"), (5, "HIGH"), (6, "VERY_HIGH"), (12, "VERY_HIGH")])
def test_risk_levels(cfg, points, level):
    assert risk_level(points, cfg) == level


def test_confidence_drops_with_missing_fundamentals(market, cfg):
    m = copy.deepcopy(market)
    stock = next(s for s in m.stocks if s.security.symbol == "INFY")
    stock.fundamentals = None
    s = by_symbol(score_universe(m, cfg), "INFY")
    assert s["confidence"] == "LOW"
    assert s["components"]["fundamentals"]["coverage"] == 0


def test_regime_confidence_never_certain(result, cfg):
    lo, hi = cfg["regime"]["confidence_bounds"]
    assert lo <= result["regime"]["confidence"] <= hi < 100
    assert result["regime"]["regime"] in ("BULLISH", "NEUTRAL", "CAUTIOUS", "BEARISH")


def test_sectors_ranked(result):
    ranks = [s["rank"] for s in result["sectors"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert all(0 <= s["score"] <= 100 for s in result["sectors"])
