"""Real holdings: read-only Kite portfolio calls, time-weighted returns, and snapshot storage."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.holdings_repository import save_snapshot
from dhandrishti.db.migrate import migrate
from dhandrishti.jobs import holdings as job
from dhandrishti.jobs.ingest import ingest, mock_providers
from dhandrishti.jobs.run_scoring import run_scoring
from dhandrishti.providers.kite.client import KiteClient, PortfolioItem
from dhandrishti.trading.holdings import period_return, snapshot_date, totals

IST = timezone(timedelta(hours=5, minutes=30))

HOLDINGS = {"status": "success", "data": [
    {"tradingsymbol": "INFY", "exchange": "NSE", "isin": "INE009A01021", "product": "CNC", "quantity": 10,
     "t1_quantity": 2, "average_price": 1500.0, "last_price": 1600.0, "close_price": 1590.0, "pnl": 1200.0},
    {"tradingsymbol": "GOLDBEES", "exchange": "NSE", "isin": "INF204KB17I5", "product": "CNC", "quantity": 50,
     "t1_quantity": 0, "average_price": 60.0, "last_price": 62.0, "close_price": 0, "pnl": 100.0},
]}
POSITIONS = {"status": "success", "data": {"net": [
    {"tradingsymbol": "TCS", "exchange": "NSE", "product": "MIS", "quantity": 0, "average_price": 0,
     "last_price": 4000, "pnl": 50},
    {"tradingsymbol": "NIFTY26OCT25000PE", "exchange": "NFO", "product": "NRML", "quantity": 75,
     "average_price": 80.0, "last_price": 95.0, "close_price": 90.0, "pnl": 1125.0},
], "day": []}}


def item(sym, qty, price, avg=100.0, kind="HOLDING", exchange="NSE"):
    return PortfolioItem(kind, sym, exchange, "CNC", None, qty, 0, avg, price, None, 0.0)


def test_client_reads_holdings_and_positions_with_get_only():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path))
        assert req.headers["Authorization"] == "token key:acc123"
        body = HOLDINGS if req.url.path == "/portfolio/holdings" else POSITIONS
        return httpx.Response(200, json=body)

    c = KiteClient("key", "acc123", transport=httpx.MockTransport(handler))
    hs, ps = c.holdings(), c.positions()
    assert seen == [("GET", "/portfolio/holdings"), ("GET", "/portfolio/positions")]
    assert hs[0].qty == 12 and hs[0].t1_qty == 2 and hs[0].close_price == 1590.0  # T1 shares count as held
    assert hs[1].close_price is None
    assert [p.tradingsymbol for p in ps] == ["NIFTY26OCT25000PE"]  # closed (zero-quantity) positions dropped


def test_client_has_no_order_methods():
    names = {n for n in dir(KiteClient) if not n.startswith("_")}
    assert not {n for n in names if any(w in n for w in ("order", "place", "modify", "cancel", "gtt"))}


def test_totals_ignore_positions():
    assert totals([item("A", 10, 120.0), item("B", 5, 50.0, kind="POSITION")]) == (1200.0, 1000.0)


def test_period_return_is_not_fooled_by_buying_more():
    prev = [item("A", 10, 100.0), item("B", 10, 100.0)]
    cur = [item("A", 50, 110.0), item("B", 10, 90.0), item("C", 100, 10.0)]  # bought 40 more A and new C
    assert period_return(prev, cur, lambda s: None) == pytest.approx(0.0)


def test_period_return_prices_sold_holdings_from_the_database_or_skips_them():
    prev = [item("A", 10, 100.0), item("SOLD", 10, 100.0), item("GONE", 10, 100.0)]
    cur = [item("A", 10, 110.0)]
    r = period_return(prev, cur, lambda s: 120.0 if s == "SOLD" else None)
    assert r == pytest.approx(15.0)  # (1100 + 1200) / 2000; GONE has no price and is left out
    assert period_return([], cur, lambda s: None) is None


def test_snapshot_date_follows_the_session():
    assert snapshot_date(datetime(2026, 10, 7, 17, 0, tzinfo=IST)) == "2026-10-07"   # evening
    assert snapshot_date(datetime(2026, 10, 7, 11, 0, tzinfo=IST)) == "2026-10-07"   # intraday: replaced later
    assert snapshot_date(datetime(2026, 10, 7, 8, 0, tzinfo=IST)) == "2026-10-06"    # before the open
    assert snapshot_date(datetime(2026, 10, 10, 12, 0, tzinfo=IST)) == "2026-10-09"  # Saturday


# ---------------------------------------------------------------- database

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
db_only = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def db():
    name = f"dd_hold_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            migrate(conn)
            providers = mock_providers()
            ingest(conn, providers, "2026-10-05", providers.market.history_start())
            run_scoring(conn, "2026-10-05")
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@db_only
def test_snapshots_chain_and_same_day_refetch_replaces(db):
    t = datetime(2026, 10, 5, 17, 0, tzinfo=IST)
    with psycopg.connect(db, autocommit=True) as conn:
        first = save_snapshot(conn, "2026-10-01", t, [item("A", 10, 100.0)])
        assert first["twr_index"] == 100.0 and first["period_return_pct"] is None
        save_snapshot(conn, "2026-10-05", t, [item("A", 10, 105.0)])
        save_snapshot(conn, "2026-10-06", t, [item("A", 10, 110.0)])
        # an earlier date is re-fetched with a different price: the later index is re-chained
        save_snapshot(conn, "2026-10-05", t, [item("A", 10, 120.0)])
        rows = conn.execute("SELECT as_of::text, twr_index, period_return_pct FROM holdings_snapshots ORDER BY as_of").fetchall()
        assert [r[0] for r in rows] == ["2026-10-01", "2026-10-05", "2026-10-06"]
        assert rows[1][1] == pytest.approx(120.0)
        assert rows[2][1] == pytest.approx(110.0) and rows[2][2] == pytest.approx(110 / 120 * 100 - 100)
        assert conn.execute("SELECT count(*) FROM holding_items WHERE as_of = '2026-10-05'").fetchone()[0] == 1
        assert rows and conn.execute("SELECT nifty_close FROM holdings_snapshots WHERE as_of = '2026-10-05'").fetchone()[0]


@db_only
def test_fetch_summarises_scores_and_the_mock_database_is_refused(db):
    sym = "INFY"

    def handler(req):
        body = HOLDINGS if req.url.path == "/portfolio/holdings" else POSITIONS
        return httpx.Response(200, json=body)

    client = KiteClient("key", "acc123", transport=httpx.MockTransport(handler))
    with psycopg.connect(db, autocommit=True) as conn:
        lines = job.fetch(conn, client, datetime(2026, 10, 7, 17, 0, tzinfo=IST))
        text = "\n".join(lines)
        assert f"{sym}" in text and "rank " in text and "GOLDBEES" in text and "not scored" in text
        assert "1 open position(s)" in text
        with pytest.raises(job.HoldingsError, match="MOCK"):
            job.ensure_real_database(conn)
