"""Append-only records of scoring runs (staged migration 0010; docs/recommendation-tracking.md).

`record_if_installed` is called by run_scoring after a run has succeeded, in its own transaction:
  * it does nothing when the tracking tables are absent (every database until 0010 is promoted);
  * it never changes or fails the scoring run: an error is logged and the run simply has no record,
    which the track-record summary reports as a gap.

A run qualifies as LIVE only when every check passes; otherwise it is recorded as DEVELOPMENT (or REPLAY
when it was scored after the next session had opened), with the failed checks listed.
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

import psycopg
from psycopg.types.json import Jsonb

from ..calendar import is_trading_day
from ..config import Config
from ..db.score_repository import config_sha256
from ..models import MarketInput
from ..paths import NSE_HOLIDAYS_PATH, REPO_ROOT
from . import manifest as M
from . import policy as P

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CLOSE = time(15, 30)
SETTLED = time(16, 30)       # same 60-minute settlement as calendar.last_completed_session
OPEN = time(9, 15)


@dataclass(frozen=True)
class CodeInfo:
    commit: str | None
    dirty: bool | None


def code_info() -> CodeInfo:
    """Current git commit, and whether the working tree has any change (tracked or untracked, not ignored)."""
    try:
        commit = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True, timeout=10).stdout.strip()
        status = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True,
                                text=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return CodeInfo(None, None)
    return CodeInfo(commit or None, bool(status.strip()))


@lru_cache(maxsize=1)
def _calendar_years() -> frozenset[int]:
    return frozenset(int(y) for y in json.loads(NSE_HOLIDAYS_PATH.read_text(encoding="utf-8"))["years"])


def next_session(as_of: str) -> str | None:
    """The trading session after `as_of`, or None when the holiday calendar does not cover it."""
    d = date.fromisoformat(as_of)
    for _ in range(15):
        d += timedelta(days=1)
        if d.year not in _calendar_years():
            return None
        if is_trading_day(d.isoformat()):
            return d.isoformat()
    return None


def at_ist(day: str, t: time) -> datetime:
    return datetime.combine(date.fromisoformat(day), t, IST)


def qualify(*, as_of: str, provenance: str, nifty_last: str | None, inputs_loaded_at: datetime,
            scored_at: datetime, entry_session: str | None, code: CodeInfo) -> tuple[str, list[str]]:
    failures = []
    if provenance == "MOCK":
        failures.append("MOCK_DATA")
    if code.commit is None:
        failures.append("NO_GIT_COMMIT")
    if code.dirty is not False:
        failures.append("UNCOMMITTED_CODE")
    if inputs_loaded_at < at_ist(as_of, SETTLED):
        failures.append("INPUTS_BEFORE_SETTLEMENT")
    if nifty_last != as_of:
        failures.append("NIFTY_NOT_UPDATED")
    if entry_session is None:
        failures.append("CALENDAR_UNKNOWN")
        # Without holidays the next session is still no later than a week after the next weekday (NSE never
        # closes that long), so a run scored after that is certainly retrospective.
        nxt = date.fromisoformat(as_of) + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        if scored_at >= at_ist((nxt + timedelta(days=7)).isoformat(), OPEN):
            failures.append("SCORED_AFTER_NEXT_OPEN")
    elif scored_at >= at_ist(entry_session, OPEN):
        failures.append("SCORED_AFTER_NEXT_OPEN")
    kind = "REPLAY" if "SCORED_AFTER_NEXT_OPEN" in failures else "DEVELOPMENT" if failures else "LIVE"
    return kind, failures


def tables_installed(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT to_regclass('recommendation_runs')").fetchone()[0] is not None


def _insert_scores(conn: psycopg.Connection, run_id: int, stocks: list[dict], last_bars: dict[str, str | None],
                   policy: dict) -> int:
    rows = []
    for s in stocks:
        eligible, reasons, selection = P.select(s, policy)
        rows.append((run_id, s["symbol"], s["rank"], s["total_score"], s["confidence"], s["data_coverage"],
                     s["risk_level"], s["risk_points"], Jsonb({k: c["score"] for k, c in s["components"].items()}),
                     Jsonb({k: c["coverage"] for k, c in s["components"].items()}), last_bars.get(s["symbol"]),
                     eligible, reasons, selection, Jsonb(s), M.result_hash(s)))
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO recommendation_scores (run_id, symbol, rank, total_score, confidence, data_coverage, risk_level,
              risk_points, component_scores, component_coverage, last_bar_date, eligible, exclusion_reasons,
              selection, result, result_sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", rows)
    return len(rows)


def record_run(conn: psycopg.Connection, run_id: int, market: MarketInput, result: dict, cfg: Config,
               inputs_loaded_at: datetime, lookback_bars: int, *, code: CodeInfo | None = None,
               policy: dict = P.POLICY_V1, scored_at: datetime | None = None,
               extra_failures: tuple[str, ...] = ()) -> str:
    """Insert the run and its per-stock scores in one transaction. Returns the record kind.

    `extra_failures` are added to the qualification failures (a record with any failure is never LIVE).
    `scored_at` exists for tests that need a past evening; production always uses the database clock."""
    code = code or code_info()
    man = M.build_manifest(market, lookback_bars)
    if (latest := M.latest_bar(man)) and latest > market.as_of:
        raise RuntimeError(f"run {run_id}: input bar dated {latest} is after as_of {market.as_of} (look-ahead)")
    with conn.transaction():
        if conn.execute("SELECT 1 FROM recommendation_runs WHERE run_id = %s", (run_id,)).fetchone():
            raise AlreadyRecorded(f"run {run_id} already has a tracking record")
        version = P.register(conn, policy)
        scored_at = scored_at or conn.execute("SELECT clock_timestamp()").fetchone()[0]
        entry = next_session(market.as_of)
        kind, failures = qualify(as_of=market.as_of, provenance=result["data_provenance"],
                                 nifty_last=market.nifty.dates[-1] if len(market.nifty) else None,
                                 inputs_loaded_at=inputs_loaded_at, scored_at=scored_at, entry_session=entry,
                                 code=code)
        failures += [f for f in extra_failures if f not in failures]
        if failures and kind == "LIVE":
            kind = "DEVELOPMENT"
        conn.execute("""
            INSERT INTO recommendation_runs (run_id, record_kind, qualification_failures, as_of, decision_at,
              inputs_loaded_at, scored_at, entry_session, entry_deadline, config_version, config_sha256, code_commit,
              code_dirty, lookback_bars, input_hash, input_manifest, output_hash, data_provenance, scored_count,
              regime, breadth, sectors, policy_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, kind, failures, market.as_of, at_ist(market.as_of, CLOSE), inputs_loaded_at, scored_at, entry,
             at_ist(entry, OPEN) if entry else None, cfg["version"], config_sha256(cfg), code.commit, code.dirty,
             lookback_bars, M.input_hash(man), Jsonb(man), M.output_hash(result), result["data_provenance"],
             len(result["stocks"]), Jsonb(result["regime"]), Jsonb(result["breadth"]), Jsonb(result["sectors"]),
             version))
        _insert_scores(conn, run_id, result["stocks"], {s: v["bars"]["last"] for s, v in man["stocks"].items()},
                       policy)
    log.info("recorded run %s as %s%s", run_id, kind, f" ({', '.join(failures)})" if failures else "")
    return kind


def record_if_installed(conn: psycopg.Connection, run_id: int, market: MarketInput, result: dict, cfg: Config,
                        inputs_loaded_at: datetime, lookback_bars: int) -> str | None:
    """Never raises: recording must not change the outcome of a scoring run."""
    try:
        if not tables_installed(conn):
            return None
        return record_run(conn, run_id, market, result, cfg, inputs_loaded_at, lookback_bars)
    except Exception as exc:  # noqa: BLE001 - a recording failure is logged, never propagated into scoring
        diagnostic = diagnose(exc, run_id)
        log.exception("run %s: could not record the scoring run for tracking (scores are unaffected). %s",
                      run_id, diagnostic)
        log_failure(conn, run_id, "RECORD", exc, diagnostic)
        return None


class AlreadyRecorded(RuntimeError):
    pass


class RetryRefused(RuntimeError):
    pass


def retry_command(run_id: int) -> str:
    return f"cd apps/worker && uv run python -m dhandrishti.jobs.tracking record {run_id}"


def diagnose(exc: BaseException, run_id: int) -> str:
    """What went wrong and what to do about it, in one line."""
    msg = str(exc)
    if isinstance(exc, (AlreadyRecorded, psycopg.errors.UniqueViolation)):
        return "The run already has a tracking record; nothing to do."
    if "look-ahead" in msg:
        return ("An input bar is dated after as_of: check the ingested prices and the --as-of date. Do not retry "
                "until the data is explained.")
    if "differs from the stored copy" in msg:
        return "A tracking policy or outcome method changed without a new version: give it a new version, then retry: " \
               + retry_command(run_id)
    if isinstance(exc, (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn,
                        psycopg.errors.UndefinedFunction)):
        return "The tracking schema differs from staged migration 0010: compare schema_migrations and the migration file."
    if isinstance(exc, psycopg.OperationalError):
        return "Database connection problem. When the database is reachable, retry: " + retry_command(run_id)
    return f"Unexpected {type(exc).__name__}. Fix the cause, then retry: " + retry_command(run_id)


def log_failure(conn: psycopg.Connection, run_id: int, stage: str, exc: BaseException, diagnostic: str) -> None:
    """Best effort: a failure to store the failure is logged and swallowed."""
    try:
        with conn.transaction():
            conn.execute("""INSERT INTO tracking_failures (run_id, stage, error_type, error_message, diagnostic, code_commit)
                            VALUES (%s, %s, %s, %s, %s, %s)""",
                         (run_id, stage, type(exc).__name__, str(exc)[:2000], diagnostic, code_info().commit))
    except Exception:  # noqa: BLE001
        log.exception("run %s: could not store the tracking failure either", run_id)


def retry_record(conn: psycopg.Connection, run_id: int, *, code: CodeInfo | None = None,
                 lookback_bars: int = 300) -> str:
    """Record a successful scoring run that has no tracking record (e.g. after a recorder failure).

    The inputs are reloaded now, so the record can only be trusted if re-scoring reproduces exactly what the run
    stored in score_history; otherwise it is refused. A retried record always carries RECORDED_BY_RETRY and is
    never LIVE. Idempotent: an existing record is left alone. Returns the record kind or ALREADY_RECORDED."""
    from ..config import default_config
    from ..db.market_repository import load_market
    from ..scoring import score_universe

    if conn.execute("SELECT 1 FROM recommendation_runs WHERE run_id = %s", (run_id,)).fetchone():
        return "ALREADY_RECORDED"
    try:
        run = conn.execute("""SELECT as_of::text, status, config_version FROM scoring_runs WHERE id = %s""",
                           (run_id,)).fetchone()
        if run is None or run[1] != "SUCCEEDED":
            raise RetryRefused(f"run {run_id} is not a successful scoring run")
        as_of, _, version = run
        cfg = default_config()
        stored_sha = conn.execute("SELECT config_sha256 FROM scoring_config_versions WHERE version = %s",
                                  (version,)).fetchone()
        if cfg["version"] != version or not stored_sha or config_sha256(cfg) != stored_sha[0]:
            raise RetryRefused(f"the current scoring configuration is not {version} as used by run {run_id}")
        stored = {s: r for s, r in conn.execute("SELECT symbol, result FROM score_history WHERE run_id = %s", (run_id,))}
        if not stored:
            raise RetryRefused(f"score_history no longer holds run {run_id} (a later run on the same day overwrote "
                               "it), so its output cannot be confirmed")
        inputs_loaded_at = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        market = load_market(conn, as_of, lookback_bars)
        result = score_universe(market, cfg)
        if {s["symbol"]: s for s in result["stocks"]} != stored:
            raise RetryRefused(f"re-scoring {as_of} now does not reproduce run {run_id}'s stored scores (inputs or code "
                               "changed since), so a faithful record cannot be made")
        return record_run(conn, run_id, market, result, cfg, inputs_loaded_at, lookback_bars, code=code,
                          extra_failures=("RECORDED_BY_RETRY",))
    except AlreadyRecorded:
        return "ALREADY_RECORDED"
    except Exception as exc:
        diagnostic = (f"Retry refused: {exc}" if isinstance(exc, RetryRefused) else diagnose(exc, run_id))
        log_failure(conn, run_id, "RETRY", exc, diagnostic)
        raise


def backfill_from_score_history(conn: psycopg.Connection, policy: dict = P.POLICY_V1) -> list[int]:
    """Copy runs that survive in score_history into the tracking tables as BACKFILLED (no manifest).

    Only rows still pointing at a run are copied; a run whose rows were overwritten by a later run on the same
    day no longer exists in score_history and cannot be recovered. Insert-only and idempotent."""
    done = []
    runs = conn.execute("""
        SELECT r.id, r.as_of::text, r.config_version, r.provenance::text, r.finished_at
        FROM scoring_runs r
        WHERE r.status = 'SUCCEEDED' AND EXISTS (SELECT 1 FROM score_history h WHERE h.run_id = r.id)
          AND NOT EXISTS (SELECT 1 FROM recommendation_runs t WHERE t.run_id = r.id)
        ORDER BY r.id""").fetchall()
    for run_id, as_of, version, prov, finished in runs:
        with conn.transaction():
            pv = P.register(conn, policy)
            stocks = [r[0] for r in conn.execute(
                "SELECT result FROM score_history WHERE run_id = %s ORDER BY rank", (run_id,))]
            reg = conn.execute("""SELECT regime, composite, confidence, factors, reason, breadth
                                  FROM market_regime_history WHERE run_id = %s""", (run_id,)).fetchone()
            sectors = [r[0] for r in conn.execute(
                "SELECT detail FROM sector_strength_history WHERE run_id = %s ORDER BY rank", (run_id,))]
            cfg_sha = conn.execute("SELECT config_sha256 FROM scoring_config_versions WHERE version = %s",
                                   (version,)).fetchone()[0]
            entry = next_session(as_of)
            regime = ({"regime": reg[0], "composite": reg[1], "confidence": reg[2], "factors": reg[3],
                       "reason": reg[4]} if reg else {})
            conn.execute("""
                INSERT INTO recommendation_runs (run_id, record_kind, qualification_failures, as_of, decision_at,
                  scored_at, entry_session, entry_deadline, config_version, config_sha256, data_provenance,
                  scored_count, regime, breadth, sectors, policy_version)
                VALUES (%s, 'BACKFILLED', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (run_id, ["BACKFILLED"], as_of, at_ist(as_of, CLOSE), finished, entry,
                 at_ist(entry, OPEN) if entry else None, version, cfg_sha, prov, len(stocks), Jsonb(regime),
                 Jsonb(reg[5] if reg else {}), Jsonb(sectors), pv))
            _insert_scores(conn, run_id, stocks, {}, policy)
        done.append(run_id)
    return done
