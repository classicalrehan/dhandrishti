"""Drawdown-control study (research only; read-only; docs in research/drawdown_control.py).

    uv run python -m dhandrishti.jobs.drawdown_study [--db dd_dev_tracking] [--paths 500] [--out FILE.md]
        [--rules fixed,dd_half] [--bases 0.4,0.45,0.5,0.55]

Defaults are the registered first run (all rules, bases 60/80/100%); --rules/--bases select a registered follow-up.

Verified period: the point-in-time universe from 2021 (as `entry_study --pit`). Crash stress period: 2015-2020 with
today's NIFTY 200 list applied to the past (survivorship-biased; flatters results). Opens the database READ ONLY.
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..db.market_repository import load_history
from ..research import drawdown_control as D
from ..research import pit_universe as P
from ..research import position_sizing as S
from .entry_study import point_in_time

STRESS = ("2015-01-01", "2020-12-31")


def _nifty_dd(history, lo: str) -> float:
    d, c = history.nifty.dates, np.asarray(history.nifty.close, float)
    i0 = next(i for i, x in enumerate(d) if x >= lo)
    eq = c[i0:] / c[i0]
    return float((eq / np.maximum.accumulate(eq) - 1).min())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="dd_dev_tracking")
    ap.add_argument("--paths", type=int, default=S.PATHS)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--rules", default=",".join(D.RULES))
    ap.add_argument("--bases", default=",".join(str(b) for b in D.BASES))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with psycopg.connect(make_conninfo(database_url(), dbname=args.db)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        latest = conn.execute("SELECT max(trade_date)::text FROM daily_prices").fetchone()[0]
        verified_h = load_history(conn, latest)
        stress_h = load_history(conn, STRESS[1])
        conn.rollback()
    members, universe = point_in_time(verified_h, latest)
    verified_q = S.prepare(verified_h, members, stops=(None,))
    today = frozenset(P.today_list())
    stress_q = S.prepare(stress_h, lambda d: today if STRESS[0] <= d <= STRESS[1] else None, stops=(None,))
    rules = [r for r in args.rules.split(",") if r]
    unknown = set(rules) - set(D.RULES)
    if unknown:
        raise SystemExit(f"unknown rules: {sorted(unknown)}")
    bases = [float(b) for b in args.bases.split(",") if b]
    verified = D.run(verified_q, verified_h, args.paths, rules=rules, bases=bases)
    stress = D.run(stress_q, stress_h, args.paths, rules=rules, bases=bases)
    v = D.verdict(verified, stress)
    best = v["recommended"]
    text = [f"# Drawdown-control study ({args.db}, prices to {latest})", "",
            "Research only. " + " ".join(universe) + f" {D.N} random members per quarter, {args.paths} paths with "
            "common random draws; cash earns 0; costs on every rebalance and exposure change.",
            f"Verified period: {len(verified_q)} quarters from {verified_h.nifty.dates[verified_q[0].start]} "
            f"(NIFTY 50 max drawdown {_nifty_dd(verified_h, verified_h.nifty.dates[verified_q[0].start]):+.1%}). "
            f"Crash test: {len(stress_q)} quarters from {stress_h.nifty.dates[stress_q[0].start]}, today's list "
            f"(survivorship-biased) (NIFTY 50 max drawdown {_nifty_dd(stress_h, STRESS[0]):+.1%}).", "",
            D.markdown(verified, stress), "",
            "## Pre-registered reading (pass: at most 10% of paths worse than -20% in BOTH periods)",
            "- Passing: " + (", ".join(f"{r} at {b:.0%}" for r, b in v["passing"]) or "none"),
            "- Recommended: " + (f"{best['rule']} at {best['base']:.0%} (2021-26 median annual "
                                 f"{best['median_annual']:+.1%}, median max drawdown {best['median_dd']:+.1%})"
                                 if best else "none: no tested rule holds a 20% limit through both periods")]
    out = "\n".join(text)
    if args.out:
        args.out.write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
