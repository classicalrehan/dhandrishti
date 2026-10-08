"""Run a point-in-time backtest of the DhanDrishti score and store it.

    uv run python -m dhandrishti.jobs.backtest --start 2023-10-01 --end 2026-10-05 \\
        [--rebalance monthly] [--top-n 10] [--max-risk MEDIUM] [--min-confidence HIGH] [--name "..."]
    uv run python -m dhandrishti.jobs.backtest --mock --start 2023-10-01   # no database, prints JSON

Reads history from PostgreSQL (or the MOCK generator with --mock). Results are hypothetical.
"""

import argparse
import json
import logging
import sys

from ..backtesting import BacktestParams, run_backtest
from ..config import default_config

log = logging.getLogger(__name__)


def parse_params(argv: list[str] | None = None) -> tuple[argparse.Namespace, BacktestParams]:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default="2026-10-05")
    ap.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly", "quarterly"])
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--max-risk", default="MEDIUM", help="LOW|MEDIUM|HIGH|VERY_HIGH or 'none'")
    ap.add_argument("--min-confidence", default=None, help="LOW|MEDIUM|HIGH")
    ap.add_argument("--buy-cost-bps", type=float, default=15.0)
    ap.add_argument("--sell-cost-bps", type=float, default=13.5)
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--risk-free", type=float, default=0.0, help="annual, e.g. 0.065")
    ap.add_argument("--name")
    ap.add_argument("--mock", action="store_true", help="use the MOCK generator instead of the database")
    a = ap.parse_args(argv)
    params = BacktestParams(
        start=a.start, end=a.end, rebalance=a.rebalance, top_n=a.top_n,
        max_risk=None if a.max_risk.lower() == "none" else a.max_risk.upper(),
        min_confidence=a.min_confidence.upper() if a.min_confidence else None,
        buy_cost_bps=a.buy_cost_bps, sell_cost_bps=a.sell_cost_bps,
        initial_capital=a.capital, risk_free_rate=a.risk_free,
    )
    params.validate()
    return a, params


def main(argv: list[str] | None = None) -> None:
    args, params = parse_params(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = default_config()

    if args.mock:
        from ..ingestion.mock_history import generate_history
        result = run_backtest(generate_history(params.end), params, cfg)
        json.dump({k: v for k, v in result.to_dict().items() if k != "equity"}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    from ..db import connect
    from ..db import backtest_repository as bt
    from ..db import score_repository as scores
    from ..db.market_repository import load_history

    with connect() as conn:
        conn.autocommit = True
        version = scores.register_config(conn, cfg)
        history = load_history(conn, params.end)
        run_id = bt.start_run(conn, args.name, params, version, history.provenance)
        try:
            result = run_backtest(history, params, cfg)
            with conn.transaction():
                bt.save_result(conn, run_id, result)
        except Exception as exc:
            bt.fail_run(conn, run_id, f"{type(exc).__name__}: {exc}")
            raise
    m = result.metrics
    print(f"backtest {run_id} [{history.provenance}] {m['period']['start']} -> {m['period']['end']}, "
          f"{m['period']['rebalances']} rebalances: CAGR {m['strategy']['cagr_pct']:.2f}% "
          f"vs NIFTY {m['nifty']['cagr_pct']:.2f}% vs equal-weight universe {m['universe_ew']['cagr_pct']:.2f}%")


if __name__ == "__main__":
    main()
