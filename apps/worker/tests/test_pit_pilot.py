"""Fundamentals pilot validation (pit.pilot_validation): reference register, official replacements, coverage,
restatement look-ahead check. Throwaway dd_* databases with staged 0009 only; real pilot files when present."""

import os
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.migrate import migrate
from dhandrishti.db.staged import apply_staged
from dhandrishti.jobs.pit_pilot import DOCUMENTS_CSV, VALUES_CSV
from dhandrishti.pit import controls, pilot_validation as V
from dhandrishti.pit.adapters import nse_xbrl as X
from dhandrishti.pit.availability import IST, decision_time
from test_nse_xbrl import bank_filing, bank_xbrl, filing, xbrl

ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")
db_only = pytest.mark.skipif(not ADMIN_URL, reason="DD_TEST_DATABASE_URL not set")
PILOT = Path(__file__).resolve().parents[3] / "data" / "pilot"
pilot = pytest.mark.skipif(not (PILOT / "batch1-xbrl").exists() or not ADMIN_URL, reason="pilot files not available")
ONLY_0009 = ["0009_fundamental_quality.sql"]


def _new_db() -> tuple[str, str]:
    name = f"dd_pilot_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    return name, make_conninfo(ADMIN_URL, dbname=name)


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture()
def conn():
    name, url = _new_db()
    try:
        with psycopg.connect(url, autocommit=True) as c:
            apply_staged(c, only=ONLY_0009)
            from dhandrishti.pit.pilot import PILOT as COMPANIES
            for s in ("TESTCO", *COMPANIES):
                c.execute("INSERT INTO securities (symbol, name, sector, provenance, source) VALUES (%s, %s, 'Test', "
                          "'EOD', 'test')", (s, s))
            yield c
    finally:
        _drop(name)


def _import(c, path, f):
    pf = X.parse(path, f)
    rec = controls.FilingRecord(X.SOURCE, path.name, V.store.file_sha256(path), f.symbol, f.basis, f.period_end,
                                pf.taxonomy, f.disseminated_at)
    return controls.import_filing(c, rec, pf.observations, pf.provenance, controls.flags_from_checks(pf.checks, pf.notes))


def _register(tmp_path, rows, doc_date="2026-04-24"):
    docs = tmp_path / "docs.csv"
    docs.write_text("document_id,company,title,url,published_on,date_basis,read_method\n"
                    f"T,TESTCO,Test results statement,https://example.invalid/t,{doc_date},DOCUMENT_DATE,test\n")
    vals = tmp_path / "values.csv"
    vals.write_text("symbol,basis,metric,period_type,period_end,official_value,document_id,locator\n"
                    + "".join(",".join(map(str, r)) + "\n" for r in rows))
    return V.load_register(vals, docs)


# ---------------------------------------------------------------- register

def test_the_committed_register_is_well_formed():
    refs = V.load_register(VALUES_CSV, DOCUMENTS_CSV)
    assert len(refs) == 62 and {r.document.document_id for r in refs} == set("ABCDEF")
    assert all(r.locator and r.document.url.startswith("https://www.sec.gov/") for r in refs)


@pytest.mark.parametrize("row,match", [
    ("TESTCO,GROUP,revenue,Q,2026-03-31,1,T,x", "bad basis"),
    ("TESTCO,CONSOLIDATED,revenue,H,2026-03-31,1,T,x", "bad basis or period type"),
    ("TESTCO,CONSOLIDATED,revenue,Q,2026-03-31,1,Z,x", "unknown document"),
    ("TESTCO,CONSOLIDATED,revenue,Q,2026-03-31,1,T, ", "locator required"),
])
def test_malformed_register_rows_are_rejected(tmp_path, row, match):
    docs = tmp_path / "d.csv"
    docs.write_text("document_id,company,title,url,published_on,date_basis,read_method\nT,X,t,u,2026-01-01,DOCUMENT_DATE,m\n")
    vals = tmp_path / "v.csv"
    vals.write_text("symbol,basis,metric,period_type,period_end,official_value,document_id,locator\n" + row + "\n")
    with pytest.raises(V.PilotError, match=match):
        V.load_register(vals, docs)


def test_duplicate_register_rows_are_rejected(tmp_path):
    with pytest.raises(V.PilotError, match="duplicate"):
        _register(tmp_path, [("TESTCO", "CONSOLIDATED", "revenue", "Q", "2026-03-31", 1, "T", "x")] * 2)


# ---------------------------------------------------------------- guards

@pytest.mark.parametrize("name", ["dhandrishti", "dhandrishti_kite", "research"])
def test_refuses_research_databases(name):
    class Fake:
        class info:
            dbname = name
    with pytest.raises(V.PilotError, match="development database"):
        V.require_dev(Fake())


@db_only
def test_refuses_a_database_without_0009():
    name, url = _new_db()
    try:
        with psycopg.connect(url, autocommit=True) as c:
            migrate(c)
            with pytest.raises(V.PilotError, match="0009"):
                V.require_dev(c)
    finally:
        _drop(name)


# ---------------------------------------------------------------- verification and official replacements

@db_only
def test_register_verifies_flags_mismatches_and_dates_official_values_conservatively(conn, tmp_path):
    out = _import(conn, bank_xbrl(tmp_path, exceptional=-5.0), bank_filing())   # HDFC Bank tagging pattern
    assert out.outcome == "IMPORTED" and ("profit_before_tax", "Q") in out.hidden
    refs = _register(tmp_path, [
        ("TESTCO", "CONSOLIDATED", "revenue", "Q", "2026-03-31", 400, "T", "income"),                 # correct
        ("TESTCO", "CONSOLIDATED", "profit_before_tax", "Q", "2026-03-31", 80, "T", "PBT"),           # tagged 75
        ("TESTCO", "CONSOLIDATED", "net_profit", "Q", "2026-03-31", 50, "T", "owners' profit"),       # tagged 45
        ("TESTCO", "CONSOLIDATED", "total_deposits", "INSTANT", "2026-03-31", 3000, "T", "deposits"),  # never stored
    ])
    rep = V.apply_register(conn, refs)
    assert rep.verified == 1 and rep.official_values_added == 2
    assert sorted((m[2], m[5], m[6]) for m in rep.mismatched) == [("net_profit", 45.0, 50.0),
                                                                  ("profit_before_tax", 75.0, 80.0)]
    assert rep.not_stored == [("TESTCO", "CONSOLIDATED", "total_deposits", "INSTANT", "2026-03-31")]

    again = V.apply_register(conn, refs)                                   # idempotent
    assert (again.verified, again.mismatched, again.already_checked, again.official_values_added) == (0, [], 3, 0)

    def usable(day):
        return {(o.metric, o.source): o.value for o in controls.as_of_usable(conn, "TESTCO", decision_time(day))
                if o.period_type == "Q"}
    on_doc_day = usable("2026-04-24")      # document dated 24 Apr: usable from 25 Apr 00:00, never the same day
    assert ("profit_before_tax", V.OFFICIAL_SOURCE) not in on_doc_day
    assert ("profit_before_tax", X.SOURCE) not in on_doc_day             # the wrong tagged value stays hidden
    assert on_doc_day[("revenue", X.SOURCE)] == 400
    later = usable("2026-04-27")
    assert later[("profit_before_tax", V.OFFICIAL_SOURCE)] == 80 and later[("net_profit", V.OFFICIAL_SOURCE)] == 50
    assert ("profit_before_tax", X.SOURCE) not in later
    stored = conn.execute("""SELECT count(*) FROM fundamental_observations WHERE symbol = 'TESTCO'
                             AND metric = 'profit_before_tax' AND source = %s""", (X.SOURCE,)).fetchone()[0]
    assert stored == 1                                                     # the filed value is kept, not replaced


@db_only
def test_coverage_reports_missing_quarters_and_verification_state(conn, tmp_path):
    _import(conn, xbrl(tmp_path), filing())
    V.apply_register(conn, _register(tmp_path, [("TESTCO", "CONSOLIDATED", "revenue", "Q", "2026-03-31", 1000, "T", "r")]))
    cov = V.coverage(conn, ["TESTCO", "INFY"])
    t = cov["TESTCO"]
    assert t["filings"] == {"IMPORTED": 1} and t["verification"]["VERIFIED"] == 1
    assert t["verification"]["UNVERIFIED"] == t["values"] - 1
    assert t["quarters_in_window"] == {"CONSOLIDATED": 1} and "2025-12-31" in t["missing_quarters"]["CONSOLIDATED"]
    assert t["missing_core_metrics"] == {}
    assert cov["INFY"]["status"] == "NO DATA" and cov["INFY"]["values"] == 0
    assert V.quarter_ends("2024-06-30", "2026-03-31")[0] == date(2024, 6, 30) and \
        len(V.quarter_ends("2024-06-30", "2026-03-31")) == 8


@db_only
def test_a_revised_filing_never_leaks_into_earlier_decisions(conn, tmp_path):
    first = filing()
    _import(conn, xbrl(tmp_path), first)
    p2 = xbrl(tmp_path, name="INTEGRATED_FILING_INDAS_9_y_WEB.xml")
    p2.write_text(p2.read_text().replace("10000000000", "11000000000").replace("10500000000", "11500000000")
                  .replace("8500000000", "9500000000"))                    # revenue 1000 -> 1100, still consistent
    revised = replace(first, xbrl_file=p2.name, disseminated_at=first.disseminated_at + timedelta(days=30))
    assert _import(conn, p2, revised).outcome == "IMPORTED"
    check = V.restatement_check(conn)
    assert check["transitions_checked"] >= 1 and check["look_ahead_failures"] == []
    before = {o.metric: o.value for o in controls.as_of_usable(conn, "TESTCO", decision_time("2026-05-22"))}
    after = {o.metric: o.value for o in controls.as_of_usable(conn, "TESTCO", decision_time("2026-05-25"))}
    assert before["revenue"] == 1000 and after["revenue"] == 1100


# ---------------------------------------------------------------- the real pilot files

@pilot
def test_real_pilot_import_and_official_register(conn):
    roots = sorted(p for p in PILOT.iterdir() if p.is_dir())
    n_files = sum(len(list(r.glob("*.xml"))) for r in roots)        # 36 on 12 Oct, more as downloads arrive
    rep = V.import_files(conn, roots)
    assert (len(rep.imported) + len(rep.unreadable), rep.refused, rep.unlisted) == (n_files, [], [])
    assert all("not supported" in u for u in rep.unreadable)            # only formats without a reader yet
    assert set(rep.hidden) >= {"INTEGRATED_FILING_BANKING_1420333_19042025104215_WEB.xml",
                               "INTEGRATED_FILING_BANKING_1553886_18102025082322_WEB.xml",
                               "INTEGRATED_FILING_BANKING_1654389_18042026072836_WEB.xml",
                               "INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml"}
    reg = V.apply_register(conn, V.load_register(VALUES_CSV, DOCUMENTS_CSV))
    assert reg.verified == 58 and reg.not_stored == [] and reg.official_values_added == 4
    assert sorted((m[2], m[4], m[5], m[6]) for m in reg.mismatched) == [
        ("net_profit", "2025-03-31", 18385.19, 18834.88),
        ("profit_before_tax", "2025-03-31", 25123.7, 25573.39),
        ("profit_before_tax", "2025-09-30", 25905.79, 26658.89),
        ("profit_before_tax", "2026-03-31", 26948.17, 27671.63)]
    assert V.restatement_check(conn)["look_ahead_failures"] == []
    assert len(V.import_files(conn, roots).already_recorded) == len(rep.imported)


# ---------------------------------------------------------------- YT-2 and readiness

def _obs(metric, ptype, end, value, unit="INR_CR", start=None):
    e = date.fromisoformat(end)
    t = datetime(e.year, e.month, e.day, 18, 0, tzinfo=IST) + timedelta(days=20)     # published after the period
    if start is None and ptype == "Q":
        start = (date(e.year, e.month - 2, 1) if e.month > 2 else date(e.year - 1, e.month + 10, 1)).isoformat()
    elif start is None and ptype == "FY":
        start = date(e.year - 1, 4, 1).isoformat()
    start = date.fromisoformat(start) if start else None
    return V.store.Observation(symbol="TESTCO", metric=metric, value=value, unit=unit, basis="CONSOLIDATED",
                               period_type=ptype, period_start=start, period_end=e,
                               filing_type="QUARTERLY_RESULT", reported_at=t, available_at=t,
                               availability_basis="EXCHANGE_TIMESTAMP", value_vintage="AS_REPORTED", source=X.SOURCE)


def _store(conn, name, observations):
    rec = controls.FilingRecord(X.SOURCE, name, name * 2, "TESTCO", "CONSOLIDATED", observations[-1].period_end,
                                "INDAS", observations[-1].reported_at)
    prov = [controls.Provenance("REPORTED", [f"in-capmkt:{o.metric}"]) for o in observations]
    return controls.import_filing(conn, rec, observations, prov, [])


QUARTERS = ("2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31")


@db_only
def test_yt2_hides_a_full_year_value_that_its_quarters_do_not_add_up_to(conn):
    _store(conn, "a", [_obs("revenue", "Q", q, 100.0) for q in QUARTERS] + [_obs("revenue", "FY", "2025-03-31", 400.4)]
           + [_obs("net_profit", "Q", q, 10.0) for q in QUARTERS] + [_obs("net_profit", "FY", "2025-03-31", 38.0)])
    added = V.yt2_flags(conn)
    assert added == [("TESTCO", "CONSOLIDATED", "net_profit", "2025-03-31", 38.0, 40.0)]   # revenue within Rs 1 cr
    assert V.yt2_flags(conn) == []                                                      # idempotent
    usable = {(o.metric, o.period_type) for o in controls.as_of_usable(conn, "TESTCO", decision_time("2025-05-02"))}
    assert ("net_profit", "FY") not in usable and ("revenue", "FY") in usable and ("net_profit", "Q") in usable
    r = V.readiness(conn, "TESTCO", "CONSOLIDATED", "2024-06-30", "2025-03-31")["metrics"]["net_profit"]
    assert "FY 2025-03-31: filed full-year value hidden pending review (not used)" in r["refused"]
    assert r["ttm"] == {"2025-03-31": 40.0} and r["fy_check"] == {}


@db_only
def test_yt2_needs_all_four_quarters(conn):
    _store(conn, "b", [_obs("revenue", "Q", q, 100.0) for q in QUARTERS[1:]] + [_obs("revenue", "FY", "2025-03-31", 999.0)])
    assert V.yt2_flags(conn) == []


@db_only
def test_readiness_refuses_what_the_inputs_cannot_support(conn):
    qs = QUARTERS + ("2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31")
    profit = [10, -3, 12, 13, 8, 14, 15, 16]                  # Sep-2024 loss: not a YoY base
    eps = [1.0, -0.3, 1.2, 1.3, 0.8, 0.7, 0.75, 0.8]          # implied shares 10 until Jun-2025, then 20 (bonus 1:1)
    obs = [_obs("net_profit", "Q", q, float(v)) for q, v in zip(qs, profit)]
    obs += [_obs("eps_basic", "Q", q, e, unit="INR_PER_SHARE") for q, e in zip(qs, eps)]
    obs += [_obs("revenue", "Q", q, 100.0) for q in qs if q != "2025-06-30"]          # one revenue quarter missing
    _store(conn, "c", obs)
    r = V.readiness(conn, "TESTCO", "CONSOLIDATED", qs[0], qs[-1])["metrics"]
    npf = r["net_profit"]
    assert npf["yoy"]["2025-06-30"] == pytest.approx(-0.2) and "YoY 2025-09-30: base -3 not positive" in npf["refused"]
    assert npf["ttm"]["2025-03-31"] == 32 and npf["ttm_yoy"] == {"2026-03-31": pytest.approx(53 / 32 - 1)}
    e = r["eps_basic"]
    assert e["yoy"] == {"2025-06-30": pytest.approx(-0.2)}                              # same share base
    assert "YoY 2025-12-31: share base changed (bonus/split?); per-share figures not comparable" in e["refused"]
    assert set(e["ttm"]) == {"2025-03-31", "2025-06-30"}                                 # no window across the bonus
    rev = r["revenue"]
    assert rev["missing"] == ["2025-06-30"] and "YoY 2025-06-30: input missing" in rev["refused"]
    assert set(rev["ttm"]) == {"2025-03-31"} and rev["ttm_yoy"] == {}


# ---------------------------------------------------------------- download assistance

@pytest.mark.skipif(not (PILOT / "batch1").exists(), reason="pilot files not available")
def test_todo_names_missing_files_from_the_listings_and_sees_what_is_present():
    needed = V.todo(PILOT, ["INFY", "HDFCBANK"], both_bases=True)
    assert len(needed) == 32 and all(n.present for n in needed)            # 8 quarters x 2 bases x 2 companies
    assert {n.page for n in needed} == {"Financial Results", "Integrated Filing - Financials"}
    unknown = V.todo(PILOT, ["NOTLISTED"])
    assert unknown and all(n.file is None and "listing CSV first" in n.note for n in unknown)


@pytest.mark.skipif(not (PILOT / "batch1").exists(), reason="pilot files not available")
def test_collect_copies_only_named_files_and_never_overwrites(tmp_path):
    import shutil
    pilot_dir, downloads = tmp_path / "pilot", tmp_path / "Downloads"
    (pilot_dir / "batch1").mkdir(parents=True)
    downloads.mkdir()
    listing = PILOT / "batch1" / "CF-FR-equities-INFY-01-04-2023-to-08-10-2026.csv"
    shutil.copy2(listing, downloads / listing.name)                       # new listing -> listings/
    shutil.copy2(PILOT / "batch1-xbrl" / "INDAS_109110_1192961_18072024074507.xml", downloads)   # named -> xbrl/
    (downloads / "INDAS_1_2_x.xml").write_text("<x/>")                    # not in any listing -> skipped
    (downloads / "notes.txt").write_text("ignored")
    (downloads / "CF-FR-equities-BAD-01-01-2025-to-02-01-2025.csv").write_text("not,a,listing\n")   # unreadable
    shutil.copy2(listing, downloads / "CF-FR-equities-INFY-01-04-2023-to-08-10-2026(1).csv")      # duplicate
    rep = V.collect(downloads, pilot_dir)
    assert rep.listings == [listing.name] and rep.xbrl == ["INDAS_109110_1192961_18072024074507.xml"]
    assert rep.unlisted == ["INDAS_1_2_x.xml"] and rep.conflicts == []
    assert [u.split(":")[0] for u in rep.unreadable] == ["CF-FR-equities-BAD-01-01-2025-to-02-01-2025.csv"]
    assert rep.redundant == ["CF-FR-equities-INFY-01-04-2023-to-08-10-2026(1).csv"]
    assert (pilot_dir / "xbrl" / "INDAS_109110_1192961_18072024074507.xml").exists()
    assert (downloads / "INDAS_109110_1192961_18072024074507.xml").exists()      # originals kept
    again = V.collect(downloads, pilot_dir)
    assert again.listings == [] and again.xbrl == [] and len(again.already_present) == 2
    (downloads / "INDAS_109110_1192961_18072024074507.xml").write_text("<changed/>")
    assert V.collect(downloads, pilot_dir).conflicts == ["INDAS_109110_1192961_18072024074507.xml"]
    assert (pilot_dir / "xbrl" / "INDAS_109110_1192961_18072024074507.xml").read_bytes() != b"<changed/>"
