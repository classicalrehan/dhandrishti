"""Factor study: predictive value of every score component and the composite, on stored history.

    uv run python -m dhandrishti.jobs.factor_study [--step 5] [--start 2013-03-01] [--end ...]
        [--daily-stability 120] [--name price-factors] [--report docs/research/....md]

Each run is an experiment with its own folder under .research/runs/<id>/ holding config.json
(parameters plus code, scoring-config and data fingerprints), results.json and report.md, and a line
in .research/runs/index.jsonl. The scored panel is cached by fingerprint in .research/panels/, so a
re-run on unchanged code and data reuses it. Results are computed, never typed in.
"""

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg

from ..config import default_config
from ..db import connect
from ..db.market_repository import load_history
from ..paths import REPO_ROOT, SCORING_CONFIG_PATH
from ..providers.kite.provider import suspicious_moves
from ..research import factors as F

log = logging.getLogger(__name__)
RESEARCH_DIR = REPO_ROOT / ".research"
SRC_DIR = Path(__file__).resolve().parents[1]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def code_fingerprint() -> str:
    return _sha(b"".join(p.read_bytes() for p in sorted(SRC_DIR.rglob("*.py"))))


def data_fingerprint(conn: psycopg.Connection) -> dict:
    n, first, last, syms, ingested = conn.execute("""
        SELECT count(*), min(trade_date)::text, max(trade_date)::text, count(DISTINCT symbol), max(ingested_at)::text
        FROM daily_prices""").fetchone()
    funds = conn.execute("SELECT count(*), max(ingested_at)::text FROM fundamentals").fetchone()
    return {"database": conn.info.dbname, "price_rows": n, "first_date": first, "last_date": last, "symbols": syms,
            "prices_ingested_at": ingested, "fundamental_rows": funds[0], "fundamentals_ingested_at": funds[1]}


def fmt(x, nd=3, pct=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:+.{nd}f}" if not pct else f"{x:+.1f}%"


def report(meta: dict, res: dict) -> str:
    H = meta["params"]["horizons"]
    L = F.LABELS
    out = [f"# Factor study `{meta['id']}`\n",
           f"Data: {meta['data']['database']}, {meta['data']['symbols']} symbols, prices "
           f"{meta['data']['first_date']} to {meta['data']['last_date']}, fundamentals rows: "
           f"{meta['data']['fundamental_rows']}. Sample: every {meta['params']['step']} sessions, "
           f"{res['n_dates']} dates from {res['first_date']} to {res['last_date']}, {res['n_obs']} stock-dates. "
           f"Scoring config {meta['config_version']}, code {meta['code']}.\n",
           "**Read with care.** The universe is today's NIFTY 200 applied to the past (survivorship bias): "
           "stocks are included because they later became large, which flatters factors that buy past "
           "winners. Forward returns are open-to-open from the session after the signal, before costs "
           "(bucket tables subtract round-trip costs on turnover). t-stats are Newey-West for overlap; "
           "|t| above about 2 is the usual bar, and with ~10 factors x 5 horizons a few will cross it by chance.\n",
           "## 1. Rank IC by factor and horizon\nMean rank IC (Newey-West t-stat). Constant factors (no data) show —.\n"]
    out.append("| Factor | " + " | ".join(f"{h}D" for h in H) + " |")
    out.append("|---|" + "---:|" * len(H))
    for f, row in res["factors"].items():
        cells = []
        for h in H:
            s = row[str(h)]["rank_ic"]
            cells.append("—" if not s.get("n_dates") else f"{s['mean']:+.3f} ({fmt(s['t_nw'], 1)})")
        out.append(f"| {L[f]} | " + " | ".join(cells) + " |")
    out.append("\n## 2. Detail for the composite and price factors\n")
    out.append("| Factor | Horizon | Rank IC mean | median | std | ICIR | hit rate | t (NW) | Pearson IC | dates | stock-dates |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for f in ("composite", "price_only", "f_momentum", "f_technicalTrend", "f_liquidity", "f_sectorStrength", "f_risk"):
        for h in H:
            r = res["factors"][f][str(h)]
            s, p = r["rank_ic"], r["ic"]
            if not s.get("n_dates"):
                continue
            out.append(f"| {L[f]} | {h}D | {s['mean']:+.4f} | {s['median']:+.4f} | {s['std']:.4f} | {fmt(s['icir'], 2)} | "
                       f"{s['hit_rate']:.0%} | {fmt(s['t_nw'], 2)} | {fmt(p.get('mean'), 4)} | {s['n_dates']} | {r['n_obs']} |")
    for title, key in (("3. By market regime", "regime"), ("4. By period", "era"), ("5. By liquidity tercile (size proxy)", "size_proxy")):
        out.append(f"\n## {title}\nMean rank IC at 20D / 60D (dates).\n")
        groups = sorted({g for f in res["splits"][key].values() for h in f.values() for g in h})
        out.append("| Factor | " + " | ".join(groups) + " |")
        out.append("|---|" + "---:|" * len(groups))
        for f, by_h in res["splits"][key].items():
            cells = []
            for g in groups:
                a, b = by_h["20"].get(g), by_h["60"].get(g)
                cells.append(f"{fmt(a and a['mean'])} / {fmt(b and b['mean'])} ({(b or a or {}).get('n_dates', 0)})")
            out.append(f"| {L[f]} | " + " | ".join(cells) + " |")
    out.append("\n## 6. By sector (sectors with 10+ stocks)\nMean rank IC at 60D within each sector (dates).\n")
    out.append("| Sector | Composite | Momentum | Technical trend |")
    out.append("|---|---:|---:|---:|")
    for sec, row in res["splits"]["sector"].items():
        out.append(f"| {sec} | " + " | ".join(
            f"{fmt(row[f]['mean'])} ({row[f]['n_dates']})" if row.get(f) else "—"
            for f in ("composite", "f_momentum", "f_technicalTrend")) + " |")
    for h, b in res["buckets"].items():
        out.append(f"\n## 7. Composite score as a portfolio, {h}-session holding periods\n"
                   f"Non-overlapping periods; equal weight; net = after round-trip costs on turnover. "
                   f"Monotonicity (deciles 1→10 vs return, Spearman): {fmt(b.get('monotonicity'), 2)}.\n")
        out.append("| Bucket | Periods | Mean return | Excess vs NIFTY | Hit rate vs NIFTY | Volatility | Worst fall | Turnover | Net CAGR | Sharpe | Sortino |")
        out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for name, s in b.items():
            if name == "monotonicity":
                continue
            out.append(f"| {name} | {s['periods']} | {s['mean_return_pct']:+.2f}% | {s['mean_excess_vs_nifty_pct']:+.2f}% | "
                       f"{s['hit_rate_vs_nifty']:.0%} | {fmt(s['volatility_ann_pct'], 1)}% | {s['max_drawdown_pct']:.1f}% | "
                       f"{fmt(s['avg_turnover'], 2)} | {s['cagr_net_pct']:+.1f}% | {fmt(s['sharpe'], 2)} | {fmt(s['sortino'], 2)} |")
    out.append("\n## 8. Missing data and eligibility variants\nMean rank IC (t).\n")
    out.append("| Variant | " + " | ".join(f"{h}D" for h in H) + " |")
    out.append("|---|" + "---:|" * len(H))
    for name, row in res["variants"].items():
        out.append(f"| {name} | " + " | ".join(
            "—" if not row[str(h)].get("n_dates") else f"{row[str(h)]['mean']:+.3f} ({fmt(row[str(h)]['t_nw'], 1)})"
            for h in H) + " |")
    out.append(f"\nStocks flagged for >35% one-day moves (excluded in the sensitivity row): "
               f"{', '.join(res['flagged']) or 'none'}.\n")
    out.append("## 9. Ranking stability\n")
    out.append("| Gap | Rank correlation | Top 10 still in top 10 | Pairs |")
    out.append("|---|---:|---:|---:|")
    for lag, s in res["stability"].items():
        out.append(f"| {lag} | {fmt(s['rank_corr'], 2)} | {fmt(s['top10_retained'], 2)} | {s['pairs']} |")
    return "\n".join(out) + "\n"


def run_study(history, conn, params: dict) -> tuple[dict, dict]:
    cfg = default_config()
    meta = {"params": params, "config_version": cfg["version"], "scoring_config": _sha(SCORING_CONFIG_PATH.read_bytes()),
            "code": code_fingerprint(), "data": data_fingerprint(conn)}
    dates = F.sample_dates(history.nifty.dates, params["start"], params["end"], params["step"])
    key = _sha(json.dumps([meta["code"], meta["scoring_config"], meta["data"], dates, params["horizons"]],
                          sort_keys=True).encode())
    cache = RESEARCH_DIR / "panels" / key
    if cache.with_suffix(".stocks.csv.gz").exists():
        log.info("reusing cached panel %s", key)
        panel = pd.read_csv(cache.with_suffix(".stocks.csv.gz"))
        dpanel = pd.read_csv(cache.with_suffix(".dates.csv.gz"))
    else:
        log.info("scoring %d dates (%s to %s)", len(dates), dates[0], dates[-1])
        panel, dpanel = F.build_panel(history, dates, params["horizons"], cfg,
                                      progress=lambda k, n, d: k % 25 == 0 and log.info("  %d/%d %s", k, n, d))
        cache.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(cache.with_suffix(".stocks.csv.gz"), index=False)
        dpanel.to_csv(cache.with_suffix(".dates.csv.gz"), index=False)
    meta["panel"] = key
    H, step = params["horizons"], params["step"]
    panel = F.with_groups(F.add_variants(panel, cfg))
    js = lambda d: {str(k): v for k, v in d.items()}  # noqa: E731

    res = {"n_dates": int(panel["date"].nunique()), "first_date": panel["date"].min(), "last_date": panel["date"].max(),
           "n_obs": int(len(panel))}
    res["factors"] = {f: js(v) for f, v in F.factor_table(panel, H, step).items()}
    split_factors = ("composite", "price_only", "f_momentum", "f_technicalTrend", "f_liquidity", "f_sectorStrength", "f_risk")
    res["splits"] = {key: {f: {str(h): F.split_ic(panel, f, h, key, step) for h in (20, 60)} for f in split_factors}
                     for key in ("regime", "era", "size_proxy")}
    big = [s for s, n in panel.groupby("sector")["symbol"].nunique().items() if n >= 10]
    def sector_ic(sec: str, f: str) -> dict | None:
        s = F.ic_summary(F.ic_by_date(panel[panel["sector"] == sec], f, 60), 60, step)
        return s if s["n_dates"] else None

    res["splits"]["sector"] = {sec: {f: sector_ic(sec, f) for f in ("composite", "f_momentum", "f_technicalTrend")}
                               for sec in sorted(big)}
    res["buckets"] = {str(h): F.bucket_study(panel, dpanel, h, step) for h in (20, 60) if h in H}

    flagged = sorted({s for s, b in history.bars.items() if suspicious_moves(s, b)})
    long = panel[panel["bars"] >= 252]
    clean = panel[~panel["symbol"].isin(flagged)]
    variants = {
        "Composite (as engine)": F.factor_table(panel, H, step, ["composite"])["composite"],
        "Composite, missing→neutral per metric": F.factor_table(panel, H, step, ["composite_shrunk"])["composite_shrunk"],
        "Composite, only stocks with 1y+ history": F.factor_table(long, H, step, ["composite"])["composite"],
        "Price-only composite": F.factor_table(panel, H, step, ["price_only"])["price_only"],
        "Composite, excluding flagged stocks": F.factor_table(clean, H, step, ["composite"])["composite"],
        "Momentum, excluding flagged stocks": F.factor_table(clean, H, step, ["f_momentum"])["f_momentum"],
    }
    res["variants"] = {k: {str(h): v[h]["rank_ic"] for h in H} for k, v in variants.items()}
    res["flagged"] = flagged
    res["stability"] = F.rank_stability(panel, [step, 4 * step, 12 * step], step)
    if params.get("daily_stability"):
        days = history.nifty.dates[-params["daily_stability"]:]
        daily, _ = F.build_panel(history, days, (), cfg)
        res["stability"] = F.rank_stability(daily, [1], 1) | res["stability"]
    return meta, res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="factor-study")
    ap.add_argument("--start", help="first sample date (default: first date with 300 sessions of history)")
    ap.add_argument("--end", default="2099-12-31")
    ap.add_argument("--step", type=int, default=5, help="sessions between sample dates")
    ap.add_argument("--horizons", default=",".join(map(str, F.HORIZONS)))
    ap.add_argument("--daily-stability", type=int, default=0, help="also score the last N sessions daily")
    ap.add_argument("--report", type=Path, help="also write the Markdown report here")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with connect() as conn:
        latest = conn.execute("SELECT max(trade_date) FROM daily_prices").fetchone()[0].isoformat()
        history = load_history(conn, latest)
        params = {"start": args.start or history.nifty.dates[300], "end": args.end, "step": args.step,
                  "horizons": [int(h) for h in args.horizons.split(",")], "daily_stability": args.daily_stability}
        meta, res = run_study(history, conn, params)
    created = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    meta["id"] = f"{created}-{args.name}"
    run_dir = RESEARCH_DIR / "runs" / meta["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(meta, indent=2, default=str))
    (run_dir / "results.json").write_text(json.dumps(res, indent=2, default=str))
    text = report(meta, res)
    (run_dir / "report.md").write_text(text)
    comp = res["factors"]["composite"]
    with (RESEARCH_DIR / "runs" / "index.jsonl").open("a") as f:
        f.write(json.dumps({"id": meta["id"], "name": args.name, "params": params, "data": meta["data"],
                            "code": meta["code"], "composite_rank_ic": {h: comp[h]["rank_ic"].get("mean") for h in comp}},
                           default=str) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text)
    print(f"saved {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
