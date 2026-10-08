"""Rule study: replay paper-trading rule variants over real history, train vs validation.

    uv run python -m dhandrishti.jobs.rule_study [--out docs/research/rule-study.md]

Every variant is replayed with the live paper engine (whole shares, Zerodha charges, next-open
fills) from ₹1 lakh, separately in each window. The variants and windows are fixed in advance
(below) so the result cannot be tuned to the data: a rule only counts as an improvement if it
helps in the training window AND still helps in the later validation window it never saw.
"""

import argparse
import logging
import sys
from dataclasses import asdict, replace
from pathlib import Path

from ..config import default_config
from ..db import connect
from ..db.market_repository import load_history
from ..research.replay import SignalCache, benchmarks, price_tables, replay
from ..scoring import score_universe
from ..trading.paper import PaperParams

log = logging.getLogger(__name__)

WINDOWS = {"Train": ("2023-12-01", "2025-03-31"), "Validation": ("2025-04-01", "2099-12-31")}

BASE = PaperParams()  # portfolio #1: monthly top 5, risk ≤ MEDIUM, 10% stop, keep while top 10, 18% kill switch
VARIANTS: list[tuple[str, PaperParams]] = [
    ("Baseline (portfolio #1)", BASE),
    ("Quarterly, keep top 15 (portfolio #2)", replace(BASE, rebalance="quarterly", rank_buffer=15)),
    ("Cash in bear markets", replace(BASE, regime_slots={"BEARISH": 0})),
    ("2 holdings in bear markets", replace(BASE, regime_slots={"BEARISH": 2})),
    ("No stop-loss", replace(BASE, stop_loss_pct=None)),
    ("Stop-loss 15%", replace(BASE, stop_loss_pct=15.0)),
    ("Trailing stop 15%", replace(BASE, stop_loss_pct=None, trailing_stop_pct=15.0)),
    ("Keep while top 20", replace(BASE, rank_buffer=20)),
    ("Min 1 year of history", replace(BASE, min_history_bars=252)),
    ("Top 10, keep top 20", replace(BASE, top_n=10, rank_buffer=20)),
    ("Weekly, cash in bear markets", replace(BASE, rebalance="weekly", regime_slots={"BEARISH": 0})),
    ("Combined: bear cash + 1y history + keep top 20",
     replace(BASE, regime_slots={"BEARISH": 0}, min_history_bars=252, rank_buffer=20)),
]


def run(history) -> dict[str, dict[str, dict]]:
    cfg = default_config()

    def score(h, day):
        r = score_universe(h.market_at(day, BASE.lookback_bars), cfg)
        return r["stocks"], r["regime"]["regime"]

    signals = SignalCache(history, score)
    opens, closes = price_tables(history)
    out: dict[str, dict[str, dict]] = {}
    for window, (start, end) in WINDOWS.items():
        days = [d for d in history.nifty.dates if start <= d <= end]
        log.info("%s window %s .. %s (%d sessions)", window, days[0], days[-1], len(days))
        rows = {}
        for name, params in VARIANTS:
            rows[name] = replay(name, params, days, signals, opens, closes).summary()
            log.info("  %-48s %+7.2f%%  dd %6.1f%%", name, rows[name]["return_pct"], rows[name]["max_drawdown_pct"])
        for name, b in benchmarks(days, signals, history, opens, closes, BASE.capital).items():
            rows[name] = b.summary()
        out[f"{window} ({days[0]} to {days[-1]})"] = rows
    return out


def table(rows: dict[str, dict]) -> str:
    head = ("| Rule | Return | CAGR | Worst fall | Sharpe | Charges | Trades | Stop-loss sells | Invested | Kill switch |\n"
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    lines = [head]
    for name, r in rows.items():
        bench = name in ("NIFTY 50", "Equal-weight universe")
        lines.append(
            f"| {'*' + name + '*' if bench else name} | {r['return_pct']:+.1f}% | {r['cagr_pct']:+.1f}% | "
            f"{r['max_drawdown_pct']:.1f}% | {r['sharpe']:.2f} | ₹{r['charges']:,.0f} | "
            f"{'—' if bench else r['trades']} | {'—' if bench else r['stop_losses']} | "
            f"{'—' if bench else format(r['avg_invested_pct'], '.0f') + '%'} | {r['halted_on'] or '—'} |")
    return "\n".join(lines)


def report(results: dict[str, dict[str, dict]]) -> str:
    parts = ["# Rule study (generated)\n",
             "Each rule replays the live paper engine from ₹1,00,000 in each window: whole shares, Zerodha "
             "delivery charges, signals at the close, fills at the next open. Universe: today's NIFTY 200 "
             "(survivorship bias inflates every row, including the equal-weight benchmark).\n",
             "Base rules (portfolio #1): " + ", ".join(f"{k}={v}" for k, v in asdict(BASE).items()) + "\n"]
    for window, rows in results.items():
        parts += [f"## {window}\n", table(rows), ""]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="write the Markdown report here")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with connect() as conn:
        latest = conn.execute("SELECT max(trade_date) FROM daily_prices").fetchone()[0]
        history = load_history(conn, latest.isoformat())
    text = report(run(history))
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
