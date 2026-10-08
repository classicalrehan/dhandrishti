"""Replay the paper-trading engine over history, exactly as `pnpm paper:run` would have traded.

Day 0 behaves like `paper create` (signal at day 0's close); every later session is
`process_day`: fills at the open, marks at the close, stop-losses, kill switch, and a rebalance on
the last session of each week/month/quarter. Same whole shares and Zerodha charges as live paper
trading, so a rule that wins here is the rule that runs live.

Benchmarks over the same window: NIFTY 50 and an equal-weight book of every scored stock,
rebalanced monthly at the next open with costs (the fairest yardstick under survivorship bias).
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..backtesting import metrics as M
from ..backtesting.engine import _Book, _period_key
from ..models import MarketHistory
from ..trading.paper import PaperParams, equity_of, new_state, plan_rebalance, process_day

Signal = tuple[list[dict], str]  # (ranked stocks, market regime)


@dataclass
class ReplayResult:
    name: str
    params: PaperParams
    dates: list[str]
    equity: np.ndarray
    invested_pct: np.ndarray
    charges: float
    trades: int
    stop_losses: int
    halted_on: str | None

    def summary(self) -> dict:
        s = M.summary(self.equity, self.dates, 0.0)
        return {
            "return_pct": (self.equity[-1] / self.equity[0] - 1) * 100,
            "cagr_pct": s["cagr_pct"],
            "max_drawdown_pct": s["max_drawdown_pct"],
            "volatility_pct": s["volatility_pct"],
            "sharpe": s["sharpe"],
            "charges": self.charges,
            "trades": self.trades,
            "stop_losses": self.stop_losses,
            "avg_invested_pct": float(np.mean(self.invested_pct)),
            "halted_on": self.halted_on,
        }


class SignalCache:
    """Scores each signal day once and shares it across every rule variant."""

    def __init__(self, history: MarketHistory, score: Callable[[MarketHistory, str], Signal]):
        self.history, self._score, self._cache = history, score, {}

    def __call__(self, day: str) -> Signal:
        if day not in self._cache:
            self._cache[day] = self._score(self.history, day)
        return self._cache[day]


def price_tables(history: MarketHistory) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """day -> {symbol: open}, day -> {symbol: close}."""
    opens: dict[str, dict[str, float]] = {}
    closes: dict[str, dict[str, float]] = {}
    for sym, b in history.bars.items():
        for d, o, c in zip(b.dates, b.open.tolist(), b.close.tolist()):
            opens.setdefault(d, {})[sym] = o
            closes.setdefault(d, {})[sym] = c
    return opens, closes


def replay(name: str, params: PaperParams, days: list[str], signals: SignalCache,
           opens: dict, closes: dict) -> ReplayResult:
    """`days` are consecutive sessions; the portfolio is created on days[0]."""
    state = new_state(params)
    ranked, regime = signals(days[0])
    state.pending, _ = plan_rebalance(state, days[0], ranked, closes[days[0]], "INITIAL", regime=regime)
    state.last_processed = days[0]
    eq, inv = [params.capital], [0.0]
    charges = trades = stops = 0
    halted = None
    for i, day in enumerate(days[1:], 1):
        nxt = days[i + 1] if i + 1 < len(days) else None
        signal_day = nxt is not None and _period_key(day, params.rebalance) != _period_key(nxt, params.rebalance)
        rk = rg = None
        if state.status == "ACTIVE" and signal_day:
            rk, rg = signals(day)
        r = process_day(state, day, opens.get(day, {}), closes.get(day, {}), rk, rg)
        charges += sum(o.charges for o in r.filled)
        trades += len(r.filled)
        stops += sum(o.reason == "STOP_LOSS" for o in r.created)
        if state.status == "HALTED" and halted is None:
            halted = day
        e = equity_of(state)
        eq.append(e)
        inv.append((e - state.cash) / e * 100 if e else 0.0)
    return ReplayResult(name, params, days, np.array(eq), np.array(inv), charges, trades, stops, halted)


def benchmarks(days: list[str], signals: SignalCache, history: MarketHistory, opens: dict, closes: dict,
               capital: float) -> dict[str, ReplayResult]:
    """NIFTY 50 and the monthly-rebalanced equal-weight universe over `days`."""
    nifty = dict(zip(history.nifty.dates, history.nifty.close.tolist()))
    n = np.array([capital * nifty[d] / nifty[days[0]] for d in days])
    book = _Book(capital, 15.0, 13.5)
    ew, pending = [], [s["symbol"] for s in signals(days[0])[0]]
    for i, day in enumerate(days):
        if pending is not None and i > 0:
            book.rebalance(pending, opens.get(day, {}))
            pending = None
        ew.append(book.mark(closes.get(day, {})) if book.shares or i else capital)
        nxt = days[i + 1] if i + 1 < len(days) else None
        if nxt and _period_key(day, "monthly") != _period_key(nxt, "monthly"):
            pending = [s["symbol"] for s in signals(day)[0]]
    zeros = np.zeros(len(days))
    p = PaperParams(capital=capital)
    return {
        "NIFTY 50": ReplayResult("NIFTY 50", p, days, n, zeros + 100, 0.0, 0, 0, None),
        "Equal-weight universe": ReplayResult("Equal-weight universe", p, days, np.array(ew), zeros + 100,
                                              book.costs, 0, 0, None),
    }
