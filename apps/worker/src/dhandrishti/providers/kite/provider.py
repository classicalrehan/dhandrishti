"""Kite Connect as a DhanDrishti data provider.

Prices and indices come from Kite (provenance "EOD": end-of-day candles). Kite Connect has no
fundamentals, events or news API, so those providers return nothing and the engine reports
"Data unavailable" for fundamentals-based components. Nothing is filled in with mock values.
"""

import logging
from collections.abc import Sequence
from functools import cached_property

import numpy as np

from ...ingestion.nse_universe import real_universe
from ...models import Bars, Event, Fundamentals, Security
from ..base import NewsItem
from .client import Candle, KiteClient

log = logging.getLogger(__name__)

INDEX_SYMBOLS = {"NIFTY 50": "NIFTY 50", "NIFTY BANK": "NIFTY BANK", "INDIA VIX": "INDIA VIX"}
# A one-day move this large in a large cap usually means an unadjusted split/bonus, not news.
SUSPICIOUS_MOVE = 0.35


def valid(c: Candle) -> bool:
    """Drop impossible candles (zero/negative prices, high below low); seen as pre-listing placeholders."""
    return min(c.open, c.high, c.low, c.close) > 0 and c.high >= c.low


def _bars(candles: list[Candle]) -> Bars:
    candles = [c for c in candles if valid(c)]
    return Bars(
        dates=[c.date for c in candles],
        open=np.array([c.open for c in candles], dtype=float),
        high=np.array([c.high for c in candles], dtype=float),
        low=np.array([c.low for c in candles], dtype=float),
        close=np.array([c.close for c in candles], dtype=float),
        volume=np.array([c.volume for c in candles], dtype=float),
    )


def suspicious_moves(symbol: str, b: Bars) -> list[str]:
    out = []
    for i in range(1, len(b)):
        move = b.close[i] / b.close[i - 1] - 1
        if abs(move) > SUSPICIOUS_MOVE:
            out.append(f"{symbol} {b.dates[i]}: {move:+.0%} close-to-close (check for an unadjusted split/bonus)")
    return out


class KiteMarketData:
    """MarketDataProvider over Kite Connect for the DhanDrishti universe."""

    name = "zerodha-kite"
    provenance = "EOD"

    def __init__(self, client: KiteClient, universe: Sequence[Security] | None = None):
        self.client = client
        self.universe = list(universe) if universe is not None else real_universe()
        self.warnings: list[str] = []

    @cached_property
    def _instruments(self) -> tuple[dict[str, int], dict[str, int]]:
        equities, indices = {}, {}
        for ins in self.client.instruments("NSE"):
            if ins.segment == "INDICES":
                indices[ins.tradingsymbol] = ins.instrument_token
            elif ins.segment == "NSE" and ins.instrument_type == "EQ":
                equities[ins.tradingsymbol] = ins.instrument_token
        return equities, indices

    def list_securities(self) -> list[Security]:
        equities, _ = self._instruments
        found = [s for s in self.universe if s.symbol in equities]
        missing = sorted({s.symbol for s in self.universe} - {s.symbol for s in found})
        if missing:
            self.warnings.append(f"Not found in Kite's NSE instrument list (renamed or delisted?): {', '.join(missing)}")
        return found

    def daily_bars(self, symbols: Sequence[str], start: str, end: str) -> dict[str, Bars]:
        equities, _ = self._instruments
        out = {}
        for i, sym in enumerate(symbols, 1):
            if sym not in equities:
                continue
            bars = _bars(self.client.daily_candles(equities[sym], start, end))
            if len(bars):
                out[sym] = bars
                self.warnings.extend(suspicious_moves(sym, bars))
            log.info("kite prices %d/%d %s: %d sessions", i, len(symbols), sym, len(bars))
        return out

    def index_bars(self, codes: Sequence[str], start: str, end: str) -> dict[str, Bars]:
        _, indices = self._instruments
        out = {}
        for code in codes:
            kite_symbol = INDEX_SYMBOLS.get(code, code)
            if kite_symbol not in indices:
                raise LookupError(f"Index {code!r} not found in Kite's INDICES segment")
            out[code] = _bars(self.client.daily_candles(indices[kite_symbol], start, end))
        return out


class Unavailable:
    """Fundamentals/events/news provider for sources that have none. Returns nothing, never guesses."""

    def __init__(self, name: str, provenance: str = "EOD"):
        self.name, self.provenance = name, provenance

    def fundamentals(self, symbols: Sequence[str], as_of: str) -> dict[str, Fundamentals]:
        return {}

    def fundamentals_history(self, symbols: Sequence[str], start: str, end: str) -> dict[str, list[Fundamentals]]:
        return {}

    def events(self, symbols: Sequence[str], start: str, end: str) -> list[Event]:
        return []

    def news(self, symbols: Sequence[str], since: str) -> list[NewsItem]:
        return []
