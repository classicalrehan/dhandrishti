"""Recommendation tracking (staged migration 0010). Throwaway dd_* test databases only.

Needs DD_TEST_DATABASE_URL (see test_db_pipeline.py). Prices in the outcome tests are hand-built so every
expected number can be checked by hand; the recorder and verification tests use the MOCK provider.
"""

import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from dhandrishti.db.market_repository import load_market
from dhandrishti.db.migrate import migrate
from dhandrishti.db.staged import ProtectedDatabaseError, apply_staged
from dhandrishti.jobs.ingest import ingest, mock_providers
from dhandrishti.jobs.run_scoring import run_scoring
from dhandrishti.models import Bars
from dhandrishti.paths import MIGRATIONS_DIR, STAGED_MIGRATIONS_DIR
from dhandrishti.trading.costs import delivery_charges
from dhandrishti.tracking import manifest as M
from dhandrishti.tracking import outcomes as O
from dhandrishti.tracking import policy as P
from dhandrishti.tracking import recorder as R
from dhandrishti.tracking import summary as S
from dhandrishti.tracking import verify as V

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")
ONLY_0010 = ["0010_recommendation_tracking.sql"]
AS_OF = "2026-10-05"
CLEAN = R.CodeInfo("0" * 40, False)
TRACKING_TABLES = ("price_change_log", "recommendation_policies", "outcome_methods", "recommendation_runs",
                   "recommendation_scores", "recommendation_outcomes", "run_verifications", "tracking_failures")
WORKER_SRC = Path(__file__).resolve().parents[1] / "src" / "dhandrishti"


# ---------------------------------------------------------------- databases

def _create() -> tuple[str, str]:
    name = f"dd_trk_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    return name, make_conninfo(ADMIN_URL, dbname=name)


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture()
def db():
    """Empty database with the normal migrations and staged 0010 only."""
    name, url = _create()
    try:
        with psycopg.connect(url, autocommit=True) as c:
            apply_staged(c, only=ONLY_0010)
            yield c
    finally:
        _drop(name)


@pytest.fixture()
def mock_db():
    """MOCK market data ingested BEFORE 0010 is applied (like production), then 0010 applied."""
    name, url = _create()
    try:
        with psycopg.connect(url) as c:
            migrate(c)
            p = mock_providers()
            ingest(c, p, AS_OF, p.market.history_start())
            c.autocommit = True
            yield c
    finally:
        _drop(name)


def _install(c) -> None:
    apply_staged(c, only=ONLY_0010)


# ---------------------------------------------------------------- schema

def test_0010_is_staged_and_independent_of_0009(db):
    assert not (MIGRATIONS_DIR / ONLY_0010[0]).exists() and (STAGED_MIGRATIONS_DIR / ONLY_0010[0]).exists()
    assert db.execute("SELECT to_regclass('recommendation_runs')").fetchone()[0] is not None
    assert db.execute("SELECT to_regclass('fundamental_filings')").fetchone()[0] is None  # 0009 not applied
    applied = {r[0] for r in db.execute("SELECT filename FROM schema_migrations")}
    assert ONLY_0010[0] in applied and "0009_fundamental_quality.sql" not in applied


@pytest.mark.parametrize("dbname", ["dhandrishti", "dhandrishti_kite", "research"])
def test_staged_migration_refuses_research_databases(dbname):
    class Fake:
        class info:
            pass
    Fake.info.dbname = dbname
    with pytest.raises(ProtectedDatabaseError):
        apply_staged(Fake(), only=ONLY_0010)


def test_only_filter_rejects_unknown_files(db):
    with pytest.raises(FileNotFoundError):
        apply_staged(db, only=["0099_missing.sql"])


def _run_row(c, kind="DEVELOPMENT", failures=("UNCOMMITTED_CODE",), as_of="2026-01-05", **over) -> int:
    c.execute("INSERT INTO scoring_config_versions VALUES ('t', '{}', 'sha') ON CONFLICT DO NOTHING")
    run_id = c.execute("""INSERT INTO scoring_runs (as_of, config_version, provenance, status)
                          VALUES (%s, 't', 'EOD', 'SUCCEEDED') RETURNING id""", (as_of,)).fetchone()[0]
    pv = P.register(c)
    vals = {"run_id": run_id, "record_kind": kind, "qualification_failures": list(failures), "as_of": as_of,
            "decision_at": R.at_ist(as_of, R.CLOSE), "inputs_loaded_at": R.at_ist(as_of, R.SETTLED),
            "scored_at": R.at_ist(as_of, R.SETTLED), "entry_session": None, "entry_deadline": None,
            "config_version": "t", "config_sha256": "sha", "code_commit": "c", "code_dirty": True,
            "lookback_bars": 300, "input_hash": "h", "input_manifest": Jsonb({}), "output_hash": "o",
            "data_provenance": "EOD", "scored_count": 0, "regime": Jsonb({}), "breadth": Jsonb({}),
            "sectors": Jsonb([]), "policy_version": pv}
    vals.update(over)
    c.execute(f"INSERT INTO recommendation_runs ({', '.join(vals)}) VALUES ({', '.join(['%s'] * len(vals))})",
              list(vals.values()))
    return run_id


def _score_row(c, run_id, symbol, rank, risk="LOW", selection=None, reasons=()):
    eligible = not reasons
    selection = selection or ("RECOMMENDED" if rank <= 5 and eligible else
                              "EXCLUDED_CANDIDATE" if rank <= 5 else "NOT_CANDIDATE")
    c.execute("""INSERT INTO recommendation_scores (run_id, symbol, rank, total_score, confidence, data_coverage,
                 risk_level, risk_points, component_scores, component_coverage, eligible, exclusion_reasons,
                 selection, result, result_sha256)
                 VALUES (%s, %s, %s, 50, 'LOW', 0.45, %s, 0, '{}', '{}', %s, %s, %s, '{}', 'x')""",
              (run_id, symbol, rank, risk, eligible, list(reasons), selection))


def _security(c, *symbols):
    for s in symbols:
        c.execute("INSERT INTO securities (symbol, name, sector, provenance, source) VALUES (%s, %s, 'Test', 'EOD', 't') "
                  "ON CONFLICT DO NOTHING", (s, s))


def test_tracking_tables_are_append_only(db):
    _security(db, "AAA")
    run_id = _run_row(db)
    _score_row(db, run_id, "AAA", 1)
    O.register(db)
    db.execute("""INSERT INTO recommendation_outcomes (run_id, symbol, horizon, method_version, evaluation_hash,
                  price_data_hash, status, entry_date, entry_price) VALUES (%s, 'AAA', 20, 'outcome-v1', 'e', 'p',
                  'NO_EXIT_PRICE', '2026-01-06', 100)""", (run_id,))
    db.execute("INSERT INTO run_verifications (run_id, status, detail) VALUES (%s, 'VERIFICATION_FAILED', '{}')",
               (run_id,))
    db.execute("""INSERT INTO tracking_failures (run_id, stage, error_type, error_message, diagnostic)
                  VALUES (%s, 'RECORD', 'RuntimeError', 'x', 'y')""", (run_id,))
    for table in TRACKING_TABLES:
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0, table
        for stmt in (f"UPDATE {table} SET {_any_column(db, table)} = {_any_column(db, table)}",
                     f"DELETE FROM {table}", f"TRUNCATE {table} CASCADE"):
            with pytest.raises(psycopg.errors.RestrictViolation):
                db.execute(stmt)


def _any_column(c, table):
    return c.execute("""SELECT column_name FROM information_schema.columns WHERE table_name = %s
                        ORDER BY ordinal_position LIMIT 1""", (table,)).fetchone()[0]


@pytest.mark.parametrize("over", [
    {"record_kind": "LIVE"},                                                       # LIVE with failures listed
    {"record_kind": "LIVE", "qualification_failures": []},                         # LIVE from dirty code
    {"record_kind": "DEVELOPMENT", "qualification_failures": []},                  # non-LIVE without a reason
    {"entry_session": "2026-01-05"},                                               # entry not after as_of
    {"input_manifest": None},                                                      # no manifest unless BACKFILLED
])
def test_run_constraints(db, over):
    with pytest.raises(psycopg.errors.CheckViolation):
        _run_row(db, **over)


def test_live_run_requires_every_condition(db):
    ok = {"record_kind": "LIVE", "failures": (), "code_dirty": False, "entry_session": "2026-01-06",
          "entry_deadline": R.at_ist("2026-01-06", R.OPEN)}
    _run_row(db, **ok)
    for bad in ({"data_provenance": "MOCK"}, {"code_commit": None},
                {"inputs_loaded_at": R.at_ist("2026-01-05", R.CLOSE) - timedelta(minutes=1)},
                {"scored_at": R.at_ist("2026-01-06", R.OPEN)}):
        with pytest.raises(psycopg.errors.CheckViolation):
            _run_row(db, **{**ok, **bad})


def test_score_and_outcome_constraints(db):
    _security(db, "AAA", "BBB")
    run_id = _run_row(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _score_row(db, run_id, "AAA", 1, reasons=("RISK_HIGH_ABOVE_MEDIUM",), selection="RECOMMENDED")
    _score_row(db, run_id, "BBB", 2)
    O.register(db)
    base = ("INSERT INTO recommendation_outcomes (run_id, symbol, horizon, method_version, evaluation_hash, "
            "price_data_hash, status, entry_date, exit_date, gross_return, net_return, nifty_return, mae_reliable) "
            "VALUES (%s, 'BBB', 20, 'outcome-v1', %s, 'p', %s, '2026-01-06', %s, %s, %s, %s, true)")
    for ev, status, exit_, gross, net, nifty in (
            ("a", "COMPLETE", "2026-02-03", 0.1, 0.09, None),        # COMPLETE needs the benchmark
            ("b", "NO_ENTRY_PRICE", None, 0.1, 0.09, None),          # no price, but a return
            ("c", "COMPLETE", "2026-01-06", 0.1, 0.09, 0.01),        # exit not after entry
            ("d", "COMPLETE", "2099-01-01", 0.1, 0.09, 0.01)):       # computed before the exit happened
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(base, (run_id, ev, status, exit_, gross, net, nifty))


def test_price_log_records_real_changes_only(db):
    _security(db, "AAA")
    ins = ("INSERT INTO daily_prices (symbol, trade_date, open, high, low, close, volume, provenance, source) "
           "VALUES ('AAA', %s, 10, 11, 9, %s, 100, 'EOD', 't') ON CONFLICT (symbol, trade_date) DO UPDATE SET "
           "close = EXCLUDED.close, ingested_at = now()")
    db.execute(ins, ("2026-01-05", 10.5))
    db.execute(ins, ("2026-01-05", 10.5))   # the daily refetch re-upserting identical values
    db.execute(ins, ("2026-01-05", 10.7))   # a restatement
    db.execute("DELETE FROM daily_prices WHERE symbol = 'AAA'")
    rows = db.execute("""SELECT op, old_close, new_close FROM price_change_log
                         WHERE table_name = 'daily_prices' ORDER BY id""").fetchall()
    assert rows == [("LOG_START", None, None), ("INSERT", None, 10.5), ("UPDATE", 10.5, 10.7), ("DELETE", 10.7, None)]


# ---------------------------------------------------------------- recorder

def _results(c, run_id):
    return {s: r for s, r in c.execute("SELECT symbol, result FROM score_history WHERE run_id = %s", (run_id,))}


def test_scoring_is_unchanged_and_unrecorded_without_0010(mock_db, cfg):
    run_a, res_a = run_scoring(mock_db, AS_OF, cfg)
    assert not R.tables_installed(mock_db)
    _install(mock_db)
    run_b, res_b = run_scoring(mock_db, AS_OF, cfg)
    assert res_a == res_b                                      # identical engine output
    rows_b = _results(mock_db, run_b)
    assert rows_b == {s["symbol"]: s for s in res_a["stocks"]}  # identical stored rows
    assert [r[0] for r in mock_db.execute("SELECT run_id FROM recommendation_runs")] == [run_b]


def test_rerunning_a_day_keeps_both_records(mock_db, cfg):
    _install(mock_db)
    run1, res1 = run_scoring(mock_db, AS_OF, cfg)
    run2, _ = run_scoring(mock_db, AS_OF, cfg)
    assert not _results(mock_db, run1)            # score_history kept only the latest run (existing behaviour)
    for run_id in (run1, run2):
        n = mock_db.execute("SELECT count(*) FROM recommendation_scores WHERE run_id = %s", (run_id,)).fetchone()[0]
        assert n == len(res1["stocks"])
    recorded = {s: r for s, r in mock_db.execute(
        "SELECT symbol, result FROM recommendation_scores WHERE run_id = %s", (run1,))}
    assert recorded == {s["symbol"]: s for s in res1["stocks"]}
    kind, failures, h1, h2 = mock_db.execute("""
        SELECT a.record_kind, a.qualification_failures, a.input_hash, b.input_hash
        FROM recommendation_runs a JOIN recommendation_runs b ON b.run_id = %s WHERE a.run_id = %s""",
                                             (run2, run1)).fetchone()
    assert kind == "REPLAY" and "MOCK_DATA" in failures and "SCORED_AFTER_NEXT_OPEN" in failures
    assert h1 == h2


def test_recording_failure_never_fails_scoring(mock_db, cfg, monkeypatch, caplog):
    _install(mock_db)

    def boom(*a, **k):
        raise RuntimeError("simulated recorder bug")
    monkeypatch.setattr(R, "record_run", boom)
    with caplog.at_level(logging.ERROR):
        run_id, result = run_scoring(mock_db, AS_OF, cfg)
    assert mock_db.execute("SELECT status FROM scoring_runs WHERE id = %s", (run_id,)).fetchone()[0] == "SUCCEEDED"
    assert len(_results(mock_db, run_id)) == len(result["stocks"])
    assert mock_db.execute("SELECT count(*) FROM recommendation_runs").fetchone()[0] == 0
    assert "simulated recorder bug" in caplog.text
    summary = S.track_record(mock_db, 20, kind="REPLAY")
    assert summary["succeeded_runs_without_record"] == 1


def _qualify(**over):
    kw = dict(as_of="2026-10-09", provenance="EOD", nifty_last="2026-10-09",
              inputs_loaded_at=R.at_ist("2026-10-09", R.SETTLED), scored_at=R.at_ist("2026-10-09", R.SETTLED),
              entry_session="2026-10-12", code=CLEAN)
    kw.update(over)
    return R.qualify(**kw)


@pytest.mark.parametrize("over,kind,failure", [
    ({}, "LIVE", None),
    ({"provenance": "MOCK"}, "DEVELOPMENT", "MOCK_DATA"),
    ({"code": R.CodeInfo("0" * 40, True)}, "DEVELOPMENT", "UNCOMMITTED_CODE"),
    ({"code": R.CodeInfo(None, None)}, "DEVELOPMENT", "NO_GIT_COMMIT"),
    ({"inputs_loaded_at": R.at_ist("2026-10-09", R.CLOSE)}, "DEVELOPMENT", "INPUTS_BEFORE_SETTLEMENT"),
    ({"nifty_last": "2026-10-08"}, "DEVELOPMENT", "NIFTY_NOT_UPDATED"),
    ({"entry_session": None}, "DEVELOPMENT", "CALENDAR_UNKNOWN"),
    ({"scored_at": R.at_ist("2026-10-12", R.OPEN)}, "REPLAY", "SCORED_AFTER_NEXT_OPEN"),
])
def test_qualification(over, kind, failure):
    k, failures = _qualify(**over)
    assert k == kind and (failures == [] if failure is None else failure in failures)


def test_unknown_calendar_still_detects_retrospective_runs():
    """A run outside the holiday calendar is never LIVE; scored long after as_of it is a REPLAY."""
    late = _qualify(as_of="2025-09-01", nifty_last="2025-09-01", entry_session=None,
                    inputs_loaded_at=R.at_ist("2026-10-12", R.SETTLED), scored_at=R.at_ist("2026-10-12", R.SETTLED))
    assert late[0] == "REPLAY" and {"CALENDAR_UNKNOWN", "SCORED_AFTER_NEXT_OPEN"} <= set(late[1])
    timely = _qualify(as_of="2026-12-31", nifty_last="2026-12-31", entry_session=None,
                      inputs_loaded_at=R.at_ist("2026-12-31", R.SETTLED), scored_at=R.at_ist("2026-12-31", R.SETTLED))
    assert timely == ("DEVELOPMENT", ["CALENDAR_UNKNOWN"])


def test_next_session_uses_the_holiday_calendar():
    assert R.next_session("2026-10-09") == "2026-10-12"        # Friday -> Monday
    assert R.next_session("2026-12-31") is None                # 2027 holidays not in the calendar file


def test_live_record_end_to_end(mock_db, cfg):
    """A clean, timely, real-data run is stored as LIVE and passes every database check."""
    from dhandrishti.scoring import score_universe
    _install(mock_db)
    market = load_market(mock_db, AS_OF)
    result = {**score_universe(market, cfg), "data_provenance": "EOD"}     # as a Kite run would carry
    mock_db.execute("INSERT INTO scoring_config_versions VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (cfg["version"], Jsonb(cfg), R.config_sha256(cfg)))
    run_id = mock_db.execute("""INSERT INTO scoring_runs (as_of, config_version, provenance, status)
                                VALUES (%s, %s, 'EOD', 'SUCCEEDED') RETURNING id""", (AS_OF, cfg["version"])).fetchone()[0]
    evening = R.at_ist(AS_OF, R.SETTLED)
    kind = R.record_run(mock_db, run_id, market, result, cfg, evening, 300, code=CLEAN,
                        scored_at=evening + timedelta(minutes=5))
    row = mock_db.execute("""SELECT record_kind, qualification_failures, entry_session::text, code_dirty
                             FROM recommendation_runs WHERE run_id = %s""", (run_id,)).fetchone()
    assert kind == "LIVE" and row == ("LIVE", [], "2026-10-06", False)
    recommended = mock_db.execute("""SELECT count(*) FROM recommendation_scores
                                     WHERE run_id = %s AND selection = 'RECOMMENDED'""", (run_id,)).fetchone()[0]
    assert 0 < recommended <= 5
    assert S.track_record(mock_db, 20)["runs_recorded"] == 1


def test_input_hash_is_deterministic_and_names_what_changed(mock_db):
    a = M.build_manifest(load_market(mock_db, AS_OF), 300)
    b = M.build_manifest(load_market(mock_db, AS_OF), 300)
    assert M.input_hash(a) == M.input_hash(b)
    sym = sorted(a["stocks"])[3]
    mock_db.execute("UPDATE daily_prices SET close = close * 1.01 WHERE symbol = %s AND trade_date = %s",
                    (sym, AS_OF))
    c = M.build_manifest(load_market(mock_db, AS_OF), 300)
    assert M.input_hash(c) != M.input_hash(a)
    assert M.diff(a, c) == {"bars": [sym]}


def test_prices_after_as_of_change_nothing(mock_db, cfg):
    before = M.build_manifest(load_market(mock_db, AS_OF), 300)
    sym = sorted(before["stocks"])[0]
    mock_db.execute("""INSERT INTO daily_prices (symbol, trade_date, open, high, low, close, volume, provenance, source)
                       VALUES (%s, '2026-10-06', 1, 1, 1, 1, 1, 'MOCK', 't')""", (sym,))
    after = M.build_manifest(load_market(mock_db, AS_OF), 300)
    assert M.input_hash(before) == M.input_hash(after)


def test_recorder_refuses_inputs_dated_after_as_of(mock_db, cfg):
    _install(mock_db)
    market = load_market(mock_db, AS_OF)
    s = market.stocks[0]
    b = s.bars
    s.bars = Bars(b.dates + ["2026-10-06"], *[np.append(getattr(b, f), getattr(b, f)[-1])
                                              for f in ("open", "high", "low", "close", "volume")])
    with pytest.raises(RuntimeError, match="look-ahead"):
        R.record_run(mock_db, 1, market, {"data_provenance": "MOCK"}, cfg, datetime.now(R.IST), 300, code=CLEAN)


def test_policy_selection():
    pol = P.POLICY_V1
    def stock(rank, risk="LOW", conf="LOW"):
        return {"rank": rank, "risk_level": risk, "confidence": conf, "technicals": {"bars": 300}}
    assert P.select(stock(1), pol) == (True, [], "RECOMMENDED")
    assert P.select(stock(2, "HIGH"), pol) == (False, ["RISK_HIGH_ABOVE_MEDIUM"], "EXCLUDED_CANDIDATE")
    assert P.select(stock(6), pol) == (True, [], "NOT_CANDIDATE")       # never promoted to fill a gap
    assert P.select(stock(9, "VERY_HIGH"), pol) == (False, ["RISK_VERY_HIGH_ABOVE_MEDIUM"], "NOT_CANDIDATE")
    strict = {**pol, "version": "x", "min_confidence": "MEDIUM", "min_history_bars": 400}
    assert P.select(stock(1), strict)[1] == ["CONFIDENCE_LOW_BELOW_MEDIUM", "HISTORY_BELOW_400_BARS"]


def test_every_scored_stock_is_recorded_with_eligibility(mock_db, cfg):
    _install(mock_db)
    run_id, result = run_scoring(mock_db, AS_OF, cfg)
    rows = mock_db.execute("""SELECT rank, risk_level, eligible, exclusion_reasons, selection
                              FROM recommendation_scores WHERE run_id = %s ORDER BY rank""", (run_id,)).fetchall()
    assert len(rows) == len(result["stocks"])
    for rank, risk, eligible, reasons, selection in rows:
        assert eligible == (risk in ("LOW", "MEDIUM")) and eligible == (not reasons)
        assert selection == ("NOT_CANDIDATE" if rank > 5 else "RECOMMENDED" if eligible else "EXCLUDED_CANDIDATE")


def test_policy_version_cannot_change_silently(db):
    P.register(db)
    with pytest.raises(RuntimeError, match="bump"):
        P.register(db, {**P.POLICY_V1, "top_n": 10})


# ---------------------------------------------------------------- outcomes (hand-built prices)

def _sessions(n: int, start="2026-01-05") -> list[str]:
    out, d = [], datetime.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.date().isoformat())
        d += timedelta(days=1)
    return out


def _bars(c, table, key, rows):
    col = "symbol" if table == "daily_prices" else "index_code"
    with c.cursor() as cur:
        cur.executemany(f"""INSERT INTO {table} ({col}, trade_date, open, high, low, close, volume, provenance, source)
                            VALUES (%s, %s, %s, %s, %s, %s, 100, 'EOD', 't')""",
                        [(key, d, o, h, lo, cl) for d, o, h, lo, cl in rows])


def _market(c, n=30, symbols=("AAA",), nifty_open=None):
    """n sessions; every stock flat at 100 unless overridden later; NIFTY flat at 1000."""
    cal = _sessions(n)
    _security(c, *symbols)
    _bars(c, "index_prices", "NIFTY 50", [(d, (nifty_open or {}).get(d, 1000.0), 1000, 1000, 1000) for d in cal])
    return cal


def _flat(cal, price=100.0, skip=(), overrides=None):
    rows = []
    for d in cal:
        if d in skip:
            continue
        o = (overrides or {}).get(d, (price, price, price, price))
        rows.append((d, *o))
    return rows


def _run_for(c, as_of, symbols):
    run_id = _run_row(c, as_of=as_of)
    for i, s in enumerate(symbols, 1):
        _score_row(c, run_id, s, i)
    return run_id


def test_outcome_matches_hand_calculation(db):
    cal = _market(db, 30, ("AAA", "BBB"))
    e, x = 1, 21                                   # as_of = cal[0]; entry cal[1]; exit cal[21]
    _bars(db, "daily_prices", "AAA", _flat(cal, overrides={cal[e]: (100, 101, 99, 100), cal[10]: (95, 96, 90, 94),
                                                           cal[x]: (110, 111, 109, 110)}))
    _bars(db, "daily_prices", "BBB", _flat(cal))
    db.execute("UPDATE index_prices SET open = 1050 WHERE trade_date = %s", (cal[x],))
    run_id = _run_for(db, cal[0], ["AAA", "BBB"])
    ev = O.evaluate(db, run_id, 20)
    a = next(r for r in ev.rows if r["symbol"] == "AAA")
    assert (a["status"], a["entry_date"], a["exit_date"], a["sessions_held"]) == ("COMPLETE", cal[e], cal[x], 20)
    assert a["gross_return"] == pytest.approx(0.10)
    s = 3 / 1e4
    buy = delivery_charges("BUY", 20000).total
    proceeds = 20000 / (100 * (1 + s)) * 110 * (1 - s)
    sell = delivery_charges("SELL", proceeds).total
    assert a["net_return"] == pytest.approx((proceeds - sell) / (20000 + buy) - 1)
    assert a["charges_inr"] == pytest.approx(buy + sell)
    assert a["nifty_return"] == pytest.approx(0.05)
    assert a["excess_vs_nifty"] == pytest.approx(a["net_return"] - 0.05)
    assert a["max_adverse_excursion"] == pytest.approx(-0.10) and a["mae_reliable"]
    b = next(r for r in ev.rows if r["symbol"] == "BBB")
    universe = (a["net_return"] + b["net_return"]) / 2
    assert a["universe_return"] == pytest.approx(universe)
    assert a["excess_vs_universe"] == pytest.approx(a["net_return"] - universe)
    assert a["net_return_no_slippage"] > a["net_return"] > a["slippage_sensitivity"]["10"] > \
        a["slippage_sensitivity"]["25"]


def test_outcome_is_pending_until_the_grace_sessions_exist(db):
    cal = _market(db, 24)                          # needs entry 1 + 20 + 3 grace = index 24
    _bars(db, "daily_prices", "AAA", _flat(cal))
    run_id = _run_for(db, cal[0], ["AAA"])
    assert O.evaluate(db, run_id, 20) is None
    rep = O.update(db, horizons=(20,))
    assert (rep.pending, rep.rows) == (1, 0)
    assert db.execute("SELECT count(*) FROM recommendation_outcomes").fetchone()[0] == 0
    _bars(db, "index_prices", "NIFTY 50", [(d, 1000, 1000, 1000, 1000) for d in _sessions(26)[24:]])
    assert O.evaluate(db, run_id, 20) is not None


def test_invalid_outcomes_are_labelled_not_filled(db):
    cal = _market(db, 30, ("NOENTRY", "NOEXIT", "JUMP", "LATE"))
    _bars(db, "daily_prices", "NOENTRY", _flat(cal, skip=cal[1:5]))
    _bars(db, "daily_prices", "NOEXIT", _flat(cal, skip=cal[21:25]))
    _bars(db, "daily_prices", "JUMP", _flat(cal, overrides={d: (50, 50, 50, 50) for d in cal[12:]}))
    _bars(db, "daily_prices", "LATE", _flat(cal, skip=[cal[1]]))
    run_id = _run_for(db, cal[0], ["NOENTRY", "NOEXIT", "JUMP", "LATE"])
    rows = {r["symbol"]: r for r in O.evaluate(db, run_id, 20).rows}
    assert rows["NOENTRY"]["status"] == "NO_ENTRY_PRICE" and rows["NOENTRY"]["net_return"] is None
    assert rows["NOEXIT"]["status"] == "NO_EXIT_PRICE" and rows["NOEXIT"]["net_return"] is None
    assert "last bar" in rows["NOEXIT"]["detail"]
    assert rows["JUMP"]["status"] == "SUSPECT_PRICE_JUMP" and rows["JUMP"]["mae_reliable"] is False
    late = rows["LATE"]
    assert late["status"] == "COMPLETE" and late["entry_date"] == cal[2] and late["sessions_held"] == 19
    assert "entry 1 session(s) late" in late["detail"]
    complete = [r["net_return"] for r in rows.values() if r["status"] == "COMPLETE"]
    assert late["universe_return"] == pytest.approx(sum(complete) / len(complete))   # invalid rows excluded


def test_missing_benchmark_is_labelled(db):
    cal = _sessions(30)
    _market(db, 30, nifty_open={cal[21]: 0.0})
    _bars(db, "daily_prices", "AAA", _flat(cal))
    run_id = _run_for(db, cal[0], ["AAA"])
    row = O.evaluate(db, run_id, 20).rows[0]
    assert row["status"] == "BENCHMARK_MISSING" and row["nifty_return"] is None and row["net_return"] is not None


def test_outcomes_are_idempotent_and_revisions_append(db):
    cal = _market(db, 30)
    _bars(db, "daily_prices", "AAA", _flat(cal))
    run_id = _run_for(db, cal[0], ["AAA"])
    first = O.update(db, horizons=(20,))
    again = O.update(db, horizons=(20,))
    assert (first.evaluated, first.rows, again.unchanged, again.rows) == (1, 1, 1, 0)
    db.execute("UPDATE daily_prices SET open = 120 WHERE symbol = 'AAA' AND trade_date = %s", (cal[21],))
    revised = O.update(db, horizons=(20,))
    assert (revised.revised, revised.rows) == (1, 1)
    old, new = db.execute("SELECT gross_return FROM recommendation_outcomes ORDER BY id").fetchall()
    assert old[0] == pytest.approx(0.0) and new[0] == pytest.approx(0.2)
    assert db.execute("SELECT gross_return FROM recommendation_outcome_latest").fetchone()[0] == pytest.approx(0.2)


def test_outcome_method_cannot_change_silently(db):
    O.register(db)
    with pytest.raises(RuntimeError, match="bump"):
        O.register(db, {**O.METHOD_V1, "notional_inr": 50000.0})


def test_outcome_charges_are_the_paper_trading_charges():
    """With no slippage, the outcome pays exactly delivery_charges on each side, the function paper trading uses."""
    net, charges = O.net_return(200.0, 220.0, 20000.0, 0.0)
    buy, sell = delivery_charges("BUY", 20000.0).total, delivery_charges("SELL", 22000.0).total
    assert charges == pytest.approx(buy + sell)
    assert net == pytest.approx((22000.0 - sell) / (20000.0 + buy) - 1)


# ---------------------------------------------------------------- summary

def test_summary_counts_only_non_overlapping_live_runs(db):
    cal = _market(db, 80)
    _bars(db, "daily_prices", "AAA", _flat(cal))
    dev = [_run_for(db, cal[i], ["AAA"]) for i in (0, 5, 25)]
    O.update(db, horizons=(20,))
    live = S.track_record(db, 20)
    assert live["runs_recorded"] == 0 and live["evidence"] == "INSUFFICIENT_EVIDENCE" and live["official"]
    d = S.track_record(db, 20, kind="DEVELOPMENT")
    assert not d["official"] and d["runs_matured"] == len(dev)
    assert d["non_overlapping_periods"] == 2                     # runs 0 and 25; run 5 overlaps run 0
    assert d["evidence"] == "INSUFFICIENT_EVIDENCE"
    assert d["recommended_status"] == {"COMPLETE": 3}
    assert "INSUFFICIENT_EVIDENCE" in S.format_report(d) and "NOT the official" in S.format_report(d)


def test_summary_reports_excluded_candidates(db):
    cal = _market(db, 30, ("AAA", "RISKY"))
    _bars(db, "daily_prices", "AAA", _flat(cal))
    _bars(db, "daily_prices", "RISKY", _flat(cal))
    run_id = _run_row(db, as_of=cal[0])
    _score_row(db, run_id, "RISKY", 1, risk="HIGH", reasons=("RISK_HIGH_ABOVE_MEDIUM",))
    _score_row(db, run_id, "AAA", 2)
    O.update(db, horizons=(20,))
    d = S.track_record(db, 20, kind="DEVELOPMENT")
    assert d["excluded_candidates"] == {"RISK_HIGH_ABOVE_MEDIUM": 1} and d["excluded_status"] == {"COMPLETE": 1}


# ---------------------------------------------------------------- verification

def _recorded_run(c, cfg) -> int:
    _install(c)
    run_id, _ = run_scoring(c, AS_OF, cfg)
    return run_id


def test_verify_reproduces_from_current_inputs(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert (v.status, v.inputs_source) == ("REPRODUCED", "CURRENT")
    assert mock_db.execute("SELECT status FROM run_verifications WHERE run_id = %s", (run_id,)).fetchone()[0] == \
        "REPRODUCED"


def test_verify_reconstructs_restated_prices(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    sym = mock_db.execute("SELECT symbol FROM recommendation_scores WHERE run_id = %s ORDER BY symbol LIMIT 1",
                          (run_id,)).fetchone()[0]
    mock_db.execute("UPDATE daily_prices SET close = close * 0.5, open = open * 0.5 WHERE symbol = %s "
                    "AND trade_date <= '2026-09-01'", (sym,))          # e.g. a split adjusted by the source
    mock_db.execute("DELETE FROM daily_prices WHERE symbol = %s AND trade_date = '2026-09-15'", (sym,))
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert (v.status, v.inputs_source) == ("REPRODUCED", "RECONSTRUCTED"), v.detail


def test_verify_reports_unlogged_input_changes(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    sym = mock_db.execute("SELECT symbol FROM recommendation_scores WHERE run_id = %s LIMIT 1", (run_id,)).fetchone()[0]
    mock_db.execute("UPDATE securities SET sector = 'Renamed' WHERE symbol = %s", (sym,))
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert v.status == "INPUTS_CHANGED" and v.detail["still_different_after_reconstruction"]["security"] == [sym]


def test_verify_detects_code_changes(mock_db, cfg, monkeypatch):
    run_id = _recorded_run(mock_db, cfg)
    real = V.score_universe

    def changed(market, c):
        out = real(market, c)
        out["stocks"][0] = {**out["stocks"][0], "total_score": out["stocks"][0]["total_score"] + 1}
        return out
    monkeypatch.setattr(V, "score_universe", changed)
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert (v.status, v.inputs_source, v.detail["n_different"]) == ("CODE_CHANGED", "CURRENT", 1)


def test_verify_never_claims_reproduction_after_a_truncate(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    rows = mock_db.execute("SELECT * FROM daily_prices").fetchall()
    mock_db.execute("TRUNCATE daily_prices")
    with mock_db.cursor() as cur:
        cur.executemany(f"INSERT INTO daily_prices VALUES ({', '.join(['%s'] * len(rows[0]))})",
                        [(*r[:5], r[5] * 1.01, *r[6:]) for r in rows])
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert v.status == "INSUFFICIENT_INPUT_HISTORY" and "truncated" in v.detail["reason"]


def test_verify_backfilled_and_broken_records(mock_db, cfg):
    run_id, _ = run_scoring(mock_db, AS_OF, cfg)    # before 0010: only score_history knows this run
    _install(mock_db)
    assert R.backfill_from_score_history(mock_db) == [run_id]
    assert R.backfill_from_score_history(mock_db) == []                     # idempotent
    kind, failures, manifest = mock_db.execute("""SELECT record_kind, qualification_failures, input_manifest
                                                  FROM recommendation_runs WHERE run_id = %s""", (run_id,)).fetchone()
    assert (kind, failures, manifest) == ("BACKFILLED", ["BACKFILLED"], None)
    assert V.verify_run(mock_db, run_id, code=CLEAN).status == "INSUFFICIENT_INPUT_HISTORY"
    assert S.track_record(mock_db, 20)["runs_recorded"] == 0                # never in the LIVE record
    broken = _run_row(mock_db, as_of=AS_OF)                                 # config hash that matches nothing
    assert V.verify_run(mock_db, broken, code=CLEAN).status == "VERIFICATION_FAILED"
    statuses = [r[0] for r in mock_db.execute("SELECT status FROM run_verifications ORDER BY id")]
    assert statuses == ["INSUFFICIENT_INPUT_HISTORY", "VERIFICATION_FAILED"]


def test_verify_requires_autocommit(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    mock_db.autocommit = False
    assert V.verify_run(mock_db, run_id, store=False).status == "VERIFICATION_FAILED"
    mock_db.rollback()
    mock_db.autocommit = True


# ---------------------------------------------------------------- isolation

def test_decisions_never_read_tracking_data():
    """Scoring, paper trading, backtests and research must not read outcomes or tracking records."""
    files = [WORKER_SRC / "scoring.py", WORKER_SRC / "db" / "market_repository.py", WORKER_SRC / "jobs" / "paper.py",
             *(WORKER_SRC / "trading").glob("*.py"), *(WORKER_SRC / "backtesting").glob("*.py"),
             *(WORKER_SRC / "research").glob("*.py")]
    pattern = re.compile(r"recommendation_|outcome_methods|price_change_log|run_verifications|\.tracking\b")
    offenders = [str(f) for f in files if pattern.search(f.read_text(encoding="utf-8"))]
    assert offenders == []


# ---------------------------------------------------------------- hardening: failure visibility and retry

def test_recorder_failure_is_stored_diagnosed_and_retried_once(mock_db, cfg, monkeypatch):
    _install(mock_db)
    real = R.record_run
    monkeypatch.setattr(R, "record_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    run_id, _ = run_scoring(mock_db, AS_OF, cfg)
    monkeypatch.setattr(R, "record_run", real)
    stage, etype, diagnostic = mock_db.execute(
        "SELECT stage, error_type, diagnostic FROM tracking_failures WHERE run_id = %s", (run_id,)).fetchone()
    assert (stage, etype) == ("RECORD", "RuntimeError") and f"jobs.tracking record {run_id}" in diagnostic
    st = S.operational_status(mock_db)
    assert not st["healthy"] and [m["run_id"] for m in st["missing_records_since_install"]] == [run_id]
    assert [f["run_id"] for f in st["unresolved_failures"]] == [run_id]
    assert "MISSING: run" in S.format_status(st) and "ATTENTION NEEDED" in S.format_status(st)

    kind = R.retry_record(mock_db, run_id, code=CLEAN)
    failures = mock_db.execute("SELECT qualification_failures FROM recommendation_runs WHERE run_id = %s",
                               (run_id,)).fetchone()[0]
    assert kind in ("DEVELOPMENT", "REPLAY") and "RECORDED_BY_RETRY" in failures
    assert R.retry_record(mock_db, run_id, code=CLEAN) == "ALREADY_RECORDED"
    assert mock_db.execute("SELECT count(*) FROM recommendation_runs WHERE run_id = %s", (run_id,)).fetchone()[0] == 1
    st = S.operational_status(mock_db)
    assert st["healthy"] and st["recorder_failures"] == 1 and not st["unresolved_failures"]   # kept, resolved


def test_a_retried_record_is_never_live(mock_db, cfg):
    """Even a clean, timely, real-data run cannot become LIVE once it carries RECORDED_BY_RETRY."""
    from dhandrishti.scoring import score_universe
    _install(mock_db)
    market = load_market(mock_db, AS_OF)
    result = {**score_universe(market, cfg), "data_provenance": "EOD"}
    mock_db.execute("INSERT INTO scoring_config_versions VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (cfg["version"], Jsonb(cfg), R.config_sha256(cfg)))
    run_id = mock_db.execute("""INSERT INTO scoring_runs (as_of, config_version, provenance, status)
                                VALUES (%s, %s, 'EOD', 'SUCCEEDED') RETURNING id""", (AS_OF, cfg["version"])).fetchone()[0]
    evening = R.at_ist(AS_OF, R.SETTLED)
    kind = R.record_run(mock_db, run_id, market, result, cfg, evening, 300, code=CLEAN,
                        scored_at=evening + timedelta(minutes=5), extra_failures=("RECORDED_BY_RETRY",))
    assert kind == "DEVELOPMENT"
    assert S.track_record(mock_db, 20)["runs_recorded"] == 0
    with pytest.raises(R.AlreadyRecorded):   # no duplicate record, whatever the caller does
        R.record_run(mock_db, run_id, market, result, cfg, evening, 300, code=CLEAN)


def test_retry_refuses_when_the_original_output_cannot_be_confirmed(mock_db, cfg):
    overwritten, _ = run_scoring(mock_db, AS_OF, cfg)        # before tracking existed
    survivor, result = run_scoring(mock_db, AS_OF, cfg)      # overwrites the first run's score_history rows
    _install(mock_db)
    with pytest.raises(R.RetryRefused, match="no longer holds"):
        R.retry_record(mock_db, overwritten, code=CLEAN)
    sym = result["stocks"][0]["symbol"]
    mock_db.execute("UPDATE daily_prices SET close = close * 1.05 WHERE symbol = %s AND trade_date = %s", (sym, AS_OF))
    with pytest.raises(R.RetryRefused, match="does not reproduce"):
        R.retry_record(mock_db, survivor, code=CLEAN)
    assert mock_db.execute("SELECT count(*) FROM recommendation_runs").fetchone()[0] == 0
    stages = mock_db.execute("SELECT run_id, stage FROM tracking_failures ORDER BY id").fetchall()
    assert stages == [(overwritten, "RETRY"), (survivor, "RETRY")]
    st = S.operational_status(mock_db)    # runs from before installation are listed separately, not as missing
    assert not st["missing_records_since_install"]
    assert {m["run_id"] for m in st["unrecorded_runs_before_install"]} == {overwritten, survivor}


def test_a_run_without_record_or_failure_row_is_still_detected(mock_db, cfg, monkeypatch):
    """E.g. the process died between scoring and recording: no failure row, but status still flags it."""
    from dhandrishti.jobs import run_scoring as job
    _install(mock_db)
    monkeypatch.setattr(job, "record_if_installed", lambda *a, **k: None)
    run_id, _ = run_scoring(mock_db, AS_OF, cfg)
    st = S.operational_status(mock_db)
    assert not st["healthy"] and st["missing_records_since_install"][0]["failures"] == 0
    assert f"retry with `jobs.tracking record {run_id}`" in S.format_status(st)
    assert S.track_record(mock_db, 20)["missing_records_since_install"] == 1


def test_status_command_exit_codes(mock_db, cfg, monkeypatch):
    from dhandrishti.jobs import tracking as cli
    monkeypatch.setenv("DD_DATABASE_URL", make_conninfo(ADMIN_URL, dbname=mock_db.info.dbname))
    assert cli.main(["status"]) == 2                       # 0010 not installed
    _install(mock_db)
    run_scoring(mock_db, AS_OF, cfg)
    assert cli.main(["status"]) == 0
    from dhandrishti.jobs import run_scoring as job
    monkeypatch.setattr(job, "record_if_installed", lambda *a, **k: None)
    run_scoring(mock_db, AS_OF, cfg)
    assert cli.main(["status"]) == 1


# ---------------------------------------------------------------- hardening: reproducibility

@pytest.mark.parametrize("change,category", [
    ("UPDATE fundamentals SET roe = coalesce(roe, 0) + 1 WHERE symbol = %(s)s", "fundamentals"),
    ("""INSERT INTO corporate_events (symbol, event_date, event_type, title, provenance, source)
        VALUES (%(s)s, '2026-10-20', 'OTHER', 'test event', 'MOCK', 't')""", "events"),
    ("UPDATE securities SET active = false WHERE symbol = %(s)s", "stocks_missing_now"),
])
def test_unlogged_input_changes_are_never_reported_as_reproduced(mock_db, cfg, change, category):
    run_id = _recorded_run(mock_db, cfg)
    sym = mock_db.execute("""SELECT f.symbol FROM recommendation_scores s JOIN fundamentals f USING (symbol)
                             WHERE s.run_id = %s ORDER BY f.symbol LIMIT 1""", (run_id,)).fetchone()[0]
    mock_db.execute(change, {"s": sym})
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert v.status == "INPUTS_CHANGED"
    assert sym in v.detail["still_different_after_reconstruction"][category]


def test_price_changes_outside_the_log_are_never_reported_as_reproduced(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    sym = mock_db.execute("SELECT symbol FROM recommendation_scores WHERE run_id = %s ORDER BY symbol LIMIT 1",
                          (run_id,)).fetchone()[0]
    mock_db.execute("ALTER TABLE daily_prices DISABLE TRIGGER daily_prices_log_update")
    mock_db.execute("UPDATE daily_prices SET close = close * 1.1 WHERE symbol = %s AND trade_date = %s", (sym, AS_OF))
    mock_db.execute("ALTER TABLE daily_prices ENABLE TRIGGER daily_prices_log_update")
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert v.status == "INSUFFICIENT_INPUT_HISTORY" and v.detail["still_different_after_reconstruction"]["bars"] == [sym]


def test_dropped_chunks_are_never_reported_as_reproduced(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    manifest = mock_db.execute("SELECT input_manifest FROM recommendation_runs WHERE run_id = %s", (run_id,)).fetchone()[0]
    first = min(v["bars"]["first"] for v in manifest["stocks"].values())
    end = mock_db.execute("""SELECT range_end FROM timescaledb_information.chunks WHERE hypertable_name = 'daily_prices'
                             AND range_start <= %s::date AND range_end > %s::date""", (first, first)).fetchone()[0]
    assert end.date().isoformat() <= AS_OF       # the chunk holding the earliest inputs ends before as_of
    dropped = mock_db.execute("SELECT count(*) FROM drop_chunks('daily_prices', older_than => %s::date)",
                              (end.date(),)).fetchone()[0]
    assert dropped > 0
    v = V.verify_run(mock_db, run_id, code=CLEAN)
    assert v.status == "INSUFFICIENT_INPUT_HISTORY"


def test_scoring_does_not_mutate_its_inputs(mock_db, cfg):
    """The recorder hashes the inputs after scoring; that is only valid if scoring leaves them untouched."""
    from dhandrishti.scoring import score_universe
    market = load_market(mock_db, AS_OF)
    before = M.input_hash(M.build_manifest(market, 300))
    score_universe(market, cfg)
    assert M.input_hash(M.build_manifest(market, 300)) == before


# ---------------------------------------------------------------- hardening: migration

def test_truncate_cascade_cannot_bypass_append_only(mock_db, cfg):
    run_id = _recorded_run(mock_db, cfg)
    for stmt in ("TRUNCATE scoring_runs CASCADE", "TRUNCATE securities CASCADE",
                 "TRUNCATE scoring_config_versions CASCADE"):
        with pytest.raises(psycopg.errors.RestrictViolation):
            mock_db.execute(stmt)
    assert mock_db.execute("SELECT count(*) FROM recommendation_scores WHERE run_id = %s", (run_id,)).fetchone()[0] > 0


def test_price_log_triggers_fire_on_existing_and_new_hypertable_chunks(mock_db):
    _install(mock_db)
    chunks = mock_db.execute("SELECT count(*) FROM show_chunks('daily_prices')").fetchone()[0]
    sym = mock_db.execute("SELECT min(symbol) FROM securities").fetchone()[0]
    mock_db.execute("UPDATE daily_prices SET close = close + 1 WHERE symbol = %s AND trade_date = %s", (sym, AS_OF))
    mock_db.execute("""INSERT INTO daily_prices (symbol, trade_date, open, high, low, close, volume, provenance, source)
                       VALUES (%s, '2031-06-02', 1, 1, 1, 1, 1, 'MOCK', 't')""", (sym,))
    mock_db.execute("""INSERT INTO index_prices (index_code, trade_date, open, high, low, close, volume, provenance, source)
                       VALUES ('NIFTY 50', '2031-06-02', 1, 1, 1, 1, 0, 'MOCK', 't')""")
    assert mock_db.execute("SELECT count(*) FROM show_chunks('daily_prices')").fetchone()[0] == chunks + 1
    logged = mock_db.execute("""SELECT table_name, op, trade_date::text FROM price_change_log
                                WHERE op IN ('UPDATE', 'INSERT') ORDER BY id""").fetchall()
    assert logged == [("daily_prices", "UPDATE", AS_OF), ("daily_prices", "INSERT", "2031-06-02"),
                      ("index_prices", "INSERT", "2031-06-02")]


def _catalog(c) -> dict:
    q = {
        "tables": "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1",
        "views": "SELECT viewname FROM pg_views WHERE schemaname = 'public' ORDER BY 1",
        "functions": """SELECT proname, md5(prosrc) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE nspname = 'public' AND proname LIKE 'dd\\_%' ORDER BY 1""",
        "triggers": """SELECT tgname, tgrelid::regclass::text FROM pg_trigger WHERE NOT tgisinternal
                       AND tgname NOT LIKE 'ts\\_%' ORDER BY 1, 2""",
        "constraints": """SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint
                          WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2""",
        "indexes": "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1",
        "migrations": "SELECT filename, sha256 FROM schema_migrations ORDER BY 1",
    }
    return {k: c.execute(v).fetchall() for k, v in q.items()}


def _contents(c, tables) -> dict:
    return {t: c.execute(f'SELECT md5(coalesce(string_agg(x, \'|\' ORDER BY x), \'\')) FROM '
                         f'(SELECT t::text AS x FROM "{t}" t) s').fetchone()[0] for t in tables}


def test_rollback_restores_the_pre_0010_schema_and_keeps_data(mock_db, cfg):
    from dhandrishti.paths import REPO_ROOT
    before = _catalog(mock_db)
    _install(mock_db)
    run_scoring(mock_db, AS_OF, cfg)
    O.update(mock_db)
    existing = [t for t, in before["tables"] if t != "schema_migrations"]   # migrations compared via the catalog
    mid = _contents(mock_db, existing)
    mock_db.execute((REPO_ROOT / "packages" / "database" / "rollback" /
                     "0010_recommendation_tracking.rollback.sql").read_text(encoding="utf-8"))
    after = _catalog(mock_db)
    assert after == before                                   # tables, triggers (incl. chunks), constraints, ...
    assert _contents(mock_db, existing) == mid                # no existing row touched by the rollback
    assert apply_staged(mock_db, only=ONLY_0010) == ONLY_0010  # and 0010 can be applied again


def test_0009_and_0010_apply_in_either_order():
    for order in (["0009_fundamental_quality.sql", "0010_recommendation_tracking.sql"],
                  ["0010_recommendation_tracking.sql", "0009_fundamental_quality.sql"]):
        name, url = _create()
        try:
            with psycopg.connect(url, autocommit=True) as c:
                for f in order:
                    assert apply_staged(c, only=[f]) == [f]
                assert c.execute("SELECT to_regclass('fundamental_filings') IS NOT NULL AND "
                                 "to_regclass('recommendation_runs') IS NOT NULL").fetchone()[0]
        finally:
            _drop(name)


# ---------------------------------------------------------------- hardening: reporting and safety

def test_reports_label_hypothetical_returns_and_never_read_paper_or_backtests(db):
    d = S.track_record(db, 20)
    assert d["return_basis"] == "HYPOTHETICAL_RECOMMENDATION"
    text = S.format_report(d)
    assert text.startswith("HYPOTHETICAL RECOMMENDATION RETURNS") and "NOT paper-portfolio results" in text \
        and "NOT backtests" in text
    for f in (WORKER_SRC / "tracking").glob("*.py"):
        assert not re.search(r"\b(paper_|backtest_)\w+", f.read_text(encoding="utf-8")), f


def test_no_order_execution_code():
    """Nothing in the worker can place, modify or cancel an order (Kite or otherwise)."""
    pattern = re.compile(r"/orders|place_order|modify_order|cancel_order|order_type|transaction_type")
    offenders = [str(f) for f in WORKER_SRC.rglob("*.py") if pattern.search(f.read_text(encoding="utf-8"))]
    assert offenders == []
