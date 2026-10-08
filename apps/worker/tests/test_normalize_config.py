import copy
import math

import pytest

from dhandrishti.config import COMPONENT_ORDER, validate_config
from dhandrishti.normalize import band, log_ramp, normalize, ramp


def test_ramp_forward_inverse_and_clipping():
    assert ramp(5, 0, 10) == 0.5
    assert ramp(-1, 0, 10) == 0 and ramp(11, 0, 10) == 1
    assert ramp(0.2, 2.0, 0.2) == 1  # inverse: lower is better
    assert ramp(math.inf, 2.5, 1.0) == 0  # loss-making PEG/PE scores zero
    assert ramp(math.inf, 0, 10) == 1


def test_log_ramp_and_band():
    assert log_ramp(5, 5, 200) == 0 and log_ramp(200, 5, 200) == 1
    assert log_ramp(0, 5, 200) == 0
    assert band(60, 30, 50, 68, 82) == 1
    assert band(40, 30, 50, 68, 82) == pytest.approx(0.5)
    assert band(75, 30, 50, 68, 82) == pytest.approx(0.5)
    assert band(85, 30, 50, 68, 82) == 0


def test_binary():
    assert normalize({"fn": "binary"}, True) == 1 and normalize({"fn": "binary"}, False) == 0


def test_default_config_is_valid_and_sums_to_100(cfg):
    assert validate_config(cfg) == []
    assert sum(cfg["components"][k]["weight"] for k in COMPONENT_ORDER) == 100
    expected = {"fundamentals": 25, "earningsGrowth": 20, "momentum": 15, "technicalTrend": 15,
                "valuation": 10, "liquidity": 5, "sectorStrength": 5, "risk": 5}
    assert {k: cfg["components"][k]["weight"] for k in COMPONENT_ORDER} == expected


def test_invalid_weights_rejected(cfg):
    bad = copy.deepcopy(cfg)
    bad["components"]["momentum"]["weight"] = 30
    assert any("sum to 100" in e for e in validate_config(bad))
