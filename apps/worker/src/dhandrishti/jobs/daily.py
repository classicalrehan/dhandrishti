"""Daily pipeline: migrate → ingest → score.

    uv run python -m dhandrishti.jobs.daily                    # MOCK data, as of 2026-10-05
    uv run python -m dhandrishti.jobs.daily --source kite      # Zerodha Kite (run `pnpm kite:login` first)
"""

import argparse
import logging

from ..db import connect
from ..db.migrate import migrate
from .ingest import extend_universe, ingest, resolve
from .run_scoring import run_scoring


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["mock", "kite"], default="mock")
    ap.add_argument("--as-of", help="default: 2026-10-05 for mock, last completed session for kite")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    providers, as_of, start = resolve(args.source, args.as_of, None)
    with connect() as conn:
        migrate(conn)
        extend_universe(conn, providers)
        ingest(conn, providers, as_of, start)
        run_id, result = run_scoring(conn, as_of)
    for w in getattr(providers.market, "warnings", []):
        logging.getLogger(__name__).warning(w)
    print(f"run {run_id}: {len(result['stocks'])} stocks scored [{result['data_provenance']}] as of {as_of}, "
          f"regime {result['regime']['regime']}")


if __name__ == "__main__":
    from ..providers.kite.client import KiteError

    try:
        main()
    except (KiteError, FileNotFoundError) as exc:  # expired/missing Kite session, API errors
        raise SystemExit(f"error: {exc}") from None
