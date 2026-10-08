"""Persistence for backtest runs."""

import psycopg
from psycopg.types.json import Jsonb

from ..backtesting import BacktestParams, BacktestResult


def start_run(conn: psycopg.Connection, name: str | None, params: BacktestParams, config_version: str,
              provenance: str) -> int:
    from dataclasses import asdict
    return conn.execute("""
        INSERT INTO backtest_runs (name, params, config_version, provenance, status)
        VALUES (%s, %s, %s, %s, 'RUNNING') RETURNING id""",
        (name, Jsonb(asdict(params)), config_version, provenance)).fetchone()[0]


def fail_run(conn: psycopg.Connection, run_id: int, error: str) -> None:
    conn.execute("UPDATE backtest_runs SET status = 'FAILED', error = %s, finished_at = now() WHERE id = %s",
                 (error, run_id))


def save_result(conn: psycopg.Connection, run_id: int, result: BacktestResult) -> None:
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO backtest_equity (run_id, trade_date, strategy, nifty, universe_ew, drawdown_pct)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            [(run_id, r["date"], r["strategy"], r["nifty"], r["universe_ew"], r["drawdown_pct"])
             for r in result.equity_rows()])
        cur.executemany("""
            INSERT INTO backtest_holdings (run_id, signal_date, execution_date, symbol, rank, total_score,
              risk_level, confidence, weight, entry_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(run_id, h["signal"], h["execution"], h["symbol"], h["rank"], h["total_score"], h["risk_level"],
              h["confidence"], h["weight"], h["entry_price"]) for h in result.holdings])
    conn.execute("""
        UPDATE backtest_runs SET status = 'SUCCEEDED', metrics = %s, periods = %s, finished_at = now()
        WHERE id = %s""", (Jsonb(result.metrics), Jsonb(result.periods), run_id))
