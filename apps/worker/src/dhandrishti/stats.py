"""Small helpers shared by engine modules."""

import statistics
from typing import Iterable

from .normalize import normalize


def median(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def weighted_normalized(metric_specs: dict, raw: dict) -> tuple[float | None, dict[str, float]]:
    """Weighted mean of normalized metrics over available values (SPEC §4.1)."""
    scores: dict[str, float] = {}
    num = den = 0.0
    for name, spec in metric_specs.items():
        v = raw.get(name)
        if v is None:
            continue
        s = normalize(spec, v)
        scores[name] = s
        num += spec["weight"] * s
        den += spec["weight"]
    return (num / den if den else None), scores
