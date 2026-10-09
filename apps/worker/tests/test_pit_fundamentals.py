"""Point-in-time fundamentals store. Values here are synthetic test figures, not company data.

Pure tests (availability rules, CSV validation) always run; store tests need DD_TEST_DATABASE_URL.
"""

import os
import time
import uuid
from datetime import date, datetime

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.migrate import migrate
from dhandrishti.pit import canonical_csv, quality, store
from dhandrishti.pit.availability import ALL_BASES, IST, available_at, decision_time
from dhandrishti.pit.metrics import METRICS, SCORE_INPUTS

SRC = "test-source"
HEADER = "symbol,metric,value,basis,period_type,period_start,period_end,filing_type,reported_at,value_vintage\n"


def obs(value=100.0, metric="net_profit", period_end=date(2025, 3, 31), period_start=date(2024, 4, 1), ptype="FY",
        reported="2025-05-15 16:30", basis="EXCHANGE_TIMESTAMP", vintage="AS_REPORTED", source=SRC, symbol="AAA",
        filing="ANNUAL_RESULT", consolidated=True):
    rep = datetime.fromisoformat(reported).replace(tzinfo=IST) if reported else None
    return store.Observation(
        symbol=symbol, metric=metric, value=value, unit=METRICS[metric].unit,
        basis="CONSOLIDATED" if consolidated else "STANDALONE", period_type=ptype,
        period_start=None if ptype == "INSTANT" else period_start, period_end=period_end, filing_type=filing,
        reported_at=rep, available_at=available_at(basis, rep, period_end, ptype, filing),
        availability_basis=basis, value_vintage=vintage, source=source)


# ---------------------------------------------------------------- availability rules (pure)

def test_decision_is_taken_at_the_close():
    assert decision_time("2025-05-15") == datetime(2025, 5, 15, 15, 30, tzinfo=IST)


def test_availability_rules_are_conservative():
    end = date(2025, 3, 31)
    ts = datetime(2025, 5, 15, 16, 30, tzinfo=IST)
    assert available_at("EXCHANGE_TIMESTAMP", ts, end, "FY", "ANNUAL_RESULT") == ts
    assert available_at("REPORTED_DATE", datetime(2025, 5, 15, tzinfo=IST), end, "FY", "ANNUAL_RESULT") \
        == datetime(2025, 5, 16, tzinfo=IST)  # date only: never usable on the day itself
    assert available_at("STATUTORY_DEADLINE", None, end, "FY", "ANNUAL_RESULT") == datetime(2025, 5, 31, tzinfo=IST)
    assert available_at("STATUTORY_DEADLINE", None, date(2024, 12, 31), "Q", "QUARTERLY_RESULT") \
        == datetime(2025, 2, 15, tzinfo=IST)  # 45 days + 1
    assert available_at("STATUTORY_DEADLINE", None, date(2024, 12, 31), "INSTANT", "SHAREHOLDING_PATTERN") \
        == datetime(2025, 1, 22, tzinfo=IST)  # 21 days + 1
    assert available_at("UNKNOWN", None, end, "FY", "ANNUAL_REPORT") is None
    with pytest.raises(ValueError):
        available_at("EXCHANGE_TIMESTAMP", None, end, "FY", "ANNUAL_RESULT")


def test_every_score_input_maps_to_catalogue_metrics():
    assert {m for need in SCORE_INPUTS.values() for m in need} <= set(METRICS)


# ---------------------------------------------------------------- canonical CSV (pure)

def write(tmp_path, body, header=HEADER):
    p = tmp_path / "obs.csv"
    p.write_text(header + body)
    return p


def test_csv_infers_availability_and_skips_blank_values(tmp_path):
    p = write(tmp_path,
              "AAA,revenue,1000,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15 16:30:05,AS_REPORTED\n"
              "AAA,net_profit,,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15 16:30:05,AS_REPORTED\n"
              "AAA,eps_diluted,2.5,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED\n"
              "AAA,promoter_holding_pct,55,CONSOLIDATED,INSTANT,,2025-03-31,SHAREHOLDING_PATTERN,,AS_CURRENTLY_DISPLAYED\n")
    rows = canonical_csv.parse(p, SRC, {"AAA"})
    assert [o.metric for o in rows] == ["revenue", "eps_diluted", "promoter_holding_pct"]  # blank value = absent
    assert [o.availability_basis for o in rows] == ["EXCHANGE_TIMESTAMP", "REPORTED_DATE", "STATUTORY_DEADLINE"]
    assert rows[0].available_at == datetime(2025, 5, 15, 16, 30, 5, tzinfo=IST)


@pytest.mark.parametrize("line, message", [
    ("AAA,ebitda_margin,1,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED", "unknown metric"),
    ("ZZZ,revenue,1,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED", "unknown symbol"),
    ("AAA,total_equity,1,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED", "cannot have period_type"),
    ("AAA,promoter_holding_pct,140,CONSOLIDATED,INSTANT,,2025-03-31,SHAREHOLDING_PATTERN,2025-04-15,AS_REPORTED", "outside 0-100"),
    ("AAA,revenue,1,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-03-20,AS_REPORTED", "before period_end"),
    ("AAA,revenue,1,CONSOLIDATED,Q,2024-10-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED", "Q period of 182 days"),
    ("AAA,revenue,1,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,GUESSED", "value_vintage"),
])
def test_csv_rejects_bad_rows_with_row_numbers(tmp_path, line, message):
    with pytest.raises(canonical_csv.CanonicalImportError, match=message) as e:
        canonical_csv.parse(write(tmp_path, line + "\n"), SRC, {"AAA"})
    assert "row 2" in str(e.value)


def test_exchange_timestamp_needs_a_time(tmp_path):
    header = HEADER.strip() + ",availability_basis\n"
    line = "AAA,revenue,1,CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED,EXCHANGE_TIMESTAMP\n"
    with pytest.raises(canonical_csv.CanonicalImportError, match="needs a broadcast time"):
        canonical_csv.parse(write(tmp_path, line, header), SRC, {"AAA"})


def test_duplicate_rows_in_one_file(tmp_path):
    line = "AAA,revenue,{v},CONSOLIDATED,Q,2025-01-01,2025-03-31,QUARTERLY_RESULT,2025-05-15,AS_REPORTED\n"
    assert len(canonical_csv.parse(write(tmp_path, line.format(v=1) * 2), SRC, {"AAA"})) == 1  # exact repeat
    with pytest.raises(canonical_csv.CanonicalImportError, match="conflicts with row 2"):
        canonical_csv.parse(write(tmp_path, line.format(v=1) + line.format(v=2)), SRC, {"AAA"})


# ---------------------------------------------------------------- store (database)

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
db_only = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")


@pytest.fixture()
def conn():
    name = f"dd_pit_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        with psycopg.connect(make_conninfo(ADMIN_URL, dbname=name), autocommit=True) as c:
            migrate(c)
            for s in ("AAA", "BBB"):
                c.execute("""INSERT INTO securities (symbol, name, sector, provenance, source)
                             VALUES (%s, %s, 'Test', 'EOD', 'test')""", (s, s))
            yield c
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def visible(conn, day, **kw):
    return {(o.metric, str(o.period_end)): o.value for o in store.as_of(conn, "AAA", decision_time(day), **kw)}


@db_only
def test_fy2025_results_are_invisible_before_publication(conn):
    """The brief's scenario: FY2025 (to 2025-03-31) published 2025-05-15."""
    store.append(conn, [obs(reported="2025-05-15 16:30")], SRC)
    assert visible(conn, "2025-04-15") == {}
    assert visible(conn, "2025-05-15") == {}  # broadcast at 16:30, after the 15:30 decision
    assert visible(conn, "2025-05-16") == {("net_profit", "2025-03-31"): 100.0}
    assert visible(conn, "2025-05-20") == {("net_profit", "2025-03-31"): 100.0}


@db_only
def test_date_only_publication_is_usable_the_next_day(conn):
    store.append(conn, [obs(reported="2025-05-15 00:00", basis="REPORTED_DATE")], SRC)
    assert visible(conn, "2025-05-15") == {}
    assert visible(conn, "2025-05-16") == {("net_profit", "2025-03-31"): 100.0}


@db_only
def test_estimated_and_unknown_dates_are_excluded_by_default(conn):
    store.append(conn, [obs(reported=None, basis="STATUTORY_DEADLINE"),
                        obs(metric="revenue", reported=None, basis="UNKNOWN", filing="ANNUAL_REPORT")], SRC)
    assert visible(conn, "2026-01-01") == {}
    assert visible(conn, "2025-05-30", bases=ALL_BASES) == {}
    assert visible(conn, "2025-06-02", bases=ALL_BASES) == {("net_profit", "2025-03-31"): 100.0}  # deadline 05-30
    # UNKNOWN never appears, whatever the options
    assert ("revenue", "2025-03-31") not in visible(conn, "2030-01-01", bases=ALL_BASES)


@db_only
def test_currently_displayed_values_are_excluded_by_default(conn):
    store.append(conn, [obs(vintage="AS_CURRENTLY_DISPLAYED")], SRC)
    assert visible(conn, "2025-06-01") == {}
    assert visible(conn, "2025-06-01", vintages=("AS_REPORTED", "AS_CURRENTLY_DISPLAYED"))


@db_only
def test_append_only_is_enforced_by_the_database(conn):
    store.append(conn, [obs()], SRC)
    for sql in ("UPDATE fundamental_observations SET value = 1", "DELETE FROM fundamental_observations",
                "TRUNCATE fundamental_observations CASCADE"):
        with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
            conn.execute(sql)
    assert conn.execute("SELECT count(*), min(value) FROM fundamental_observations").fetchone() == (1, 100.0)


@db_only
def test_reimport_is_idempotent_and_changes_create_versions(conn):
    r1 = store.append(conn, [obs(100.0)], SRC)
    r2 = store.append(conn, [obs(100.0)], SRC)
    assert (r1.inserted, r2.inserted, r2.duplicates) == (1, 0, 1)
    r3 = store.append(conn, [obs(101.0)], SRC)  # same publication, value fixed: a correction
    assert (r3.versioned, r3.restatements) == (1, 0)
    v = store.versions(conn, "AAA", "net_profit", "2025-03-31")
    assert [(o.value, o.data_version, o.is_restatement) for o in v] == [(100.0, 1, False), (101.0, 2, False)]
    assert v[1].supersedes_id == v[0].id
    assert visible(conn, "2025-05-20") == {("net_profit", "2025-03-31"): 101.0}


@db_only
def test_restatement_is_visible_only_after_it_was_published(conn):
    store.append(conn, [obs(100.0, reported="2025-05-15 16:30")], SRC)
    store.append(conn, [obs(90.0, reported="2026-05-14 17:00")], SRC)  # restated in next year's results
    v = store.versions(conn, "AAA", "net_profit", "2025-03-31")
    assert [(o.value, o.is_restatement) for o in v] == [(100.0, False), (90.0, True)]
    assert visible(conn, "2025-12-31") == {("net_profit", "2025-03-31"): 100.0}
    assert visible(conn, "2026-05-15") == {("net_profit", "2025-03-31"): 90.0}


@db_only
def test_restatement_stored_before_the_original_still_resolves_by_publication_date(conn):
    store.append(conn, [obs(90.0, reported="2026-05-14 17:00")], SRC)  # captured first
    store.append(conn, [obs(100.0, reported="2025-05-15 16:30")], SRC)  # original captured later
    assert visible(conn, "2025-12-31") == {("net_profit", "2025-03-31"): 100.0}
    assert visible(conn, "2026-06-01") == {("net_profit", "2025-03-31"): 90.0}


@db_only
def test_known_by_reconstructs_what_dhandrishti_had_stored(conn):
    store.append(conn, [obs(100.0)], SRC)
    time.sleep(0.01)
    between = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    time.sleep(0.01)
    store.append(conn, [obs(101.0)], SRC)
    decision = decision_time("2025-06-02")
    assert [o.value for o in store.as_of(conn, "AAA", decision, known_by=between)] == [100.0]
    assert [o.value for o in store.as_of(conn, "AAA", decision)] == [101.0]


@db_only
def test_sources_and_bases_are_kept_apart_and_reported_as_conflicts(conn):
    store.append(conn, [obs(100.0), obs(100.0, consolidated=False)], SRC)
    store.append(conn, [obs(104.0, source="other")], "other")
    seen = store.as_of(conn, "AAA", decision_time("2025-06-02"))
    assert sorted((o.source, o.basis, o.value) for o in seen) == [
        ("other", "CONSOLIDATED", 104.0), (SRC, "CONSOLIDATED", 100.0), (SRC, "STANDALONE", 100.0)]
    a = quality.analyse(conn, ["AAA"])
    assert len(a["conflicts"]) == 1 and "other 104" in a["conflicts"][0]


@db_only
def test_historical_reconstruction_quarter_by_quarter(conn):
    quarters = [("2024-06-30", "2024-04-01", "2024-07-20 15:45"), ("2024-09-30", "2024-07-01", "2024-10-18 14:00"),
                ("2024-12-31", "2024-10-01", "2025-01-17 16:10"), ("2025-03-31", "2025-01-01", "2025-04-17 16:00")]
    store.append(conn, [obs(10.0 * (i + 1), metric="revenue", ptype="Q", period_end=date.fromisoformat(e),
                            period_start=date.fromisoformat(s), reported=r, filing="QUARTERLY_RESULT")
                        for i, (e, s, r) in enumerate(quarters)], SRC)
    known = lambda d: sorted(k[1] for k in visible(conn, d))  # noqa: E731
    assert known("2024-07-19") == []
    assert known("2024-10-18") == ["2024-06-30", "2024-09-30"]  # 14:00 broadcast, before the close
    assert known("2025-01-17") == ["2024-06-30", "2024-09-30"]  # 16:10 broadcast, after the close
    assert known("2025-04-21") == ["2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]


@db_only
def test_quality_checks_quarter_sums_and_reconstruction(conn):
    qs = [("2024-06-30", "2024-04-01"), ("2024-09-30", "2024-07-01"), ("2024-12-31", "2024-10-01"), ("2025-03-31", "2025-01-01")]
    rows = [obs(25.0, metric="revenue", ptype="Q", period_end=date.fromisoformat(e), period_start=date.fromisoformat(s),
                reported="2025-05-15 16:30", filing="QUARTERLY_RESULT") for e, s in qs]
    rows.append(obs(120.0, metric="revenue"))  # FY 120 vs quarters 100: mismatch
    store.append(conn, rows, SRC)
    a = quality.analyse(conn, ["AAA", "BBB"])
    assert len(a["sum_mismatches"]) == 1 and "quarters sum 100.0 vs FY 120.0" in a["sum_mismatches"][0]
    assert a["stocks"]["AAA"]["quarters_revenue"] == 4 and a["stocks"]["BBB"]["rows"] == 0
    assert a["stocks"]["AAA"]["inputs"]["revenue_growth"] == "partial"  # 4 quarters, needs 8
    assert a["stocks"]["AAA"]["inputs"]["roe"] == "no"
    assert "| AAA |" in quality.markdown(a)
