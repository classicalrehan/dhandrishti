"""(Re)generate golden fixtures in packages/quant-spec/fixtures.

Run ONLY when the quant spec version changes, and record the change in SPEC.md §12:

    uv run python -m dhandrishti.jobs.generate_fixtures
"""

import json

from ..ingestion.fixtures import load_market, market_to_json
from ..ingestion.mock import generate_market
from ..paths import FIXTURES_DIR
from ..scoring import score_universe

GOLDEN_SYMBOLS = ("HDFCBANK", "ICICIBANK", "RELIANCE")


def _dump(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    inputs = FIXTURES_DIR / "inputs" / "universe-2026-10-05.json"
    _dump(inputs, market_to_json(generate_market("2026-10-05")))
    # Score from the serialized file so the expected output matches what tests replay.
    result = score_universe(load_market(inputs))
    by_symbol = {s["symbol"]: s for s in result["stocks"]}
    for sym in GOLDEN_SYMBOLS:
        _dump(FIXTURES_DIR / "expected" / f"{sym.lower()}.json", by_symbol[sym])
    _dump(FIXTURES_DIR / "expected" / "universe-summary.json", {
        "as_of": result["as_of"],
        "config_version": result["config_version"],
        "data_provenance": result["data_provenance"],
        "stocks": [
            {k: s[k] for k in ("rank", "symbol", "total_score", "confidence", "risk_level", "risk_points",
                               "data_coverage", "key_reason")}
            | {"components": {c: v["score"] for c, v in s["components"].items()}}
            for s in result["stocks"]
        ],
    })
    _dump(FIXTURES_DIR / "expected" / "market.json",
          {k: result[k] for k in ("as_of", "regime", "breadth", "sectors")})
    print(f"Fixtures written to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
