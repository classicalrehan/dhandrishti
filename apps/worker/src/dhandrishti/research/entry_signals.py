"""Entry-signal study: do pullback, breakout or trend-continuation entries beat simply owning the universe?

Experimental research only. Reads prices; writes nothing; not connected to scoring, paper trading or orders.

Signals are fixed in advance (not fitted) and use only data up to the close of the signal day; the trade enters
at the NEXT session's open and exits at the open `h` sessions later (h = 5, 20, 60). Each event is compared with
the equal-weight average of every stock that traded over exactly the same dates (the control), and with NIFTY 50.

  uptrend       close > SMA200 and SMA50 > SMA200
  pullback      uptrend and RSI(14) falls below 40 (crosses from >= 40)
  breakout      close above the highest close of the previous 55 sessions, volume >= 1.5x its 20-day average,
                close > SMA200
  continuation  uptrend and close crosses back above SMA20 (from at or below it the previous session)
After an event a stock is ignored by the same strategy for 20 sessions. A stock needs 252 sessions of history.

Costs: the backtester's 15 bps buy + 13.5 bps sell (incl. ~3 bps slippage); also shown with 10 bps extra per side.
Events whose window contains a close-to-close move above 35% are excluded (possible unadjusted corporate action).
Statistics are clustered by entry date: average excess per date, then mean, hit rate and a Newey-West t over dates.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .. import indicators as ind
from ..models import Bars, MarketHistory
from .factors import ROUND_TRIP_COST, newey_west_t

HORIZONS = (5, 20, 60)
COOLDOWN = 20
MIN_HISTORY = 252
SUSPECT_MOVE = 0.35
EXTRA_SLIPPAGE = 2 * 10 / 1e4            # stress test: +10 bps on each side
PERIODS = (("2013-2018", "2013-01-01", "2018-12-31"), ("2019-2022", "2019-01-01", "2022-12-31"),
           ("2023-2026", "2023-01-01", "2026-12-31"))


def _uptrend(c: np.ndarray, s50: np.ndarray, s200: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return (c > s200) & (s50 > s200)


def signals(b: Bars) -> dict[str, np.ndarray]:
    """Boolean arrays (one per strategy, aligned with b.dates). Entry i uses only bars[0..i]."""
    c, v = np.asarray(b.close, float), np.asarray(b.volume, float)
    n = len(c)
    s20, s50, s200 = ind.sma(c, 20), ind.sma(c, 50), ind.sma(c, 200)
    r = ind.rsi(c, 14)
    up = _uptrend(c, s50, s200)
    prev = lambda a: np.concatenate(([np.nan], a[:-1]))  # noqa: E731  value at i-1
    hi55 = np.full(n, np.nan)
    for i in range(55, n):
        hi55[i] = c[i - 55:i].max()
    vol20_prev = prev(ind.sma(v, 20))
    with np.errstate(invalid="ignore"):
        out = {
            "pullback": up & (r < 40) & (prev(r) >= 40),
            "breakout": (c > hi55) & (v >= 1.5 * vol20_prev) & (c > s200),
            "continuation": up & (c > s20) & (prev(c) <= prev(s20)),
        }
    for k, a in out.items():
        a[:MIN_HISTORY] = False
        out[k] = _cooldown(np.nan_to_num(a, nan=0).astype(bool))
    return out


def _cooldown(a: np.ndarray, gap: int = COOLDOWN) -> np.ndarray:
    keep, last = np.zeros_like(a), -10**9
    for i in np.flatnonzero(a):
        if i - last > gap:
            keep[i], last = True, i
    return keep


@dataclass
class Panel:
    calendar: list[str]
    opens: np.ndarray            # [session, stock], NaN where the stock has no bar
    lows: np.ndarray
    closes: np.ndarray
    symbols: list[str]
    nifty_open: np.ndarray


def panel(history: MarketHistory) -> Panel:
    cal = list(history.nifty.dates)
    pos = {d: i for i, d in enumerate(cal)}
    syms = sorted(history.bars)
    shape = (len(cal), len(syms))
    o, lo, c = np.full(shape, np.nan), np.full(shape, np.nan), np.full(shape, np.nan)
    for j, s in enumerate(syms):
        b = history.bars[s]
        idx = np.array([pos.get(d, -1) for d in b.dates])
        ok = idx >= 0
        o[idx[ok], j], lo[idx[ok], j], c[idx[ok], j] = (np.asarray(b.open, float)[ok], np.asarray(b.low, float)[ok],
                                                        np.asarray(b.close, float)[ok])
    return Panel(cal, o, lo, c, syms, np.asarray(history.nifty.open, float))


@dataclass
class Event:
    strategy: str
    symbol: str
    signal_date: str
    horizon: int
    gross: float
    net: float
    net_stress: float
    excess: float               # gross minus the control's gross over the same dates
    excess_nifty: float
    mae: float


@dataclass
class StudyResult:
    events: list[Event]
    excluded: dict[str, int] = field(default_factory=dict)


def run(history: MarketHistory, horizons=HORIZONS, signal_fn: Callable[[Bars], dict] = signals,
        members: Callable[[str], frozenset[str] | None] | None = None) -> StudyResult:
    """`members(day)` (point-in-time universe): when given, a signal counts only if the stock is a member on the
    signal day, and the control is the members on that day; days it answers None for (unknown) are skipped."""
    p = panel(history)
    pos = {d: i for i, d in enumerate(p.calendar)}
    T = len(p.calendar)
    with np.errstate(invalid="ignore", divide="ignore"):
        jumps = np.abs(p.closes[1:] / p.closes[:-1] - 1) > SUSPECT_MOVE
    res = StudyResult([], {"no_entry_or_exit_price": 0, "suspect_price_jump": 0, "window_beyond_data": 0})
    if members is not None:
        res.excluded |= {"not_a_member": 0, "membership_unknown": 0}
    in_universe: dict[int, np.ndarray] = {}           # signal session -> mask of member columns
    control: dict[tuple[int, int, int], float] = {}
    for j, s in enumerate(p.symbols):
        b = history.bars[s]
        for strat, mask in signal_fn(b).items():
            for i in np.flatnonzero(mask):
                t = pos.get(b.dates[i])
                if t is None:
                    continue
                if members is not None:
                    if t not in in_universe:
                        m = members(p.calendar[t])
                        in_universe[t] = None if m is None else np.array([x in m for x in p.symbols])
                    if in_universe[t] is None:
                        res.excluded["membership_unknown"] += len(horizons)
                        continue
                    if not in_universe[t][j]:
                        res.excluded["not_a_member"] += len(horizons)
                        continue
                universe = in_universe[t] if members is not None else True
                for h in horizons:
                    e, x = t + 1, t + 1 + h
                    if x >= T:
                        res.excluded["window_beyond_data"] += 1
                        continue
                    entry, exit_ = p.opens[e, j], p.opens[x, j]
                    if not (entry > 0 and exit_ > 0):
                        res.excluded["no_entry_or_exit_price"] += 1
                        continue
                    if jumps[t:x, j].any():
                        res.excluded["suspect_price_jump"] += 1
                        continue
                    if (t, e, x) not in control:   # every (member) stock trading on both dates, minus suspect windows
                        both = (p.opens[e] > 0) & (p.opens[x] > 0) & ~jumps[t:x].any(axis=0) & universe
                        control[(t, e, x)] = float(np.mean(p.opens[x, both] / p.opens[e, both] - 1))
                    gross = exit_ / entry - 1
                    lows = p.lows[e:x, j]
                    mae = float(np.nanmin(np.append(lows, exit_)) / entry - 1)
                    nifty = p.nifty_open[x] / p.nifty_open[e] - 1 if p.nifty_open[e] > 0 else np.nan
                    res.events.append(Event(strat, s, b.dates[i], h, gross, gross - ROUND_TRIP_COST,
                                            gross - ROUND_TRIP_COST - EXTRA_SLIPPAGE, gross - control[(t, e, x)],
                                            gross - nifty, mae))
    return res


def summarize(res: StudyResult, periods=PERIODS) -> list[dict]:
    """One row per strategy x horizon x period (plus 'all'): statistics clustered by signal date."""
    rows = []
    strategies = sorted({e.strategy for e in res.events})
    horizons = sorted({e.horizon for e in res.events})
    for strat in strategies:
        for h in horizons:
            for name, lo, hi in (("all", "0000", "9999"), *periods):
                ev = [e for e in res.events if e.strategy == strat and e.horizon == h and lo <= e.signal_date <= hi]
                if not ev:
                    rows.append({"strategy": strat, "horizon": h, "period": name, "events": 0})
                    continue
                by_date: dict[str, list[Event]] = {}
                for e in ev:
                    by_date.setdefault(e.signal_date, []).append(e)
                dates = sorted(by_date)
                x = np.array([np.mean([e.excess for e in by_date[d]]) for d in dates])
                rows.append({
                    "strategy": strat, "horizon": h, "period": name, "events": len(ev), "dates": len(dates),
                    "mean_gross": float(np.mean([e.gross for e in ev])),
                    "mean_net": float(np.mean([e.net for e in ev])),
                    "mean_net_stress": float(np.mean([e.net_stress for e in ev])),
                    "mean_excess": float(x.mean()),
                    "mean_excess_nifty": float(np.nanmean([e.excess_nifty for e in ev])),
                    "hit_rate": float(np.mean([e.excess > 0 for e in ev])),
                    "t_nw": newey_west_t(x, h),
                    "median_mae": float(np.median([e.mae for e in ev])),
                })
    return rows


def verdict(rows: list[dict], later_periods=("2019-2022", "2023-2026"),
            caveat: str = "still survivorship-biased") -> dict[tuple[str, int], str]:
    """Pre-registered reading: an edge needs positive excess with |t| >= 2 in BOTH later periods (2019-22, 2023-26;
    2021-22 and 2023-26 for the point-in-time universe). Anything else is 'no demonstrated edge' (or 'negative' when
    both are significantly negative)."""
    out = {}
    keyed = {(r["strategy"], r["horizon"], r["period"]): r for r in rows}
    for strat, h in sorted({(r["strategy"], r["horizon"]) for r in rows}):
        later = [keyed.get((strat, h, p)) for p in later_periods]
        ts = [(r or {}).get("t_nw") for r in later]
        ex = [(r or {}).get("mean_excess") for r in later]
        if all(t is not None and t >= 2 and e > 0 for t, e in zip(ts, ex)):
            out[(strat, h)] = f"CANDIDATE (consistent positive excess; {caveat})"
        elif all(t is not None and t <= -2 for t in ts):
            out[(strat, h)] = "NEGATIVE (consistently worse than the universe)"
        else:
            out[(strat, h)] = "NO DEMONSTRATED EDGE"
    return out


def markdown(rows: list[dict], res: StudyResult) -> str:
    pct = lambda v: "—" if v is None else f"{v * 100:+.2f}%"  # noqa: E731
    lines = ["| Strategy | h | Period | Events | Dates | Net (base cost) | Net (+10 bps/side) | Excess vs universe | "
             "t (NW) | Hit rate | Excess vs NIFTY | Median MAE |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        if not r["events"]:
            lines.append(f"| {r['strategy']} | {r['horizon']} | {r['period']} | 0 | | | | | | | | |")
            continue
        t = "—" if r["t_nw"] is None else f"{r['t_nw']:+.1f}"
        lines.append(f"| {r['strategy']} | {r['horizon']} | {r['period']} | {r['events']} | {r['dates']} | "
                     f"{pct(r['mean_net'])} | {pct(r['mean_net_stress'])} | {pct(r['mean_excess'])} | {t} | "
                     f"{r['hit_rate']:.0%} | {pct(r['mean_excess_nifty'])} | {pct(r['median_mae'])} |")
    lines.append("")
    lines.append("Excluded event windows: " + ", ".join(f"{k} {v}" for k, v in res.excluded.items()))
    return "\n".join(lines)
