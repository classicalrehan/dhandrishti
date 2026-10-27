"""Phase 1 data-quality controls (staged migration 0009). Throwaway test databases only.

Synthetic tests always run (with DD_TEST_DATABASE_URL); tests marked `pilot` also use the real NSE pilot files
in data/pilot/ (not committed) and skip when they are absent.
"""

import hashlib
import os
import shutil
import uuid
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.migrate import migrate
from dhandrishti.db.staged import ProtectedDatabaseError, apply_staged
from dhandrishti.paths import MIGRATIONS_DIR, STAGED_MIGRATIONS_DIR
from dhandrishti.pit import backfill, controls, store
from dhandrishti.pit.adapters import nse_results_listing as L
from dhandrishti.pit.adapters import nse_shp as S
from dhandrishti.pit.adapters import nse_shp_listing as SL
from dhandrishti.pit.adapters import nse_xbrl as X
from dhandrishti.pit.availability import IST, decision_time
from test_nse_xbrl import bank_filing, bank_xbrl, filing, xbrl

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
db_only = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")
PILOT = Path(__file__).resolve().parents[3] / "data" / "pilot"
pilot = pytest.mark.skipif(not (PILOT / "batch1-xbrl").exists() or not ADMIN_URL, reason="pilot files not available")
NEW_TABLES = ("fundamental_filings", "fundamental_value_provenance", "fundamental_quality_flags",
              "fundamental_flag_dispositions", "fundamental_verifications")
IMPORTED_2026_10_09 = {  # the 17 results files of the production import on 2026-10-09
    "BANKING_101078_1023175_16012024051131.xml",
    "BANKING_101079_1023183_16012024051248.xml",
    "BANKING_117524_1359008_23012025122553.xml",
    "BANKING_117525_1359016_23012025122721.xml",
    "INDAS_117292_1348213_16012025074012.xml",
    "INDAS_117294_1348219_16012025074210.xml",
    "INTEGRATED_FILING_BANKING_1421434_21042025050837_WEB.xml",
    "INTEGRATED_FILING_BANKING_1603567_17012026092616_WEB.xml",
    "INTEGRATED_FILING_BANKING_1603568_17012026092624_WEB.xml",
    "INTEGRATED_FILING_BANKING_1696123_18072026040126_WEB.xml",
    "INTEGRATED_FILING_BANKING_1696125_18072026040136_WEB.xml",
    "INTEGRATED_FILING_INDAS_1417992_17042025113033_WEB.xml",
    "INTEGRATED_FILING_INDAS_1417999_17042025113633_WEB.xml",
    "INTEGRATED_FILING_INDAS_1601189_14012026083824_WEB.xml",
    "INTEGRATED_FILING_INDAS_1601190_14012026083832_WEB.xml",
    "INTEGRATED_FILING_INDAS_1658040_23042026090154_WEB.xml",
    "INTEGRATED_FILING_INDAS_1658041_23042026090203_WEB.xml",
}
HELD_BACK = {"INTEGRATED_FILING_BANKING_1420333_19042025104215_WEB.xml", "INTEGRATED_FILING_BANKING_1553886_18102025082322_WEB.xml",
             "INTEGRATED_FILING_BANKING_1654389_18042026072836_WEB.xml", "INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml"}


def _new_db(prefix: str) -> tuple[str, str]:
    name = f"dd_{prefix}_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    return name, make_conninfo(ADMIN_URL, dbname=name)


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _securities(c):
    for s in ("TESTCO", "INFY", "HDFCBANK"):
        c.execute("INSERT INTO securities (symbol, name, sector, provenance, source) VALUES (%s, %s, 'Test', 'EOD', 'test') "
                  "ON CONFLICT DO NOTHING", (s, s))


@pytest.fixture()
def conn():
    name, url = _new_db("qc")
    try:
        with psycopg.connect(url, autocommit=True) as c:
            apply_staged(c, only=["0009_fundamental_quality.sql"])
            _securities(c)
            yield c
    finally:
        _drop(name)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _import_xbrl(c, path: Path, f: L.ResultFiling) -> controls.ImportOutcome:
    pf = X.parse(path, f)
    rec = controls.FilingRecord(X.SOURCE, path.name, _sha(path), f.symbol, f.basis, f.period_end, pf.taxonomy,
                                f.disseminated_at)
    return controls.import_filing(c, rec, pf.observations, pf.provenance, controls.flags_from_checks(pf.checks, pf.notes))


def _usable(c, symbol, day, **kw):
    return {(o.metric, o.period_type, o.basis, o.source): o.value
            for o in controls.as_of_usable(c, symbol, decision_time(day), **kw)}


# ---------------------------------------------------------------- migration and safeguards

def test_staged_migration_is_outside_the_normal_migration_path():
    assert not list(MIGRATIONS_DIR.glob("0009*")), "0009 must not be in migrations/ during Phase 1"
    assert (STAGED_MIGRATIONS_DIR / "0009_fundamental_quality.sql").exists()


def test_apply_staged_refuses_research_databases():
    class Fake:
        class info:
            dbname = "dhandrishti_kite"
    with pytest.raises(ProtectedDatabaseError):
        apply_staged(Fake())
    Fake.info.dbname = "dhandrishti"
    with pytest.raises(ProtectedDatabaseError):
        apply_staged(Fake())
    Fake.info.dbname = "some_other_db"
    with pytest.raises(ProtectedDatabaseError):
        apply_staged(Fake())


@db_only
def test_existing_observation_guard_is_untouched_by_the_staged_migration():
    name, url = _new_db("qcg")
    try:
        with psycopg.connect(url, autocommit=True) as c:
            migrate(c)
            before = c.execute("SELECT md5(prosrc) FROM pg_proc WHERE proname = 'dd_reject_observation_change'").fetchone()
            trig_before = c.execute("""SELECT array_agg(tgname ORDER BY tgname) FROM pg_trigger
                                       WHERE tgrelid = 'fundamental_observations'::regclass AND NOT tgisinternal""").fetchone()
            apply_staged(c, only=["0009_fundamental_quality.sql"])
            after = c.execute("SELECT md5(prosrc) FROM pg_proc WHERE proname = 'dd_reject_observation_change'").fetchone()
            trig_after = c.execute("""SELECT array_agg(tgname ORDER BY tgname) FROM pg_trigger
                                      WHERE tgrelid = 'fundamental_observations'::regclass AND NOT tgisinternal""").fetchone()
            assert before == after and trig_before == trig_after
            assert set(trig_after[0]) == {"fundamental_observations_no_update", "fundamental_observations_no_truncate"}
    finally:
        _drop(name)


@db_only
def test_new_tables_are_append_only(conn, tmp_path):
    out = _import_xbrl(conn, bank_xbrl(tmp_path, exceptional=-5.0), bank_filing())
    obs_id = conn.execute("SELECT id FROM fundamental_observations LIMIT 1").fetchone()[0]
    flag_id = conn.execute("SELECT id FROM fundamental_quality_flags LIMIT 1").fetchone()[0]
    controls.record_disposition(conn, flag_id, "EXPLAINED", "test", "user")
    controls.record_verification(conn, obs_id, "doc", "table", 1.0, "test")
    assert out.outcome == "IMPORTED"
    for t in NEW_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] > 0
        for sql in (f"UPDATE {t} SET {'id' if t != 'fundamental_value_provenance' else 'observation_id'} = "
                    f"{'id' if t != 'fundamental_value_provenance' else 'observation_id'}", f"DELETE FROM {t}",
                    f"TRUNCATE {t} CASCADE"):
            with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
                conn.execute(sql)


# ---------------------------------------------------------------- provenance

@db_only
@pytest.mark.parametrize("how, concepts, derivation, note", [
    ("REPORTED", ["a:X"], "x * 2", None),          # reported values have no formula
    ("REPORTED", ["a:X", "a:Y"], None, None),       # one concept only
    ("SUMMED", ["a:X"], "sum: X", None),            # a sum needs two or more
    ("INFERRED", ["a:Flag"], "0 if false", None),   # inference must be explained
])
def test_provenance_constraints(conn, tmp_path, how, concepts, derivation, note):
    _import_xbrl(conn, bank_xbrl(tmp_path), bank_filing())
    fresh = store.Observation(symbol="TESTCO", metric="revenue", value=1.0, unit="INR_CR", basis="STANDALONE",
                              period_type="Q", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                              filing_type="QUARTERLY_RESULT", reported_at=datetime(2026, 4, 23, 21, tzinfo=IST),
                              available_at=datetime(2026, 4, 23, 21, tzinfo=IST), availability_basis="EXCHANGE_TIMESTAMP",
                              value_vintage="AS_REPORTED", source="x")
    store.append(conn, [fresh], "x")
    obs_id = store.current_version(conn, fresh.key()).id
    with pytest.raises(psycopg.errors.CheckViolation):
        controls.write_provenance(conn, obs_id, None, controls.Provenance(how, concepts, [], derivation, note))


@db_only
def test_every_imported_value_gets_one_provenance_row_of_the_right_kind(conn, tmp_path):
    out = _import_xbrl(conn, bank_xbrl(tmp_path), bank_filing())
    rows = dict(conn.execute("""SELECT o.metric, p.how_obtained FROM fundamental_observations o
                                JOIN fundamental_value_provenance p ON p.observation_id = o.id""").fetchall())
    assert out.observations == len(rows) == conn.execute("SELECT count(*) FROM fundamental_observations").fetchone()[0]
    assert rows["revenue"] == "REPORTED" and rows["net_profit"] == "REPORTED"
    assert rows["total_equity"] == "SUMMED" and rows["cash_and_equivalents"] == "SUMMED"
    assert rows["shares_outstanding"] == "CALCULATED"
    note = conn.execute("""SELECT p.mapping_note, p.source_concepts FROM fundamental_observations o
                           JOIN fundamental_value_provenance p ON p.observation_id = o.id WHERE o.metric = 'revenue'""").fetchone()
    assert "total income" in note[0] and note[1] == ["in-capmkt:Income"]


def test_shareholding_pledge_is_inferred_and_holdings_reported(tmp_path):
    from test_nse_shp import shp
    sf = S.parse(shp(tmp_path))
    kinds = {o.metric: p.how_obtained for o, p in sf.observations_with_provenance(datetime(2026, 4, 16, 16, 50, tzinfo=IST), "x")}
    assert kinds == {"promoter_holding_pct": "REPORTED", "fii_holding_pct": "REPORTED", "dii_holding_pct": "REPORTED",
                     "promoter_pledged_pct": "INFERRED"}


def test_every_reader_check_is_mapped_to_a_code():
    with pytest.raises(controls.UnmappedCheckError):
        controls.flags_from_checks([("a check nobody mapped", "WARN", "x")])
    assert controls.flags_from_checks([("PAT = PBT - tax", "PASS", "")]) == []


# ---------------------------------------------------------------- BLOCK, REVIEW, NOTE

@db_only
def test_block_refuses_the_whole_filing_but_records_it(conn, tmp_path):
    p = xbrl(tmp_path)
    p.write_text(p.read_text().replace(">10500000000<", ">10600000000<"))  # Income no longer = revenue + other income
    out = _import_xbrl(conn, p, filing())
    assert out.outcome == "REFUSED"
    assert conn.execute("SELECT count(*) FROM fundamental_observations").fetchone()[0] == 0
    row = conn.execute("SELECT outcome, import_batch_id FROM fundamental_filings").fetchone()
    assert row == ("REFUSED", None)
    # income no longer equals revenue + other income, and profit no longer equals income - expenses: 2 identities
    assert conn.execute("SELECT count(*) FROM fundamental_quality_flags WHERE severity = 'BLOCK' AND check_code = 'ID-1'").fetchone()[0] == 2


@db_only
def test_review_hides_only_the_named_values(conn, tmp_path):
    """Minority interest tagged as an exceptional item (HDFC Bank pattern): PBT and owners' profit/EPS are
    hidden, every other value of the same filing stays usable."""
    out = _import_xbrl(conn, bank_xbrl(tmp_path, exceptional=-5.0), bank_filing())
    assert out.outcome == "IMPORTED"
    assert sorted(set(out.hidden)) == [("eps_basic", "Q"), ("eps_diluted", "Q"), ("net_profit", "Q"), ("profit_before_tax", "Q")]
    usable = _usable(conn, "TESTCO", "2026-04-24")
    assert ("revenue", "Q", "CONSOLIDATED", X.SOURCE) in usable and ("total_equity", "INSTANT", "CONSOLIDATED", X.SOURCE) in usable
    for m in ("profit_before_tax", "net_profit", "eps_basic"):
        assert (m, "Q", "CONSOLIDATED", X.SOURCE) not in usable
    stored = {o.metric for o in store.as_of(conn, "TESTCO", decision_time("2026-04-24"))}
    assert {"profit_before_tax", "net_profit"} <= stored  # hidden from research, never deleted


@db_only
def test_note_hides_nothing(conn, tmp_path):
    p = xbrl(tmp_path)  # contains a nine-month context -> 'skipped period' NOTE
    out = _import_xbrl(conn, p, filing())
    notes = conn.execute("SELECT check_code FROM fundamental_quality_flags WHERE severity = 'NOTE'").fetchall()
    assert ("YT-1",) in notes and out.hidden == []
    assert len(_usable(conn, "TESTCO", "2026-04-24")) == out.observations


@db_only
def test_cash_cross_check_hides_only_the_cash_value(conn, tmp_path):
    """HDFC Bank standalone 31-Mar-2026 pattern: balance-sheet cash and cash-flow cash disagree."""
    import re
    p = bank_xbrl(tmp_path)
    p.write_text(re.sub(r'(CashAndCashEquivalentsCashFlowStatement contextRef="OneI" unitRef="INR" decimals="-7">)\d+',
                        r"\g<1>1900000000", p.read_text()))
    out = _import_xbrl(conn, p, bank_filing())
    sev = dict(conn.execute("SELECT check_code, severity FROM fundamental_quality_flags").fetchall())
    assert out.outcome == "IMPORTED" and sev == {"RC-2": "REVIEW"}
    assert out.hidden == [("cash_and_equivalents", "INSTANT")]
    assert len(_usable(conn, "TESTCO", "2026-04-24")) == out.observations - 1


@db_only
def test_review_on_a_value_that_is_not_stored_becomes_a_filing_note(conn, tmp_path):
    p = bank_xbrl(tmp_path)
    pf = X.parse(p, bank_filing())
    rec = controls.FilingRecord(X.SOURCE, p.name, _sha(p), "TESTCO", "CONSOLIDATED", date(2026, 3, 31), "BANKING", None)
    flag = controls.Flag("MI-9", "REVIEW", "doubt about depreciation", (("depreciation", "Q"),))  # banks report none
    out = controls.import_filing(conn, rec, pf.observations, pf.provenance, [flag])
    row = conn.execute("SELECT severity, observation_id, message FROM fundamental_quality_flags").fetchone()
    assert out.hidden == [] and row[0] == "NOTE" and row[1] is None and "not stored" in row[2]


# ---------------------------------------------------------------- dispositions and official values

@db_only
def test_superseded_value_is_replaced_by_the_official_figure(conn, tmp_path):
    _import_xbrl(conn, bank_xbrl(tmp_path, exceptional=-5.0), bank_filing())
    flag = conn.execute("""SELECT f.id FROM fundamental_quality_flags f JOIN fundamental_observations o ON o.id = f.observation_id
                           WHERE o.metric = 'net_profit' AND f.check_code = 'MI-3'""").fetchone()[0]
    xbrl_np = conn.execute("SELECT value FROM fundamental_observations WHERE metric = 'net_profit'").fetchone()[0]
    controls.record_disposition(conn, flag, "SUPERSEDED_BY_OFFICIAL_SOURCE", "minority interest counted twice", "user",
                                "company results document")
    when = datetime(2026, 4, 23, 21, 1, 54, tzinfo=IST)
    official = store.Observation(symbol="TESTCO", metric="net_profit", value=50.0, unit="INR_CR", basis="CONSOLIDATED",
                                 period_type="Q", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                                 filing_type="QUARTERLY_RESULT", reported_at=when, available_at=when,
                                 availability_basis="EXCHANGE_TIMESTAMP", value_vintage="AS_REPORTED",
                                 source="Company results (official)", source_record_id="doc")
    controls.add_official_value(conn, official, "Net profit after minority interest", "company results document")
    usable = _usable(conn, "TESTCO", "2026-04-24", metrics=("net_profit",))
    assert usable == {("net_profit", "Q", "CONSOLIDATED", "Company results (official)"): 50.0}
    assert xbrl_np == 45.0 and conn.execute(
        "SELECT count(*) FROM fundamental_observations WHERE metric = 'net_profit'").fetchone()[0] == 2  # both kept


@db_only
def test_latest_disposition_wins_and_earlier_ones_are_kept(conn, tmp_path):
    _import_xbrl(conn, bank_xbrl(tmp_path, exceptional=-5.0), bank_filing())
    flag = conn.execute("""SELECT f.id FROM fundamental_quality_flags f JOIN fundamental_observations o ON o.id = f.observation_id
                           WHERE o.metric = 'profit_before_tax' AND f.check_code = 'MI-1'""").fetchone()[0]
    others = [r[0] for r in conn.execute("""SELECT f.id FROM fundamental_quality_flags f JOIN fundamental_observations o
                                             ON o.id = f.observation_id WHERE o.metric = 'profit_before_tax' AND f.id <> %s""", (flag,))]
    for fid in [flag] + others:
        controls.record_disposition(conn, fid, "ACCEPTED_AS_FILED", "looked fine", "user")
    assert ("profit_before_tax", "Q", "CONSOLIDATED", X.SOURCE) in _usable(conn, "TESTCO", "2026-04-24")
    controls.record_disposition(conn, flag, "EXCLUDED", "on second look, wrong", "user")
    assert ("profit_before_tax", "Q", "CONSOLIDATED", X.SOURCE) not in _usable(conn, "TESTCO", "2026-04-24")
    assert conn.execute("SELECT count(*) FROM fundamental_flag_dispositions WHERE flag_id = %s", (flag,)).fetchone()[0] == 2


@db_only
def test_verification_status(conn, tmp_path):
    _import_xbrl(conn, bank_xbrl(tmp_path), bank_filing())
    oid = conn.execute("SELECT id FROM fundamental_observations WHERE metric = 'revenue'").fetchone()[0]
    assert controls.record_verification(conn, oid, "doc", "t", 400.0, "test") == "VERIFIED"
    assert controls.record_verification(conn, oid, "doc", "t", 401.0, "test") == "MISMATCH"
    assert controls.record_verification(conn, oid, "doc", "t", None, "test") == "NOT_IN_DOCUMENT"
    assert conn.execute("SELECT verification FROM fundamental_observation_status WHERE id = %s", (oid,)).fetchone()[0] == "NOT_IN_DOCUMENT"


# ---------------------------------------------------------------- timestamps, restatements, history

@db_only
def test_timestamps_restatements_and_provenance_history(conn, tmp_path):
    _import_xbrl(conn, bank_xbrl(tmp_path), bank_filing())
    assert _usable(conn, "TESTCO", "2026-04-23") == {}  # published 21:01, after the 15:30 decision
    v1 = conn.execute("SELECT * FROM fundamental_observations WHERE metric = 'revenue'").fetchone()
    old = store.current_version(conn, ("TESTCO", "revenue", "CONSOLIDATED", "Q", date(2026, 3, 31), X.SOURCE))
    later = datetime(2026, 7, 18, 16, 1, tzinfo=IST)
    restated = replace(old, value=410.0, reported_at=later, available_at=later, id=None, data_version=None,
                       supersedes_id=None, ingested_at=None, import_batch_id=None, is_restatement=False)
    store.append(conn, [restated], X.SOURCE)
    new = store.current_version(conn, old.key())
    controls.write_provenance(conn, new.id, None, controls.Provenance("REPORTED", ["in-capmkt:Income"], [], None,
                                                                       "restated comparative"))
    assert new.is_restatement and new.data_version == 2
    assert _usable(conn, "TESTCO", "2026-05-01", metrics=("revenue",))[("revenue", "Q", "CONSOLIDATED", X.SOURCE)] == 400.0
    assert _usable(conn, "TESTCO", "2026-07-20", metrics=("revenue",))[("revenue", "Q", "CONSOLIDATED", X.SOURCE)] == 410.0
    prov = conn.execute("""SELECT o.data_version, p.mapping_note FROM fundamental_value_provenance p
                           JOIN fundamental_observations o ON o.id = p.observation_id WHERE o.metric = 'revenue'
                           ORDER BY o.data_version""").fetchall()
    assert [r[0] for r in prov] == [1, 2]
    assert conn.execute("SELECT * FROM fundamental_observations WHERE id = %s", (v1[0],)).fetchone() == v1  # untouched


@db_only
def test_reimporting_the_same_file_is_recorded_once(conn, tmp_path):
    p = bank_xbrl(tmp_path)
    assert _import_xbrl(conn, p, bank_filing()).outcome == "IMPORTED"
    assert _import_xbrl(conn, p, bank_filing()).outcome == "ALREADY_RECORDED"
    assert conn.execute("SELECT count(*) FROM fundamental_filings").fetchone()[0] == 1


@db_only
def test_review_flag_must_name_a_value(conn, tmp_path):
    _import_xbrl(conn, bank_xbrl(tmp_path), bank_filing())
    fid = conn.execute("SELECT id FROM fundamental_filings").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("""INSERT INTO fundamental_quality_flags (filing_id, check_code, check_version, severity, message)
                        VALUES (%s, 'X', 1, 'REVIEW', 'filing-level review is not allowed')""", (fid,))


# ---------------------------------------------------------------- real HDFC Bank regressions

def _pilot_index():
    return {f.xbrl_file: f for p in (PILOT / "batch1").glob("*.csv") for f in L.parse(p)}


@pilot
def test_real_hdfc_bank_tagging_errors_hide_only_the_wrong_values(conn):
    idx = _pilot_index()
    d = PILOT / "batch1-xbrl"
    results = {n: _import_xbrl(conn, d / n, idx[n]) for n in HELD_BACK}
    assert all(r.outcome == "IMPORTED" for r in results.values())
    mar25 = _usable(conn, "HDFCBANK", "2025-04-22")
    assert mar25[("revenue", "Q", "CONSOLIDATED", X.SOURCE)] == 120268.76          # unaffected
    for m in ("profit_before_tax", "net_profit", "eps_basic"):                       # owners' profit wrong in XBRL
        assert (m, "Q", "CONSOLIDATED", X.SOURCE) not in mar25
    sep25 = _usable(conn, "HDFCBANK", "2025-10-20")
    assert sep25[("net_profit", "Q", "CONSOLIDATED", X.SOURCE)] == 19610.67        # equals official SEC 6-K value
    assert ("profit_before_tax", "Q", "CONSOLIDATED", X.SOURCE) not in sep25        # official 26,658.89 vs XBRL 25,905.79
    mar26 = _usable(conn, "HDFCBANK", "2026-04-20")
    assert mar26[("net_profit", "Q", "CONSOLIDATED", X.SOURCE)] == 20350.76        # equals official
    assert ("profit_before_tax", "Q", "CONSOLIDATED", X.SOURCE) not in mar26
    assert mar26[("net_profit", "Q", "STANDALONE", X.SOURCE)] == 19221.05          # standalone filing: only cash doubtful
    assert mar26[("profit_before_tax", "Q", "STANDALONE", X.SOURCE)] == 25193.35
    assert ("cash_and_equivalents", "INSTANT", "STANDALONE", X.SOURCE) not in mar26


@pilot
def test_real_clean_filings_raise_no_review(conn):
    idx = _pilot_index()
    for n in sorted(set(idx) & {p.name for p in (PILOT / "batch1-xbrl").glob("*.xml")} - HELD_BACK):
        out = _import_xbrl(conn, PILOT / "batch1-xbrl" / n, idx[n])
        assert out.outcome == "IMPORTED" and out.hidden == [], n


# ---------------------------------------------------------------- backfill of the existing 285 observations

def _legacy_import(c):
    """Recreate the production state: the 32 filings imported on 2026-10-09 by the pre-0009 code path."""
    idx = _pilot_index()
    for p in sorted((PILOT / "batch1-xbrl").glob("*.xml")):
        if p.name not in IMPORTED_2026_10_09:   # held-back files and files received later
            continue
        store.append(c, X.parse(p, idx[p.name]).observations, X.SOURCE, p.name, _sha(p))
    rows = {r.xbrl_file: r for lp in (PILOT / "batch1-shp").glob("CF-Shareholding-Pattern-*.csv") for r in SL.parse(lp)}
    for p in sorted((PILOT / "batch1-shp").glob("SHP_*.xml")):
        store.append(c, S.parse(p).observations(rows[p.name].disseminated_at, p.name), S.SOURCE, p.name, _sha(p))


def _obs_fingerprint(c):
    return c.execute("""SELECT count(*), md5(string_agg(t::text, '|' ORDER BY id)), md5(string_agg(xmin::text, ',' ORDER BY id))
                        FROM fundamental_observations t""").fetchone()


@pilot
def test_backfill_describes_the_285_observations_without_touching_them():
    name, url = _new_db("qcb")
    try:
        with psycopg.connect(url, autocommit=True) as c:
            migrate(c)
            _securities(c)
            _legacy_import(c)
            before = _obs_fingerprint(c)
            assert before[0] == 285
            apply_staged(c, only=["0009_fundamental_quality.sql"])
            roots = [PILOT / "batch1", PILOT / "batch1-xbrl", PILOT / "batch1-shp"]
            dry = backfill.run(c, roots, apply=False)
            assert dry.batches == 32 and c.execute("SELECT count(*) FROM fundamental_filings").fetchone()[0] == 0
            rep = backfill.run(c, roots, apply=True)
            assert (rep.filings_inserted, rep.provenance_inserted) == (32, 285)
            assert backfill.run(c, roots, apply=True).filings_inserted == 0          # idempotent
            assert _obs_fingerprint(c) == before                                       # content and row versions unchanged
            kinds = dict(c.execute("SELECT how_obtained, count(*) FROM fundamental_value_provenance GROUP BY 1").fetchall())
            assert kinds == {"REPORTED": 242, "SUMMED": 11, "CALCULATED": 17, "INFERRED": 15}
            assert c.execute("SELECT count(*) FROM fundamental_quality_flags WHERE severity = 'REVIEW'").fetchone()[0] == 0
            # point-in-time answers are unchanged for clean data (11 real-data checks of 2026-10-09)
            for sym, day in (("INFY", "2025-01-17"), ("INFY", "2025-04-21"), ("HDFCBANK", "2024-01-17"),
                             ("HDFCBANK", "2025-04-22"), ("INFY", "2026-04-17")):
                plain = {(o.metric, o.period_type, o.period_end, o.basis): o.value for o in store.as_of(c, sym, decision_time(day))}
                gated = {(o.metric, o.period_type, o.period_end, o.basis): o.value for o in controls.as_of_usable(c, sym, decision_time(day))}
                assert plain == gated, (sym, day)
    finally:
        _drop(name)


@pilot
def test_backfill_refuses_a_file_that_differs_from_the_imported_one(tmp_path):
    name, url = _new_db("qcb")
    try:
        with psycopg.connect(url, autocommit=True) as c:
            migrate(c)
            _securities(c)
            _legacy_import(c)
            apply_staged(c, only=["0009_fundamental_quality.sql"])
            fake = tmp_path / "batch1-xbrl"
            shutil.copytree(PILOT / "batch1-xbrl", fake)
            victim = fake / sorted(n for n in IMPORTED_2026_10_09 if n.startswith("INDAS_"))[0]   # one that was imported
            victim.write_bytes(victim.read_bytes() + b"\n")
            with pytest.raises(backfill.BackfillError, match="differs from the imported file"):
                backfill.run(c, [PILOT / "batch1", fake, PILOT / "batch1-shp"], apply=True)
            assert c.execute("SELECT count(*) FROM fundamental_filings").fetchone()[0] == 0   # all or nothing
    finally:
        _drop(name)


def test_backfill_refuses_research_databases():
    class Fake:
        class info:
            dbname = "dhandrishti_kite"
    with pytest.raises(backfill.BackfillError, match="protected"):
        backfill.backfill(Fake(), [], apply=False)
