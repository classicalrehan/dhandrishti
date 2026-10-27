"""Entry-signal study (research only; read-only; docs in research/entry_signals.py).

    uv run python -m dhandrishti.jobs.entry_study [--db dd_dev_tracking] [--pit] [--out FILE.md]

Opens the database in a READ ONLY session (nothing can be written) and defaults to the development copy, not the
research database. Credentials come from DD_DATABASE_URL; only the database name is replaced.

--pit: point-in-time universe (research/pit_universe.py). Signals and the control are limited to the stocks that
were NIFTY 200 members on the signal day, from the verified start (2021) only; former members are priced from
data/kite-backfill/ (jobs/former_member_prices.py). Stops if membership contradicts a listing date.
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..db.market_repository import load_history
from ..research import entry_signals as E
from ..research import pit_universe as P

PIT_PERIODS = (("2021-2022", "2021-01-01", "2022-12-31"), ("2023-2026", "2023-01-01", "2026-12-31"))


def point_in_time(history, latest: str) -> tuple[object, list[str]]:
    """Add former members' prices; return the membership function and a description of the universe."""
    h = P.verified_history()
    backfill = {s: b for s, b in P.load_backfill().items() if s not in history.bars}
    history.bars.update(backfill)
    for s in P.UNCERTAIN:
        history.bars.pop(s, None)
    first_trade = {s: date.fromisoformat(b.dates[0]) for s, b in history.bars.items() if len(b)}
    data_start = min(first_trade.values())
    conflicts = [c for c in P.listing_conflicts(h, first_trade, data_start) if c.split(":")[0] not in P.UNCERTAIN]
    if conflicts:
        raise SystemExit("membership contradicts listing dates: " + "; ".join(conflicts))
    share, missing = P.coverage(h, set(history.bars), date.fromisoformat(latest))

    def members(day: str):
        m = h.members_on(date.fromisoformat(day))
        return None if m is None else m - P.UNCERTAIN.keys()

    note = [f"Point-in-time universe: NIFTY 200 members on each signal day, verified from {P.VERIFIED_FROM} "
            f"({len(h.periods) - 1} membership changes); former members priced from Kite ({len(backfill)} series). "
            f"Member-days with prices: {share:.1%}; unpriced: {', '.join(missing) or 'none'}. "
            f"Left out (membership uncertain): {', '.join(P.UNCERTAIN)}."]
    return members, note


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="dd_dev_tracking")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--pit", action="store_true", help="point-in-time NIFTY 200 universe (2021 onward)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with psycopg.connect(make_conninfo(database_url(), dbname=args.db)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        latest = conn.execute("SELECT max(trade_date)::text FROM daily_prices").fetchone()[0]
        history = load_history(conn, latest)
        conn.rollback()
    if args.pit:
        members, universe = point_in_time(history, latest)
        res = E.run(history, members=members)
        rows = E.summarize(res, PIT_PERIODS)
        verdicts = E.verdict(rows, ("2021-2022", "2023-2026"), "point-in-time universe, one window per period")
        rule = "## Pre-registered verdicts (edge = positive excess, t >= 2 in 2021-22 AND 2023-26)"
    else:
        res = E.run(history)
        rows = E.summarize(res)
        verdicts = E.verdict(rows)
        universe = ["Universe = today's NIFTY 200 applied to the past (survivorship bias)."]
        rule = "## Pre-registered verdicts (edge = positive excess, t >= 2 in 2019-22 AND 2023-26)"
    text = [f"# Entry-signal study ({args.db}, prices to {latest}, {len(history.bars)} stocks)", "",
            "Research only. " + " ".join(universe) + " Price returns (dividends excluded); entry next open, exit "
            "open after h sessions; costs 15/13.5 bps per side.", "", E.markdown(rows, res), "", rule]
    text += [f"- {s}, {h} sessions: {v}" for (s, h), v in verdicts.items()]
    out = "\n".join(text)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
