"""Fetch daily prices for former NIFTY 200 members from Kite into data/kite-backfill/ (research only).

    uv run python -m dhandrishti.jobs.former_member_prices [--db dd_dev_tracking] [--start 2020-01-01]

Former members = symbols in the verified point-in-time membership (research/pit_universe.py) without prices in the
given database (read in a READ ONLY session). Uses the existing read-only Kite client and today's session
(`pnpm kite:login`); market data only, no order endpoints. Writes CSV files and a manifest; writes no database.
A series is accepted only if Kite's history starts no later than the stock's first member day (see pit_universe).
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..providers.kite.client import KiteClient
from ..providers.kite.provider import _bars, suspicious_moves
from ..providers.kite.session import load_session
from ..research import pit_universe as P

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="dd_dev_tracking")
    ap.add_argument("--start", default="2020-01-01")        # a year of history before the verified window
    ap.add_argument("--out", type=Path, default=P.BACKFILL)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    h = P.verified_history()
    first = P.first_member_day(h)
    with psycopg.connect(make_conninfo(database_url(), dbname=args.db)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        have = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM daily_prices")}
        end = conn.execute("SELECT max(trade_date)::text FROM daily_prices").fetchone()[0]
        conn.rollback()
    need = sorted(set(first) - have)

    client = KiteClient.from_session(load_session())
    try:
        equities = {i.tradingsymbol: i.instrument_token for i in client.instruments("NSE")
                    if i.segment == "NSE" and i.instrument_type == "EQ"}
        report = {}
        for sym in need:
            kite_sym = P.PRICE_SYMBOLS.get(sym, sym)
            info = {"kite_symbol": kite_sym, "first_member_day": first[sym].isoformat()}
            if kite_sym not in equities:
                report[sym] = {**info, "status": "not_in_kite"}
                continue
            bars = _bars(client.daily_candles(equities[kite_sym], args.start, end))
            info |= {"instrument_token": equities[kite_sym], "sessions": len(bars),
                     "first": bars.dates[0] if len(bars) else None, "last": bars.dates[-1] if len(bars) else None,
                     "suspicious_moves": suspicious_moves(sym, bars)}
            if not len(bars) or bars.dates[0] > first[sym].isoformat():
                report[sym] = {**info, "status": "history_starts_too_late"}    # new listing, not the old company
                continue
            P.save_backfill(args.out, sym, bars)
            report[sym] = {**info, "status": "ok"}
            log.info("%s (%s): %d sessions %s..%s", sym, kite_sym, len(bars), info["first"], info["last"])
    finally:
        client.close()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps({
        "fetched_at": datetime.now().isoformat(timespec="seconds"), "source": "Kite Connect historical (day)",
        "start": args.start, "end": end, "verified_from": P.VERIFIED_FROM.isoformat(), "price_db": args.db,
        "symbols": report}, indent=1), encoding="utf-8")
    ok = sorted(s for s, r in report.items() if r["status"] == "ok")
    share, missing = P.coverage(h, have | set(ok), datetime.fromisoformat(end).date())
    print(f"former members needing prices: {len(need)}; fetched: {len(ok)}; member-days priced: {share:.1%}")
    for status in ("not_in_kite", "history_starts_too_late"):
        print(f"{status}: {', '.join(s for s, r in report.items() if r['status'] == status) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
