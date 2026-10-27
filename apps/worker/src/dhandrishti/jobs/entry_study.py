"""Entry-signal study (research only; read-only; docs in research/entry_signals.py).

    uv run python -m dhandrishti.jobs.entry_study [--db dd_dev_tracking] [--out FILE.md]

Opens the database in a READ ONLY session (nothing can be written) and defaults to the development copy, not the
research database. Credentials come from DD_DATABASE_URL; only the database name is replaced.
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..db.market_repository import load_history
from ..research import entry_signals as E


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
    res = E.run(history)
    rows = E.summarize(res)
    verdicts = E.verdict(rows)
    text = [f"# Entry-signal study ({args.db}, prices to {latest}, {len(history.bars)} stocks)", "",
            "Research only. Universe = today's NIFTY 200 applied to the past (survivorship bias); price returns "
            "(dividends excluded); entry next open, exit open after h sessions; costs 15/13.5 bps per side.", "",
            E.markdown(rows, res), "", "## Pre-registered verdicts (edge = positive excess, t >= 2 in 2019-22 AND 2023-26)"]
    text += [f"- {s}, {h} sessions: {v}" for (s, h), v in verdicts.items()]
    out = "\n".join(text)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
