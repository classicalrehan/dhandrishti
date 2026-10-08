"""Persistence for real holdings snapshots (migration 0006)."""

from datetime import datetime

import psycopg

from ..providers.kite.client import PortfolioItem
from ..trading.holdings import period_return, totals

_COLS = ("kind", "tradingsymbol", "exchange", "product", "isin", "qty", "t1_qty", "avg_price", "last_price",
         "close_price", "pnl")


def _items(conn: psycopg.Connection, as_of: str) -> list[PortfolioItem]:
    rows = conn.execute(f"SELECT {', '.join(_COLS)} FROM holding_items WHERE as_of = %s", (as_of,)).fetchall()
    return [PortfolioItem(*r) for r in rows]


def save_snapshot(conn: psycopg.Connection, as_of: str, fetched_at: datetime, items: list[PortfolioItem]) -> dict:
    """Write (or replace) the snapshot for `as_of`, chaining the time-weighted index from the previous one."""
    prev = conn.execute("""SELECT as_of, twr_index FROM holdings_snapshots WHERE as_of < %s
                           ORDER BY as_of DESC LIMIT 1""", (as_of,)).fetchone()
    ret = None
    index = 100.0
    if prev:
        def close_on(sym: str) -> float | None:
            row = conn.execute("""SELECT close FROM daily_prices WHERE symbol = %s AND trade_date <= %s
                                  ORDER BY trade_date DESC LIMIT 1""", (sym, as_of)).fetchone()
            return row[0] if row else None
        ret = period_return(_items(conn, prev[0].isoformat()), items, close_on)
        index = prev[1] * (1 + (ret or 0.0) / 100)
    nifty = conn.execute("""SELECT close FROM index_prices WHERE index_code = 'NIFTY 50' AND trade_date <= %s
                            ORDER BY trade_date DESC LIMIT 1""", (as_of,)).fetchone()
    value, invested = totals(items)
    with conn.transaction():
        conn.execute("DELETE FROM holdings_snapshots WHERE as_of = %s", (as_of,))
        conn.execute("""INSERT INTO holdings_snapshots (as_of, fetched_at, value, invested, period_return_pct,
                        twr_index, nifty_close) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                     (as_of, fetched_at, value, invested, ret, index, nifty[0] if nifty else None))
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO holding_items (as_of, {', '.join(_COLS)}) VALUES (%s{', %s' * len(_COLS)})",
                [(as_of, *(getattr(i, c) for c in _COLS)) for i in items])
    # A later snapshot's index was chained from the one just replaced; keep the chain consistent.
    later = [r[0].isoformat() for r in conn.execute(
        "SELECT as_of FROM holdings_snapshots WHERE as_of > %s ORDER BY as_of LIMIT 1", (as_of,))]
    if later:
        save_snapshot(conn, later[0], *conn.execute(
            "SELECT fetched_at FROM holdings_snapshots WHERE as_of = %s", (later[0],)).fetchone(), _items(conn, later[0]))
    return {"as_of": as_of, "value": value, "invested": invested, "period_return_pct": ret, "twr_index": index}
