"""Golden fixtures: the engine must reproduce packages/quant-spec/fixtures/expected exactly.

If this fails after an intentional spec change, bump the spec version, regenerate with
`uv run python -m dhandrishti.jobs.generate_fixtures`, and record the change in SPEC.md §12.
"""

import json

import pytest

from dhandrishti.ingestion.fixtures import load_market
from dhandrishti.jobs.generate_fixtures import GOLDEN_SYMBOLS
from dhandrishti.paths import FIXTURES_DIR
from dhandrishti.scoring import score_universe

INPUT = FIXTURES_DIR / "inputs" / "universe-2026-10-05.json"
EXPECTED = FIXTURES_DIR / "expected"


def _close(a, b, path="$"):
    if isinstance(a, float) or isinstance(b, float):
        assert a == pytest.approx(b, abs=1e-6), path
    elif isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    else:
        assert a == b, path


@pytest.fixture(scope="module")
def replay(cfg):
    if not INPUT.exists():
        pytest.fail(f"missing fixture {INPUT}; run dhandrishti.jobs.generate_fixtures")
    return score_universe(load_market(INPUT), cfg)


@pytest.mark.parametrize("symbol", GOLDEN_SYMBOLS)
def test_golden_stock(replay, symbol):
    expected = json.loads((EXPECTED / f"{symbol.lower()}.json").read_text(encoding="utf-8"))
    actual = next(s for s in replay["stocks"] if s["symbol"] == symbol)
    _close(json.loads(json.dumps(actual)), expected)


def test_golden_universe_summary(replay):
    expected = json.loads((EXPECTED / "universe-summary.json").read_text(encoding="utf-8"))
    actual = [
        {k: s[k] for k in ("rank", "symbol", "total_score", "confidence", "risk_level", "risk_points",
                           "data_coverage", "key_reason")}
        | {"components": {c: v["score"] for c, v in s["components"].items()}}
        for s in replay["stocks"]
    ]
    assert replay["config_version"] == expected["config_version"]
    _close(json.loads(json.dumps(actual)), expected["stocks"])


def test_golden_market(replay):
    expected = json.loads((EXPECTED / "market.json").read_text(encoding="utf-8"))
    _close(json.loads(json.dumps({k: replay[k] for k in ("as_of", "regime", "breadth", "sectors")})), expected)
