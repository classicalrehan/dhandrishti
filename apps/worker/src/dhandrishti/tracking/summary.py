"""Track-record summary: what the recorded outcomes do and do not show (docs/recommendation-tracking.md).

Only LIVE runs form the official track record; other kinds can be summarised for debugging but are labelled.
Per run, the recommended stocks form one equal-weight basket; statistics are over runs, not stock-rows.
Overlapping windows (a run every day, 60-session horizon) are not independent, so the headline sample size is
the number of NON-overlapping runs (each entry at least `horizon` sessions after the previous one). Fewer than
MIN_PERIODS of them is reported as INSUFFICIENT_EVIDENCE: a display threshold, not a significance test.
"""

import bisect
import math
import statistics
from collections import Counter

import numpy as np
import psycopg

from ..research.factors import newey_west_t
from .outcomes import METHOD_V1

MIN_PERIODS = 12
VALID = ("COMPLETE",)
RETURN_BASIS = "HYPOTHETICAL_RECOMMENDATION"
BASIS_NOTE = (
    "Hypothetical recommendation returns: each run's recommended stocks bought at the next open on a fixed "
    "Rs 20,000 notional with fractional shares and held a fixed number of sessions. These are NOT paper-portfolio "
    "results (actual simulated trades: `pnpm paper`, tables paper_*) and NOT backtests (historical simulations: "
    "`pnpm backtest`, tables backtest_*).")
LIMITATIONS = (
    "Overlapping windows: consecutive runs share most of their holding period; only the non-overlapping count is "
    "an honest sample size.",
    "Returns are price-only (dividends excluded) and NIFTY 50 is the price index, not total return.",
    "Slippage per side is an assumption, not a measured execution cost; see the sensitivity rows.",
    "The equal-weight benchmark is today's NIFTY 200 universe as scored in each run.",
    "Scores are price-only while fundamentals are missing (55 of 100 points neutral).",
)


def _stats(x: list[float]) -> dict:
    if not x:
        return {"n": 0}
    sd = statistics.stdev(x) if len(x) > 1 else None
    return {"n": len(x), "mean": statistics.fmean(x), "median": statistics.median(x), "std": sd,
            "t": statistics.fmean(x) / (sd / math.sqrt(len(x))) if sd else None,
            "hit_rate": sum(v > 0 for v in x) / len(x)}


def _mean(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r[key] is not None]
    return statistics.fmean(vals) if vals else None


def track_record(conn: psycopg.Connection, horizon: int, *, kind: str = "LIVE",
                 method: str = METHOD_V1["version"]) -> dict:
    cal = [r[0] for r in conn.execute(
        "SELECT trade_date::text FROM index_prices WHERE index_code = 'NIFTY 50' ORDER BY trade_date")]
    runs = conn.execute("""SELECT run_id, as_of::text FROM recommendation_runs WHERE record_kind = %s
                           ORDER BY as_of, run_id""", (kind,)).fetchall()
    missing = missing_records(conn)
    out = {"horizon": horizon, "record_kind": kind, "official": kind == "LIVE", "return_basis": RETURN_BASIS,
           "method": method, "runs_recorded": len(runs),
           "succeeded_runs_without_record": len(missing["after_install"]) + len(missing["before_install"]),
           "missing_records_since_install": len(missing["after_install"]), "runs_pending": 0,
           "runs_matured": 0, "recommended_status": Counter(), "excluded_candidates": Counter(),
           "excluded_status": Counter(), "limitations": list(LIMITATIONS)}
    per_run = []
    for run_id, as_of in runs:
        rows = conn.execute("""
            SELECT s.selection, s.exclusion_reasons, o.status, o.gross_return, o.net_return, o.net_return_no_slippage,
                   o.slippage_sensitivity, o.excess_vs_nifty, o.excess_vs_universe, o.max_adverse_excursion,
                   o.mae_reliable
            FROM recommendation_scores s
            LEFT JOIN recommendation_outcome_latest o
              ON o.run_id = s.run_id AND o.symbol = s.symbol AND o.horizon = %s AND o.method_version = %s
            WHERE s.run_id = %s AND s.selection <> 'NOT_CANDIDATE'""", (horizon, method, run_id)).fetchall()
        keys = ("selection", "reasons", "status", "gross", "net", "net0", "sens", "x_nifty", "x_univ", "mae", "mae_ok")
        rows = [dict(zip(keys, r)) for r in rows]
        if not conn.execute("""SELECT 1 FROM recommendation_outcomes WHERE run_id = %s AND horizon = %s
                               AND method_version = %s LIMIT 1""", (run_id, horizon, method)).fetchone():
            out["runs_pending"] += 1
            continue
        out["runs_matured"] += 1
        rec = [r for r in rows if r["selection"] == "RECOMMENDED"]
        exc = [r for r in rows if r["selection"] == "EXCLUDED_CANDIDATE"]
        out["recommended_status"].update(r["status"] for r in rec)
        out["excluded_status"].update(r["status"] for r in exc)
        for r in exc:
            out["excluded_candidates"].update(r["reasons"])
        ok = [r for r in rec if r["status"] in VALID]
        ok_exc = [r for r in exc if r["status"] in VALID]
        per_run.append({
            "run_id": run_id, "as_of": as_of, "entry_index": bisect.bisect_right(cal, as_of),
            "n_recommended": len(rec), "n_valid": len(ok),
            "gross": _mean(ok, "gross"), "net": _mean(ok, "net"), "net0": _mean(ok, "net0"),
            "net_10": _mean([{"v": r["sens"].get("10")} for r in ok], "v") if ok else None,
            "net_25": _mean([{"v": r["sens"].get("25")} for r in ok], "v") if ok else None,
            "x_nifty": _mean(ok, "x_nifty"), "x_univ": _mean(ok, "x_univ"),
            "mae": _mean([r for r in ok if r["mae_ok"]], "mae"),
            "excluded_x_nifty": _mean(ok_exc, "x_nifty"),
        })
    chosen, last = [], None
    for p in per_run:
        if p["n_valid"] and (last is None or p["entry_index"] >= last + horizon):
            chosen.append(p)
            last = p["entry_index"]
    valid_runs = [p for p in per_run if p["n_valid"]]

    def col(ps, k):
        return [p[k] for p in ps if p[k] is not None]

    out["non_overlapping_periods"] = len(chosen)
    out["evidence"] = "INSUFFICIENT_EVIDENCE" if len(chosen) < MIN_PERIODS else "MINIMUM_SAMPLE_REACHED"
    out["non_overlapping"] = {k: _stats(col(chosen, k)) for k in ("gross", "net", "x_nifty", "x_univ")}
    out["all_runs"] = {k: _stats(col(valid_runs, k)) for k in ("gross", "net0", "net", "net_10", "net_25",
                                                              "x_nifty", "x_univ", "mae", "excluded_x_nifty")}
    for k in ("x_nifty", "x_univ"):
        x = np.array(col(valid_runs, k), dtype=float)
        out["all_runs"][k]["t_newey_west"] = newey_west_t(x, horizon) if len(x) else None
    out["recommended_status"] = dict(out["recommended_status"])
    out["excluded_status"] = dict(out["excluded_status"])
    out["excluded_candidates"] = dict(out["excluded_candidates"])
    return out


def format_report(s: dict) -> str:
    def pct(v):
        return "—" if v is None else f"{v * 100:+.2f}%"

    lines = [f"HYPOTHETICAL RECOMMENDATION RETURNS: {s['horizon']} sessions, {s['record_kind']} runs"
             + ("" if s["official"] else "  (NOT the official track record)"),
             f"  {BASIS_NOTE}",
             f"  evidence: {s['evidence']} ({s['non_overlapping_periods']} non-overlapping periods; "
             f"{MIN_PERIODS} needed to display conclusions, which is not a significance test)",
             f"  runs recorded {s['runs_recorded']}, matured {s['runs_matured']}, pending {s['runs_pending']}; "
             f"successful scoring runs with no tracking record: {s['succeeded_runs_without_record']} "
             f"({s['missing_records_since_install']} since tracking was installed; see `jobs.tracking status`)",
             f"  recommended outcomes by status: {s['recommended_status'] or '{}'}",
             f"  excluded candidates by reason: {s['excluded_candidates'] or '{}'}; their outcomes: "
             f"{s['excluded_status'] or '{}'}"]
    if s["evidence"] == "INSUFFICIENT_EVIDENCE":
        lines.append("  No conclusion can be drawn. Figures below are descriptive only.")
    a = s["all_runs"]
    for label, k in (("gross", "gross"), ("net, no slippage", "net0"), ("net, base slippage", "net"),
                     ("net, 10 bps slippage", "net_10"), ("net, 25 bps slippage", "net_25"),
                     ("excess vs NIFTY 50", "x_nifty"), ("excess vs equal-weight universe", "x_univ"),
                     ("max adverse excursion (reliable only)", "mae"),
                     ("excluded candidates: excess vs NIFTY", "excluded_x_nifty")):
        st = a.get(k, {"n": 0})
        extra = f", Newey-West t {st['t_newey_west']:.2f}" if st.get("t_newey_west") is not None else ""
        lines.append(f"  {label:<40} runs {st['n']:>4}  mean {pct(st.get('mean'))}"
                     + (f"  hit rate {st['hit_rate']:.0%}" if st.get("hit_rate") is not None else "") + extra)
    lines.append("  Limitations:")
    lines += [f"    - {t}" for t in s["limitations"]]
    return "\n".join(lines)


# ---------------------------------------------------------------- operational status

def installed_at(conn: psycopg.Connection):
    return conn.execute("SELECT min(changed_at) FROM price_change_log WHERE op = 'LOG_START'").fetchone()[0]


def missing_records(conn: psycopg.Connection) -> dict:
    """Successful scoring runs with no tracking record, split by whether tracking existed when they ran."""
    since = installed_at(conn)
    rows = conn.execute("""
        SELECT r.id, r.as_of::text, r.started_at,
               EXISTS (SELECT 1 FROM score_history h WHERE h.run_id = r.id) AS rows_survive,
               (SELECT count(*) FROM tracking_failures f WHERE f.run_id = r.id) AS failures,
               (SELECT f.diagnostic FROM tracking_failures f WHERE f.run_id = r.id ORDER BY f.id DESC LIMIT 1)
        FROM scoring_runs r
        WHERE r.status = 'SUCCEEDED' AND NOT EXISTS (SELECT 1 FROM recommendation_runs t WHERE t.run_id = r.id)
        ORDER BY r.id""").fetchall()
    out = {"after_install": [], "before_install": []}
    for run_id, as_of, started, survive, failures, diagnostic in rows:
        item = {"run_id": run_id, "as_of": as_of, "score_history_rows_survive": survive, "failures": failures,
                "last_diagnostic": diagnostic}
        out["after_install" if since is not None and started >= since else "before_install"].append(item)
    return out


def operational_status(conn: psycopg.Connection) -> dict:
    """Is tracking keeping up with scoring? `healthy` is False when a run since installation has no record."""
    missing = missing_records(conn)
    failures = conn.execute("""
        SELECT f.run_id, f.stage, f.error_type, f.diagnostic, f.occurred_at,
               EXISTS (SELECT 1 FROM recommendation_runs t WHERE t.run_id = f.run_id) AS resolved
        FROM tracking_failures f ORDER BY f.id""").fetchall()
    kinds = dict(conn.execute("SELECT record_kind, count(*) FROM recommendation_runs GROUP BY 1").fetchall())
    latest = conn.execute("""SELECT run_id, as_of::text, record_kind, qualification_failures FROM recommendation_runs
                             ORDER BY run_id DESC LIMIT 1""").fetchone()
    latest_live = conn.execute("SELECT max(as_of)::text FROM recommendation_runs WHERE record_kind = 'LIVE'").fetchone()[0]
    verif = dict(conn.execute("""SELECT status, count(*) FROM (SELECT DISTINCT ON (run_id) status FROM run_verifications
                                 ORDER BY run_id, id DESC) v GROUP BY 1""").fetchall())
    failed_scoring = conn.execute("SELECT count(*) FROM scoring_runs WHERE status = 'FAILED'").fetchone()[0]
    unresolved = [f for f in failures if not f[5]]
    return {
        "installed_at": installed_at(conn),
        "records_by_kind": kinds,
        "latest_record": latest and {"run_id": latest[0], "as_of": latest[1], "kind": latest[2], "failures": latest[3]},
        "latest_live_as_of": latest_live,
        "missing_records_since_install": missing["after_install"],
        "unrecorded_runs_before_install": missing["before_install"],
        "recorder_failures": len(failures),
        "unresolved_failures": [{"run_id": f[0], "stage": f[1], "error_type": f[2], "diagnostic": f[3],
                                 "occurred_at": f[4]} for f in unresolved],
        "latest_verification_by_status": verif,
        "failed_scoring_runs": failed_scoring,
        "healthy": not missing["after_install"] and not unresolved,
    }


def format_status(st: dict) -> str:
    lines = [f"Tracking status: {'OK' if st['healthy'] else 'ATTENTION NEEDED'}",
             f"  installed {st['installed_at']}; records by kind {st['records_by_kind'] or '{}'}; "
             f"latest LIVE as_of {st['latest_live_as_of'] or 'none yet'}"]
    if st["latest_record"]:
        r = st["latest_record"]
        lines.append(f"  latest record: run {r['run_id']} ({r['as_of']}) {r['kind']}"
                     + (f", failures {', '.join(r['failures'])}" if r["failures"] else ""))
    for m in st["missing_records_since_install"]:
        lines.append(f"  MISSING: run {m['run_id']} ({m['as_of']}) has no tracking record; {m['failures']} failure(s). "
                     + (m["last_diagnostic"] or "No failure was stored: check the scoring log, then retry with "
                        f"`jobs.tracking record {m['run_id']}`."))
    for f in st["unresolved_failures"]:
        lines.append(f"  FAILURE: run {f['run_id']} {f['stage']} {f['error_type']} at {f['occurred_at']}: {f['diagnostic']}")
    if st["unrecorded_runs_before_install"]:
        ids = [m["run_id"] for m in st["unrecorded_runs_before_install"]]
        lines.append(f"  {len(ids)} run(s) predate tracking ({ids}); `jobs.tracking backfill --apply` copies those still "
                     "in score_history as BACKFILLED (never LIVE)")
    lines.append(f"  recorder failures stored: {st['recorder_failures']} ({len(st['unresolved_failures'])} unresolved); "
                 f"failed scoring runs: {st['failed_scoring_runs']}; latest verification per run: "
                 f"{st['latest_verification_by_status'] or '{}'}")
    return "\n".join(lines)
