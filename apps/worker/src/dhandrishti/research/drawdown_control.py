"""Drawdown-control study: can a portfolio-level rule (cut exposure after a fall from the peak, or while the market is
in a downtrend) keep a small portfolio within a 20% maximum drawdown, including through a crash like March 2020?

Experimental research only. Reads prices; writes nothing; not connected to scoring, paper trading or orders.

Builds on research/position_sizing.py: the same quarterly baskets of N random point-in-time members (same seeds, so
every rule sees the same stocks); here the share of capital invested changes day by day. A rule decides at a close
using data up to that close; money moves at that mark (approximating a fill at the next open). Between decisions the
invested part moves with the stocks and cash stays put, as in position_sizing ("fixed" reproduces it exactly).
Costs: the round trip on the invested part at each quarterly rebalance, plus half a round trip on every amount moved
between stocks and cash. Cash earns 0. Fixed in advance (not fitted):
  fixed          always `base` invested (the baseline)
  dd_half        portfolio 10% below its peak -> base/2; back to base when less than 5% below the peak
  dd_cash_trend  portfolio 10% below its peak -> cash; back to base when NIFTY 50 closes above its 50-session average
                 (the peak is reset at re-entry, so the next 10% is measured from there)
  trend200       base while NIFTY 50 closes above its 200-session average, otherwise cash
  trend200_half  base above the 200-session average, base/2 below

Pre-registered reading: a setting PASSES when at most 10% of paths are worse than -20% in BOTH the verified period
(2021-26, point-in-time universe) and the crash stress period (2015-20, today's list: survivorship-biased, flatters
results). Recommended: the passing setting with the highest 2021-26 median annual return.
"""

import numpy as np

from .. import indicators as ind
from ..models import MarketHistory
from .factors import ROUND_TRIP_COST
from .position_sizing import SEED, Quarter

RULES = ("fixed", "dd_half", "dd_cash_trend", "trend200", "trend200_half")
BASES = (0.6, 0.8, 1.0)
N = 15
TRIGGER, RECOVER = 0.10, 0.05
LIMIT, MAX_BREACH = -0.20, 0.10


def market_flags(history: MarketHistory) -> tuple[np.ndarray, np.ndarray]:
    """Per calendar session: NIFTY 50 close above its 200- and its 50-session average (False while undefined)."""
    c = np.asarray(history.nifty.close, float)
    with np.errstate(invalid="ignore"):
        return c > ind.sma(c, 200), c > ind.sma(c, 50)


def _baskets(quarters: list[Quarter], n: int, paths: int, seed: int) -> list[list[np.ndarray]]:
    """Equal-weight basket paths per path and quarter; the same draws as position_sizing.simulate."""
    rng = np.random.default_rng([seed, n])
    picks = [[rng.choice(len(q.symbols), size=min(n, len(q.symbols)), replace=False) for q in quarters]
             for _ in range(paths)]
    return [[q.rel[None][idx].mean(axis=0) for q, idx in zip(quarters, p)] for p in picks]


def simulate(quarters: list[Quarter], baskets: list[list[np.ndarray]], rule: str, base: float,
             above200: np.ndarray, above50: np.ndarray) -> np.ndarray:
    """Equity curves [path, step]. The invested part moves with the basket and cash stays put; money moves between
    them only at a quarterly rebalance or when the rule changes the target. Step j of a quarter is the close of
    session start+j; the last step is the next rebalance open, which takes the signal of the session before."""
    half_cost = ROUND_TRIP_COST / 2
    curves = []
    for path in baskets:
        value, peak, out, curve = 1.0, 1.0, False, []
        target = base
        if rule.startswith("trend200"):
            target = base if above200[quarters[0].start - 1] else (0.0 if rule == "trend200" else base / 2)
        for q, b in zip(quarters, path):
            value *= 1 - target * ROUND_TRIP_COST             # quarterly rebalance of the invested part
            invested, cash, prev = target * value, (1 - target) * value, 1.0
            for j, level in enumerate(b):
                invested *= level / prev
                prev = level
                value = invested + cash
                peak = max(peak, value)
                curve.append(value)
                t = min(q.start + j, q.end - 1)                # session whose close decides the next exposure
                if rule == "fixed":
                    new = base
                elif rule == "dd_half":
                    dd = value / peak - 1
                    new = base / 2 if dd <= -TRIGGER else (base if dd > -RECOVER else target)
                elif rule == "dd_cash_trend":
                    if not out and value / peak - 1 <= -TRIGGER:
                        out = True
                    elif out and above50[t]:
                        out, peak = False, value
                    new = 0.0 if out else base
                else:
                    new = base if above200[t] else (0.0 if rule == "trend200" else base / 2)
                if new != target:                              # trade the difference, pay half a round trip on it
                    move = new * value - invested
                    invested += move
                    cash -= move + abs(move) * half_cost
                    value = invested + cash
                    target = new
        curves.append(curve)
    return np.array(curves)


def stats(curves: np.ndarray, days: int) -> dict:
    eq = np.concatenate([np.ones((len(curves), 1)), curves], axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    annual = eq[:, -1] ** (252 / days) - 1
    return {"median_annual": float(np.median(annual)), "p5_annual": float(np.percentile(annual, 5)),
            "median_dd": float(np.median(dd)), "p95_dd": float(np.percentile(dd, 5)),
            "breach_20": float(np.mean(dd < LIMIT))}


def run(quarters: list[Quarter], history: MarketHistory, paths: int, seed: int = SEED, rules=RULES,
        bases=BASES) -> list[dict]:
    above200, above50 = market_flags(history)
    baskets = _baskets(quarters, N, paths, seed)
    days = sum(q.end - q.start for q in quarters)
    return [{"rule": r, "base": b, **stats(simulate(quarters, baskets, r, b, above200, above50), days)}
            for r in rules for b in bases]


def verdict(verified: list[dict], stress: list[dict]) -> dict:
    s = {(r["rule"], r["base"]): r for r in stress}
    passing = [r for r in verified if r["breach_20"] <= MAX_BREACH and s[(r["rule"], r["base"])]["breach_20"] <= MAX_BREACH]
    best = max(passing, key=lambda r: r["median_annual"]) if passing else None
    return {"passing": [(r["rule"], r["base"]) for r in passing], "recommended": best}


def markdown(verified: list[dict], stress: list[dict]) -> str:
    pct = lambda v: f"{v * 100:+.1f}%"  # noqa: E731
    s = {(r["rule"], r["base"]): r for r in stress}
    lines = ["| Rule | Base invested | 2021-26 median annual | 5th pct annual | Median max DD | 1-in-20 max DD | "
             "Paths worse than -20% | Crash test: median annual | median max DD | worse than -20% |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in verified:
        x = s[(r["rule"], r["base"])]
        lines.append(f"| {r['rule']} | {r['base']:.0%} | {pct(r['median_annual'])} | {pct(r['p5_annual'])} | "
                     f"{pct(r['median_dd'])} | {pct(r['p95_dd'])} | {r['breach_20']:.0%} | {pct(x['median_annual'])} | "
                     f"{pct(x['median_dd'])} | {x['breach_20']:.0%} |")
    return "\n".join(lines)
