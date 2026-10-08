"""Scoring engine (SPEC §4, §8, §10, §11). Entry point: `score_universe`."""

import math
import statistics
from typing import Any

from .config import COMPONENT_ORDER, Config, default_config
from .fundamentals import growth_metrics, quality_metrics
from .models import MarketInput, StockInput
from .momentum import momentum_metrics, trend_metrics
from .normalize import normalize
from .regime import compute_breadth, compute_regime
from .risk import RiskFlag, assess_risk, risk_level
from .sector import SectorContext, sector_contexts, sector_strengths
from .technicals import Technicals, compute_technicals
from .valuation import reprice, valuation_metrics

CONFIDENCE_LEVELS = ("LOW", "MEDIUM", "HIGH")


# ---------------------------------------------------------------- formatting

def _r(x: float | None, nd: int) -> float | None:
    if x is None:
        return None
    if isinstance(x, float) and math.isinf(x):
        return None  # JSON has no infinity; the reason text explains it
    return round(float(x), nd)


def format_value(spec: dict, v: Any) -> str:
    if spec["fn"] == "binary":
        return "Yes" if v else "No"
    if isinstance(v, float) and math.isinf(v):
        return "not meaningful (loss-making)"
    unit = spec.get("unit", "")
    if unit == "%":
        return f"{v:.1f}%"
    if unit == "pp":
        return f"{v:+.1f} pp"
    if unit == "x":
        return f"{v:.2f}x"
    if unit == "₹ Cr":
        return f"₹{v:,.0f} Cr"
    if unit == "ratio":
        return f"{v:.2f}"
    if unit == "share":
        return f"{v:.0%}"
    if unit == "score100":
        return f"{v * 100:.0f}/100"
    if unit == "pts":
        return f"{v:g}"
    return f"{v:.1f}"


# ---------------------------------------------------------------- components

def score_component(
    key: str, raw: dict, cfg: Config, *, is_financial: bool, as_of: str, cap: float | None = None,
    cap_reason: str | None = None,
) -> dict:
    comp = cfg["components"][key]
    W = comp["weight"]
    pos_t, neg_t = cfg["reason_thresholds"]["positive"], cfg["reason_thresholds"]["negative"]

    applicable: dict[str, dict] = {}
    for name, spec in comp["metrics"].items():
        if spec.get("non_financial_only") and is_financial:
            continue
        w = spec.get("weight_financial", spec["weight"]) if is_financial else spec["weight"]
        applicable[name] = {**spec, "weight": w}

    available = {m: raw[m] for m in applicable if raw.get(m) is not None}
    w_app = sum(s["weight"] for s in applicable.values())
    w_av = sum(applicable[m]["weight"] for m in available)
    coverage = w_av / w_app if w_app else 0.0

    metric_scores = {m: normalize(applicable[m], v) for m, v in available.items()}
    reasons: list[dict] = []
    if w_av:
        normalized = sum(applicable[m]["weight"] * s for m, s in metric_scores.items()) / w_av
        for m, s in metric_scores.items():
            impact = W * (applicable[m]["weight"] / w_av) * (s - 0.5)
            kind = "positive" if s >= pos_t else "negative" if s <= neg_t else "neutral"
            reasons.append({
                "text": f"{applicable[m]['label']}: {format_value(applicable[m], available[m])}",
                "impact": kind,
                "metric": m,
                "points": round(impact, 2),
                "_impact": impact,
            })
    else:
        normalized = cfg["missing_data_neutral"]
        reasons.append({"text": f"{comp['label']}: Data unavailable — neutral score applied",
                        "impact": "neutral", "metric": None, "points": 0.0, "_impact": 0.0})

    if cap is not None and normalized > cap:
        normalized = cap
        reasons.append({"text": cap_reason or "Score capped", "impact": "negative",
                        "metric": None, "points": 0.0, "_impact": 0.0})

    reasons.sort(key=lambda r: (-abs(r["_impact"]), r["metric"] or ""))
    return {
        "key": key,
        "label": comp["label"],
        "weight": W,
        "max": W,
        "normalized_score": normalized,
        "score": normalized * W,
        "coverage": coverage,
        "raw_metrics": {m: raw.get(m) for m in applicable},
        "metric_scores": metric_scores,
        "reasons": reasons,
        "data_timestamp": as_of,
    }


def confidence_level(components: dict[str, dict], bars: int, cfg: Config) -> tuple[str, float]:
    cc = cfg["confidence"]
    total_w = sum(c["weight"] for c in components.values())
    coverage = sum(c["weight"] * c["coverage"] for c in components.values()) / total_w
    if coverage >= cc["high_coverage"] and bars >= cc["min_history_bars"]:
        idx = 2
    elif coverage >= cc["medium_coverage"]:
        idx = 1
    else:
        idx = 0
    dispersion = statistics.pstdev(c["normalized_score"] for c in components.values())
    if dispersion > cc["dispersion_downgrade"]:
        idx = max(0, idx - 1)
    return CONFIDENCE_LEVELS[idx], coverage


def key_reason(components: dict[str, dict], cfg: Config) -> str:
    kr = cfg["key_reason"]
    strong = sorted(
        (components[k] for k in kr["components"] if components[k]["normalized_score"] >= kr["min_normalized"]),
        key=lambda c: (-c["normalized_score"], c["key"]),
    )[: kr["max_items"]]
    return " + ".join(c["label"] for c in strong) if strong else "No dominant strength"


def score_stock(
    stock: StockInput, t: Technicals, ctx: SectorContext, sector_norm: float, as_of: str, cfg: Config,
    fundamentals=None,
) -> dict:
    sec = stock.security
    f = fundamentals if fundamentals is not None else stock.fundamentals
    fin = sec.is_financial

    val_raw = valuation_metrics(f, ctx.median_pe, ctx.median_pb)
    flags: list[RiskFlag] = assess_risk(stock, t, val_raw.get("pe_vs_sector"), as_of, cfg)
    points = sum(fl.points for fl in flags)

    comps: dict[str, dict] = {}
    kw = {"is_financial": fin, "as_of": as_of}
    comps["fundamentals"] = score_component(
        "fundamentals", quality_metrics(f, ctx.median_operating_margin), cfg, **kw)
    comps["earningsGrowth"] = score_component("earningsGrowth", growth_metrics(f), cfg, **kw)
    comps["momentum"] = score_component("momentum", momentum_metrics(t), cfg, **kw)
    comps["technicalTrend"] = score_component("technicalTrend", trend_metrics(t), cfg, **kw)

    guard = cfg["components"]["valuation"]["value_trap_guard"]
    weak_quality = comps["fundamentals"]["coverage"] > 0 and \
        comps["fundamentals"]["normalized_score"] < guard["min_quality"]
    shrinking = f is not None and f.eps_cagr_3y is not None and f.eps_cagr_3y < guard["min_eps_cagr_3y"]
    comps["valuation"] = score_component(
        "valuation", val_raw, cfg, **kw,
        cap=guard["cap"] if (weak_quality or shrinking) else None,
        cap_reason="Low valuation not fully rewarded: weak quality or shrinking earnings",
    )
    comps["liquidity"] = score_component(
        "liquidity", {"avg_traded_value_cr": t.avg_traded_value_cr}, cfg, **kw)
    comps["sectorStrength"] = score_component(
        "sectorStrength", {"sector_strength": sector_norm}, cfg, **kw)
    comps["risk"] = score_component("risk", {"risk_points": points}, cfg, **kw)

    total = sum(c["score"] for c in comps.values())
    confidence, coverage = confidence_level(comps, t.bars, cfg)

    impacts = [
        {"component": k, "metric": r["metric"], "text": r["text"], "impact": r["_impact"]}
        for k in COMPONENT_ORDER if k != "risk"
        for r in comps[k]["reasons"] if r["metric"] is not None
    ]
    positives = sorted((i for i in impacts if i["impact"] > 0), key=lambda i: (-i["impact"], i["metric"]))[:5]
    negatives = sorted((i for i in impacts if i["impact"] < 0), key=lambda i: (i["impact"], i["metric"]))[:5]
    negatives += [
        {"component": "risk", "metric": fl.code, "text": fl.message, "impact": -fl.points}
        for fl in flags if fl.points > 0
    ]

    return {
        "symbol": sec.symbol,
        "name": sec.name,
        "sector": sec.sector,
        "as_of": as_of,
        "total_score": total,
        "max_score": 100,
        "confidence": confidence,
        "data_coverage": coverage,
        "risk_level": risk_level(points, cfg),
        "risk_points": points,
        "risk_flags": [fl.to_dict() for fl in flags],
        "key_reason": key_reason(comps, cfg),
        "top_positives": positives,
        "top_negatives": negatives,
        "components": comps,
        "technicals": t.to_dict(),
    }


# ---------------------------------------------------------------- output

def _round_tree(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _round_tree(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [_round_tree(v) for v in x]
    if isinstance(x, bool) or x is None or isinstance(x, (int, str)):
        return x
    if isinstance(x, float):
        return _r(x, 4)
    return x


def finalize_stock(s: dict) -> dict:
    """Apply the output rounding contract (SPEC §11)."""
    out = _round_tree(s)
    out["total_score"] = _r(s["total_score"], 2)
    out["data_coverage"] = _r(s["data_coverage"], 3)
    for k, c in out["components"].items():
        src = s["components"][k]
        c["score"] = _r(src["score"], 2)
        c["normalized_score"] = _r(src["normalized_score"], 3)
        c["coverage"] = _r(src["coverage"], 3)
        c["metric_scores"] = {m: _r(v, 3) for m, v in src["metric_scores"].items()}
    for lst in ("top_positives", "top_negatives"):
        for item, src_item in zip(out[lst], s[lst]):
            item["impact"] = _r(src_item["impact"], 2)
    return out


def score_universe(market: MarketInput, cfg: Config | None = None) -> dict:
    cfg = cfg or default_config()
    tech = {s.security.symbol: compute_technicals(s.bars, market.nifty) for s in market.stocks}
    funds = {s.security.symbol: reprice(s.fundamentals, tech[s.security.symbol].close) for s in market.stocks}
    contexts = sector_contexts(market.stocks, funds)
    sectors = sector_strengths(market.stocks, tech, cfg)

    scored = [
        score_stock(s, tech[s.security.symbol], contexts[s.security.sector],
                    sectors[s.security.sector].normalized, market.as_of, cfg, funds[s.security.symbol])
        for s in market.stocks
    ]
    scored.sort(key=lambda s: (-round(s["total_score"], 6), s["symbol"]))
    stocks = []
    for i, s in enumerate(scored, 1):
        s["rank"] = i
        s["data_provenance"] = market.provenance
        s["config_version"] = cfg["version"]
        stocks.append(finalize_stock(s))

    breadth = compute_breadth(list(tech.values()))
    regime = compute_regime(market.nifty, market.bank_nifty, market.india_vix, breadth,
                            list(sectors.values()), cfg)
    return {
        "as_of": market.as_of,
        "data_provenance": market.provenance,
        "config_version": cfg["version"],
        "stocks": stocks,
        "sectors": [_round_tree(s.to_dict()) for s in sectors.values()],
        "breadth": _round_tree(breadth.to_dict()),
        "regime": _round_tree(regime.to_dict()),
    }
