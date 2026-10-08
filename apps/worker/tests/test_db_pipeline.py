"""Integration tests: migrations → ingest (MOCK provider) → score from DB → persist.

Needs a PostgreSQL server where the user may CREATE DATABASE:

    DD_TEST_DATABASE_URL=postgresql://dhandrishti:dhandrishti_dev@localhost:5432/postgres uv run pytest

Each run creates and drops a throwaway database. Skipped when the variable is unset.
"""

import copy
import json
import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db import market_repository as repo
from dhandrishti.db.migrate import migrate
from dhandrishti.paths import MIGRATIONS_DIR
from dhandrishti.ingestion.fixtures import load_market as load_fixture
from dhandrishti.jobs.generate_fixtures import GOLDEN_SYMBOLS
from dhandrishti.jobs.ingest import ingest, mock_providers
from dhandrishti.jobs.run_scoring import run_scoring
from dhandrishti.paths import FIXTURES_DIR
from dhandrishti.scoring import score_universe

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
AS_OF = "2026-10-05"

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def db_url():
    name = f"dd_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_conninfo(ADMIN_URL, dbname=name)
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def pipeline(db_url, cfg):
    providers = mock_providers()
    with psycopg.connect(db_url) as conn:
        applied = migrate(conn)
        counts = ingest(conn, providers, AS_OF, providers.market.history_start())
        run_id, result = run_scoring(conn, AS_OF, cfg)
    return {"applied": applied, "counts": counts, "run_id": run_id, "result": result}


def test_migrations_applied_once(db_url, pipeline):
    on_disk = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert pipeline["applied"] == on_disk and on_disk[0] == "0001_core_schema.sql"
    with psycopg.connect(db_url) as conn:
        assert migrate(conn) == []


def test_ingest_counts(pipeline):
    c = pipeline["counts"]
    assert c["securities"] == 44
    assert c["daily_prices"] == 44 * 1060  # ~4 years of MOCK history (latest 300 match the golden fixtures)
    assert c["index_prices"] == 3 * 1060
    assert c["fundamentals"] == 44 * 17  # quarterly point-in-time snapshots
    assert c["news"] == 0  # the mock provider never fabricates news


def test_ingest_is_idempotent(db_url, pipeline):
    providers = mock_providers()
    with psycopg.connect(db_url) as conn:
        before = conn.execute("SELECT count(*) FROM daily_prices").fetchone()[0]
        ingest(conn, providers, AS_OF, providers.market.history_start())
        after = conn.execute("SELECT count(*) FROM daily_prices").fetchone()[0]
    assert before == after


def test_db_round_trip_matches_golden_fixtures(pipeline):
    """Scoring from PostgreSQL must equal scoring the golden fixture file."""
    from test_golden_fixtures import _close

    expected_dir = FIXTURES_DIR / "expected"
    by_symbol = {s["symbol"]: s for s in pipeline["result"]["stocks"]}
    for sym in GOLDEN_SYMBOLS:
        expected = json.loads((expected_dir / f"{sym.lower()}.json").read_text(encoding="utf-8"))
        _close(json.loads(json.dumps(by_symbol[sym])), expected, path=sym)
    market = json.loads((expected_dir / "market.json").read_text(encoding="utf-8"))
    _close(json.loads(json.dumps({k: pipeline["result"][k] for k in market})), market)


def test_db_input_equals_fixture_input(db_url, pipeline, cfg):
    with psycopg.connect(db_url) as conn:
        from_db = repo.load_market(conn, AS_OF)
    from_file = load_fixture(FIXTURES_DIR / "inputs" / "universe-2026-10-05.json")
    a = score_universe(from_db, cfg)
    b = score_universe(from_file, cfg)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_results_persisted_with_mock_provenance(db_url, pipeline):
    run_id = pipeline["run_id"]
    with psycopg.connect(db_url) as conn:
        status, prov, n = conn.execute(
            "SELECT status, provenance, stock_count FROM scoring_runs WHERE id = %s", (run_id,)).fetchone()
        assert (status, prov, n) == ("SUCCEEDED", "MOCK", 44)
        rows = conn.execute("""SELECT rank, symbol, total_score, provenance FROM ranking_history
                               WHERE as_of = %s ORDER BY rank""", (AS_OF,)).fetchall()
        assert [r[0] for r in rows] == list(range(1, 45))
        assert {r[3] for r in rows} == {"MOCK"}
        top = pipeline["result"]["stocks"][0]
        assert rows[0][1] == top["symbol"] and rows[0][2] == pytest.approx(top["total_score"])
        assert conn.execute("SELECT count(*) FROM technical_indicators WHERE as_of = %s",
                            (AS_OF,)).fetchone()[0] == 44
        assert conn.execute("SELECT count(*) FROM sector_strength_history").fetchone()[0] == 14
        regime = conn.execute("SELECT regime, provenance FROM market_regime_history WHERE as_of = %s",
                              (AS_OF,)).fetchone()
        assert regime == (pipeline["result"]["regime"]["regime"], "MOCK")


def test_rescoring_same_day_overwrites(db_url, pipeline, cfg):
    with psycopg.connect(db_url) as conn:
        run2, _ = run_scoring(conn, AS_OF, cfg)
        n, runs = conn.execute("""SELECT count(*), array_agg(DISTINCT run_id) FROM score_history
                                  WHERE as_of = %s""", (AS_OF,)).fetchone()
    assert n == 44 and runs == [run2]


def test_changed_config_without_version_bump_is_rejected(db_url, pipeline, cfg):
    altered = copy.deepcopy(cfg)
    altered["components"]["momentum"]["weight"] = 20
    altered["components"]["valuation"]["weight"] = 5
    with psycopg.connect(db_url) as conn, pytest.raises(RuntimeError, match="bump"):
        run_scoring(conn, AS_OF, altered)


def test_edited_migration_is_rejected(db_url, pipeline, tmp_path):
    from dhandrishti.paths import MIGRATIONS_DIR
    src = (MIGRATIONS_DIR / "0001_core_schema.sql").read_text(encoding="utf-8")
    (tmp_path / "0001_core_schema.sql").write_text(src + "\n-- edited\n", encoding="utf-8")
    with psycopg.connect(db_url) as conn, pytest.raises(RuntimeError, match="modified"):
        migrate(conn, tmp_path)


def test_no_look_ahead(db_url, pipeline):
    with psycopg.connect(db_url) as conn:
        m = repo.load_market(conn, "2026-09-01")
    assert all(s.bars.dates[-1] <= "2026-09-01" for s in m.stocks)
    # Only snapshots already published on that date are used.
    assert all(s.fundamentals is not None and s.fundamentals.as_of <= "2026-09-01" for s in m.stocks)


def test_indicator_series_persisted(db_url, pipeline):
    with psycopg.connect(db_url) as conn:
        n, with_sma200 = conn.execute("""SELECT count(*), count(sma200) FROM indicator_series
                                         WHERE symbol = 'HDFCBANK'""").fetchone()
        last_rsi = conn.execute("""SELECT rsi14 FROM indicator_series WHERE symbol = 'HDFCBANK'
                                   ORDER BY trade_date DESC LIMIT 1""").fetchone()[0]
    assert n == 300 and with_sma200 == 300 - 199
    hdfc = next(s for s in pipeline["result"]["stocks"] if s["symbol"] == "HDFCBANK")
    assert last_rsi == pytest.approx(hdfc["technicals"]["rsi14"], abs=1e-3)


def test_backtest_round_trip(db_url, pipeline, cfg):
    """History loaded from PostgreSQL gives the same backtest as the in-memory generator."""
    from dhandrishti.backtesting import BacktestParams, run_backtest
    from dhandrishti.db import backtest_repository as bt
    from dhandrishti.ingestion.mock_history import generate_history

    params = BacktestParams(start="2025-09-01", end="2026-03-31", rebalance="quarterly", top_n=5)
    with psycopg.connect(db_url, autocommit=True) as conn:
        history = repo.load_history(conn, params.end)
        result = run_backtest(history, params, cfg)
        run_id = bt.start_run(conn, "test", params, cfg["version"], history.provenance)
        with conn.transaction():
            bt.save_result(conn, run_id, result)
        status, metrics = conn.execute("SELECT status, metrics FROM backtest_runs WHERE id = %s", (run_id,)).fetchone()
        n_equity = conn.execute("SELECT count(*) FROM backtest_equity WHERE run_id = %s", (run_id,)).fetchone()[0]
        n_hold = conn.execute("SELECT count(*) FROM backtest_holdings WHERE run_id = %s", (run_id,)).fetchone()[0]
    assert status == "SUCCEEDED" and n_equity == len(result.dates) and n_hold == len(result.holdings)
    assert metrics["strategy"]["cagr_pct"] == result.metrics["strategy"]["cagr_pct"]
    assert history.provenance == "MOCK"
    in_memory = run_backtest(generate_history("2026-10-05"), params, cfg)
    assert in_memory.metrics == result.metrics
