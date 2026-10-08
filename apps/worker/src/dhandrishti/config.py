"""Loads and validates scoring-config.json — the only place weights/thresholds are defined."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .paths import SCORING_CONFIG_PATH

COMPONENT_ORDER = (
    "fundamentals",
    "earningsGrowth",
    "momentum",
    "technicalTrend",
    "valuation",
    "liquidity",
    "sectorStrength",
    "risk",
)

Config = dict[str, Any]


def validate_config(cfg: Config) -> list[str]:
    errors: list[str] = []
    comps = cfg.get("components", {})
    missing = [k for k in COMPONENT_ORDER if k not in comps]
    if missing:
        errors.append(f"missing components: {missing}")
        return errors
    total = sum(comps[k]["weight"] for k in COMPONENT_ORDER)
    if abs(total - 100) > 1e-9:
        errors.append(f"component weights must sum to 100 (got {total})")
    for k in COMPONENT_ORDER:
        if comps[k]["weight"] < 0:
            errors.append(f"weight of {k} must be non-negative")
        for m, spec in comps[k]["metrics"].items():
            if spec.get("weight", 0) <= 0:
                errors.append(f"{k}.{m}: metric weight must be positive")
            if spec["fn"] not in ("ramp", "log_ramp", "binary", "band"):
                errors.append(f"{k}.{m}: unknown fn {spec['fn']}")
    t = cfg["regime"]["thresholds"]
    if not (t["bullish"] > t["neutral"] > t["cautious"]):
        errors.append("regime thresholds must be descending")
    if not 0 <= cfg["missing_data_neutral"] <= 1:
        errors.append("missing_data_neutral must be within [0, 1]")
    return errors


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else SCORING_CONFIG_PATH
    cfg = json.loads(p.read_text(encoding="utf-8"))
    errors = validate_config(cfg)
    if errors:
        raise ValueError(f"Invalid scoring config {p}: {'; '.join(errors)}")
    return cfg


@lru_cache(maxsize=1)
def default_config() -> Config:
    return load_config()
