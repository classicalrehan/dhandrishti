"""Import real fundamentals (quarterly results + shareholding CSVs) into the database.

    uv run python -m dhandrishti.jobs.import_fundamentals --quarterly results.csv [--shareholding sh.csv]
        [--source "TrueData"] [--dry-run]

File formats: docs/fundamentals-import.md (templates in docs/templates/). Snapshots are dated by
publication date, so backtests and paper trading only see numbers after they became public.
"""

import argparse
import bisect
import os
import sys
from pathlib import Path

import psycopg

from ..db import connect
from ..db import market_repository as repo
from ..db.migrate import migrate
from ..ingestion.fundamentals_import import ImportError_, build_snapshots, parse_quarterly, parse_shareholding

KEY_FIELDS = ("revenue_growth_yoy", "profit_growth_yoy", "eps_cagr_3y", "roe", "operating_margin",
              "debt_to_equity", "cfo_to_pat", "pe", "promoter_pledge", "positive_eps_quarters_8")


def closes_lookup(conn: psycopg.Connection, symbols: list[str]):
    series: dict[str, tuple[list[str], list[float]]] = {}
    for sym, d, c in conn.execute("""
            SELECT symbol, trade_date, close FROM daily_prices WHERE symbol = ANY(%s) ORDER BY symbol, trade_date""",
            (symbols,)):
        dates, closes = series.setdefault(sym, ([], []))
        dates.append(d.isoformat())
        closes.append(c)

    def close_on(sym: str, day: str) -> float | None:
        dates, closes = series.get(sym, ([], []))
        i = bisect.bisect_right(dates, day) - 1
        return closes[i] if i >= 0 else None

    return close_on


def run(conn: psycopg.Connection, quarterly: Path, shareholding: Path | None, source: str,
        dry_run: bool) -> list[str]:
    provenances = {r[0] for r in conn.execute("SELECT DISTINCT provenance FROM securities")}
    if not provenances:
        raise ImportError_("this database has no securities yet; run the price pipeline first")
    if "MOCK" in provenances:
        raise ImportError_("this is the MOCK database; import real fundamentals into the Kite database "
                           "(pnpm fundamentals:import uses it by default)")
    known = {r[0] for r in conn.execute("SELECT symbol FROM securities")}
    quarters = parse_quarterly(quarterly, known)
    holdings = parse_shareholding(shareholding, known) if shareholding else {}
    symbols = sorted(set(quarters) | set(holdings))
    snaps = build_snapshots(quarters, holdings, closes_lookup(conn, symbols))

    lines = [f"{len(symbols)} symbols, {sum(map(len, quarters.values()))} quarters, "
             f"{sum(map(len, holdings.values()))} shareholding rows -> {sum(map(len, snaps.values()))} snapshots"]
    for sym in symbols:
        if not snaps.get(sym):
            lines.append(f"  {sym}: no snapshot")
            continue
        last = snaps[sym][-1]
        missing = [f for f in KEY_FIELDS if getattr(last, f) is None]
        nq = len(quarters.get(sym, []))
        hint = " (need 8+ quarters for growth, 16 for 3-year CAGR)" if nq < 16 else ""
        lines.append(f"  {sym}: {len(snaps[sym])} snapshots, latest {last.as_of}, {nq} quarters{hint}"
                     + (f"; missing {', '.join(missing)}" if missing else "; all key fields present"))
    missing_universe = sorted(known - set(symbols))
    if missing_universe:
        lines.append(f"no fundamentals in these files for: {', '.join(missing_universe)}")
    if dry_run:
        lines.append("dry run: nothing written")
    else:
        with conn.transaction():
            n = repo.upsert_fundamentals(conn, snaps, "EOD", source)
        lines.append(f"wrote {n} snapshots (source: {source}). Re-score with `pnpm pipeline:kite`.")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quarterly", type=Path, required=True)
    ap.add_argument("--shareholding", type=Path)
    ap.add_argument("--source", default="manual import")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    # pnpm runs this from apps/worker; resolve relative paths against where the user typed the command.
    base = Path(os.environ.get("INIT_CWD", os.getcwd()))
    args.quarterly = args.quarterly if args.quarterly.is_absolute() else base / args.quarterly
    if args.shareholding and not args.shareholding.is_absolute():
        args.shareholding = base / args.shareholding
    try:
        with connect() as conn:
            migrate(conn)
            print("\n".join(run(conn, args.quarterly, args.shareholding, args.source, args.dry_run)))
    except (ImportError_, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
