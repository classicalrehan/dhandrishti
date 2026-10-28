"""Position-sizing study on the point-in-time NIFTY 200 universe (research only; read-only; docs in
research/position_sizing.py).

    uv run python -m dhandrishti.jobs.sizing_study [--db dd_dev_tracking] [--paths 500] [--out FILE.md]

Opens the database in a READ ONLY session and uses the same point-in-time universe as `entry_study --pit`.
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..db.market_repository import load_history
from ..research import position_sizing as S
from .entry_study import point_in_time


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="dd_dev_tracking")
    ap.add_argument("--paths", type=int, default=S.PATHS)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with psycopg.connect(make_conninfo(database_url(), dbname=args.db)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        latest = conn.execute("SELECT max(trade_date)::text FROM daily_prices").fetchone()[0]
        history = load_history(conn, latest)
        conn.rollback()
    members, universe = point_in_time(history, latest)
    quarters = S.prepare(history, members)
    cal = history.nifty.dates
    rows = S.run(quarters, paths=args.paths)
    v = S.verdict(rows)
    best = v["recommended"]
    text = [f"# Position-sizing study ({args.db}, prices to {latest})", "",
            "Research only. " + " ".join(universe) + f" {len(quarters)} quarterly rebalances "
            f"({cal[quarters[0].start]} to {cal[quarters[-1].end]}); N random members per quarter; {args.paths} "
            "paths with common random draws; cash earns 0; costs 15/13.5 bps on the invested part per rebalance.",
            "", "## Equal weights", "", S.markdown(rows, "equal"), "", "## Inverse-volatility weights", "",
            S.markdown(rows, "ivol"), "",
            "## Pre-registered reading (acceptable: at most 10% of paths worse than -20% drawdown)",
            f"- Acceptable configurations: {v['acceptable']} of {len(rows)}",
            "- Recommended: " + (f"{S.label(best)} (median annual {best['median_annual']:+.1%}, median max drawdown "
                                 f"{best['median_dd']:+.1%}, worse than -20% in {best['breach_20']:.0%} of paths)"
                                 if best else "none"),
            "- 8% stop helps (>= 5 points fewer paths worse than -20%, <= 1 point return cost): "
            + (", ".join(f"{n} stocks {x:.0%} {w}" for n, x, w in v["stop_helps"]) or "nowhere")]
    out = "\n".join(text)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
