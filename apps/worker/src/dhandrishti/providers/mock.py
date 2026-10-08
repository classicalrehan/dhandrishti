"""MOCK implementation of all four provider interfaces.

The mock market is a fixed synthetic history of `history_bars` sessions ending on `anchor`
(the latest 300 match the golden fixtures); requests are served by slicing it, so repeated or
incremental ingestion is consistent. Fundamentals are point-in-time quarterly snapshots.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from functools import cached_property

from ..ingestion.mock import DEFAULT_SEED
from ..ingestion.mock_history import generate_history
from ..models import Bars, Event, Fundamentals, MarketHistory, Security
from .base import NewsItem

MOCK_ANCHOR = "2026-10-05"
INDEX_CODES = ("NIFTY 50", "NIFTY BANK", "INDIA VIX")


def _slice(b: Bars, start: str, end: str) -> Bars:
    idx = [i for i, d in enumerate(b.dates) if start <= d <= end]
    if not idx:
        return Bars(dates=[], open=b.open[:0], high=b.high[:0], low=b.low[:0], close=b.close[:0],
                    volume=b.volume[:0])
    s, e = idx[0], idx[-1] + 1
    return Bars(dates=b.dates[s:e], open=b.open[s:e], high=b.high[s:e], low=b.low[s:e],
                close=b.close[s:e], volume=b.volume[s:e])


class MockProvider:
    """Implements MarketDataProvider, FundamentalDataProvider, CorporateActionProvider, NewsProvider."""

    name = "dhandrishti-mock"
    provenance = "MOCK"

    def __init__(self, anchor: str = MOCK_ANCHOR, history_bars: int = 1060, seed: int = DEFAULT_SEED):
        self.anchor, self.history_bars, self.seed = anchor, history_bars, seed

    @cached_property
    def _history(self) -> MarketHistory:
        return generate_history(self.anchor, history_bars=self.history_bars, seed=self.seed)

    # MarketDataProvider
    def list_securities(self) -> list[Security]:
        return list(self._history.securities)

    def daily_bars(self, symbols: Sequence[str], start: str, end: str) -> dict[str, Bars]:
        bars = self._history.bars
        return {sym: _slice(bars[sym], start, end) for sym in symbols if sym in bars}

    def index_bars(self, codes: Sequence[str], start: str, end: str) -> dict[str, Bars]:
        h = self._history
        series = {"NIFTY 50": h.nifty, "NIFTY BANK": h.bank_nifty, "INDIA VIX": h.india_vix}
        return {c: _slice(series[c], start, end) for c in codes if c in series}

    # FundamentalDataProvider
    def fundamentals(self, symbols: Sequence[str], as_of: str) -> dict[str, Fundamentals]:
        out = {}
        for sym in symbols:
            known = [f for f in self._history.fundamentals.get(sym, []) if f.as_of and f.as_of <= as_of]
            if known:
                out[sym] = known[-1]
        return out

    def fundamentals_history(self, symbols: Sequence[str], start: str, end: str) -> dict[str, list[Fundamentals]]:
        return {sym: [f for f in self._history.fundamentals.get(sym, []) if f.as_of and start <= f.as_of <= end]
                for sym in symbols}

    # CorporateActionProvider
    def events(self, symbols: Sequence[str], start: str, end: str) -> list[Event]:
        ev = self._history.events
        return [e for sym in symbols for e in ev.get(sym, []) if start <= e.date <= end]

    # NewsProvider — deliberately empty: we do not fabricate headlines about real companies.
    def news(self, symbols: Sequence[str], since: str) -> list[NewsItem]:
        return []

    def history_start(self) -> str:
        return self._history.nifty.dates[0]

    @staticmethod
    def event_horizon(as_of: str, days: int = 90) -> str:
        return (date.fromisoformat(as_of) + timedelta(days=days)).isoformat()
