"""Describe already-imported observations with filings, provenance and flags. Insert-only.

For each import batch: find its file, require the file's SHA-256 to equal the hash recorded at import, re-read
it with the same reader, and match every stored observation of the batch to exactly one regenerated
observation (key, value and publication time). Only then insert the filing row, provenance and flags.
Nothing in fundamental_observations or fundamental_import_batches is changed. Re-running inserts nothing.

Phase 1: refuses the protected research databases (see db/staged.py).
"""

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from ..db.staged import PROTECTED_DATABASES
from . import controls, store
from .adapters import nse_results_listing, nse_shp, nse_shp_listing, nse_xbrl


class BackfillError(RuntimeError):
    pass


@dataclass
class BackfillReport:
    batches: int = 0
    filings_inserted: int = 0
    provenance_inserted: int = 0
    flags_inserted: int = 0
    already_described: int = 0
    lines: list[str] = field(default_factory=list)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _regenerate(path: Path, results_index: dict, shp_index: dict):
    """(observations, provenance, flags, FilingRecord-fields) for one file, using the same readers as import."""
    if path.name in results_index:
        f = results_index[path.name]
        pf = nse_xbrl.parse(path, f)
        flags = controls.flags_from_checks(pf.checks, pf.notes)
        return pf.observations, pf.provenance, flags, (nse_xbrl.SOURCE, f.symbol, f.basis, f.period_end, pf.taxonomy,
                                                       f.disseminated_at)
    if path.name in shp_index:
        row = shp_index[path.name]
        sf = nse_shp.parse(path)
        pairs = sf.observations_with_provenance(row.disseminated_at, path.name)
        checks = list(sf.checks) + [
            ("listing symbol and as-on date match the file",
             "PASS" if (row.symbol, row.as_on) == (sf.symbol, sf.as_on) else "FAIL", f"{row.symbol} {row.as_on}")]
        if row.promoter_pct is not None and "promoter" in sf.pct:
            checks.append(("listing promoter % = file promoter %",
                           "PASS" if abs(row.promoter_pct - sf.pct["promoter"]) <= 0.01 else "WARN",
                           f"{row.promoter_pct} vs {sf.pct['promoter']:.2f}"))
        flags = controls.flags_from_checks(checks, sf.notes)
        return [o for o, _ in pairs], [p for _, p in pairs], flags, (nse_shp.SOURCE, sf.symbol, None, sf.as_on,
                                                                     "in-bse-shp", row.disseminated_at)
    raise BackfillError(f"{path.name}: not in any results or shareholding listing")


def backfill(conn: psycopg.Connection, roots: list[Path], apply: bool) -> BackfillReport:
    if conn.info.dbname in PROTECTED_DATABASES:
        raise BackfillError(f"Phase 1: refusing to backfill protected database {conn.info.dbname!r}")
    if conn.execute("SELECT to_regclass('fundamental_filings')").fetchone()[0] is None:
        raise BackfillError("quality-control tables missing: apply the staged migration first")
    files = {p.name: p for r in roots for p in r.glob("*.xml")}
    results_index = {f.xbrl_file: f for r in roots for p in r.glob("CF-*.csv")
                     if not p.name.startswith("CF-Shareholding") for f in nse_results_listing.parse(p)}
    shp_index = {x.xbrl_file: x for r in roots for p in r.glob("CF-Shareholding-Pattern-*.csv")
                 for x in nse_shp_listing.parse(p)}
    rep = BackfillReport()
    batches = conn.execute("SELECT id, source, file_name, file_sha256 FROM fundamental_import_batches ORDER BY id").fetchall()
    with conn.transaction():
        for batch_id, source, file_name, sha in batches:
            rep.batches += 1
            if conn.execute("SELECT 1 FROM fundamental_filings WHERE import_batch_id = %s", (batch_id,)).fetchone():
                rep.already_described += 1
                continue
            path = files.get(file_name)
            if path is None:
                raise BackfillError(f"batch {batch_id}: file {file_name} not found under {[str(r) for r in roots]}")
            if _sha(path) != sha:
                raise BackfillError(f"batch {batch_id}: {file_name} on disk differs from the imported file (SHA-256)")
            obs, prov, flags, (src, symbol, basis, period_end, taxonomy, published) = _regenerate(path, results_index, shp_index)
            if src != source:
                raise BackfillError(f"batch {batch_id}: source {source!r} but the reader says {src!r}")
            stored = [store._row(r) for r in conn.execute(
                f"SELECT {', '.join(store.COLUMNS)} FROM fundamental_observations WHERE import_batch_id = %s", (batch_id,))]
            matched = {}
            for s_obs in stored:
                hits = [i for i, o in enumerate(obs) if o.key() == s_obs.key() and o.reported_at == s_obs.reported_at
                        and math.isclose(o.value, s_obs.value, rel_tol=1e-9, abs_tol=1e-12)]
                if len(hits) != 1:
                    raise BackfillError(f"batch {batch_id}: stored {s_obs.metric} {s_obs.period_type} {s_obs.period_end} "
                                        f"matches {len(hits)} regenerated values (expected exactly 1)")
                matched[hits[0]] = s_obs
            if len(matched) != len(stored):
                raise BackfillError(f"batch {batch_id}: duplicate matches")
            if any(f.severity == "BLOCK" for f in flags):
                raise BackfillError(f"batch {batch_id}: today's checks would BLOCK this already-imported file; review needed")
            rep.lines.append(f"batch {batch_id} {file_name}: {len(stored)} observations, "
                             f"{sum(f.severity == 'REVIEW' for f in flags)} review / {sum(f.severity == 'NOTE' for f in flags)} note flags")
            if not apply:
                continue
            filing_id = conn.execute("""
                INSERT INTO fundamental_filings (source, file_name, file_sha256, symbol, basis, period_end, taxonomy,
                                                 published_at, outcome, import_batch_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'IMPORTED', %s) RETURNING id""",
                (source, file_name, sha, symbol, basis, period_end, taxonomy, published, batch_id)).fetchone()[0]
            rep.filings_inserted += 1
            ids = {}
            for i, s_obs in matched.items():
                rep.provenance_inserted += controls.write_provenance(conn, s_obs.id, filing_id, prov[i])
                ids[(s_obs.metric, s_obs.period_type, s_obs.period_end)] = s_obs.id
            out = controls.ImportOutcome(filing_id, "IMPORTED")
            for f in flags:
                rep.flags_inserted += controls._write_flag(conn, filing_id, f, ids, period_end, out)
        if not apply:
            raise _DryRun(rep)
    return rep


class _DryRun(Exception):
    def __init__(self, rep):
        super().__init__("dry run")
        self.rep = rep


def run(conn: psycopg.Connection, roots: list[Path], apply: bool) -> BackfillReport:
    """Dry run rolls back everything (nothing is written) and still returns the report."""
    try:
        return backfill(conn, roots, apply)
    except _DryRun as d:
        return d.rep
