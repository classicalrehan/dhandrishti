"""Fetch your real Zerodha holdings (read-only) and show how DhanDrishti scores each one.

    uv run python -m dhandrishti.jobs.holdings          # fetch, save today's snapshot, print a summary

Uses the session from `pnpm kite:login`. Only GET /portfolio/holdings and /portfolio/positions are
called: nothing is ever bought, sold or changed in your account. Snapshots stay in the local
database and are not available to the AI assistant.
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

import psycopg

from ..db import connect
from ..db.holdings_repository import save_snapshot
from ..db.migrate import migrate
from ..providers.kite.client import KiteClient, KiteError, PortfolioItem
from ..providers.kite.session import load_session
from ..trading.holdings import snapshot_date

IST = timezone(timedelta(hours=5, minutes=30))


class HoldingsError(RuntimeError):
    pass


def ensure_real_database(conn: psycopg.Connection) -> None:
    if conn.execute("SELECT 1 FROM securities WHERE provenance = 'MOCK' LIMIT 1").fetchone():
        raise HoldingsError("this is the MOCK database; real holdings belong in the Kite database "
                            "(`pnpm holdings` uses it by default)")


def summary(conn: psycopg.Connection, items: list[PortfolioItem], snap: dict) -> list[str]:
    run = conn.execute("""SELECT id, as_of, (SELECT count(*) FROM score_history h WHERE h.run_id = r.id)
                          FROM scoring_runs r WHERE status = 'SUCCEEDED' ORDER BY as_of DESC, id DESC LIMIT 1""").fetchone()
    scores = {}
    if run:
        scores = {s: (rank, score, risk) for s, rank, score, risk in conn.execute(
            "SELECT symbol, rank, total_score, risk_level FROM score_history WHERE run_id = %s", (run[0],))}
    hs = sorted((i for i in items if i.kind == "HOLDING" and i.qty > 0), key=lambda i: -i.qty * i.last_price)
    pnl = snap["value"] - snap["invested"]
    lines = [f"Holdings on {snap['as_of']}: {len(hs)} stocks, value ₹{snap['value']:,.0f}, invested ₹{snap['invested']:,.0f}, "
             f"P&L ₹{pnl:+,.0f} ({(pnl / snap['invested'] * 100) if snap['invested'] else 0:+.2f}%)"]
    if snap["period_return_pct"] is not None:
        lines.append(f"Change since the previous snapshot (time-weighted): {snap['period_return_pct']:+.2f}%")
    for i in hs:
        s = scores.get(i.tradingsymbol)
        tag = (f"rank {s[0]}/{run[2]}, score {s[1]:.1f}, risk {s[2]}" if s else "not scored (outside the universe)")
        lines.append(f"  {i.tradingsymbol:<12} {i.qty:>6} × ₹{i.last_price:,.2f}  P&L {i.pnl:+,.0f}   {tag}")
    positions = [i for i in items if i.kind == "POSITION"]
    if positions:
        lines.append(f"{len(positions)} open position(s): " + ", ".join(f"{p.tradingsymbol} {p.qty:+d}" for p in positions))
    lines.append("Saved. See it at /portfolio (pnpm dev:kite).")
    return lines


def fetch(conn: psycopg.Connection, client: KiteClient, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(IST)
    items = client.holdings() + client.positions()
    snap = save_snapshot(conn, snapshot_date(now), now, items)
    return summary(conn, items, snap)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    try:
        client = KiteClient.from_session(load_session())
        with connect() as conn:
            migrate(conn)
            conn.autocommit = True
            ensure_real_database(conn)
            print("\n".join(fetch(conn, client)))
        client.close()
    except (KiteError, HoldingsError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
