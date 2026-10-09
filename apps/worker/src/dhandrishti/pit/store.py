"""Append-only store and point-in-time queries for fundamental observations (migration 0008).

Versioning key: (symbol, metric, basis, period_type, period_end, source). Appending an observation
for a key:
  - no previous version                         -> data_version 1
  - same value, reported_at and vintage as the
    current version                             -> duplicate, skipped (re-imports are idempotent)
  - anything else                               -> data_version n+1, supersedes the current version;
                                                   is_restatement when the issuer published the new
                                                   figure later than the old one (reported_at later),
                                                   otherwise a correction of how we captured it.

Two time axes (bitemporal):
  available_at  when the market could know it   -> backtests: what could a decision use on day D?
  ingested_at   when DhanDrishti stored it       -> audit: what did DhanDrishti actually hold on day D?
"""

import hashlib
import math
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from pathlib import Path

import psycopg

from .availability import STRICT_BASES

KEY = ("symbol", "metric", "basis", "period_type", "period_end", "source")
REL_TOL = 1e-9


@dataclass(frozen=True)
class Observation:
    symbol: str
    metric: str
    value: float
    unit: str
    basis: str
    period_type: str
    period_start: date | None
    period_end: date
    filing_type: str
    reported_at: datetime | None
    available_at: datetime | None
    availability_basis: str
    value_vintage: str
    source: str
    source_record_id: str | None = None
    currency: str = "INR"
    # set by the store
    id: int | None = None
    data_version: int | None = None
    supersedes_id: int | None = None
    is_restatement: bool = False
    ingested_at: datetime | None = None
    import_batch_id: int | None = None

    def key(self) -> tuple:
        return tuple(getattr(self, k) for k in KEY)


COLUMNS = tuple(f.name for f in fields(Observation))
INSERT_COLUMNS = tuple(c for c in COLUMNS if c not in ("id", "ingested_at"))


@dataclass
class AppendResult:
    batch_id: int
    inserted: int = 0
    versioned: int = 0
    restatements: int = 0
    duplicates: int = 0


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same(a: Observation, b: Observation) -> bool:
    return (math.isclose(a.value, b.value, rel_tol=REL_TOL, abs_tol=1e-12) and a.reported_at == b.reported_at
            and a.value_vintage == b.value_vintage and a.unit == b.unit)


def _row(r: tuple) -> Observation:
    return Observation(**dict(zip(COLUMNS, r)))


def current_version(conn: psycopg.Connection, key: tuple) -> Observation | None:
    row = conn.execute(f"""
        SELECT {', '.join(COLUMNS)} FROM fundamental_observations
        WHERE symbol = %s AND metric = %s AND basis = %s AND period_type = %s AND period_end = %s AND source = %s
        ORDER BY data_version DESC LIMIT 1""", key).fetchone()
    return _row(row) if row else None


def append(conn: psycopg.Connection, observations: list[Observation], source: str,
           file_name: str | None = None, sha256: str | None = None, notes: str | None = None) -> AppendResult:
    """Append in one transaction. Never updates or deletes an existing observation."""
    with conn.transaction():
        batch = conn.execute("""INSERT INTO fundamental_import_batches (source, file_name, file_sha256, notes)
                                VALUES (%s, %s, %s, %s) RETURNING id""", (source, file_name, sha256, notes)).fetchone()[0]
        res = AppendResult(batch)
        # Oldest publication first, so versions within one import follow publication order.
        ordered = sorted(observations, key=lambda o: (o.reported_at is None, o.reported_at.timestamp() if o.reported_at else 0))
        for o in ordered:
            if o.source != source:
                raise ValueError(f"observation source {o.source!r} does not match batch source {source!r}")
            cur = current_version(conn, o.key())
            if cur is not None and _same(cur, o):
                res.duplicates += 1
                continue
            new = replace(o, data_version=1 if cur is None else cur.data_version + 1,
                          supersedes_id=None if cur is None else cur.id,
                          is_restatement=bool(cur and cur.reported_at and o.reported_at
                                              and o.reported_at > cur.reported_at),
                          import_batch_id=batch)
            conn.execute(f"""INSERT INTO fundamental_observations ({', '.join(INSERT_COLUMNS)})
                             VALUES ({', '.join(['%s'] * len(INSERT_COLUMNS))})""",
                         tuple(getattr(new, c) for c in INSERT_COLUMNS))
            if cur is None:
                res.inserted += 1
            else:
                res.versioned += 1
                res.restatements += new.is_restatement
        conn.execute("""UPDATE fundamental_import_batches SET rows_read = %s, rows_inserted = %s,
                        rows_versioned = %s, rows_duplicate = %s WHERE id = %s""",
                     (len(observations), res.inserted, res.versioned, res.duplicates, batch))
    return res


def as_of(conn: psycopg.Connection, symbol: str, decision: datetime, *, bases: tuple[str, ...] = STRICT_BASES,
          vintages: tuple[str, ...] = ("AS_REPORTED",), known_by: datetime | None = None,
          metrics: tuple[str, ...] | None = None) -> list[Observation]:
    """Observations usable for a decision at `decision`: for each key, the most recently published
    version with available_at <= decision (ties, i.e. corrections of the same publication, go to the
    highest data_version), optionally limited to what DhanDrishti had stored by `known_by`.

    Defaults are strict: exact or dated publication only, values as originally reported.
    """
    rows = conn.execute(f"""
        SELECT DISTINCT ON (metric, basis, period_type, period_end, source) {', '.join(COLUMNS)}
        FROM fundamental_observations
        WHERE symbol = %s AND available_at IS NOT NULL AND available_at <= %s
          AND availability_basis = ANY(%s) AND value_vintage = ANY(%s)
          AND (%s::timestamptz IS NULL OR ingested_at <= %s::timestamptz)
          AND (%s::text[] IS NULL OR metric = ANY(%s::text[]))
        ORDER BY metric, basis, period_type, period_end, source, available_at DESC, data_version DESC""",
        (symbol, decision, list(bases), list(vintages), known_by, known_by,
         list(metrics) if metrics else None, list(metrics) if metrics else None)).fetchall()
    return [_row(r) for r in rows]


def versions(conn: psycopg.Connection, symbol: str, metric: str, period_end: date | str) -> list[Observation]:
    """Every stored version of one figure, oldest first (all sources and bases)."""
    rows = conn.execute(f"""SELECT {', '.join(COLUMNS)} FROM fundamental_observations
                            WHERE symbol = %s AND metric = %s AND period_end = %s
                            ORDER BY source, basis, period_type, data_version""",
                        (symbol, metric, period_end)).fetchall()
    return [_row(r) for r in rows]


def latest_by_period(obs: list[Observation], metric: str, period_type: str,
                     basis_order: tuple[str, ...] = ("CONSOLIDATED", "STANDALONE")) -> dict[date, Observation]:
    """{period_end: observation} for one metric, preferring consolidated figures."""
    out: dict[date, Observation] = {}
    for o in sorted(obs, key=lambda o: basis_order.index(o.basis) if o.basis in basis_order else 99, reverse=True):
        if o.metric == metric and o.period_type == period_type:
            out[o.period_end] = o
    return dict(sorted(out.items()))
