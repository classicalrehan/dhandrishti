"""Recommendation tracking commands (staged migration 0010; docs/recommendation-tracking.md).

    uv run python -m dhandrishti.jobs.tracking status                   # missing records, failures (exit 1 if any)
    uv run python -m dhandrishti.jobs.tracking record RUN_ID            # retry recording a run (never LIVE)
    uv run python -m dhandrishti.jobs.tracking outcomes                 # evaluate matured horizons
    uv run python -m dhandrishti.jobs.tracking verify RUN_ID [RUN_ID ...] | --all
    uv run python -m dhandrishti.jobs.tracking summary [--horizon 60] [--kind LIVE]
    uv run python -m dhandrishti.jobs.tracking backfill [--apply]       # copy score_history runs as BACKFILLED

Every command needs the tracking tables, which exist only where 0010 has been applied.
"""

import argparse
import json
import logging
import sys

from ..db import connect
from ..tracking import outcomes, summary, verify
from ..tracking.recorder import RetryRefused, backfill_from_score_history, retry_record, tables_installed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("record")
    r.add_argument("run_id", type=int)
    sub.add_parser("outcomes")
    v = sub.add_parser("verify")
    v.add_argument("run_ids", nargs="*", type=int)
    v.add_argument("--all", action="store_true")
    s = sub.add_parser("summary")
    s.add_argument("--horizon", type=int, default=60, choices=outcomes.HORIZONS)
    s.add_argument("--kind", default="LIVE", choices=("LIVE", "DEVELOPMENT", "REPLAY", "BACKFILLED"))
    s.add_argument("--json", action="store_true")
    b = sub.add_parser("backfill")
    b.add_argument("--apply", action="store_true", help="without it, only list what would be copied")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with connect() as conn:
        conn.autocommit = True
        if not tables_installed(conn):
            print(f"error: tracking tables are not installed in {conn.info.dbname!r} (staged migration 0010)",
                  file=sys.stderr)
            return 2
        if args.cmd == "status":
            st = summary.operational_status(conn)
            print(summary.format_status(st))
            return 0 if st["healthy"] else 1
        if args.cmd == "record":
            try:
                print(f"run {args.run_id}: {retry_record(conn, args.run_id)}")
            except RetryRefused as exc:
                print(f"run {args.run_id}: not recorded: {exc}", file=sys.stderr)
                return 1
        elif args.cmd == "outcomes":
            print(outcomes.update(conn))
        elif args.cmd == "verify":
            ids = args.run_ids or ([r[0] for r in conn.execute("SELECT run_id FROM recommendation_runs ORDER BY run_id")]
                                   if args.all else [])
            if not ids:
                ap.error("give run ids or --all")
            for run_id in ids:
                res = verify.verify_run(conn, run_id)
                print(f"run {run_id}: {res.status}" + (f" ({res.inputs_source} inputs)" if res.inputs_source else ""),
                      json.dumps(res.detail, default=str))
        elif args.cmd == "summary":
            rep = summary.track_record(conn, args.horizon, kind=args.kind)
            print(json.dumps(rep, indent=2, default=str) if args.json else summary.format_report(rep))
        elif args.cmd == "backfill":
            if not args.apply:
                rows = conn.execute("""SELECT r.id, r.as_of FROM scoring_runs r WHERE r.status = 'SUCCEEDED'
                    AND EXISTS (SELECT 1 FROM score_history h WHERE h.run_id = r.id)
                    AND NOT EXISTS (SELECT 1 FROM recommendation_runs t WHERE t.run_id = r.id) ORDER BY r.id""").fetchall()
                print("would copy as BACKFILLED:", [f"run {i} ({d})" for i, d in rows] or "nothing")
            else:
                print("copied as BACKFILLED:", backfill_from_score_history(conn) or "nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
