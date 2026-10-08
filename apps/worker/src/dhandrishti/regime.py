"""Market regime (SPEC §9). Reports a regime with bounded confidence — never certainty."""

from dataclasses import asdict, dataclass

from . import indicators as ind
from .config import Config
from .models import Bars
from .normalize import normalize
from .sector import SectorStrength
from .technicals import Technicals


@dataclass
class Breadth:
    advances: int
    declines: int
    unchanged: int
    advance_ratio: float | None
    pct_above_sma50: float | None
    pct_above_sma200: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Regime:
    regime: str
    composite: float
    confidence: int
    factors: list[dict]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_breadth(tech: list[Technicals]) -> Breadth:
    adv = sum(1 for t in tech if t.change is not None and t.change > 0)
    dec = sum(1 for t in tech if t.change is not None and t.change < 0)
    unch = len(tech) - adv - dec

    def share(flags: list[bool]) -> float | None:
        return sum(flags) / len(flags) if flags else None

    return Breadth(
        advances=adv,
        declines=dec,
        unchanged=unch,
        advance_ratio=adv / (adv + dec) if adv + dec else None,
        pct_above_sma50=share([t.close > t.sma50 for t in tech if t.sma50 is not None]),
        pct_above_sma200=share([t.close > t.sma200 for t in tech if t.sma200 is not None]),
    )


def _trend_score(bars: Bars, p: dict) -> float:
    c = bars.close
    close = float(c[-1])
    s50, s200 = ind.last(ind.sma(c, 50)), ind.last(ind.sma(c, 200))
    r3 = ind.pct_return(c, ind.LOOKBACK["m3"])
    score = 0.0
    score += 25 if s50 is not None and close > s50 else 0
    score += 25 if s200 is not None and close > s200 else 0
    score += 25 if s50 is not None and s200 is not None and s50 > s200 else 0
    score += 25 * (normalize(p["trend_ret_3m"], r3) if r3 is not None else 0.5)
    return score


def _avg(parts: list[tuple[float, float | None]], neutral: float) -> float:
    """Weighted mean over available parts; neutral when nothing is available."""
    avail = [(w, v) for w, v in parts if v is not None]
    if not avail:
        return 100 * neutral
    return 100 * sum(w * v for w, v in avail) / sum(w for w, _ in avail)


def compute_regime(
    nifty: Bars, bank_nifty: Bars, vix: Bars, breadth: Breadth,
    sectors: list[SectorStrength], cfg: Config,
) -> Regime:
    rc = cfg["regime"]
    p = rc["params"]
    neutral = cfg["missing_data_neutral"]

    def n(key: str, v: float | None) -> float | None:
        return None if v is None else normalize(p[key], v)

    vix_level = float(vix.close[-1])
    vix_chg = ind.pct_return(vix.close, ind.LOOKBACK["m1"])
    sec_1m = [s.median_ret_1m for s in sectors if s.median_ret_1m is not None]
    sec_pos = sum(1 for r in sec_1m if r > 0) / len(sec_1m) if sec_1m else None

    raw_scores = {
        "index_trend": _trend_score(nifty, p),
        "bank_nifty_trend": _trend_score(bank_nifty, p),
        "breadth": _avg([(1, n("advance_ratio", breadth.advance_ratio)),
                         (2, n("pct_above_sma50", breadth.pct_above_sma50)),
                         (1, n("pct_above_sma200", breadth.pct_above_sma200))], neutral),
        "volatility": _avg([(2, n("vix_level", vix_level)), (1, n("vix_change_1m", vix_chg))], neutral),
        "sector_participation": _avg([(1, n("sectors_positive_1m", sec_pos))], neutral),
        "index_momentum": _avg([(1, n("nifty_ret_1m", ind.pct_return(nifty.close, 21))),
                                (1, n("nifty_ret_6m", ind.pct_return(nifty.close, 126)))], neutral),
    }
    weights = {k: v["weight"] for k, v in rc["factors"].items()}
    composite = sum(weights[k] * raw_scores[k] for k in weights) / sum(weights.values())
    composite = round(composite, 1)

    t = rc["thresholds"]
    regime = ("BULLISH" if composite >= t["bullish"] else "NEUTRAL" if composite >= t["neutral"]
              else "CAUTIOUS" if composite >= t["cautious"] else "BEARISH")

    mad = sum(abs(raw_scores[k] - composite) for k in weights) / len(weights)
    lo, hi = rc["confidence_bounds"]
    confidence = int(min(hi, max(lo, round(100 * (1 - mad / 50)))))

    factors = [
        {"key": k, "label": rc["factors"][k]["label"], "weight": weights[k], "score": round(raw_scores[k], 1)}
        for k in weights
    ]
    ordered = sorted(factors, key=lambda f: (-f["score"], f["key"]))
    strong = [f["label"] for f in ordered[:2]]
    weakest = ordered[-1]["label"]
    reason = f"{strong[0]} and {strong[1]} are supportive; {weakest} is the weakest factor."
    return Regime(regime=regime, composite=composite, confidence=confidence, factors=factors, reason=reason)
