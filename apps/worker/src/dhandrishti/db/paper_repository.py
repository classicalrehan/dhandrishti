"""Persistence for paper portfolios. The engine (trading.paper) stays pure; this maps it to SQL."""

from dataclasses import asdict

import psycopg
from psycopg.types.json import Jsonb

from ..trading.paper import DayResult, Order, PaperParams, PaperState, Position


def create(conn: psycopg.Connection, name: str, state: PaperState, start: str, provenance: str) -> int:
    return conn.execute("""
        INSERT INTO paper_portfolios (name, params, status, cash, peak_equity, start_date, last_processed, provenance)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, Jsonb(asdict(state.params)), state.status, state.cash, state.peak_equity, start, start,
         provenance)).fetchone()[0]


def portfolios(conn: psycopg.Connection, include_closed: bool = False) -> list[tuple[int, str]]:
    q = "SELECT id, name FROM paper_portfolios" + ("" if include_closed else " WHERE status <> 'CLOSED'")
    return conn.execute(q + " ORDER BY id").fetchall()


def load(conn: psycopg.Connection, pid: int) -> tuple[str, PaperState]:
    row = conn.execute("""
        SELECT name, params, status, halt_reason, cash, peak_equity, last_processed
        FROM paper_portfolios WHERE id = %s""", (pid,)).fetchone()
    if row is None:
        raise LookupError(f"no paper portfolio {pid}")
    name, params, status, halt, cash, peak, last = row
    state = PaperState(params=PaperParams(**params), cash=cash, peak_equity=peak, status=status,
                       halt_reason=halt, last_processed=last.isoformat())
    for sym, qty, avg, entry, last_close, high_close in conn.execute("""
            SELECT symbol, qty, avg_price, entry_date, last_close, high_close FROM paper_positions
            WHERE portfolio_id = %s ORDER BY symbol""", (pid,)):
        state.positions[sym] = Position(sym, qty, avg, entry.isoformat(), last_close, high_close)
    for oid, created, side, sym, qty, reason, note, attempts in conn.execute("""
            SELECT id, created_on, side, symbol, qty, reason, note, attempts FROM paper_orders
            WHERE portfolio_id = %s AND status = 'PENDING' ORDER BY id""", (pid,)):
        state.pending.append(Order(created.isoformat(), side, sym, qty, reason, note=note, attempts=attempts, id=oid))
    return name, state


def _upsert_orders(conn: psycopg.Connection, pid: int, orders: list[Order]) -> None:
    for o in orders:
        if o.id is None:
            o.id = conn.execute("""
                INSERT INTO paper_orders (portfolio_id, created_on, side, symbol, qty, reason, status, fill_date,
                  fill_price, charges, note, attempts)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (pid, o.created_on, o.side, o.symbol, o.qty, o.reason, o.status, o.fill_date, o.fill_price,
                 o.charges, o.note, o.attempts)).fetchone()[0]
        else:
            conn.execute("""
                UPDATE paper_orders SET qty = %s, status = %s, fill_date = %s, fill_price = %s, charges = %s,
                  note = %s, attempts = %s WHERE id = %s""",
                (o.qty, o.status, o.fill_date, o.fill_price, o.charges, o.note, o.attempts, o.id))


def save(conn: psycopg.Connection, pid: int, state: PaperState, results: list[DayResult],
         nifty: dict[str, float], new_orders: list[Order] | None = None) -> None:
    """Persist state after processing; call inside a transaction."""
    conn.execute("""
        UPDATE paper_portfolios SET status = %s, halt_reason = %s, cash = %s, peak_equity = %s, last_processed = %s
        WHERE id = %s""", (state.status, state.halt_reason, state.cash, state.peak_equity, state.last_processed, pid))
    conn.execute("DELETE FROM paper_positions WHERE portfolio_id = %s", (pid,))
    for p in state.positions.values():
        conn.execute("""
            INSERT INTO paper_positions (portfolio_id, symbol, qty, avg_price, entry_date, last_close, high_close)
            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (pid, p.symbol, p.qty, p.avg_price, p.entry_date, p.last_close, p.high_close))
    touched: dict[int, Order] = {}
    for r in results:
        for o in r.filled + r.cancelled + r.created:
            touched[id(o)] = o
    for o in state.pending + list(new_orders or []):
        touched[id(o)] = o
    _upsert_orders(conn, pid, list(touched.values()))
    for r in results:
        row = r.daily_row()
        conn.execute("""
            INSERT INTO paper_daily (portfolio_id, trade_date, cash, holdings_value, equity, drawdown_pct,
              nifty_close, events)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (portfolio_id, trade_date) DO UPDATE SET cash = EXCLUDED.cash,
              holdings_value = EXCLUDED.holdings_value, equity = EXCLUDED.equity,
              drawdown_pct = EXCLUDED.drawdown_pct, nifty_close = EXCLUDED.nifty_close, events = EXCLUDED.events""",
            (pid, row["trade_date"], row["cash"], row["holdings_value"], row["equity"], row["drawdown_pct"],
             nifty.get(r.day), Jsonb(r.events)))


def set_status(conn: psycopg.Connection, pid: int, status: str, peak: float | None = None) -> None:
    if peak is None:
        conn.execute("UPDATE paper_portfolios SET status = %s, halt_reason = NULL WHERE id = %s", (status, pid))
    else:
        conn.execute("UPDATE paper_portfolios SET status = %s, halt_reason = NULL, peak_equity = %s WHERE id = %s",
                     (status, peak, pid))
