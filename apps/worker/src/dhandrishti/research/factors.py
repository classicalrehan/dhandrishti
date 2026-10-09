"""Factor research: does each score component (and the composite) predict forward returns?

Panel: on each sample date d, score the universe exactly as the engine would at d's close
(`MarketHistory.market_at`), and record every stock's component scores alongside its forward
return from the NEXT session's open over h sessions (h = 5, 20, 60, 120, 252). Entering at the
next open is what a real trade could do; nothing after d's close is used to compute the factors.

Statistics (per factor and horizon):
  rank IC   Spearman correlation across stocks on one date, then summarised over dates
  IC        Pearson correlation of the same
  ICIR      mean IC / std IC
  hit rate  share of dates with IC > 0
  t-stat    Newey-West, lag = overlapping windows (h / sampling step), so overlapping forward
            returns do not inflate significance

Caveat that applies to everything here: the universe is today's NIFTY 200 (survivorship bias).
It flatters factors that select past winners, momentum first. See the report header.
"""

import math
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from ..config import COMPONENT_ORDER, Config, default_config
from ..models import MarketHistory
from ..scoring import score_universe

HORIZONS = (5, 20, 60, 120, 252)
MIN_STOCKS = 10  # cross-sections smaller than this give no IC
ROUND_TRIP_COST = (15.0 + 13.5) / 1e4  # same per-side costs as the backtester
ERAS = (("2013-2016", "2013-01-01", "2016-12-31"), ("2017-2019", "2017-01-01", "2019-12-31"),
        ("2020-2022", "2020-01-01", "2022-12-31"), ("2023-2026", "2023-01-01", "2026-12-31"))


# ---------------------------------------------------------------- panel

def sample_dates(calendar: list[str], start: str, end: str, step: int) -> list[str]:
    days = [d for d in calendar if start <= d <= end]
    return days[::step]


def build_panel(history: MarketHistory, dates: Iterable[str], horizons: Iterable[int] = HORIZONS,
                cfg: Config | None = None, lookback: int = 300,
                progress: Callable[[int, int, str], None] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (stock panel, date panel). Forward returns are open-to-open from the next session."""
    cfg = cfg or default_config()
    calendar = history.nifty.dates
    pos = {d: i for i, d in enumerate(calendar)}
    opens = {s: dict(zip(b.dates, b.open.tolist())) for s, b in history.bars.items()}
    n_open = dict(zip(calendar, history.nifty.open.tolist()))
    horizons = tuple(horizons)
    dates = list(dates)
    rows, drows = [], []
    for k, d in enumerate(dates):
        i = pos[d]
        res = score_universe(history.market_at(d, lookback), cfg)
        entry = calendar[i + 1] if i + 1 < len(calendar) else None
        exits = {h: calendar[i + 1 + h] if i + 1 + h < len(calendar) else None for h in horizons}
        drow = {"date": d, "regime": res["regime"]["regime"], "n": len(res["stocks"])}
        for h in horizons:
            ok = entry and exits[h] and n_open.get(entry) and n_open.get(exits[h])
            drow[f"nifty_{h}"] = n_open[exits[h]] / n_open[entry] - 1 if ok else np.nan
        drows.append(drow)
        for s in res["stocks"]:
            sym, t = s["symbol"], s["technicals"]
            row = {"date": d, "symbol": sym, "sector": s["sector"], "regime": drow["regime"],
                   "bars": t.get("bars"), "liquidity": t.get("avg_traded_value_cr"),
                   "rank": s["rank"], "composite": s["total_score"], "risk_level": s["risk_level"]}
            for c in COMPONENT_ORDER:
                comp = s["components"][c]
                row[f"f_{c}"] = comp["normalized_score"]
                row[f"cov_{c}"] = comp["coverage"]
            o = opens.get(sym, {})
            for h in horizons:
                a = o.get(entry) if entry else None
                b = o.get(exits[h]) if exits[h] else None
                row[f"ret_{h}"] = b / a - 1 if a and b else np.nan
            rows.append(row)
        if progress:
            progress(k + 1, len(dates), d)
    return pd.DataFrame(rows), pd.DataFrame(drows)


def add_variants(panel: pd.DataFrame, cfg: Config | None = None) -> pd.DataFrame:
    """Derived factors for the missing-data study (research only; the engine is unchanged).

    composite_shrunk: each component's score shrunk toward neutral by its missing share,
        cov * score + (1 - cov) * 0.5, i.e. a missing metric counts as neutral at its own weight
        instead of the remaining metrics taking over its weight.
    price_only: the 5 price-based components re-weighted to 100 (fundamentals carry no information yet).
    """
    cfg = cfg or default_config()
    w = {c: cfg["components"][c]["weight"] for c in COMPONENT_ORDER}
    neutral = cfg["missing_data_neutral"]
    p = panel.copy()
    p["composite_shrunk"] = sum(
        w[c] * (p[f"cov_{c}"] * p[f"f_{c}"] + (1 - p[f"cov_{c}"]) * neutral) for c in COMPONENT_ORDER)
    price = ("momentum", "technicalTrend", "liquidity", "sectorStrength", "risk")
    p["price_only"] = sum(w[c] * p[f"f_{c}"] for c in price) * 100 / sum(w[c] for c in price)
    return p


FACTORS = tuple(f"f_{c}" for c in COMPONENT_ORDER) + ("composite", "composite_shrunk", "price_only")
LABELS = {"f_fundamentals": "Quality", "f_earningsGrowth": "Growth", "f_momentum": "Momentum",
          "f_technicalTrend": "Technical trend", "f_valuation": "Valuation", "f_liquidity": "Liquidity",
          "f_sectorStrength": "Sector strength", "f_risk": "Risk (less is better)",
          "composite": "Composite score", "composite_shrunk": "Composite, missing→neutral per metric",
          "price_only": "Price-only composite"}


# ---------------------------------------------------------------- IC statistics

def rank_corr(a: pd.Series, b: pd.Series) -> float:
    """Spearman correlation (average ranks for ties) without SciPy."""
    return a.rank().corr(b.rank())


def ic_by_date(panel: pd.DataFrame, factor: str, h: int, method: str = "spearman") -> pd.Series:
    """One cross-sectional correlation per date (NaN when too few stocks or a constant factor)."""
    col = f"ret_{h}"

    def one(g: pd.DataFrame) -> float:
        g = g[[factor, col]].dropna()
        if len(g) < MIN_STOCKS or g[factor].nunique() < 2 or g[col].nunique() < 2:
            return np.nan
        return rank_corr(g[factor], g[col]) if method == "spearman" else g[factor].corr(g[col])

    return panel.groupby("date", sort=True)[[factor, col]].apply(one)


def newey_west_t(x: np.ndarray, lag: int) -> float | None:
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return None
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else None


def ic_summary(ic: pd.Series, h: int, step: int) -> dict:
    x = ic.dropna().to_numpy()
    if len(x) == 0:
        return {"n_dates": 0}
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    return {
        "n_dates": int(len(x)),
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "std": sd,
        "icir": float(np.mean(x) / sd) if sd else None,
        "hit_rate": float(np.mean(x > 0)),
        "t_nw": newey_west_t(x, max(0, math.ceil(h / step) - 1)),
    }


def factor_table(panel: pd.DataFrame, horizons: Iterable[int], step: int,
                 factors: Iterable[str] = FACTORS) -> dict:
    """{factor: {h: {"rank_ic": summary, "ic": summary, "n_obs": stock-dates}}}"""
    out = {}
    for f in factors:
        out[f] = {}
        for h in horizons:
            n_obs = int(panel[[f, f"ret_{h}"]].dropna().shape[0])
            out[f][h] = {"rank_ic": ic_summary(ic_by_date(panel, f, h), h, step),
                         "ic": ic_summary(ic_by_date(panel, f, h, "pearson"), h, step),
                         "n_obs": n_obs}
    return out


def split_ic(panel: pd.DataFrame, factor: str, h: int, by: str, step: int, min_stocks: int = MIN_STOCKS) -> dict:
    """Mean rank IC within each group of `by` (a column constant per date, or per stock)."""
    out = {}
    for key, g in panel.groupby(by):
        ic = ic_by_date(g, factor, h) if len(g) else pd.Series(dtype=float)
        s = ic_summary(ic, h, step)
        if s["n_dates"]:
            out[str(key)] = s
    return out


def with_groups(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds era and a per-date liquidity tercile (proxy for market-cap size; true market cap needs
    shares outstanding, which arrive with fundamentals)."""
    p = panel.copy()
    p["era"] = "other"
    for name, a, b in ERAS:
        p.loc[(p["date"] >= a) & (p["date"] <= b), "era"] = name
    p["size_proxy"] = p.groupby("date")["liquidity"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 3, labels=["low liquidity", "mid liquidity", "high liquidity"]))
    return p


# ---------------------------------------------------------------- composite as a portfolio

def bucket_study(panel: pd.DataFrame, dates_df: pd.DataFrame, h: int, step: int,
                 score: str = "composite") -> dict:
    """Non-overlapping holding periods of h sessions. Buckets by score rank on each date."""
    every = max(1, math.ceil(h / step))
    all_dates = sorted(panel["date"].unique())
    dates = all_dates[::every]
    nifty = dates_df.set_index("date")[f"nifty_{h}"]
    ret = f"ret_{h}"
    buckets = {"Top 5": ("top", 5), "Top 10": ("top", 10), "Top 20": ("top", 20),
               "Top decile": ("decile", 9), "Bottom decile": ("decile", 0)}
    series: dict[str, list] = {b: [] for b in buckets} | {f"Decile {i + 1}": [] for i in range(10)}
    prev: dict[str, set] = {}
    turnover: dict[str, list] = {b: [] for b in series}
    for d in dates:
        g = panel[(panel["date"] == d)].dropna(subset=[ret, score]).sort_values(score, ascending=False)
        if len(g) < 20 or np.isnan(nifty.get(d, np.nan)):
            continue
        dec = pd.qcut(g[score].rank(method="first"), 10, labels=False)
        groups = {}
        for b, (kind, n) in buckets.items():
            groups[b] = g.head(n) if kind == "top" else g[dec == n]
        for i in range(10):
            groups[f"Decile {i + 1}"] = g[dec == 9 - i]  # Decile 1 = highest scores
        for b, sel in groups.items():
            names = set(sel["symbol"])
            to = 1.0 if b not in prev else 1 - len(names & prev[b]) / max(len(names), 1)
            prev[b] = names
            turnover[b].append(to)
            r = float(sel[ret].mean())
            series[b].append((d, r, float(nifty[d]), r - to * ROUND_TRIP_COST))
    out = {}
    per_year = 252 / h
    for b, rows in series.items():
        if not rows:
            continue
        r = np.array([x[1] for x in rows])
        n = np.array([x[2] for x in rows])
        net = np.array([x[3] for x in rows])
        ex = r - n
        eq = np.cumprod(1 + net)
        dd = float((eq / np.maximum.accumulate(eq) - 1).min() * 100)
        downside = net[net < 0]
        out[b] = {
            "periods": len(rows),
            "mean_return_pct": float(r.mean() * 100),
            "mean_excess_vs_nifty_pct": float(ex.mean() * 100),
            "hit_rate_vs_nifty": float(np.mean(ex > 0)),
            "volatility_ann_pct": float(np.std(r, ddof=1) * math.sqrt(per_year) * 100) if len(r) > 1 else None,
            "max_drawdown_pct": dd,
            "avg_turnover": float(np.mean(turnover[b][1:])) if len(turnover[b]) > 1 else None,
            "mean_net_return_pct": float(net.mean() * 100),
            "cagr_net_pct": float((eq[-1] ** (per_year / len(net)) - 1) * 100),
            "sharpe": float(net.mean() / np.std(net, ddof=1) * math.sqrt(per_year)) if len(net) > 1 and np.std(net) else None,
            "sortino": float(net.mean() / math.sqrt(np.mean(downside ** 2)) * math.sqrt(per_year)) if len(downside) else None,
        }
    deciles = [out[f"Decile {i + 1}"]["mean_return_pct"] for i in range(10) if f"Decile {i + 1}" in out]
    if len(deciles) == 10:
        out["monotonicity"] = float(rank_corr(pd.Series(deciles), pd.Series(range(10, 0, -1), dtype=float)))
    return out


# ---------------------------------------------------------------- ranking stability

def rank_stability(panel: pd.DataFrame, lags: Iterable[int], step: int, top: int = 10) -> dict:
    """Spearman correlation of ranks and top-N retention between dates `lag` sessions apart."""
    dates = sorted(panel["date"].unique())
    ranks = {d: g.set_index("symbol")["rank"] for d, g in panel.groupby("date")}
    out = {}
    for lag in lags:
        k = lag // step
        if k < 1 or lag % step:
            continue
        corr, keep = [], []
        for a, b in zip(dates, dates[k:]):
            ra, rb = ranks[a], ranks[b]
            common = ra.index.intersection(rb.index)
            if len(common) >= MIN_STOCKS:
                corr.append(rank_corr(ra[common], rb[common]))
            ta, tb = set(ra.nsmallest(top).index), set(rb.nsmallest(top).index)
            keep.append(len(ta & tb) / top)
        out[f"{lag} sessions"] = {"rank_corr": float(np.nanmean(corr)) if corr else None,
                                  f"top{top}_retained": float(np.mean(keep)) if keep else None,
                                  "pairs": len(keep)}
    return out
