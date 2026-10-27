"""Data-quality controls for fundamental observations (staged migration 0009; docs/fundamentals-quality-design.md).

Phase 1 (2026-10-09): used only against throwaway test databases. Nothing here writes to
fundamental_observations except through store.append, and nothing updates or deletes any row.

Outcomes of a check:
  BLOCK   the filing is refused: nothing is imported (data-integrity failures only)
  REVIEW  the filing is imported, but the specific values the check concerns are hidden from research
          until a disposition is recorded; the filing's other values stay usable
  NOTE    recorded for context; hides nothing
"""

import json
from dataclasses import dataclass, field
from datetime import datetime

import psycopg

from . import store
from .availability import STRICT_BASES

CHECK_VERSION = 1


@dataclass(frozen=True)
class Provenance:
    how_obtained: str              # REPORTED | SUMMED | CALCULATED | INFERRED
    source_concepts: list[str]
    source_contexts: list[str] = field(default_factory=list)
    derivation: str | None = None
    mapping_note: str | None = None


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str                  # BLOCK | REVIEW | NOTE
    message: str
    affects: tuple[tuple[str, str], ...] = ()   # (metric, period_type) values a REVIEW hides
    observed: dict = field(default_factory=dict)


# Reader check name -> (code, severity when the check fails or warns, values affected by a REVIEW).
# Every check a reader can emit must be listed: an unmapped name raises, so no check is silently dropped.
EPS_AFFECTS = (("net_profit", "Q"), ("eps_basic", "Q"), ("eps_diluted", "Q"))
CHECK_MAP: dict[str, tuple[str, str, tuple]] = {
    # identities (ID-1): the filing contradicts itself
    "income = revenue + other income": ("ID-1", "BLOCK", ()),
    "profit before exceptional items = income - expenses": ("ID-1", "BLOCK", ()),
    "profit after tax = PBT - tax (continuing)": ("ID-1", "BLOCK", ()),
    "assets = equity + liabilities": ("ID-1", "BLOCK", ()),
    "income = interest earned + other income": ("ID-1", "BLOCK", ()),
    "operating profit = income - expenditure excl. provisions": ("ID-1", "BLOCK", ()),
    "PBT = operating profit - provisions + exceptional items": ("ID-1", "BLOCK", ()),
    "PAT = PBT - tax": ("ID-1", "BLOCK", ()),
    "assets = capital and liabilities": ("ID-1", "BLOCK", ()),
    "insurer PAT = PBT - shareholders' taxes": ("ID-1", "BLOCK", ()),
    "sources of funds = application of funds": ("ID-1", "BLOCK", ()),
    "liability lines sum to capital and liabilities": ("ID-1", "BLOCK", ()),
    "asset lines sum to assets": ("ID-1", "BLOCK", ()),
    "promoter + public + non-promoter non-public shares = total": ("ID-1", "BLOCK", ()),
    "public = foreign + domestic institutions + government + non-institutions": ("ID-1", "BLOCK", ()),
    # timing (TM-1)
    "published on/after the board meeting": ("TM-1", "BLOCK", ()),
    "listing symbol and as-on date match the file": ("CS-1", "BLOCK", ()),
    # accounting cross-checks: scoped REVIEW
    "exceptional item looks like minority interest (MI-1)": ("MI-1", "REVIEW", (("profit_before_tax", "Q"),)),
    "EPS x period-end shares ≈ owners' profit (2%)": ("MI-3", "REVIEW", EPS_AFFECTS),
    "segment profit before tax = PBT (cross-check)": ("MI-4", "REVIEW", (("profit_before_tax", "Q"),)),
    "balance-sheet cash = cash-flow cash (cross-check)": ("RC-2", "REVIEW", (("cash_and_equivalents", "INSTANT"),)),
    "listing promoter % = file promoter %": ("RC-4", "REVIEW", (("promoter_holding_pct", "INSTANT"),)),
    "promoter pledge stated": ("MS-3", "NOTE", ()),
}
STATUS_TO_FLAG = {"FAIL", "WARN"}


class UnmappedCheckError(KeyError):
    pass


def flags_from_checks(checks: list[tuple[str, str, str]], notes: list[str] = ()) -> list[Flag]:
    """Translate a reader's (name, status, detail) checks and notes into typed flags."""
    out = []
    for name, status, detail in checks:
        if name not in CHECK_MAP:
            raise UnmappedCheckError(f"check {name!r} has no code/severity in CHECK_MAP")
        if status not in STATUS_TO_FLAG:
            continue  # PASS and N/A raise nothing
        code, severity, affects = CHECK_MAP[name]
        if status == "FAIL" and severity != "BLOCK":
            severity = "BLOCK"
        out.append(Flag(code, severity, f"{name}: {detail}", affects, {"check": name, "detail": detail}))
    for n in notes:
        code = "PD-1" if "header says" in n else "YT-1" if "skipped period" in n else "FM-1" if "not defined" in n else "MS-1"
        out.append(Flag(code, "NOTE", n))
    return out


# ---------------------------------------------------------------- writing

def _require_tables(conn: psycopg.Connection) -> None:
    if conn.execute("SELECT to_regclass('fundamental_filings')").fetchone()[0] is None:
        raise RuntimeError("quality-control tables are missing (staged migration 0009 not applied to this database)")


@dataclass
class FilingRecord:
    source: str
    file_name: str
    file_sha256: str
    symbol: str
    basis: str | None
    period_end: object
    taxonomy: str
    published_at: datetime | None


@dataclass
class ImportOutcome:
    filing_id: int
    outcome: str                   # IMPORTED | REFUSED | ALREADY_RECORDED
    observations: int = 0
    flags: int = 0
    hidden: list[tuple[str, str]] = field(default_factory=list)


def import_filing(conn: psycopg.Connection, rec: FilingRecord, observations: list[store.Observation],
                  provenance: list[Provenance], flags: list[Flag]) -> ImportOutcome:
    """Import one filing with its provenance and flags, in one transaction. Insert-only."""
    _require_tables(conn)
    if len(observations) != len(provenance):
        raise ValueError("one provenance entry per observation is required")
    with conn.transaction():
        existing = conn.execute("SELECT id FROM fundamental_filings WHERE file_sha256 = %s", (rec.file_sha256,)).fetchone()
        if existing:
            return ImportOutcome(existing[0], "ALREADY_RECORDED")
        blocked = any(f.severity == "BLOCK" for f in flags)
        batch_id = None
        if not blocked:
            res = store.append(conn, observations, rec.source, rec.file_name, rec.file_sha256)
            batch_id = res.batch_id
        filing_id = conn.execute("""
            INSERT INTO fundamental_filings (source, file_name, file_sha256, symbol, basis, period_end, taxonomy,
                                             published_at, outcome, import_batch_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (rec.source, rec.file_name, rec.file_sha256, rec.symbol, rec.basis, rec.period_end, rec.taxonomy,
             rec.published_at, "REFUSED" if blocked else "IMPORTED", batch_id)).fetchone()[0]
        out = ImportOutcome(filing_id, "REFUSED" if blocked else "IMPORTED")
        ids = {}
        if not blocked:
            for o, p in zip(observations, provenance):
                cur = store.current_version(conn, o.key())
                ids[(o.metric, o.period_type, o.period_end)] = cur.id
                write_provenance(conn, cur.id, filing_id, p)
            out.observations = len(observations)
        for f in flags:
            out.flags += _write_flag(conn, filing_id, f, ids, rec.period_end, out)
    return out


def write_provenance(conn: psycopg.Connection, observation_id: int, filing_id: int | None, p: Provenance) -> bool:
    """Insert provenance for an observation unless it already has some. Returns True if inserted."""
    r = conn.execute("""
        INSERT INTO fundamental_value_provenance (observation_id, filing_id, how_obtained, source_concepts,
                                                  source_contexts, derivation, mapping_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (observation_id) DO NOTHING""",
        (observation_id, filing_id, p.how_obtained, p.source_concepts, p.source_contexts or None, p.derivation,
         p.mapping_note))
    return r.rowcount == 1


def _write_flag(conn, filing_id, f: Flag, ids, period_end, out: ImportOutcome) -> int:
    def insert(obs_id, severity, message):
        conn.execute("""INSERT INTO fundamental_quality_flags (filing_id, observation_id, check_code, check_version,
                        severity, observed, message) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                     (filing_id, obs_id, f.code, CHECK_VERSION, severity, json.dumps(f.observed), message))

    if f.severity != "REVIEW":
        insert(None, f.severity, f.message)
        return 1
    n = 0
    for metric, ptype in f.affects:
        obs_id = ids.get((metric, ptype, period_end))
        if obs_id is None:
            continue
        insert(obs_id, "REVIEW", f.message)
        out.hidden.append((metric, ptype))
        n += 1
    if n == 0:  # the doubtful value is not stored (e.g. a cross-check element): keep the finding as context
        insert(None, "NOTE", f.message + " (affected value not stored)")
        n = 1
    return n


def record_disposition(conn: psycopg.Connection, flag_id: int, disposition: str, reason: str, decided_by: str,
                       evidence: str | None = None) -> int:
    _require_tables(conn)
    return conn.execute("""INSERT INTO fundamental_flag_dispositions (flag_id, disposition, reason, evidence, decided_by)
                           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                        (flag_id, disposition, reason, evidence, decided_by)).fetchone()[0]


def record_verification(conn: psycopg.Connection, observation_id: int, reference_doc: str, locator: str,
                        reference_value: float | None, method: str, tolerance: float = 0.005) -> str:
    _require_tables(conn)
    value = conn.execute("SELECT value FROM fundamental_observations WHERE id = %s", (observation_id,)).fetchone()[0]
    if reference_value is None:
        status, diff = "NOT_IN_DOCUMENT", None
    else:
        diff = value - reference_value
        status = "VERIFIED" if abs(diff) <= tolerance else "MISMATCH"
    conn.execute("""INSERT INTO fundamental_verifications (observation_id, reference_doc, reference_locator,
                    reference_value, difference, status, method) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (observation_id, reference_doc, locator, reference_value, diff, status, method))
    return status


def add_official_value(conn: psycopg.Connection, o: store.Observation, document_line: str, document: str) -> int:
    """Store a value read from an official results document as its own source (never overwrites XBRL)."""
    _require_tables(conn)
    with conn.transaction():
        store.append(conn, [o], o.source, None, None, notes=document)
        obs_id = store.current_version(conn, o.key()).id
        write_provenance(conn, obs_id, None, Provenance("REPORTED", [document_line], [], None, f"official document: {document}"))
    return obs_id


# ---------------------------------------------------------------- reading

def as_of_usable(conn: psycopg.Connection, symbol: str, decision: datetime, *, bases=STRICT_BASES,
                 vintages=("AS_REPORTED",), metrics: tuple[str, ...] | None = None) -> list[store.Observation]:
    """Like store.as_of, but only values that are usable (no open REVIEW, not excluded or superseded).
    Unusable rows are removed before picking the latest version, so an earlier usable version can surface."""
    _require_tables(conn)
    rows = conn.execute(f"""
        SELECT DISTINCT ON (metric, basis, period_type, period_end, source) {', '.join(store.COLUMNS)}
        FROM fundamental_observation_status
        WHERE symbol = %s AND usable AND available_at IS NOT NULL AND available_at <= %s
          AND availability_basis = ANY(%s) AND value_vintage = ANY(%s)
          AND (%s::text[] IS NULL OR metric = ANY(%s::text[]))
        ORDER BY metric, basis, period_type, period_end, source, available_at DESC, data_version DESC""",
        (symbol, decision, list(bases), list(vintages), list(metrics) if metrics else None,
         list(metrics) if metrics else None)).fetchall()
    return [store._row(r) for r in rows]
