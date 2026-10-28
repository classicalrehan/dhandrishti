"""Position-sizing study: how many stocks, and how much of the capital invested, keep a small portfolio's maximum
drawdown within a limit (15-20%)? Does an 8% stop help when the portfolio is concentrated?

Experimental research only. Reads prices; writes nothing; not connected to scoring, paper trading or orders.

Selection is deliberately random, because no selection or entry rule has shown an edge: at each quarterly
rebalance (decision at the close of the first session of Jan/Apr/Jul/Oct, trades at the next open) a portfolio
holds N stocks drawn at random from that day's NIFTY 200 members (point-in-time universe). So the study measures
concentration and exposure risk, not stock-picking. Every configuration sees the SAME random draws (common random
numbers, fixed seed), so differences come from the configuration alone. Fixed in advance:
  N            5, 10, 15, 20 stocks
  exposure     50% .. 100% of capital invested; the rest is cash earning 0 (conservative)
  weighting    equal, or inverse 60-session volatility (known at the decision close)
  stop         none, or exit a stock when a close is 8% below its entry, filled at the next open; the money
               stays in cash until the next rebalance
Costs: the backtester's round trip (15 + 13.5 bps) on the invested capital at every rebalance (full turnover is
assumed: conservative). The portfolio is marked at daily closes.

Pre-registered reading: a configuration is ACCEPTABLE when at most 10% of paths have a maximum drawdown worse than
-20%; the recommended one is the acceptable configuration with the highest median annual return. The stop HELPS a
configuration when it lowers the share of paths worse than -20% by at least 5 points and costs at most 1 point of
median annual return.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..models import MarketHistory
from .factors import ROUND_TRIP_COST

N_STOCKS = (5, 10, 15, 20)
EXPOSURES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
WEIGHTINGS = ("equal", "ivol")
STOPS = (None, 0.08)
PATHS = 500
SEED = 20261028
LIMIT = -0.20
MAX_BREACH = 0.10
VOL_WINDOW = 60
QUARTER_MONTHS = ("01", "04", "07", "10")


@dataclass
class Quarter:
    start: int                       # calendar index of the entry session (decision session + 1)
    end: int                         # calendar index of the next entry session (exclusive)
    symbols: list[str]
    rel: dict[float | None, np.ndarray]     # stop -> [stock, day] value relative to entry (cash after a stop)
    vol: np.ndarray                  # 60-session daily volatility at the decision close


def quarter_starts(calendar: list[str]) -> list[int]:
    return [i for i, d in enumerate(calendar) if d[5:7] in QUARTER_MONTHS and (i == 0 or d[:7] != calendar[i - 1][:7])]


def prepare(history: MarketHistory, members: Callable[[str], frozenset[str] | None], stops=STOPS) -> list[Quarter]:
    """Per quarter: each eligible member's daily value path relative to its entry open, with and without a stop."""
    cal = list(history.nifty.dates)
    pos = {d: i for i, d in enumerate(cal)}
    T = len(cal)
    opens, closes = {}, {}
    for s, b in history.bars.items():
        o, c = np.full(T, np.nan), np.full(T, np.nan)
        idx = np.array([pos.get(d, -1) for d in b.dates])
        ok = idx >= 0
        o[idx[ok]], c[idx[ok]] = np.asarray(b.open, float)[ok], np.asarray(b.close, float)[ok]
        opens[s], closes[s] = o, c
    starts = quarter_starts(cal)
    out = []
    for q, t in enumerate(starts):
        m = members(cal[t])
        if m is None or q + 1 >= len(starts):
            continue
        e, end = t + 1, starts[q + 1] + 1
        if end >= T:
            continue
        syms, rels, vols = [], {s: [] for s in stops}, []
        for s in sorted(m):
            if s not in opens or not opens[s][e] > 0:
                continue
            hist = closes[s][max(0, t - VOL_WINDOW):t + 1]
            hist = hist[~np.isnan(hist)]
            if len(hist) < VOL_WINDOW // 2:
                continue
            path = _ffill(closes[s][e:end]) / opens[s][e]
            exit_open = opens[s][end]
            final = (exit_open if exit_open > 0 else path[-1] * opens[s][e]) / opens[s][e]
            path = np.append(path, final)                     # last point: the next rebalance open
            syms.append(s)
            vols.append(float(np.std(np.diff(np.log(hist)))))
            for stop in stops:
                p = path.copy()
                if stop is not None:
                    hit = np.flatnonzero(p[:-1] <= 1 - stop)
                    if len(hit):
                        k = hit[0]
                        fill = opens[s][e + k + 1] / opens[s][e] if opens[s][e + k + 1] > 0 else p[k]
                        p[k + 1:] = fill
                rels[stop].append(p)
        if syms:
            out.append(Quarter(e, end, syms, {k: np.array(v) for k, v in rels.items()}, np.array(vols)))
    return out


def _ffill(x: np.ndarray) -> np.ndarray:
    x = x.copy()
    for i in range(1, len(x)):
        if np.isnan(x[i]):
            x[i] = x[i - 1]
    if np.isnan(x[0]):
        first = np.flatnonzero(~np.isnan(x))
        x[: first[0] if len(first) else len(x)] = x[first[0]] if len(first) else 1.0
    return x


def simulate(quarters: list[Quarter], n: int, exposure: float, weighting: str, stop: float | None,
             paths: int = PATHS, seed: int = SEED) -> np.ndarray:
    """Equity curves [path, day] (start 1.0) for one configuration. The draws depend only on (seed, n), so every
    exposure / weighting / stop setting sees the same stocks."""
    rng = np.random.default_rng([seed, n])
    picks = [[rng.choice(len(q.symbols), size=min(n, len(q.symbols)), replace=False) for q in quarters]
             for _ in range(paths)]
    curves = []
    for p in range(paths):
        value, curve = 1.0, []
        for q, idx in zip(quarters, picks[p]):
            w = np.ones(len(idx)) if weighting == "equal" else 1 / np.maximum(q.vol[idx], 1e-6)
            w = w / w.sum()
            basket = w @ q.rel[stop][idx]                           # invested part, relative to the entry open
            value *= 1 - exposure * ROUND_TRIP_COST
            curve.extend(value * (1 - exposure + exposure * basket))       # closes, then the next entry open
            value = curve[-1]
        curves.append(curve)
    return np.array(curves)


def path_stats(curves: np.ndarray, days: int) -> dict:
    eq = np.concatenate([np.ones((len(curves), 1)), curves], axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    annual = eq[:, -1] ** (252 / days) - 1
    return {"median_annual": float(np.median(annual)), "p5_annual": float(np.percentile(annual, 5)),
            "median_dd": float(np.median(dd)), "p95_dd": float(np.percentile(dd, 5)),
            "breach_20": float(np.mean(dd < LIMIT)), "breach_15": float(np.mean(dd < -0.15))}


def run(quarters: list[Quarter], paths: int = PATHS, seed: int = SEED) -> list[dict]:
    days = sum(q.end - q.start for q in quarters)
    rows = []
    for n in N_STOCKS:
        for weighting in WEIGHTINGS:
            for stop in STOPS:
                for x in EXPOSURES:
                    curves = simulate(quarters, n, x, weighting, stop, paths, seed)
                    rows.append({"n": n, "exposure": x, "weighting": weighting, "stop": stop,
                                 **path_stats(curves, days)})
    return rows


def verdict(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["breach_20"] <= MAX_BREACH]
    best = max(ok, key=lambda r: r["median_annual"]) if ok else None
    key = {(r["n"], r["exposure"], r["weighting"], r["stop"]): r for r in rows}
    stop_helps = []
    for r in rows:
        if r["stop"] is None:
            continue
        base = key[(r["n"], r["exposure"], r["weighting"], None)]
        if base["breach_20"] - r["breach_20"] >= 0.05 and base["median_annual"] - r["median_annual"] <= 0.01:
            stop_helps.append((r["n"], r["exposure"], r["weighting"]))
    return {"recommended": best, "acceptable": len(ok), "stop_helps": stop_helps}


def label(r: dict) -> str:
    return f"{r['n']} stocks, {r['exposure']:.0%} invested, {r['weighting']} weights, " + \
        ("8% stop" if r["stop"] else "no stop")


def markdown(rows: list[dict], weighting: str = "equal") -> str:
    pct = lambda v: f"{v * 100:+.1f}%"  # noqa: E731
    lines = [f"| N | Invested | Stop | Median annual | 5th pct annual | Median max DD | 1-in-20 max DD | "
             f"Paths worse than -20% | worse than -15% |", "|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        if r["weighting"] != weighting:
            continue
        lines.append(f"| {r['n']} | {r['exposure']:.0%} | {'8%' if r['stop'] else '—'} | {pct(r['median_annual'])} | "
                     f"{pct(r['p5_annual'])} | {pct(r['median_dd'])} | {pct(r['p95_dd'])} | {r['breach_20']:.0%} | "
                     f"{r['breach_15']:.0%} |")
    return "\n".join(lines)
