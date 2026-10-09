"""Data-quality checks over stored observations, for the pilot report. Read-only.

Checks (all computed from the database, nothing assumed):
  coverage        metrics and periods per stock; quarters of history per flow metric
  dates           share of rows with exact / dated / estimated / unknown availability; reporting lag
  conflicts       same figure (key without source) with different latest values across sources
  versions        restatements (issuer re-published) and corrections (capture fixed)
  consistency     Q1+Q2+Q3+Q4 against the FY figure for revenue and net profit (same source and basis)
  reconstruction  for each score input: are its metrics present with strict point-in-time dates
                  and enough quarters of history as of the latest data?
"""

from collections import defaultdict
import psycopg

from .availability import IST, STRICT_BASES, statutory_deadline
from .metrics import HISTORY_QUARTERS, METRICS, SCORE_INPUTS
from .store import COLUMNS, Observation, _row

CONFLICT_TOL = 0.005  # 0.5% relative difference
SUM_TOL = 0.01        # quarters vs full year: 1%


def load_latest(conn: psycopg.Connection, symbols: list[str] | None) -> list[Observation]:
    """Latest version of every key (all sources), for quality checks."""
    rows = conn.execute(f"""
        SELECT DISTINCT ON (symbol, metric, basis, period_type, period_end, source) {', '.join(COLUMNS)}
        FROM fundamental_observations WHERE (%s::text[] IS NULL OR symbol = ANY(%s::text[]))
        ORDER BY symbol, metric, basis, period_type, period_end, source, data_version DESC""",
        (symbols, symbols)).fetchall()
    return [_row(r) for r in rows]


def version_stats(conn: psycopg.Connection, symbols: list[str] | None) -> dict:
    r = conn.execute("""
        SELECT count(*), count(*) FILTER (WHERE data_version > 1), count(*) FILTER (WHERE is_restatement),
               count(DISTINCT import_batch_id)
        FROM fundamental_observations WHERE (%s::text[] IS NULL OR symbol = ANY(%s::text[]))""",
        (symbols, symbols)).fetchone()
    return {"rows": r[0], "later_versions": r[1], "restatements": r[2], "corrections": r[1] - r[2], "batches": r[3]}


def _q_count(obs: list[Observation], metric: str, strict: bool) -> int:
    return len({o.period_end for o in obs if o.metric == metric and o.period_type == "Q"
                and (not strict or (o.availability_basis in STRICT_BASES and o.value_vintage == "AS_REPORTED"))})


def analyse(conn: psycopg.Connection, symbols: list[str]) -> dict:
    obs = load_latest(conn, symbols)
    by_sym: dict[str, list[Observation]] = defaultdict(list)
    for o in obs:
        by_sym[o.symbol].append(o)

    stocks = {}
    for s in symbols:
        os_ = by_sym.get(s, [])
        ends = sorted(o.period_end for o in os_)
        strict = [o for o in os_ if o.availability_basis in STRICT_BASES and o.value_vintage == "AS_REPORTED"]
        inputs = {}
        for name, needs in SCORE_INPUTS.items():
            have = all(any(o.metric == m for o in strict) for m in needs)
            q_needed = HISTORY_QUARTERS.get(name, 4)
            flow = [m for m in needs if "Q" in METRICS[m].period_types]
            q_have = min((_q_count(os_, m, True) for m in flow), default=None)
            inputs[name] = "yes" if have and (q_have is None or q_have >= q_needed) else \
                "partial" if have else "no"
        stocks[s] = {
            "rows": len(os_),
            "metrics": sorted({o.metric for o in os_}),
            "missing_metrics": sorted(set(METRICS) - {o.metric for o in os_}),
            "first_period": str(ends[0]) if ends else None,
            "last_period": str(ends[-1]) if ends else None,
            "quarters_revenue": _q_count(os_, "revenue", False),
            "quarters_eps": _q_count(os_, "eps_diluted", False),
            "strict_rows": len(strict),
            "inputs": inputs,
        }

    basis_count = defaultdict(int)
    vintage_count = defaultdict(int)
    lags, late = [], []
    for o in obs:
        basis_count[o.availability_basis] += 1
        vintage_count[o.value_vintage] += 1
        if o.reported_at is not None and o.filing_type in ("QUARTERLY_RESULT", "ANNUAL_RESULT", "SHAREHOLDING_PATTERN"):
            reported = o.reported_at.astimezone(IST).date()
            lag = (reported - o.period_end).days
            lags.append(lag)
            deadline = statutory_deadline(o.period_end, o.period_type, o.filing_type)
            if deadline and reported > deadline:
                late.append(f"{o.symbol} {o.metric} {o.period_end}: reported {reported} (deadline {deadline})")

    groups: dict[tuple, list[Observation]] = defaultdict(list)
    for o in obs:
        groups[(o.symbol, o.metric, o.basis, o.period_type, o.period_end)].append(o)
    conflicts = []
    for k, g in groups.items():
        vals = [o.value for o in g]
        if len(g) > 1 and max(vals) - min(vals) > CONFLICT_TOL * max(abs(v) for v in vals):
            conflicts.append(f"{k[0]} {k[1]} {k[2].lower()} {k[3]} {k[4]}: " +
                             ", ".join(f"{o.source} {o.value:g}" for o in g))

    sums = []
    for (sym, metric, basis, ptype, end), g in groups.items():
        if ptype != "FY" or metric not in ("revenue", "net_profit"):
            continue
        for fy in g:
            qs = [o for (s2, m2, b2, p2, e2), gg in groups.items() if (s2, m2, b2, p2) == (sym, metric, basis, "Q")
                  and fy.period_start <= e2 <= fy.period_end for o in gg if o.source == fy.source]
            if len(qs) == 4:
                total = sum(o.value for o in qs)
                if abs(total - fy.value) > SUM_TOL * abs(fy.value):
                    sums.append(f"{sym} {metric} {basis.lower()} FY to {end}: quarters sum {total:,.1f} vs FY {fy.value:,.1f} ({fy.source})")

    lags.sort()
    return {
        "symbols": symbols,
        "stocks": stocks,
        "rows_latest": len(obs),
        "versions": version_stats(conn, symbols),
        "availability": dict(basis_count),
        "vintage": dict(vintage_count),
        "lag_days": {"n": len(lags), "min": lags[0], "median": lags[len(lags) // 2], "max": lags[-1]} if lags else None,
        "late_filings": late,
        "conflicts": conflicts,
        "sum_mismatches": sums,
        "sources": sorted({o.source for o in obs}),
    }


def markdown(a: dict) -> str:
    out = ["| Stock | Rows | Periods | Revenue quarters | EPS quarters | Strict PIT rows | Missing metrics |",
           "|---|---:|---|---:|---:|---:|---|"]
    for s, d in a["stocks"].items():
        out.append(f"| {s} | {d['rows']} | {d['first_period'] or '—'} to {d['last_period'] or '—'} | {d['quarters_revenue']} | "
                   f"{d['quarters_eps']} | {d['strict_rows']} | {len(d['missing_metrics'])} of {len(METRICS)} |")
    inputs = list(SCORE_INPUTS)
    out += ["", "Score inputs reconstructable point-in-time (yes = metrics present with strict dates and enough quarters):", "",
            "| Stock | " + " | ".join(inputs) + " |", "|---|" + "---|" * len(inputs)]
    for s, d in a["stocks"].items():
        out.append(f"| {s} | " + " | ".join(d["inputs"][i] for i in inputs) + " |")
    v = a["versions"]
    out += ["", f"- Observations (latest versions): {a['rows_latest']}; all versions: {v['rows']}; import batches: {v['batches']}",
            f"- Availability basis: {a['availability'] or 'none'}", f"- Value vintage: {a['vintage'] or 'none'}",
            f"- Reporting lag (days after period end): {a['lag_days'] or 'no dated rows'}",
            f"- Later versions: {v['later_versions']} (restatements {v['restatements']}, corrections {v['corrections']})",
            f"- Sources: {', '.join(a['sources']) or 'none'}",
            f"- Filed after the statutory deadline: {len(a['late_filings'])}",
            *[f"  - {x}" for x in a["late_filings"][:20]],
            f"- Conflicting values across sources (> {CONFLICT_TOL:.1%}): {len(a['conflicts'])}",
            *[f"  - {x}" for x in a["conflicts"][:30]],
            f"- Quarters not adding up to the full year (> {SUM_TOL:.0%}): {len(a['sum_mismatches'])}",
            *[f"  - {x}" for x in a["sum_mismatches"][:30]]]
    return "\n".join(out) + "\n"
