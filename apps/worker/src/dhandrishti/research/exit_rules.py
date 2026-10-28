"""Exit-rule study: do stop-loss, trailing-stop, target or trend exits reduce drawdown (or add return) compared with
simply holding for a fixed period?

Experimental research only. Reads prices; writes nothing; not connected to scoring, paper trading or orders.

Entries are deliberately neutral, because no entry signal has shown an edge (entry-signal study): at the close of
the first session of each month, every stock that is a NIFTY 200 member that day (point-in-time universe) is
"bought" at the next open. Each exit rule is applied to exactly the same trades, so differences come from the exit
alone. Every rule also exits after HOLD sessions at the latest (the baseline does only that).

Rules are checked on each daily close using data up to that close; a triggered exit fills at the NEXT session's
open, so overnight gaps through a stop are included. Fixed in advance (not fitted):
  time60       hold 60 sessions (baseline)
  stop8        close <= entry x 0.92
  stop15       close <= entry x 0.85
  trail15      close <= 0.85 x highest close since entry (entry price counts as the first high)
  atr3         close <= highest close since entry - 3 x ATR(14)   (volatility-scaled trailing stop)
  sma50        close < its 50-session average
  tgt15_stop8  close >= entry x 1.15 (take profit) or close <= entry x 0.92 (stop)
Costs: the backtester's round trip (15 + 13.5 bps) on every trade; cash after an exit earns nothing (conservative).

Portfolio view: each monthly cohort is an equal-weight basket marked at daily closes (an exited position is held as
cash at its exit price); the portfolio's daily return is the average of the active cohorts' returns (about three
overlapping cohorts). Drawdown and annual return come from that curve.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .. import indicators as ind
from ..models import MarketHistory
from .factors import ROUND_TRIP_COST, newey_west_t

HOLD = 60
MIN_HISTORY = 60
SUSPECT_MOVE = 0.35
RULES = ("time60", "stop8", "stop15", "trail15", "atr3", "sma50", "tgt15_stop8")
BASELINE = "time60"
PERIODS = (("2021-2022", "2021-01-01", "2022-12-31"), ("2023-2026", "2023-01-01", "2026-12-31"))
DD_MARGIN = 0.03                         # drawdown must shrink by at least 3 percentage points to count


@dataclass
class Trade:
    rule: str
    symbol: str
    cohort: str                          # decision date (first session of the month)
    net: float
    held: int                            # sessions held
    reason: str                          # time | stop | target | trend


@dataclass
class ExitResult:
    trades: list[Trade]
    curves: dict[str, tuple[list[str], np.ndarray]]      # rule -> (dates, daily portfolio returns)
    excluded: dict[str, int] = field(default_factory=dict)


def _exit(rule: str, k0: int, entry: float, c: np.ndarray, sma50: np.ndarray, atr14: np.ndarray) -> tuple[int, str]:
    """Index of the close that triggers the exit (fill at the next open) and why; k0 = entry session."""
    last = k0 + HOLD - 1
    high = entry
    for k in range(k0, last):
        ck = c[k]
        high = max(high, ck)
        if rule == "stop8" and ck <= entry * 0.92 or rule == "stop15" and ck <= entry * 0.85:
            return k, "stop"
        if rule == "trail15" and ck <= 0.85 * high:
            return k, "stop"
        if rule == "atr3" and atr14[k] > 0 and ck <= high - 3 * atr14[k]:
            return k, "stop"
        if rule == "sma50" and ck < sma50[k]:
            return k, "trend"
        if rule == "tgt15_stop8":
            if ck >= entry * 1.15:
                return k, "target"
            if ck <= entry * 0.92:
                return k, "stop"
    return last, "time"


def first_sessions(calendar: list[str]) -> list[int]:
    """Index of the first session of each month."""
    return [i for i, d in enumerate(calendar) if i == 0 or d[:7] != calendar[i - 1][:7]]


def run(history: MarketHistory, members: Callable[[str], frozenset[str] | None], rules=RULES) -> ExitResult:
    cal = list(history.nifty.dates)
    T = len(cal)
    excluded = {"membership_unknown": 0, "window_beyond_data": 0, "short_history": 0, "no_price": 0,
                "suspect_price_jump": 0}
    prepared = {}
    for s, b in history.bars.items():
        c = np.asarray(b.close, float)
        prepared[s] = (b, {d: i for i, d in enumerate(b.dates)}, c, np.asarray(b.open, float),
                       ind.sma(c, 50), ind.atr(np.asarray(b.high, float), np.asarray(b.low, float), c, 14))
    trades: list[Trade] = []
    paths: dict[str, list[tuple[int, np.ndarray]]] = {r: [] for r in rules}       # (first calendar idx, path)
    for t in first_sessions(cal):
        m = members(cal[t])
        if m is None:
            excluded["membership_unknown"] += 1
            continue
        if t + 1 + HOLD >= T:
            excluded["window_beyond_data"] += 1
            continue
        cohort = {r: [] for r in rules}
        for s in sorted(m):
            if s not in prepared:
                excluded["no_price"] += 1
                continue
            b, pos, c, o, sma50, atr14 = prepared[s]
            k0 = pos.get(cal[t + 1])
            if k0 is None or k0 < MIN_HISTORY or k0 + HOLD >= len(c) or not o[k0] > 0:
                excluded["short_history" if k0 is not None and k0 < MIN_HISTORY else "no_price"] += 1
                continue
            window = c[k0 - 1:k0 + HOLD]
            if np.any(np.abs(window[1:] / window[:-1] - 1) > SUSPECT_MOVE):
                excluded["suspect_price_jump"] += 1
                continue
            for r in rules:
                k, why = (k0 + HOLD - 1, "time") if r == BASELINE else _exit(r, k0, o[k0], c, sma50, atr14)
                exit_price = o[k + 1]
                net = exit_price / o[k0] - 1 - ROUND_TRIP_COST
                trades.append(Trade(r, s, cal[t], float(net), k + 1 - k0, why))
                path = c[k0:k0 + HOLD] / o[k0]                    # marked at closes; cash after the exit
                j = k + 1 - k0                                     # first day out of the stock
                if j < HOLD:
                    path[j:] = exit_price / o[k0] - ROUND_TRIP_COST
                else:
                    path[-1] -= ROUND_TRIP_COST                    # time exit: costs on the last mark
                cohort[r].append(path)
        for r in rules:
            if cohort[r]:
                paths[r].append((t + 1, np.mean(cohort[r], axis=0)))
    curves = {r: _portfolio(cal, paths[r]) for r in rules}
    return ExitResult(trades, curves, excluded)


def _portfolio(cal: list[str], cohorts: list[tuple[int, np.ndarray]]) -> tuple[list[str], np.ndarray]:
    """Daily return = average of active cohorts' daily returns (cohort value starts at 1 at the entry open)."""
    if not cohorts:
        return [], np.array([])
    start, end = cohorts[0][0], max(i + len(p) for i, p in cohorts)
    sums, counts = np.zeros(end - start), np.zeros(end - start)
    for i, p in cohorts:
        r = np.diff(np.concatenate([[1.0], p])) / np.concatenate([[1.0], p[:-1]])
        sums[i - start:i - start + len(p)] += r
        counts[i - start:i - start + len(p)] += 1
    return cal[start:end], np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)


def curve_stats(dates: list[str], r: np.ndarray, lo: str, hi: str) -> dict:
    sel = np.array([lo <= d <= hi for d in dates], bool)
    x = r[sel]
    if not len(x):
        return {"days": 0}
    eq = np.cumprod(1 + x)
    dd = float(np.min(eq / np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:] - 1))
    return {"days": len(x), "annual_return": float(eq[-1] ** (252 / len(x)) - 1), "max_drawdown": dd,
            "volatility": float(np.std(x) * np.sqrt(252))}


def summarize(res: ExitResult, periods=PERIODS) -> list[dict]:
    """Per rule and period: trade statistics, difference vs the baseline on the same trades, portfolio curve."""
    base = {(t.symbol, t.cohort): t.net for t in res.trades if t.rule == BASELINE}
    rows = []
    for rule in dict.fromkeys(t.rule for t in res.trades):
        for name, lo, hi in (("all", "0000", "9999"), *periods):
            tr = [t for t in res.trades if t.rule == rule and lo <= t.cohort <= hi]
            if not tr:
                continue
            by_cohort: dict[str, list[float]] = {}
            for t in tr:
                by_cohort.setdefault(t.cohort, []).append(t.net - base[(t.symbol, t.cohort)])
            diffs = np.array([np.mean(by_cohort[c]) for c in sorted(by_cohort)])
            net = np.array([t.net for t in tr])
            rows.append({
                "rule": rule, "period": name, "trades": len(tr), "cohorts": len(by_cohort),
                "mean_net": float(net.mean()), "p5_net": float(np.percentile(net, 5)),
                "loss_over_15": float(np.mean(net < -0.15)), "mean_held": float(np.mean([t.held for t in tr])),
                "exited_early": float(np.mean([t.reason != "time" for t in tr])),
                "diff_vs_base": float(diffs.mean()), "t_diff": newey_west_t(diffs, 3) if rule != BASELINE else None,
                **curve_stats(*res.curves[rule], lo, hi),
            })
    return rows


def verdict(rows: list[dict], periods=PERIODS) -> dict[str, list[str]]:
    """Pre-registered reading (fixed before running), per rule against the baseline:
      REDUCES DRAWDOWN  max drawdown smaller by >= 3 points in BOTH periods, and the full-period return
                        difference is not significantly negative (t > -2)
      IMPROVES RETURN   per-trade difference > 0 with t >= 2 in BOTH periods
      COSTS RETURN      per-trade difference with t <= -2 in BOTH periods
      otherwise         NO DEMONSTRATED BENEFIT"""
    key = {(r["rule"], r["period"]): r for r in rows}
    out = {}
    for rule in dict.fromkeys(r["rule"] for r in rows):
        if rule == BASELINE:
            continue
        names = [p[0] for p in periods]
        per = [key.get((rule, p)) for p in names]
        base = [key.get((BASELINE, p)) for p in names]
        everything = key.get((rule, "all"), {})
        found = []
        if all(r and b and r["max_drawdown"] - b["max_drawdown"] >= DD_MARGIN for r, b in zip(per, base)) and \
                (everything.get("t_diff") is None or everything["t_diff"] > -2):
            found.append("REDUCES DRAWDOWN")
        ts = [(r or {}).get("t_diff") for r in per]
        ds = [(r or {}).get("diff_vs_base") for r in per]
        if all(t is not None and t >= 2 and d > 0 for t, d in zip(ts, ds)):
            found.append("IMPROVES RETURN")
        if all(t is not None and t <= -2 for t in ts):
            found.append("COSTS RETURN")
        out[rule] = found or ["NO DEMONSTRATED BENEFIT"]
    return out


def markdown(rows: list[dict], res: ExitResult) -> str:
    pct = lambda v: "—" if v is None else f"{v * 100:+.2f}%"  # noqa: E731
    lines = ["| Rule | Period | Trades | Mean net | 5th pct | Losses >15% | Held | Exited early | Diff vs hold | "
             "t | Portfolio annual | Max drawdown |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        t = "—" if r["t_diff"] is None else f"{r['t_diff']:+.1f}"
        lines.append(f"| {r['rule']} | {r['period']} | {r['trades']} | {pct(r['mean_net'])} | {pct(r['p5_net'])} | "
                     f"{r['loss_over_15']:.1%} | {r['mean_held']:.0f} | {r['exited_early']:.0%} | "
                     f"{pct(r['diff_vs_base'])} | {t} | {pct(r.get('annual_return'))} | {pct(r.get('max_drawdown'))} |")
    lines += ["", "Excluded: " + ", ".join(f"{k} {v}" for k, v in res.excluded.items())]
    return "\n".join(lines)
