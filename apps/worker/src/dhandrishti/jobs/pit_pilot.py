"""Fundamentals pilot in a development database (dd_* only; staged migration 0009).

    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals todo [SYMBOL ...]   # files still needed
    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals collect [--from ~/Downloads]
    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals setup     # create if absent, migrate, 0009, securities
    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals import [ROOT ...]   # default: data/pilot/*
    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals verify    # apply the official reference register
    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals report [--json]
    uv run python -m dhandrishti.jobs.pit_pilot --db dd_dev_fundamentals readiness   # YoY / TTM support

Connection details (user, password, host) come from DD_DATABASE_URL; only the database name is replaced.
The research databases are refused (see pit.pilot_validation.require_dev and db.staged).
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from ..db import database_url
from ..db import market_repository as repo
from ..db.staged import PROTECTED_DATABASES, apply_staged
from ..ingestion.nse_universe import real_universe
from ..paths import REPO_ROOT
from ..pit import pilot_validation as V
from ..pit.pilot import PILOT

PILOT_DIR = REPO_ROOT / "data" / "pilot"
REGISTER = REPO_ROOT / "docs" / "research" / "reference"
VALUES_CSV = REGISTER / "2026-10-official-values.csv"
DOCUMENTS_CSV = REGISTER / "2026-10-official-documents.csv"


def setup(db: str) -> list[str]:
    if db in PROTECTED_DATABASES or not db.startswith("dd_"):
        raise SystemExit(f"error: refusing {db!r}; use a dd_* development database")
    with psycopg.connect(make_conninfo(database_url(), dbname="postgres"), autocommit=True) as admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
            admin.execute(f'CREATE DATABASE "{db}"')
    with psycopg.connect(make_conninfo(database_url(), dbname=db), autocommit=True) as c:
        applied = apply_staged(c, only=["0009_fundamental_quality.sql"])
        if not c.execute("SELECT 1 FROM securities LIMIT 1").fetchone():
            with c.transaction():
                repo.upsert_securities(c, real_universe(), "EOD", "NSE index constituent files (repo)")
    return applied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="development database name (dd_*)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    t = sub.add_parser("todo", help="results XBRL files still needed (manual NSE download)")
    t.add_argument("symbols", nargs="*")
    t.add_argument("--both-bases", action="store_true", help="standalone too (default: consolidated only)")
    co = sub.add_parser("collect", help="copy downloaded NSE listing CSVs and XBRL files into the pilot folder")
    co.add_argument("--from", dest="source", type=Path, default=Path.home() / "Downloads")
    i = sub.add_parser("import")
    i.add_argument("roots", nargs="*", type=Path)
    sub.add_parser("verify")
    r = sub.add_parser("report")
    r.add_argument("--json", action="store_true")
    sub.add_parser("readiness")
    args = ap.parse_args(argv)

    if args.cmd == "setup":
        print("applied:", setup(args.db) or "nothing (up to date)")
        return 0
    if args.cmd == "todo":
        return _todo(args.symbols or list(PILOT), args.both_bases)
    if args.cmd == "collect":
        rep = V.collect(args.source, PILOT_DIR)
        print(f"copied {len(rep.listings)} listing CSV(s) and {len(rep.xbrl)} XBRL file(s) from {args.source}; "
              f"{len(rep.already_present)} already present")
        for name in rep.conflicts:
            print(f"  CONFLICT (same name, different content; not copied): {name}")
        for name in rep.unlisted:
            print(f"  not in any listing CSV yet (not copied): {name}")
        for name in rep.unreadable:
            print(f"  unreadable listing (not copied): {name}")
        for name in rep.redundant:
            print(f"  listing adds no new filing (not copied): {name}")
        return 1 if rep.conflicts else 0
    with psycopg.connect(make_conninfo(database_url(), dbname=args.db), autocommit=True) as c:
        try:
            if args.cmd == "import":
                roots = args.roots or sorted(p for p in PILOT_DIR.iterdir() if p.is_dir())
                rep = V.import_files(c, roots)
                print(f"imported {len(rep.imported)}, refused {len(rep.refused)}, already recorded "
                      f"{len(rep.already_recorded)}, unlisted (no publication time, skipped) {len(rep.unlisted)}")
                for name, hidden in rep.hidden.items():
                    print(f"  {name}: hidden pending review {hidden}")
                for name in rep.refused + rep.unlisted:
                    print(f"  not imported: {name}")
                for msg in rep.unreadable:
                    print(f"  not imported (reader): {msg}")
            elif args.cmd == "verify":
                rep = V.apply_register(c, V.load_register(VALUES_CSV, DOCUMENTS_CSV))
                print(f"verified {rep.verified}, mismatched {len(rep.mismatched)}, already checked {rep.already_checked}, "
                      f"official values added {rep.official_values_added}, register rows with no stored value "
                      f"{len(rep.not_stored)}")
                for m in rep.mismatched:
                    print("  MISMATCH", m)
                for m in rep.not_stored:
                    print("  NOT STORED", m)
                added = V.yt2_flags(c)
                print(f"YT-2 (quarters add up to the full year): {len(added)} full-year value(s) flagged for review")
                for a in added:
                    print("  YT-2 REVIEW", a)
            elif args.cmd == "readiness":
                syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM fundamental_filings ORDER BY 1")]
                print(json.dumps([V.readiness(c, s, b) for s in syms for b in V.BASES], indent=1, default=str))
            else:
                out = {"coverage": V.coverage(c, list(PILOT)), "restatements": V.restatement_check(c)}
                print(json.dumps(out, indent=1, default=str) if args.json else _text(out))
        except V.PilotError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    return 0


def _todo(symbols: list[str], both_bases: bool) -> int:
    needed = V.todo(PILOT_DIR, symbols, both_bases=both_bases)
    missing = [n for n in needed if not n.present]
    by_page: dict[str, list] = {}
    for n in missing:
        by_page.setdefault(n.page if n.file else "LISTING CSV FIRST", []).append(n)
    print(f"{len(needed) - len(missing)} of {len(needed)} files present; {len(missing)} still needed")
    for page, items in by_page.items():
        print(f"\n== {page}")
        for n in items:
            print(f"  {n.symbol:<11} {n.basis[:4].lower():<5} {n.quarter}  {n.broadcast:<18} {n.file or ''}  {n.note}")
    return 0


def _text(out: dict) -> str:
    lines = ["company     filings            values  verified  mismatch  not-in-doc  unverified  hidden  official  "
             "quarters (window 8)"]
    for sym, c in out["coverage"].items():
        v = c["verification"]
        lines.append(f"{sym:<11} {str(c['filings'] or 'NO DATA'):<18} {c['values']:>6}  {v['VERIFIED']:>8}  "
                     f"{v['MISMATCH']:>8}  {v['NOT_IN_DOCUMENT']:>10}  {v['UNVERIFIED']:>10}  "
                     f"{c['hidden_open_review']:>6}  {c['official_replacements']:>8}  {c['quarters_in_window'] or '-'}")
    r = out["restatements"]
    lines.append(f"restatements: {r['figures_with_versions']} figures with several versions, "
                 f"{r['transitions_checked']} transitions checked, look-ahead failures {len(r['look_ahead_failures'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
