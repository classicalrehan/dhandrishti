"""End to end with a fake Kite API: ingest real-shaped EOD data into its own database and score it.

Needs DD_TEST_DATABASE_URL (see test_db_pipeline.py).
"""

import os
import uuid

import httpx
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.migrate import migrate
from dhandrishti.jobs.ingest import MixedProvenanceError, ingest, kite_providers, mock_providers
from dhandrishti.jobs.run_scoring import run_scoring
from dhandrishti.providers.kite.client import KiteClient
from test_kite import FakeKite

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")
AS_OF = "2026-10-05"
START = "2025-06-01"


@pytest.fixture()
def fresh_db():
    name = f"dd_kite_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = make_conninfo(ADMIN_URL, dbname=name)
        with psycopg.connect(url) as conn:
            migrate(conn)
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def fake_kite_providers():
    c = KiteClient("key", "acc123", transport=httpx.MockTransport(FakeKite()), sleep=lambda s: None)
    return kite_providers(client=c)


def test_kite_ingest_and_score_reports_missing_fundamentals_honestly(fresh_db, cfg):
    with psycopg.connect(fresh_db) as conn:
        counts = ingest(conn, fake_kite_providers(), AS_OF, START)
        assert counts["securities"] == 2 and counts["fundamentals"] == 0
        _, result = run_scoring(conn, AS_OF, cfg)
    assert result["data_provenance"] == "EOD"
    for s in result["stocks"]:
        assert s["data_provenance"] == "EOD"
        for k in ("fundamentals", "earningsGrowth", "valuation"):
            assert s["components"][k]["coverage"] == 0  # "Data unavailable", never mocked
        assert s["confidence"] == "LOW"


def test_refuses_to_mix_real_and_mock_data(fresh_db):
    with psycopg.connect(fresh_db) as conn:
        ingest(conn, fake_kite_providers(), AS_OF, START)
        with pytest.raises(MixedProvenanceError, match="separate database"):
            ingest(conn, mock_providers(), AS_OF, "2026-01-01")


def test_restated_history_is_refetched_in_full(fresh_db):
    """A split adjusts all past prices at the source; stored rows older than the refresh must follow."""
    providers = mock_providers()
    with psycopg.connect(fresh_db) as conn:
        ingest(conn, providers, AS_OF, "2025-01-01")
        sym = "INFY"
        original = providers.market.daily_bars

        def split_adjusted(symbols, start, end):
            out = original(symbols, start, end)
            if sym in out:
                b = out[sym]
                out[sym] = type(b)(dates=b.dates, open=b.open / 2, high=b.high / 2, low=b.low / 2,
                                   close=b.close / 2, volume=b.volume * 2)
            return out

        before = conn.execute("SELECT close FROM daily_prices WHERE symbol = %s AND trade_date = '2025-02-03'",
                              (sym,)).fetchone()[0]
        providers.market.daily_bars = split_adjusted
        counts = ingest(conn, providers, AS_OF, "2026-06-01")  # refresh covers only recent months
        after = conn.execute("SELECT close FROM daily_prices WHERE symbol = %s AND trade_date = '2025-02-03'",
                             (sym,)).fetchone()[0]
        assert counts["restated"] == 1
        assert after == pytest.approx(before / 2)  # old rows were refetched, not left unadjusted
