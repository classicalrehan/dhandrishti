"""Point-in-time fundamentals: import, inspect and check data quality. Kite database by default.

    pnpm pit import FILE.csv --source "NSE filing (manual)" [--dry-run]
    pnpm pit as-of SYMBOL 2024-06-30 [--include-estimated] [--include-displayed] [--known-by 2024-07-01]
    pnpm pit history SYMBOL METRIC PERIOD_END
    pnpm pit report [--symbols A,B] [--out FILE.md]
    pnpm pit listing FILE.csv [FILE.csv ...]      # read NSE results listings; writes nothing
    pnpm pit xbrl FILE.xml [...] --listings DIR [--import]   # NSE results XBRL; dry run unless --import
    pnpm pit shp FILE.xml [...] --listings DIR [--import]     # NSE shareholding XBRL; dry run unless --import

Writes only to fundamental_observations / fundamental_import_batches (append-only). Production
scoring does not read these tables yet.
"""

import argparse
import os
import sys
from pathlib import Path

from ..db import connect
from ..db.migrate import migrate
from ..calendar import is_trading_day
from ..pit import canonical_csv, quality, store
from ..pit.adapters import nse_results_listing as listing
from ..pit.adapters import nse_shp, nse_shp_listing, nse_xbrl
from ..pit.availability import ALL_BASES, IST, STRICT_BASES, decision_time
from ..pit.pilot import PILOT


def _path(p: Path) -> Path:
    return p if p.is_absolute() else Path(os.environ.get("INIT_CWD", os.getcwd())) / p


def fmt(o: store.Observation) -> str:
    when = o.available_at.astimezone(IST).strftime("%Y-%m-%d %H:%M") if o.available_at else "never"
    return (f"{o.metric:<22} {o.period_type:<7} {o.period_end} {o.basis[:4].lower():<4} {o.value:>16,.2f} {o.unit:<13} "
            f"available {when} ({o.availability_basis.lower()}, {o.value_vintage.lower()}) v{o.data_version} {o.source}")


def first_decision_day(published, sessions: set[str] | None = None) -> str:
    """First trading day whose 15:30 IST decision may use something published at `published`.

    `sessions` are actual trading days (NIFTY 50 history in the database). The holiday file only covers
    recent years, so it is used only beyond the stored history.
    """
    from datetime import timedelta
    last = max(sessions) if sessions else ""
    trading = lambda day: day in sessions if sessions and day <= last else is_trading_day(day)  # noqa: E731
    d = published.astimezone(IST).date()
    while not (trading(d.isoformat()) and decision_time(d.isoformat()) >= published):
        d += timedelta(days=1)
    return d.isoformat()


def describe_listings(paths: list[Path], known: set[str], sessions: set[str] | None = None) -> list[str]:
    lines = []
    merged: dict[str, list] = {}
    for path in paths:
        fs = listing.parse(path)
        if not fs:
            lines.append(f"{path.name}: no filings")
            continue
        merged.setdefault(fs[0].symbol, []).extend(fs)
        lines.append(f"read {path.name}: {fs[0].symbol}, {len(fs)} filings ({fs[0].source_page})")
    for sym, filings in merged.items():
        filings.sort(key=lambda f: (f.period_end, f.basis))
        dupes = {(f.period_end, f.basis) for f in filings if sum((g.period_end, g.basis) == (f.period_end, f.basis)
                                                                   for g in filings) > 1}
        lines.append(f"{sym} ({filings[0].company}), {len(filings)} filings from {len({f.source_page for f in filings})} page(s)"
                     + ("" if sym in known else "  WARNING: symbol not in the universe"))
        lines.append(f"  {'period end':<11} {'basis':<12} {'type':<8} {'published (IST)':<17} {'lag':>4} "
                     f"{'first usable decision':<22} xbrl")
        for f in filings:
            lines.append(f"  {f.period_end!s:<11} {f.basis.lower():<12} {f.taxonomy:<8} "
                         f"{f.disseminated_at:%Y-%m-%d %H:%M}  {f.lag_days:>3}d {first_decision_day(f.disseminated_at, sessions):<22} "
                         f"{f.xbrl_file}" + ("  LATE (after SEBI deadline)" if f.after_deadline else "")
                         + (f"  {f.submission.upper()} {f.revised_at:%Y-%m-%d %H:%M} {f.revision_remarks or ''}"
                            if f.submission.lower() != "original" else ""))
        by_end: dict = {}
        for f in filings:
            by_end.setdefault(f.period_end, {})[f.basis] = f
        gaps = [(end, (b["CONSOLIDATED"].disseminated_at - b["STANDALONE"].disseminated_at))
                for end, b in by_end.items() if len(b) == 2]
        big = [f"{end} ({abs(g.total_seconds()) / 3600:.1f} h)" for end, g in gaps if abs(g.total_seconds()) > 3600]
        ends = sorted(by_end)
        q_ends = [e for e in ends]
        missing = []
        for a, b in zip(q_ends, q_ends[1:]):
            months = (b.year - a.year) * 12 + b.month - a.month
            if months > 3:
                missing.append(f"{a} → {b}")
        if missing:
            lines.append(f"  GAP in quarters: {', '.join(missing)}")
        if dupes:
            lines.append(f"  same quarter and basis listed more than once (revisions?): {sorted(dupes)}")
        lines.append(f"  quarters {ends[0]} to {ends[-1]}: {len(ends)}; both bases for {len(gaps)}; "
                     f"lag {min(f.lag_days for f in filings)}-{max(f.lag_days for f in filings)} days; "
                     f"late filings {sum(f.after_deadline for f in filings)}; "
                     f"published in market hours (usable same day) {sum(first_decision_day(f.disseminated_at, sessions) == f.disseminated_at.date().isoformat() for f in filings)}")
        if big:
            lines.append(f"  consolidated and standalone published more than 1 hour apart: {', '.join(big)}")
        received_gap = max((f.disseminated_at - f.received_at).total_seconds() for f in filings)
        lines.append(f"  longest gap between NSE receiving and publishing: {received_gap / 60:.1f} min")
    return lines


def xbrl_command(conn, args) -> int:
    index = {}
    for p in sorted(_path(args.listings).glob("*.csv")):
        for f in listing.parse(p):
            index[f.xbrl_file] = f
    failed = False
    parsed = []
    for path in [_path(p) for p in args.files]:
        filing = index.get(path.name)
        if filing is None:
            print(f"error: {path.name} is not in any listing under {args.listings}: no publication time, not imported",
                  file=sys.stderr)
            failed = True
            continue
        try:
            pf = nse_xbrl.parse(path, filing)
        except nse_xbrl.XbrlError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"{path.name}: {pf.symbol} {pf.basis.lower()} period ended {pf.period_end}, published "
              f"{filing.disseminated_at:%Y-%m-%d %H:%M} IST, {len(pf.observations)} observations")
        for o in sorted(pf.observations, key=lambda o: (o.period_type, o.metric)):
            print(f"  {o.metric:<32} {o.period_type:<7} {str(o.period_start or ''):<10} {o.period_end} "
                  f"{o.value:>14,.2f} {o.unit}")
        for name, status, detail in pf.checks:
            print(f"  check {status}: {name} ({detail})")
        for n in pf.notes:
            print(f"  note: {n}")
        if any(status == "FAIL" for _, status, _ in pf.checks):
            print("  not imported: a consistency check failed", file=sys.stderr)
            failed = True
            continue
        if any(status == "WARN" for _, status, _ in pf.checks) and not args.accept_warnings:
            print("  held back: a cross-check warned; review it, then re-run with --accept-warnings", file=sys.stderr)
            failed = True
            continue
        parsed.append((path, pf))
    if args.do_import and parsed:
        for path, pf in parsed:
            res = store.append(conn, pf.observations, nse_xbrl.SOURCE, path.name, store.file_sha256(path))
            print(f"imported {path.name}: batch {res.batch_id}, {res.inserted} new, {res.versioned} new versions, "
                  f"{res.duplicates} duplicates")
    elif parsed:
        print("dry run: nothing written (add --import to store)")
    return 1 if failed else 0


def shp_command(conn, args) -> int:
    index = {}
    if args.listings:
        for p in sorted(_path(args.listings).glob("CF-Shareholding-Pattern-*.csv")):
            for row in nse_shp_listing.parse(p):
                index[row.xbrl_file] = row
    failed, ready = False, []
    for path in [_path(p) for p in args.files]:
        try:
            f = nse_shp.parse(path)
        except nse_xbrl.XbrlError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failed = True
            continue
        row = index.get(path.name)
        checks = list(f.checks)
        if row is not None:
            checks.append(("listing symbol and as-on date match the file",
                           "PASS" if (row.symbol, row.as_on) == (f.symbol, f.as_on) else "FAIL",
                           f"listing {row.symbol} {row.as_on}, file {f.symbol} {f.as_on}"))
            if row.promoter_pct is not None and "promoter" in f.pct:
                checks.append(("listing promoter % = file promoter %",
                               "PASS" if abs(row.promoter_pct - f.pct["promoter"]) <= 0.01 else "WARN",
                               f"{row.promoter_pct:.2f}% vs {f.pct['promoter']:.2f}%"))
        published = f"published {row.disseminated_at:%Y-%m-%d %H:%M} IST" if row else "NO PUBLICATION TIME"
        print(f"{path.name}: {f.symbol} shareholding as on {f.as_on}, total {f.shares['total'] / 1e7:,.2f} cr shares, {published}")
        for k in ("promoter", "fii", "dii"):
            if k in f.pct:
                print(f"  {k:<26} {f.pct[k]:7.2f}%")
        print(f"  promoter shares pledged: {'none (stated)' if f.promoter_pledged is False else 'see warning'}")
        for name, status, detail in checks:
            print(f"  check {status}: {name} ({detail})")
        for n in f.notes:
            print(f"  note: {n}")
        if row is None:
            print("  not importable: not in any shareholding listing (no publication time)", file=sys.stderr)
            failed = True
        elif any(st == "FAIL" for _, st, _ in checks):
            print("  not imported: a consistency check failed", file=sys.stderr)
            failed = True
        elif any(st == "WARN" for _, st, _ in checks) and not args.accept_warnings:
            print("  held back: a cross-check warned; review it, then re-run with --accept-warnings", file=sys.stderr)
            failed = True
        else:
            ready.append((path, f.observations(row.disseminated_at, path.name)))
    if args.do_import and ready:
        for path, obs in ready:
            res = store.append(conn, obs, nse_shp.SOURCE, path.name, store.file_sha256(path))
            print(f"imported {path.name}: batch {res.batch_id}, {res.inserted} new, {res.versioned} new versions, "
                  f"{res.duplicates} duplicates")
    elif ready:
        print(f"dry run: {len(ready)} file(s) ready, nothing written (add --import to store)")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import")
    i.add_argument("file", type=Path)
    i.add_argument("--source", required=True)
    i.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("as-of")
    a.add_argument("symbol")
    a.add_argument("date", help="decision date; the decision is taken at that day's 15:30 IST close")
    a.add_argument("--include-estimated", action="store_true", help="also use statutory-deadline dates")
    a.add_argument("--include-displayed", action="store_true", help="also use AS_CURRENTLY_DISPLAYED values")
    a.add_argument("--known-by", help="only what DhanDrishti had stored by this date")
    h = sub.add_parser("history")
    h.add_argument("symbol")
    h.add_argument("metric")
    h.add_argument("period_end")
    li = sub.add_parser("listing")
    li.add_argument("files", nargs="+", type=Path)
    x = sub.add_parser("xbrl")
    x.add_argument("files", nargs="+", type=Path)
    x.add_argument("--listings", type=Path, required=True, help="folder with the NSE results listing CSVs")
    x.add_argument("--import", dest="do_import", action="store_true", help="write to the store (default: dry run)")
    x.add_argument("--accept-warnings", action="store_true",
                   help="also import files whose cross-checks WARN (after reviewing them)")
    sh = sub.add_parser("shp")
    sh.add_argument("files", nargs="+", type=Path)
    sh.add_argument("--listings", type=Path, help="folder with the NSE shareholding listing CSV(s)")
    sh.add_argument("--import", dest="do_import", action="store_true", help="write to the store (default: dry run)")
    sh.add_argument("--accept-warnings", action="store_true", help="also import files whose cross-checks WARN")
    r = sub.add_parser("report")
    r.add_argument("--symbols", help="comma-separated (default: the 20-stock pilot)")
    r.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    with connect() as conn:
        migrate(conn)
        conn.autocommit = True
        if conn.execute("SELECT 1 FROM securities WHERE provenance = 'MOCK' LIMIT 1").fetchone():
            print("error: this is the MOCK database; use the Kite database (pnpm pit uses it by default)", file=sys.stderr)
            return 1
        if args.cmd == "listing":
            known = {s for (s,) in conn.execute("SELECT symbol FROM securities")}
            try:
                sessions = {d.isoformat() for (d,) in conn.execute(
                    "SELECT trade_date FROM index_prices WHERE index_code = 'NIFTY 50'")}
                print("\n".join(describe_listings([_path(p) for p in args.files], known, sessions)))
            except (listing.ListingError, FileNotFoundError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        elif args.cmd == "shp":
            return shp_command(conn, args)
        elif args.cmd == "xbrl":
            return xbrl_command(conn, args)
        elif args.cmd == "import":
            path = _path(args.file)
            known = {s for (s,) in conn.execute("SELECT symbol FROM securities")}
            try:
                obs = canonical_csv.parse(path, args.source, known)
            except (canonical_csv.CanonicalImportError, FileNotFoundError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"{len(obs)} observations parsed from {path.name}")
            if args.dry_run:
                print("dry run: nothing written")
                return 0
            res = store.append(conn, obs, args.source, path.name, store.file_sha256(path))
            print(f"batch {res.batch_id}: {res.inserted} new, {res.versioned} new versions "
                  f"({res.restatements} restatements), {res.duplicates} duplicates skipped")
        elif args.cmd == "as-of":
            decision = decision_time(args.date)
            known_by = decision_time(args.known_by) if args.known_by else None
            obs = store.as_of(conn, args.symbol, decision,
                              bases=ALL_BASES if args.include_estimated else STRICT_BASES,
                              vintages=("AS_REPORTED", "AS_CURRENTLY_DISPLAYED") if args.include_displayed else ("AS_REPORTED",),
                              known_by=known_by)
            print(f"{args.symbol}: {len(obs)} observations usable for a decision at {decision:%Y-%m-%d %H:%M} IST")
            for o in sorted(obs, key=lambda o: (o.metric, o.period_end)):
                print("  " + fmt(o))
        elif args.cmd == "history":
            for o in store.versions(conn, args.symbol, args.metric, args.period_end):
                tag = "restatement" if o.is_restatement else "correction" if o.data_version > 1 else "original"
                print(f"  {fmt(o)}  [{tag}, ingested {o.ingested_at:%Y-%m-%d %H:%M}]")
        elif args.cmd == "report":
            symbols = args.symbols.split(",") if args.symbols else list(PILOT)
            text = quality.markdown(quality.analyse(conn, symbols))
            print(text)
            if args.out:
                _path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
