"""Score the universe and print the result as JSON.

    uv run python -m dhandrishti.jobs.score_universe [--fixture PATH] [--as-of YYYY-MM-DD] [--out FILE]

Without --fixture the deterministic MOCK generator is used.
"""

import argparse
import json
import sys
from pathlib import Path

from ..ingestion.fixtures import load_market
from ..ingestion.mock import DEFAULT_SEED, generate_market
from ..scoring import score_universe


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture", type=Path)
    ap.add_argument("--as-of", default="2026-10-05")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    market = load_market(args.fixture) if args.fixture else generate_market(args.as_of, seed=args.seed)
    result = score_universe(market)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
