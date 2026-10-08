"""Point-in-time backtest of the DhanDrishti score.

At every rebalance:
  1. Signal  - score the universe with only the data knowable at the close of the signal date
               (`MarketHistory.market_at`: prices up to that close, fundamentals already published).
  2. Select  - equal-weight the top N by score, after optional risk/confidence filters.
  3. Execute - trade at the NEXT session's open, paying Indian delivery costs.

Two comparison books run on the same schedule and costs: the NIFTY 50 index and an
equal-weight portfolio of every scored stock. Beating the equal-weight universe is the real
test, because it isolates whether the score adds anything over simply owning the universe.

Simplifications (documented in docs/backtesting.md): fractional shares; costs applied as a
proportional haircut at rebalance; a stock without an open price on an execution day is not
bought, and is valued/sold at its last known price; dividends are ignored (price returns,
and NIFTY is the price index, not total return).
"""

from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

from ..config import Config, default_config
from ..models import Bars, MarketHistory
from ..scoring import score_universe
from . import metrics as M

RISK_ORDER = ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
CONFIDENCE_ORDER = ("LOW", "MEDIUM", "HIGH")


@dataclass(frozen=True)
class BacktestParams:
    start: str
    end: str
    rebalance: str = "monthly"  # weekly | monthly | quarterly
    top_n: int = 10
    max_risk: str | None = "MEDIUM"  # skip HIGH / VERY_HIGH risk stocks
    min_confidence: str | None = None
    # Indian equity delivery, per side, in basis points of traded value. Buy: STT 10 + stamp duty 1.5
    # + exchange/SEBI/GST ~0.5 + slippage ~3. Sell: STT 10 + ~0.5 + slippage ~3. Brokerage taken as 0.
    buy_cost_bps: float = 15.0
    sell_cost_bps: float = 13.5
    initial_capital: float = 1_000_000.0
    risk_free_rate: float = 0.0  # annual, for Sharpe/Sortino
    lookback_bars: int = 300
    quantiles: int = 5

    def validate(self) -> None:
        if self.rebalance not in ("weekly", "monthly", "quarterly"):
            raise ValueError("rebalance must be weekly, monthly or quarterly")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.max_risk is not None and self.max_risk not in RISK_ORDER:
            raise ValueError(f"max_risk must be one of {RISK_ORDER}")
        if self.min_confidence is not None and self.min_confidence not in CONFIDENCE_ORDER:
            raise ValueError(f"min_confidence must be one of {CONFIDENCE_ORDER}")
        if self.quantiles < 2:
            raise ValueError("quantiles must be >= 2")


@dataclass
class BacktestResult:
    params: BacktestParams
    config_version: str
    provenance: str
    dates: list[str]
    strategy: np.ndarray
    nifty: np.ndarray
    universe_ew: np.ndarray
    metrics: dict
    periods: list[dict] = field(default_factory=list)
    holdings: list[dict] = field(default_factory=list)

    def equity_rows(self) -> list[dict]:
        dd = M.drawdown_series(self.strategy)
        return [
            {"date": d, "strategy": round(float(s), 2), "nifty": round(float(n), 2),
             "universe_ew": round(float(u), 2), "drawdown_pct": round(float(x), 4)}
            for d, s, n, u, x in zip(self.dates, self.strategy, self.nifty, self.universe_ew, dd)
        ]

    def to_dict(self) -> dict:
        return {
            "params": asdict(self.params),
            "config_version": self.config_version,
            "data_provenance": self.provenance,
            "metrics": self.metrics,
            "periods": self.periods,
            "holdings": self.holdings,
            "equity": self.equity_rows(),
        }


def _period_key(d: str, freq: str) -> tuple:
    dt = date.fromisoformat(d)
    if freq == "weekly":
        y, w, _ = dt.isocalendar()
        return (y, w)
    if freq == "quarterly":
        return (dt.year, (dt.month - 1) // 3)
    return (dt.year, dt.month)


def rebalance_dates(calendar: list[str], start: str, end: str, freq: str) -> list[tuple[str, str]]:
    """(signal, execution) pairs: the last session of each period, traded at the next session."""
    days = [d for d in calendar if d <= end]
    pairs = []
    for i, d in enumerate(days[:-1]):
        if d < start:
            continue
        if _period_key(d, freq) != _period_key(days[i + 1], freq):
            pairs.append((d, days[i + 1]))
    return pairs


class _Book:
    """Fractional-share, fully invested, equal-weight book."""

    def __init__(self, capital: float, buy_bps: float, sell_bps: float):
        self.cash = capital
        self.shares: dict[str, float] = {}
        self.last: dict[str, float] = {}
        self.buy_bps, self.sell_bps = buy_bps, sell_bps
        self.costs = 0.0
        self.turnover: list[float] = []

    def mark(self, prices: dict[str, float]) -> float:
        self.last.update({s: p for s, p in prices.items() if s in self.shares})
        return self.cash + sum(n * self.last[s] for s, n in self.shares.items())

    def rebalance(self, targets: list[str], opens: dict[str, float]) -> float:
        nav = self.mark(opens)
        tradable = [s for s in targets if s in opens]
        desired = {s: (nav / len(tradable)) / opens[s] for s in tradable} if tradable else {}
        buys = sells = 0.0
        for s in set(self.shares) | set(desired):
            price = opens.get(s, self.last.get(s, 0.0))
            delta = (desired.get(s, 0.0) - self.shares.get(s, 0.0)) * price
            if delta > 0:
                buys += delta
            else:
                sells -= delta
        cost = buys * self.buy_bps / 1e4 + sells * self.sell_bps / 1e4
        self.costs += cost
        self.turnover.append((buys + sells) / 2 / nav if nav else 0.0)
        if desired:
            scale = (nav - cost) / nav
            self.shares = {s: n * scale for s, n in desired.items()}
            self.last.update({s: opens[s] for s in desired})
            self.cash = 0.0
        else:
            self.shares, self.cash = {}, nav - cost
        return nav - cost


def _price_maps(bars: dict[str, Bars]) -> tuple[dict, dict]:
    opens = {s: dict(zip(b.dates, b.open.tolist())) for s, b in bars.items()}
    closes = {s: dict(zip(b.dates, b.close.tolist())) for s, b in bars.items()}
    return opens, closes


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


def run_backtest(history: MarketHistory, params: BacktestParams, cfg: Config | None = None) -> BacktestResult:
    params.validate()
    cfg = cfg or default_config()
    calendar = history.nifty.dates
    pairs = rebalance_dates(calendar, params.start, params.end, params.rebalance)
    if not pairs:
        raise ValueError("no rebalance dates in the requested window")
    first_needed = calendar.index(pairs[0][0]) + 1
    if first_needed < params.lookback_bars:
        raise ValueError(
            f"start {params.start} leaves only {first_needed} sessions of history; "
            f"{params.lookback_bars} are needed before the first signal")

    opens, closes = _price_maps(history.bars)
    n_open = dict(zip(history.nifty.dates, history.nifty.open.tolist()))
    n_close = dict(zip(history.nifty.dates, history.nifty.close.tolist()))
    risk_cap = RISK_ORDER.index(params.max_risk) if params.max_risk else len(RISK_ORDER) - 1
    conf_min = CONFIDENCE_ORDER.index(params.min_confidence) if params.min_confidence else 0

    # 1. Signals (point in time).
    signals = []
    for signal, execution in pairs:
        result = score_universe(history.market_at(signal, params.lookback_bars), cfg)
        ranked = result["stocks"]
        eligible = [
            s for s in ranked
            if RISK_ORDER.index(s["risk_level"]) <= risk_cap and CONFIDENCE_ORDER.index(s["confidence"]) >= conf_min
        ]
        signals.append({"signal": signal, "execution": execution, "ranked": ranked,
                        "picks": eligible[: params.top_n], "regime": result["regime"]["regime"]})

    # 2. Simulate daily.
    exec_dates = {s["execution"]: s for s in signals}
    first_exec = signals[0]["execution"]
    days = [d for d in calendar if first_exec <= d <= params.end]
    strat = _Book(params.initial_capital, params.buy_cost_bps, params.sell_cost_bps)
    ew = _Book(params.initial_capital, params.buy_cost_bps, params.sell_cost_bps)
    nifty_base = n_open[first_exec]
    out_dates, s_nav, e_nav, n_nav = [], [], [], []
    period_start: dict[str, float] = {}
    holdings: list[dict] = []
    periods: list[dict] = []

    def close_period(day: str) -> None:
        """Book the just-finished holding period, valued at `day`'s open (or the final close)."""
        if not periods:
            return
        p = periods[-1]
        at_open = day in exec_dates
        px = (lambda s: opens[s].get(day)) if at_open else (lambda s: closes[s].get(day))
        prices = {s: v for s in opens if (v := px(s)) is not None}
        s_val, e_val = strat.mark(prices), ew.mark(prices)
        n_val = (n_open if at_open else n_close)[day]
        p["end"] = day
        p["strategy_return_pct"] = (s_val / period_start["strategy"] - 1) * 100
        p["universe_return_pct"] = (e_val / period_start["universe"] - 1) * 100
        p["nifty_return_pct"] = (n_val / period_start["nifty"] - 1) * 100
        # Signal quality: forward return of every scored stock over the period.
        fwd, scores = [], []
        for s in p["_ranked"]:
            a, b = opens[s["symbol"]].get(p["execution"]), prices.get(s["symbol"])
            if a and b:
                fwd.append(b / a - 1)
                scores.append(s["total_score"])
        fwd_arr, sc_arr = np.array(fwd), np.array(scores)
        p["ic"] = M.spearman(sc_arr, fwd_arr)
        order = np.argsort(sc_arr, kind="stable")
        buckets = np.array_split(order, params.quantiles)
        p["quantile_returns_pct"] = [float(np.mean(fwd_arr[b]) * 100) if len(b) else None for b in buckets]

    for day in days:
        if day in exec_dates:
            close_period(day)
            sig = exec_dates[day]
            day_opens = {s: o[day] for s, o in opens.items() if day in o}
            picks = [p["symbol"] for p in sig["picks"]]
            period_start = {
                "strategy": strat.rebalance(picks, day_opens),
                "universe": ew.rebalance([s["symbol"] for s in sig["ranked"]], day_opens),
                "nifty": n_open[day],
            }
            periods.append({"signal": sig["signal"], "execution": day, "regime": sig["regime"],
                            "picks": picks, "turnover_pct": strat.turnover[-1] * 100, "_ranked": sig["ranked"]})
            weight = 1 / len([s for s in picks if s in day_opens]) if any(s in day_opens for s in picks) else 0
            for p in sig["picks"]:
                if p["symbol"] in day_opens:
                    holdings.append({"signal": sig["signal"], "execution": day, "symbol": p["symbol"],
                                     "rank": p["rank"], "total_score": p["total_score"],
                                     "risk_level": p["risk_level"], "confidence": p["confidence"],
                                     "weight": weight, "entry_price": day_opens[p["symbol"]]})
        day_closes = {s: c[day] for s, c in closes.items() if day in c}
        out_dates.append(day)
        s_nav.append(strat.mark(day_closes))
        e_nav.append(ew.mark(day_closes))
        n_nav.append(params.initial_capital * n_close[day] / nifty_base)
    close_period(days[-1])

    s_arr, e_arr, n_arr = np.array(s_nav), np.array(e_nav), np.array(n_nav)
    return BacktestResult(
        params=params,
        config_version=cfg["version"],
        provenance=history.provenance,
        dates=out_dates,
        strategy=s_arr,
        nifty=n_arr,
        universe_ew=e_arr,
        metrics=_metrics(params, out_dates, s_arr, n_arr, e_arr, periods, strat),
        periods=[_clean_period(p) for p in periods],
        holdings=[{k: _r(v, 6) if isinstance(v, float) else v for k, v in h.items()} for h in holdings],
    )


def _clean_period(p: dict) -> dict:
    return {k: (_r(v) if isinstance(v, float) else [_r(x) for x in v] if k == "quantile_returns_pct" else v)
            for k, v in p.items() if not k.startswith("_")}


def _metrics(params: BacktestParams, dates: list[str], s: np.ndarray, n: np.ndarray, e: np.ndarray,
             periods: list[dict], book: _Book) -> dict:
    rf = params.risk_free_rate
    strat, nifty, univ = M.summary(s, dates, rf), M.summary(n, dates, rf), M.summary(e, dates, rf)
    ics = [p["ic"] for p in periods if p.get("ic") is not None]
    q = np.array([p["quantile_returns_pct"] for p in periods if None not in p.get("quantile_returns_pct", [None])])
    q_mean = q.mean(axis=0).tolist() if len(q) else []
    beat_n = [p["strategy_return_pct"] > p["nifty_return_pct"] for p in periods]
    beat_u = [p["strategy_return_pct"] > p["universe_return_pct"] for p in periods]
    ic_sd = float(np.std(ics, ddof=1)) if len(ics) > 1 else 0.0

    def rnd(d: dict) -> dict:
        return {k: (_r(v) if isinstance(v, float) else v) for k, v in d.items()}

    return {
        "period": {"start": dates[0], "end": dates[-1], "rebalances": len(periods)},
        "strategy": rnd(strat),
        "nifty": rnd(nifty),
        "universe_ew": rnd(univ),
        "vs_nifty": rnd({"excess_cagr_pct": None if strat["cagr_pct"] is None else strat["cagr_pct"] - nifty["cagr_pct"],
                         **M.relative(s, n), "periods_beaten_pct": 100 * np.mean(beat_n) if beat_n else None}),
        "vs_universe": rnd({"excess_cagr_pct": None if strat["cagr_pct"] is None else strat["cagr_pct"] - univ["cagr_pct"],
                            **M.relative(s, e), "periods_beaten_pct": 100 * np.mean(beat_u) if beat_u else None}),
        # The first rebalance builds the portfolio from cash; it is not turnover in the usual sense.
        "trading": rnd({"avg_holdings": float(np.mean([len(p["picks"]) for p in periods])) if periods else 0.0,
                        "avg_turnover_pct": float(np.mean(book.turnover[1:]) * 100) if len(book.turnover) > 1 else 0.0,
                        "total_costs": book.costs,
                        "costs_pct_of_capital": book.costs / params.initial_capital * 100}),
        "signal": rnd({"mean_ic": float(np.mean(ics)) if ics else None,
                       "ic_t_stat": float(np.mean(ics) / ic_sd * np.sqrt(len(ics))) if ic_sd else None,
                       "positive_ic_pct": 100 * float(np.mean([x > 0 for x in ics])) if ics else None,
                       "top_minus_bottom_pct": (q_mean[-1] - q_mean[0]) if q_mean else None})
        | {"quantile_mean_returns_pct": [_r(x) for x in q_mean]},
    }
