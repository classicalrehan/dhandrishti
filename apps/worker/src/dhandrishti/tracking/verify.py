"""Verify that a recorded scoring run can be reproduced (docs/recommendation-tracking.md).

  1. Load the run's inputs from the current tables and compare the manifest hash with the recorded one.
  2. If they differ, rebuild daily_prices / index_prices as they stood when the inputs were read, from the
     price change log (temporary tables shadow the real ones inside one transaction; nothing is written),
     and compare again.
  3. With identical inputs, re-score with the recorded configuration and compare every stock's result hash.

Statuses:
  REPRODUCED                  identical inputs (current or reconstructed) and identical results
  CODE_CHANGED                identical inputs, different results: the scoring code differs from the run's
  INPUTS_CHANGED              inputs differ even after reconstruction because securities, fundamentals or events
                              changed (those tables are not logged), so the original cannot be rebuilt
  INSUFFICIENT_INPUT_HISTORY  no manifest (BACKFILLED); prices changed and the log does not cover the run; or prices
                              still differ after reconstruction (log incomplete: chunk dropped, triggers disabled)
  VERIFICATION_FAILED         the check itself could not run (missing configuration, unexpected error)
A hash only proves equality; when the inputs cannot be rebuilt this never reports REPRODUCED.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from ..config import default_config
from ..db.market_repository import load_market
from ..db.score_repository import config_sha256
from ..scoring import score_universe
from . import manifest as M
from .recorder import CodeInfo, code_info

log = logging.getLogger(__name__)

_COLS = "open, high, low, close, volume, provenance, source"


@dataclass
class Verification:
    run_id: int
    status: str
    inputs_source: str | None = None
    detail: dict = field(default_factory=dict)


def log_coverage(conn: psycopg.Connection, at: datetime) -> str | None:
    """None when the price change log covers everything that happened after `at`; otherwise why not."""
    for table in ("daily_prices", "index_prices"):
        start = conn.execute("""SELECT min(changed_at) FROM price_change_log
                                WHERE table_name = %s AND op = 'LOG_START'""", (table,)).fetchone()[0]
        if start is None or start > at:
            return f"{table}: price change log started after the run ({start})"
        if conn.execute("""SELECT 1 FROM price_change_log WHERE table_name = %s AND op = 'TRUNCATE'
                           AND changed_at > %s LIMIT 1""", (table, at)).fetchone():
            return f"{table}: truncated after the run; earlier rows are not recoverable"
    return None


def _shadow(conn: psycopg.Connection, table: str, key: str, at: datetime, lo: str, hi: str) -> None:
    """Temporary `table` holding its rows as they stood at `at` (for trade dates lo..hi)."""
    conn.execute(f"CREATE TEMP TABLE {table} (LIKE public.{table}) ON COMMIT DROP")
    conn.execute(f"""
        INSERT INTO pg_temp.{table} ({key}, trade_date, {_COLS}, ingested_at)
        WITH ev AS (
          SELECT DISTINCT ON (key, trade_date) key, trade_date, op, old_open, old_high, old_low, old_close,
                 old_volume, old_provenance, old_source
          FROM price_change_log
          WHERE table_name = %(t)s AND op IN ('INSERT', 'UPDATE', 'DELETE') AND changed_at > %(at)s
            AND trade_date BETWEEN %(lo)s AND %(hi)s
          ORDER BY key, trade_date, changed_at, id)
        SELECT p.{key}, p.trade_date, p.open, p.high, p.low, p.close, p.volume, p.provenance, p.source, p.ingested_at
        FROM public.{table} p
        LEFT JOIN ev ON ev.key = p.{key} AND ev.trade_date = p.trade_date
        WHERE ev.key IS NULL AND p.trade_date BETWEEN %(lo)s AND %(hi)s
        UNION ALL
        SELECT key, trade_date, old_open, old_high, old_low, old_close, old_volume, old_provenance::data_provenance,
               old_source, %(at)s
        FROM ev WHERE op IN ('UPDATE', 'DELETE')""", {"t": table, "at": at, "lo": lo, "hi": hi})


def _config(conn: psycopg.Connection, version: str, digest: str):
    stored = conn.execute("SELECT config FROM scoring_config_versions WHERE version = %s", (version,)).fetchone()
    for cfg in (default_config(), stored[0] if stored else None):
        if cfg is not None and cfg.get("version") == version and config_sha256(cfg) == digest:
            return cfg
    return None


def verify_run(conn: psycopg.Connection, run_id: int, *, store: bool = True, code: CodeInfo | None = None) -> Verification:
    try:
        v = _verify(conn, run_id)
    except Exception as exc:  # noqa: BLE001 - reported as a status, never as a pass
        log.exception("verification of run %s failed", run_id)
        v = Verification(run_id, "VERIFICATION_FAILED", detail={"error": f"{type(exc).__name__}: {exc}"})
    if store:
        code = code or code_info()
        with conn.transaction():
            conn.execute("""INSERT INTO run_verifications (run_id, status, inputs_source, code_commit, code_dirty, detail)
                            VALUES (%s, %s, %s, %s, %s, %s)""",
                         (run_id, v.status, v.inputs_source, code.commit, code.dirty, Jsonb(v.detail)))
    return v


def _verify(conn: psycopg.Connection, run_id: int) -> Verification:
    if not conn.autocommit:
        # The reconstruction's temporary tables must be dropped at the end of their own transaction; inside an
        # outer transaction they would shadow the real price tables for the rest of it.
        raise RuntimeError("verify_run needs an autocommit connection")
    run = conn.execute("""SELECT record_kind, as_of::text, inputs_loaded_at, config_version, config_sha256, code_commit,
                                 lookback_bars, input_hash, input_manifest, output_hash
                          FROM recommendation_runs WHERE run_id = %s""", (run_id,)).fetchone()
    if run is None:
        return Verification(run_id, "VERIFICATION_FAILED", detail={"error": "no tracking record for this run"})
    kind, as_of, at, version, cfg_sha, commit, lookback, in_hash, recorded, out_hash = run
    if recorded is None:
        return Verification(run_id, "INSUFFICIENT_INPUT_HISTORY",
                            detail={"reason": f"{kind} record has no input manifest; inputs cannot be identified"})
    cfg = _config(conn, version, cfg_sha)
    if cfg is None:
        return Verification(run_id, "VERIFICATION_FAILED", detail={"error": f"configuration {version} not available"})

    market = load_market(conn, as_of, lookback)
    current = M.build_manifest(market, lookback)
    source = "CURRENT"
    if M.input_hash(current) != in_hash:
        changed = M.diff(recorded, current)
        why = log_coverage(conn, at)
        if why:
            return Verification(run_id, "INSUFFICIENT_INPUT_HISTORY", detail={"reason": why, "changed_now": changed})
        firsts = [v["bars"]["first"] for v in recorded["stocks"].values() if v["bars"]["first"]]
        firsts += [v["first"] for v in recorded["indices"].values() if v["first"]]
        lo = min(firsts) if firsts else as_of
        try:
            with conn.transaction():
                _shadow(conn, "daily_prices", "symbol", at, lo, as_of)
                _shadow(conn, "index_prices", "index_code", at, lo, as_of)
                market = load_market(conn, as_of, lookback)
        except LookupError as exc:
            return Verification(run_id, "INSUFFICIENT_INPUT_HISTORY",
                                detail={"reason": f"reconstruction incomplete: {exc}", "changed_now": changed})
        rebuilt = M.build_manifest(market, lookback)
        if M.input_hash(rebuilt) != in_hash:
            remaining = M.diff(recorded, rebuilt)
            if "bars" in remaining or "indices" in remaining:
                # Prices are logged, so a price difference left after reconstruction means the log is incomplete
                # (chunks dropped, triggers disabled, rows changed outside the triggers).
                return Verification(run_id, "INSUFFICIENT_INPUT_HISTORY", detail={
                    "reason": "price rows changed without being recorded in price_change_log",
                    "still_different_after_reconstruction": remaining, "changed_now": changed})
            return Verification(run_id, "INPUTS_CHANGED", detail={
                "still_different_after_reconstruction": remaining, "changed_now": changed,
                "note": "only daily_prices and index_prices are logged; securities, fundamentals and events are not"})
        source = "RECONSTRUCTED"

    result = score_universe(market, cfg)
    if M.output_hash(result) == out_hash:
        return Verification(run_id, "REPRODUCED", source, {"recorded_commit": commit})
    stored = dict(conn.execute("SELECT symbol, result_sha256 FROM recommendation_scores WHERE run_id = %s", (run_id,)))
    now = {s["symbol"]: M.result_hash(s) for s in result["stocks"]}
    differing = sorted(s for s in set(stored) | set(now) if stored.get(s) != now.get(s))
    return Verification(run_id, "CODE_CHANGED", source, {
        "recorded_commit": commit, "stocks_with_different_results": differing[:50], "n_different": len(differing),
        "market_outputs_differ": not differing})
