"""Normalization functions (SPEC §4). All map a raw value to [0, 1]."""

import math
from typing import Any


def clip01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ramp(x: float, lo: float, hi: float) -> float:
    """Linear ramp; when lo > hi the ramp is inverse (lower is better)."""
    if math.isinf(x):
        return (1.0 if hi > lo else 0.0) if x > 0 else (0.0 if hi > lo else 1.0)
    return clip01((x - lo) / (hi - lo))


def log_ramp(x: float, lo: float, hi: float) -> float:
    if x <= 0:
        return 0.0
    return ramp(math.log10(x), math.log10(lo), math.log10(hi))


def band(x: float, zero_lo: float, full_lo: float, full_hi: float, zero_hi: float) -> float:
    if x <= zero_lo or x >= zero_hi:
        return 0.0
    if x < full_lo:
        return (x - zero_lo) / (full_lo - zero_lo)
    if x <= full_hi:
        return 1.0
    return (zero_hi - x) / (zero_hi - full_hi)


def normalize(spec: dict[str, Any], x: float | bool) -> float:
    fn = spec["fn"]
    if fn == "binary":
        return 1.0 if x else 0.0
    x = float(x)
    if fn == "ramp":
        return ramp(x, spec["lo"], spec["hi"])
    if fn == "log_ramp":
        return log_ramp(x, spec["lo"], spec["hi"])
    if fn == "band":
        return band(x, spec["zero_lo"], spec["full_lo"], spec["full_hi"], spec["zero_hi"])
    raise ValueError(f"unknown normalization fn: {fn}")
