"""Paper trading end to end on PostgreSQL (MOCK data). Needs DD_TEST_DATABASE_URL."""

import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.migrate import migrate
from dhandrishti.jobs import paper
from dhandrishti.jobs.ingest import ingest, mock_providers
from dhandrishti.trading.paper import PaperParams

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def db():
    name = f"dd_paper_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url) as conn:
            migrate(conn)
            providers = mock_providers()
            ingest(conn, providers, "2026-10-05", providers.market.history_start())
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_paper_portfolio_lifecycle(db):
    with psycopg.connect(db, autocommit=True) as conn:
        pid = paper.create(conn, "test top 3", PaperParams(capital=100_000, top_n=3, rank_buffer=6), as_of="2026-08-20")
        initial = conn.execute("SELECT count(*), min(status) FROM paper_orders WHERE portfolio_id = %s", (pid,)).fetchone()
        assert initial == (3, "PENDING")

        summary = paper.run(conn)
        assert any(f"#{pid}" in line and "2026-10-05" in line for line in summary)

        # Initial orders filled at the NEXT session's open, never on the signal day.
        fills = conn.execute("""
            SELECT o.fill_date, o.fill_price, p.open FROM paper_orders o
            JOIN daily_prices p ON p.symbol = o.symbol AND p.trade_date = o.fill_date
            WHERE o.portfolio_id = %s AND o.reason = 'INITIAL'""", (pid,)).fetchall()
        assert len(fills) == 3
        assert all(d.isoformat() == "2026-08-21" and price == open_ for d, price, open_ in fills)

        # One row per processed session; the monthly signal on 2026-08-31 produced a rebalance decision.
        days = conn.execute("SELECT count(*) FROM paper_daily WHERE portfolio_id = %s", (pid,)).fetchone()[0]
        sessions = conn.execute("""SELECT count(*) FROM index_prices WHERE index_code = 'NIFTY 50'
                                   AND trade_date BETWEEN '2026-08-20' AND '2026-10-05'""").fetchone()[0]
        assert days == sessions
        n_pos = conn.execute("SELECT count(*) FROM paper_positions WHERE portfolio_id = %s", (pid,)).fetchone()[0]
        assert 1 <= n_pos <= 3
        cash, last = conn.execute("SELECT cash, last_processed FROM paper_portfolios WHERE id = %s", (pid,)).fetchone()
        assert cash >= 0 and last.isoformat() == "2026-10-05"
        charges = conn.execute("SELECT sum(charges) FROM paper_orders WHERE portfolio_id = %s AND status = 'FILLED'",
                               (pid,)).fetchone()[0]
        assert charges > 0

        # Idempotent: nothing new to process.
        assert any("up to date" in line for line in paper.run(conn))


def test_duplicate_names_are_rejected(db):
    with psycopg.connect(db, autocommit=True) as conn:
        paper.create(conn, "dup", PaperParams(), as_of="2026-09-01")
        with pytest.raises(psycopg.errors.UniqueViolation):
            paper.create(conn, "dup", PaperParams(), as_of="2026-09-01")
