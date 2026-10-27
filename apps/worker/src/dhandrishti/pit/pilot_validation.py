"""Fundamentals pilot validation in a development database (staged migration 0009 applied; dd_* only).

  import_files     read every pilot file with the production readers and import it through the 0009 controls
                   (BLOCK refuses, REVIEW hides only the doubtful values, NOTE hides nothing), oldest first
  apply_register   compare stored values with the official reference register (documents + values CSV) and record
                   one fundamental_verifications row per stored version; a MISMATCH also stores the official
                   figure as its own source ('official document'), dated by the document (never earlier)
  coverage         per company: filings, values, verification state, hidden values, official replacements,
                   missing quarters and missing core metrics; register rows with no stored value
  restatement_check  for every figure with more than one published version, the version visible just before a
                   later publication must be the earlier one (no look-ahead)
  yt2_flags        design check YT-2: Q1+Q2+Q3+Q4 must equal the filed full year; otherwise REVIEW (hide) the FY value
  readiness        which YoY / TTM figures the trusted quarterly values support (analysis only, never scoring)

Flag dispositions are NOT recorded here: who may record them is still an open decision.
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg

from ..db.staged import PROTECTED_DATABASES
from . import controls, store
from .adapters import nse_results_listing, nse_shp_listing
from .availability import IST, available_at
from .backfill import _regenerate

OFFICIAL_SOURCE = "official document"
METHOD = "official reference register: document read via web-fetch summary with verbatim quotes; tolerance 0.005"
BASES = ("CONSOLIDATED", "STANDALONE")
PERIOD_TYPES = ("Q", "FY", "INSTANT")
CORE_Q = ("revenue", "profit_before_tax", "net_profit", "eps_basic")


class PilotError(RuntimeError):
    pass


def require_dev(conn: psycopg.Connection) -> None:
    name = conn.info.dbname
    if name in PROTECTED_DATABASES or not name.startswith("dd_"):
        raise PilotError(f"refusing {name!r}: the pilot runs only in a dd_* development database")
    if conn.execute("SELECT to_regclass('fundamental_filings')").fetchone()[0] is None:
        raise PilotError(f"{name!r} has no quality-control tables: apply staged migration 0009 first")


# ---------------------------------------------------------------- import

@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    already_recorded: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)   # no listing row: no publication time, so never imported
    unreadable: list[str] = field(default_factory=list)  # reader refused the file (e.g. a format not mapped yet)
    hidden: dict[str, list] = field(default_factory=dict)


def import_files(conn: psycopg.Connection, roots: list[Path]) -> ImportReport:
    require_dev(conn)
    files = sorted({p for r in roots for p in r.glob("*.xml")})
    results = {f.xbrl_file: f for r in roots for p in r.glob("CF-*.csv") if not p.name.startswith("CF-Shareholding")
               for f in nse_results_listing.parse(p)}
    shp = {x.xbrl_file: x for r in roots for p in r.glob("CF-Shareholding-Pattern-*.csv") for x in nse_shp_listing.parse(p)}
    rep, work = ImportReport(), []
    for path in files:
        if path.name not in results and path.name not in shp:
            rep.unlisted.append(path.name)
            continue
        try:
            obs, prov, flags, (src, symbol, basis, period_end, taxonomy, published) = _regenerate(path, results, shp)
        except ValueError as exc:            # XbrlError and listing mismatches: reported, never half-imported
            rep.unreadable.append(f"{path.name}: {exc}")
            continue
        work.append((published, path, obs, prov, flags,
                     controls.FilingRecord(src, path.name, store.file_sha256(path), symbol, basis, period_end, taxonomy,
                                           published)))
    for published, path, obs, prov, flags, rec in sorted(work, key=lambda w: (w[0], w[1].name)):
        out = controls.import_filing(conn, rec, obs, prov, flags)
        {"IMPORTED": rep.imported, "REFUSED": rep.refused, "ALREADY_RECORDED": rep.already_recorded}[out.outcome].append(path.name)
        if out.hidden:
            rep.hidden[path.name] = out.hidden
    return rep


# ---------------------------------------------------------------- reference register

@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    url: str
    published_on: date
    date_basis: str


@dataclass(frozen=True)
class Reference:
    symbol: str
    basis: str
    metric: str
    period_type: str
    period_end: date
    official_value: float
    document: Document
    locator: str


def load_register(values_csv: Path, documents_csv: Path) -> list[Reference]:
    """Validated register rows; any malformed or duplicate row is an error, never skipped."""
    docs = {}
    for r in csv.DictReader(documents_csv.open(encoding="utf-8")):
        docs[r["document_id"]] = Document(r["document_id"], r["title"], r["url"], date.fromisoformat(r["published_on"]),
                                          r["date_basis"])
    out, seen = [], set()
    for n, r in enumerate(csv.DictReader(values_csv.open(encoding="utf-8")), start=2):
        if r["basis"] not in BASES or r["period_type"] not in PERIOD_TYPES:
            raise PilotError(f"{values_csv.name} line {n}: bad basis or period type")
        if r["document_id"] not in docs:
            raise PilotError(f"{values_csv.name} line {n}: unknown document {r['document_id']!r}")
        if not r["locator"].strip():
            raise PilotError(f"{values_csv.name} line {n}: locator required")
        ref = Reference(r["symbol"], r["basis"], r["metric"], r["period_type"], date.fromisoformat(r["period_end"]),
                        float(r["official_value"]), docs[r["document_id"]], r["locator"])
        key = (ref.symbol, ref.basis, ref.metric, ref.period_type, ref.period_end, ref.document.document_id)
        if key in seen:
            raise PilotError(f"{values_csv.name} line {n}: duplicate reference {key}")
        seen.add(key)
        out.append(ref)
    return out


@dataclass
class RegisterReport:
    verified: int = 0
    mismatched: list[tuple] = field(default_factory=list)
    not_stored: list[tuple] = field(default_factory=list)      # official value exists, no stored value to check
    already_checked: int = 0
    official_values_added: int = 0


def _doc_label(d: Document) -> str:
    return f"{d.document_id}: {d.title} ({d.url})"


def apply_register(conn: psycopg.Connection, refs: list[Reference]) -> RegisterReport:
    """Insert-only and idempotent: an identical verification or official value is not recorded twice."""
    require_dev(conn)
    rep = RegisterReport()
    for ref in refs:
        stored = conn.execute(f"""
            SELECT {', '.join(store.COLUMNS)} FROM fundamental_observations
            WHERE symbol = %s AND basis = %s AND metric = %s AND period_type = %s AND period_end = %s AND source <> %s
            ORDER BY data_version""", (ref.symbol, ref.basis, ref.metric, ref.period_type, ref.period_end,
                                       OFFICIAL_SOURCE)).fetchall()
        if not stored:
            rep.not_stored.append((ref.symbol, ref.basis, ref.metric, ref.period_type, ref.period_end.isoformat()))
            continue
        for o in map(store._row, stored):
            label = _doc_label(ref.document)
            if conn.execute("""SELECT 1 FROM fundamental_verifications WHERE observation_id = %s AND reference_doc = %s
                               AND reference_value = %s""", (o.id, label, ref.official_value)).fetchone():
                rep.already_checked += 1
                continue
            status = controls.record_verification(conn, o.id, label, ref.locator, ref.official_value, METHOD)
            if status == "VERIFIED":
                rep.verified += 1
            else:
                rep.mismatched.append((ref.symbol, ref.basis, ref.metric, ref.period_type, ref.period_end.isoformat(),
                                       o.value, ref.official_value))
                rep.official_values_added += _add_official(conn, o, ref)
    return rep


def _add_official(conn: psycopg.Connection, o: store.Observation, ref: Reference) -> int:
    """Store the official figure as its own source, available the day after the document's date."""
    key = (o.symbol, o.metric, o.basis, o.period_type, o.period_end, OFFICIAL_SOURCE)
    cur = store.current_version(conn, key)
    if cur is not None and abs(cur.value - ref.official_value) < 1e-9:
        return 0
    reported = datetime.combine(ref.document.published_on, time(0, 0), IST)
    official = store.Observation(
        symbol=o.symbol, metric=o.metric, value=ref.official_value, unit=o.unit, basis=o.basis,
        period_type=o.period_type, period_start=o.period_start, period_end=o.period_end, filing_type=o.filing_type,
        reported_at=reported, available_at=available_at("REPORTED_DATE", reported, o.period_end, o.period_type,
                                                         o.filing_type),
        availability_basis="REPORTED_DATE", value_vintage="AS_REPORTED", source=OFFICIAL_SOURCE,
        source_record_id=ref.document.document_id)
    controls.add_official_value(conn, official, ref.locator, _doc_label(ref.document))
    return 1


# ---------------------------------------------------------------- coverage

QUARTER_END_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def quarter_ends(first: str, last: str) -> list[date]:
    lo, hi = date.fromisoformat(first), date.fromisoformat(last)
    return [d for y in range(lo.year, hi.year + 1) for m, day in QUARTER_END_DAY.items()
            if lo <= (d := date(y, m, day)) <= hi]


def coverage(conn: psycopg.Connection, symbols: list[str], first_quarter: str = "2024-06-30",
             last_quarter: str = "2026-03-31") -> dict:
    """Per company: what is stored, verified, hidden or missing. Symbols with nothing stored are listed as such."""
    require_dev(conn)
    window = quarter_ends(first_quarter, last_quarter)
    out = {}
    for sym in symbols:
        filings = dict(conn.execute("""SELECT outcome, count(*) FROM fundamental_filings WHERE symbol = %s GROUP BY 1""",
                                    (sym,)).fetchall())
        rows = conn.execute("""
            SELECT s.source = %s AS official, s.basis, s.period_type, s.period_end, s.metric, s.usable, s.open_review,
                   s.verification
            FROM fundamental_observation_status s WHERE s.symbol = %s""", (OFFICIAL_SOURCE, sym)).fetchall()
        filed = [r for r in rows if not r[0]]
        state = {"VERIFIED": 0, "MISMATCH": 0, "NOT_IN_DOCUMENT": 0, "UNVERIFIED": 0}
        for r in filed:
            state[r[7] or "UNVERIFIED"] += 1
        missing_q, missing_core = {}, {}
        for basis in BASES:
            have = {r[3] for r in filed if r[1] == basis and r[2] == "Q"}
            if not have:
                continue
            missing_q[basis] = [d.isoformat() for d in window if d not in have]
            for d in sorted(have & set(window)):
                lacking = [m for m in CORE_Q if not any(r[1] == basis and r[2] == "Q" and r[3] == d and r[4] == m
                                                       for r in filed)]
                if lacking:
                    missing_core[f"{basis} {d.isoformat()}"] = lacking
        out[sym] = {
            "filings": filings, "values": len(filed), "verification": state,
            "hidden_open_review": sum(bool(r[6]) for r in filed),
            "official_replacements": sum(bool(r[0]) for r in rows),
            "quarters_in_window": {b: len(window) - len(v) for b, v in missing_q.items()},
            "missing_quarters": missing_q, "missing_core_metrics": missing_core,
            "status": "NO DATA" if not rows else "PARTIAL",
        }
    return out


# ---------------------------------------------------------------- restatements

def restatement_check(conn: psycopg.Connection) -> dict:
    """For each figure with several published versions: just before each later version became available, the
    point-in-time query must return the earlier version; at that moment it must return the later one."""
    require_dev(conn)
    keys = conn.execute("""SELECT symbol, metric, basis, period_type, period_end, source FROM fundamental_observations
                           GROUP BY 1, 2, 3, 4, 5, 6 HAVING count(*) > 1""").fetchall()
    checked, failures = 0, []
    for sym, metric, basis, ptype, end, source in keys:
        vs = [store._row(r) for r in conn.execute(f"""
            SELECT {', '.join(store.COLUMNS)} FROM fundamental_observations WHERE symbol = %s AND metric = %s
            AND basis = %s AND period_type = %s AND period_end = %s AND source = %s ORDER BY available_at, data_version""",
            (sym, metric, basis, ptype, end, source))]
        for prev, nxt in zip(vs, vs[1:]):
            if prev.available_at is None or nxt.available_at is None or nxt.available_at <= prev.available_at:
                continue
            checked += 1

            def seen(at):
                return next((o for o in store.as_of(conn, sym, at, metrics=(metric,))
                             if (o.basis, o.period_type, o.period_end, o.source) == (basis, ptype, end, source)), None)
            before, after = seen(nxt.available_at - timedelta(seconds=1)), seen(nxt.available_at)
            if before is None or before.id != prev.id or after is None or after.id != nxt.id:
                failures.append((sym, metric, basis, ptype, end.isoformat(), source))
    return {"figures_with_versions": len(keys), "transitions_checked": checked, "look_ahead_failures": failures}


# ---------------------------------------------------------------- YT-2: four quarters must add up to the year

YT2_ABS_CR, YT2_REL = 1.0, 0.005     # design: tolerance Rs 1 cr or 0.5%


def yt2_flags(conn: psycopg.Connection) -> list[tuple]:
    """Check YT-2 (docs/fundamentals-quality-design.md): for every flow metric with a filed, usable full-year value
    and four trusted quarters of the same fiscal year, Q1+Q2+Q3+Q4 must equal FY within Rs 1 cr or 0.5%. Otherwise a
    REVIEW flag is added to the FY value (hiding it). Insert-only and idempotent. Returns the flags added."""
    require_dev(conn)
    added = []
    fy_rows = conn.execute("""
        SELECT s.id, s.symbol, s.basis, s.metric, s.period_end, s.value, p.filing_id
        FROM fundamental_observation_status s JOIN fundamental_value_provenance p ON p.observation_id = s.id
        WHERE s.period_type = 'FY' AND s.source <> %s AND s.usable AND s.unit = 'INR_CR'
          AND NOT EXISTS (SELECT 1 FROM fundamental_quality_flags f WHERE f.observation_id = s.id AND f.check_code = 'YT-2')
        ORDER BY s.symbol, s.basis, s.metric, s.period_end""", (OFFICIAL_SOURCE,)).fetchall()
    trusted_cache: dict[tuple, dict] = {}
    for obs_id, sym, basis, metric, end, fy, filing_id in fy_rows:
        t = trusted_cache.setdefault((sym, basis), _trusted(conn, sym, basis))
        quarters = [q for q in quarter_ends(date(end.year - 1, 6, 30).isoformat(), end.isoformat())]
        vals = [t.get((metric, "Q", q)) for q in quarters]
        if len(quarters) != 4 or None in vals:
            continue
        total = sum(v[0] for v in vals)
        diff = total - fy
        if abs(diff) <= YT2_ABS_CR or (fy and abs(diff / fy) <= YT2_REL):
            continue
        flag = controls.Flag("YT-2", "REVIEW",
                             f"Q1+Q2+Q3+Q4 = {total:,.2f} but the filed full-year {metric} is {fy:,.2f} "
                             f"(difference {diff:,.2f}, {diff / fy:+.2%}); quarters used: "
                             + ", ".join(f"{q} {v[0]:,.2f} ({v[2]})" for q, v in zip(quarters, vals)),
                             ((metric, "FY"),), {"quarters": {q.isoformat(): v[0] for q, v in zip(quarters, vals)},
                                                 "full_year": fy, "difference": diff})
        out = controls.ImportOutcome(filing_id, "IMPORTED")
        with conn.transaction():
            controls._write_flag(conn, filing_id, flag, {(metric, "FY", end): obs_id}, end, out)
        added.append((sym, basis, metric, end.isoformat(), fy, total))
    return added


# ---------------------------------------------------------------- readiness (analysis only; not connected to scoring)

FLOW_METRICS = ("revenue", "profit_before_tax", "net_profit")
PER_SHARE = ("eps_basic",)
FY_TOLERANCE = 0.005      # quarterly sums must match the filed full-year figure within 0.5%
SHARE_BASE_TOLERANCE = 0.05


def _trusted(conn: psycopg.Connection, symbol: str, basis: str) -> dict[tuple, tuple]:
    """{(metric, period_type, period_end): (value, source, verification)}: the latest usable filed value, or the
    official-document value when the filed one is hidden or mismatched. Hidden values are never returned."""
    rows = conn.execute("""
        SELECT DISTINCT ON (metric, period_type, period_end, official) metric, period_type, period_end, value,
               source, usable, verification
        FROM (SELECT *, source = %s AS official FROM fundamental_observation_status
              WHERE symbol = %s AND basis = %s) s
        ORDER BY metric, period_type, period_end, official, available_at DESC, data_version DESC""",
        (OFFICIAL_SOURCE, symbol, basis)).fetchall()
    out = {}
    for metric, ptype, end, value, source, usable, verification in rows:
        key = (metric, ptype, end)
        official = source == OFFICIAL_SOURCE
        if official:
            out[key] = (value, source, "OFFICIAL")            # replaces a mismatched filed value
        elif usable and verification != "MISMATCH" and key not in out:
            out[key] = (value, source, verification or "UNVERIFIED")
    return out


def readiness(conn: psycopg.Connection, symbol: str, basis: str, first_quarter: str = "2024-06-30",
              last_quarter: str = "2026-03-31") -> dict:
    """Which quarterly, year-on-year and trailing-twelve-month figures the stored data genuinely supports.
    A figure is computed only when every input is present and trusted; reasons are given otherwise."""
    require_dev(conn)
    qs = quarter_ends(first_quarter, last_quarter)
    t = _trusted(conn, symbol, basis)
    hidden = conn.execute("""SELECT metric, period_type, period_end FROM fundamental_observation_status
                             WHERE symbol = %s AND basis = %s AND NOT usable""", (symbol, basis)).fetchall()
    q = {m: {d: t.get((m, "Q", d)) for d in qs} for m in FLOW_METRICS + PER_SHARE}

    def shares(d):  # implied share base, crore shares = profit (Rs cr) / EPS (Rs)
        np_, eps = q["net_profit"][d], q["eps_basic"][d]
        return np_[0] / eps[0] if np_ and eps and eps[0] else None

    def same_base(ds):
        s = [shares(d) for d in ds]
        return None not in s and max(s) / min(s) - 1 <= SHARE_BASE_TOLERANCE

    out = {"symbol": symbol, "basis": basis, "quarters": [d.isoformat() for d in qs], "metrics": {}}
    for m in FLOW_METRICS + PER_SHARE:
        vals = q[m]
        missing = [d.isoformat() for d in qs if vals[d] is None]
        yoy, ttm, refused = {}, {}, []
        for i, d in enumerate(qs):
            if i >= 4:
                a, b = vals[qs[i - 4]], vals[d]
                if a is None or b is None:
                    refused.append(f"YoY {d}: input missing")
                elif a[0] <= 0:
                    refused.append(f"YoY {d}: base {a[0]:g} not positive")
                elif m in PER_SHARE and not same_base([qs[i - 4], d]):
                    refused.append(f"YoY {d}: share base changed (bonus/split?); per-share figures not comparable")
                else:
                    yoy[d.isoformat()] = b[0] / a[0] - 1
            if i >= 3:
                window = qs[i - 3: i + 1]
                if any(vals[x] is None for x in window):
                    refused.append(f"TTM {d}: input missing")
                elif m in PER_SHARE and not same_base(window):
                    refused.append(f"TTM {d}: share base changed within the four quarters")
                else:
                    ttm[d.isoformat()] = sum(vals[x][0] for x in window)
        fy_checks = {}
        for d in qs:
            fy = t.get((m, "FY", d))
            if fy and d.isoformat() in ttm:
                diff = ttm[d.isoformat()] / fy[0] - 1 if fy[0] else None
                fy_checks[d.isoformat()] = {"sum_of_quarters": ttm[d.isoformat()], "filed_full_year": fy[0],
                                            "difference": diff,
                                            "status": "CONSISTENT" if diff is not None and abs(diff) <= FY_TOLERANCE
                                            else "INCONSISTENT"}
        ttm_yoy = {}
        for d in qs[7:]:
            prev = qs[qs.index(d) - 4]
            if d.isoformat() in ttm and prev.isoformat() in ttm and ttm[prev.isoformat()] > 0:
                ttm_yoy[d.isoformat()] = ttm[d.isoformat()] / ttm[prev.isoformat()] - 1
        verification = {}
        for d in qs:
            if vals[d]:
                verification[vals[d][2]] = verification.get(vals[d][2], 0) + 1
        for (hid_metric, ptype, end) in hidden:
            if hid_metric == m and ptype == "FY" and end in qs:
                refused.append(f"FY {end}: filed full-year value hidden pending review (not used)")
        out["metrics"][m] = {"quarters_present": len(qs) - len(missing), "missing": missing,
                             "verification": verification, "yoy": yoy, "ttm": ttm, "ttm_yoy": ttm_yoy,
                             "fy_check": fy_checks, "refused": refused}
    return out


# ---------------------------------------------------------------- download assistance (manual downloads only)

@dataclass
class Needed:
    symbol: str
    basis: str
    quarter: str
    page: str            # NSE page the file is listed on
    broadcast: str       # NSE broadcast time (IST)
    file: str | None     # exact NSE file name, or None when no listing row exists yet
    present: bool
    note: str = ""


def listing_rows(pilot_dir: Path) -> list:
    rows = []
    for p in sorted(pilot_dir.rglob("CF-*.csv")):
        if not p.name.startswith("CF-Shareholding"):
            rows += nse_results_listing.parse(p)
    return rows


def present_files(pilot_dir: Path) -> set[str]:
    return {p.name for p in pilot_dir.rglob("*.xml")}


def todo(pilot_dir: Path, symbols: list[str], first_quarter: str = "2024-06-30", last_quarter: str = "2026-03-31",
         both_bases: bool = False) -> list[Needed]:
    """The results XBRL files still needed for each symbol and quarter, named from the downloaded listing CSVs.
    Consolidated only, unless the company has no consolidated results or `both_bases`."""
    rows, have = listing_rows(pilot_dir), present_files(pilot_dir)
    out = []
    for sym in symbols:
        mine = [r for r in rows if r.symbol == sym and r.period_type == "Q"]
        bases = list(BASES) if both_bases or not any(r.basis == "CONSOLIDATED" for r in mine) else ["CONSOLIDATED"]
        for q in quarter_ends(first_quarter, last_quarter):
            for basis in bases:
                hits = sorted({r.xbrl_file: r for r in mine if r.basis == basis and r.period_end == q}.values(),
                              key=lambda r: r.disseminated_at)          # the same filing may sit in several listings
                if not hits:
                    page = "Financial Results" if q < date(2025, 3, 31) else "Integrated Filing - Financials"
                    out.append(Needed(sym, basis, q.isoformat(), page, "", None, False,
                                      "no listing row: download this company's listing CSV first"))
                    continue
                for i, r in enumerate(hits):
                    out.append(Needed(sym, basis, q.isoformat(), r.source_page,
                                      r.disseminated_at.strftime("%d-%b-%Y %H:%M"), r.xbrl_file, r.xbrl_file in have,
                                      "" if i == 0 else f"later submission ({r.submission}); also needed"))
    return out


@dataclass
class CollectReport:
    listings: list[str] = field(default_factory=list)
    xbrl: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)     # same name, different content: never overwritten
    unlisted: list[str] = field(default_factory=list)      # XBRL with no listing row: not copied
    unreadable: list[str] = field(default_factory=list)    # listing CSV the parser refuses: not copied
    redundant: list[str] = field(default_factory=list)     # listing CSV naming no new filing: not copied


def collect(source: Path, pilot_dir: Path) -> CollectReport:
    """Copy manually downloaded NSE files from `source` (e.g. ~/Downloads) into the pilot folder: listing CSVs to
    listings/, results XBRL named in a listing to xbrl/. Copies only; never overwrites; never deletes the originals."""
    import shutil
    rep = CollectReport()
    existing = {p.name: p for p in pilot_dir.rglob("*") if p.is_file()}

    def place(p: Path, sub: str, bucket: list[str]) -> None:
        if p.name in existing:
            same = store.file_sha256(p) == store.file_sha256(existing[p.name])
            (rep.already_present if same else rep.conflicts).append(p.name)
            return
        dest = pilot_dir / sub
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest / p.name)
        existing[p.name] = dest / p.name
        bucket.append(p.name)

    known = {r.xbrl_file for r in listing_rows(pilot_dir)}
    def original_first(p: Path):            # "x(1).csv" from a repeat download comes after "x.csv"
        return re.sub(r" ?\(\d+\)(?=\.csv$)", "", p.name), "(" in p.name

    for p in sorted(source.glob("CF-*.csv"), key=original_first):
        if p.name.startswith("CF-Shareholding"):
            continue
        try:
            rows = nse_results_listing.parse(p)   # refuse anything that is not a clean NSE results listing
        except nse_results_listing.ListingError as exc:
            rep.unreadable.append(f"{p.name}: {str(exc).splitlines()[0]}")
            continue
        if p.name not in existing and rows and {r.xbrl_file for r in rows} <= known:
            rep.redundant.append(p.name)
            continue
        place(p, "listings", rep.listings)
        known |= {r.xbrl_file for r in rows}
    named = {r.xbrl_file for r in listing_rows(pilot_dir)}
    for p in sorted(source.glob("*.xml")):
        if p.name in named:
            place(p, "xbrl", rep.xbrl)
        elif p.name.startswith(("INDAS_", "BANKING_", "INTEGRATED_FILING_")):
            rep.unlisted.append(p.name)
    return rep
