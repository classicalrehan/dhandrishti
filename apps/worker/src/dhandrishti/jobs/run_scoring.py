"""Score the universe from PostgreSQL and persist results.

    uv run python -m dhandrishti.jobs.run_scoring --as-of 2026-10-05

Reads only from the database — never from a provider — so scoring is decoupled from data sources.
"""

import argparse
import logging

import psycopg

from ..config import Config, default_config
from ..db import connect
from ..db import score_repository as scores
from ..db.market_repository import load_market
from ..scoring import score_universe

log = logging.getLogger(__name__)


def run_scoring(conn: psycopg.Connection, as_of: str, cfg: Config | None = None,
                lookback_bars: int = 300) -> tuple[int, dict]:
    cfg = cfg or default_config()
    conn.commit()
    conn.autocommit = True  # the run row must survive a failed scoring transaction
    version = scores.register_config(conn, cfg)
    market = load_market(conn, as_of, lookback_bars)
    run_id = scores.start_run(conn, as_of, version, market.provenance)
    try:
        result = score_universe(market, cfg)
        with conn.transaction():
            scores.save_results(conn, run_id, result)
            scores.save_indicator_series(conn, market)
            scores.finish_run(conn, run_id, stock_count=len(result["stocks"]))
    except Exception as exc:
        scores.finish_run(conn, run_id, error=f"{type(exc).__name__}: {exc}")
        raise
    log.info("run %s scored %d stocks as of %s (%s)", run_id, len(result["stocks"]), as_of, market.provenance)
    return run_id, result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="2026-10-05")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with connect() as conn:
        run_id, result = run_scoring(conn, args.as_of)
    top = ", ".join(f"{s['rank']}. {s['symbol']} {s['total_score']:.1f}" for s in result["stocks"][:5])
    print(f"run {run_id} [{result['data_provenance']}] {result['regime']['regime']} — top: {top}")


if __name__ == "__main__":
    main()
