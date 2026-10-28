"""Exit-rule study on the point-in-time NIFTY 200 universe (research only; read-only; docs in research/exit_rules.py).

    uv run python -m dhandrishti.jobs.exit_study [--db dd_dev_tracking] [--out FILE.md]

Opens the database in a READ ONLY session and uses the same point-in-time universe as `entry_study --pit`
(verified membership from 2021, former members priced from data/kite-backfill/).
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..db.market_repository import load_history
from ..research import exit_rules as X
from .entry_study import point_in_time


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="dd_dev_tracking")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with psycopg.connect(make_conninfo(database_url(), dbname=args.db)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        latest = conn.execute("SELECT max(trade_date)::text FROM daily_prices").fetchone()[0]
        history = load_history(conn, latest)
        conn.rollback()
    members, universe = point_in_time(history, latest)
    res = X.run(history, members)
    rows = X.summarize(res)
    verdicts = X.verdict(rows)
    nifty = history.nifty
    nifty_r = [nifty.close[i] / nifty.close[i - 1] - 1 for i in range(1, len(nifty.close))]
    bench = [(name, X.curve_stats(list(nifty.dates[1:]), np.array(nifty_r), lo, hi))
             for name, lo, hi in (("all", "2021-01-01", "9999"), *X.PERIODS)]
    text = [f"# Exit-rule study ({args.db}, prices to {latest})", "",
            "Research only. " + " ".join(universe) + " Neutral entries: every member at the open after the first "
            f"session of each month; each rule exits by {X.HOLD} sessions at the latest; stops checked on closes, "
            "filled at the next open; costs 15/13.5 bps per side.", "", X.markdown(rows, res), "",
            "NIFTY 50 (price index) for context: " + "; ".join(
                f"{n}: annual {s['annual_return']:+.1%}, max drawdown {s['max_drawdown']:+.1%}" for n, s in bench if s["days"]),
            "", "## Pre-registered verdicts (vs holding 60 sessions; drawdown must shrink >= 3 points in 2021-22 AND "
            "2023-26 without a significant return cost)"]
    text += [f"- {r}: {', '.join(v)}" for r, v in verdicts.items()]
    out = "\n".join(text)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
