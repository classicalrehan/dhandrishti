"""Engine input models. `None` always means "Data unavailable"."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np


@dataclass(frozen=True)
class Security:
    symbol: str
    name: str
    sector: str
    is_financial: bool
    exchange: str = "NSE"
    industry: str | None = None
    indices: tuple[str, ...] = ()


@dataclass
class Bars:
    """Columnar daily OHLCV, ascending by date."""

    dates: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __len__(self) -> int:
        return len(self.dates)

    @classmethod
    def from_columns(cls, dates: list[str], cols: dict[str, list[float]]) -> "Bars":
        return cls(
            dates=list(dates),
            open=np.asarray(cols["open"], dtype=float),
            high=np.asarray(cols["high"], dtype=float),
            low=np.asarray(cols["low"], dtype=float),
            close=np.asarray(cols["close"], dtype=float),
            volume=np.asarray(cols["volume"], dtype=float),
        )

    def to_columns(self) -> dict[str, list[float]]:
        return {
            "open": self.open.tolist(),
            "high": self.high.tolist(),
            "low": self.low.tolist(),
            "close": self.close.tolist(),
            "volume": [int(v) for v in self.volume],
        }


FUNDAMENTAL_FIELDS = (
    "market_cap_cr",
    "revenue_growth_yoy",
    "profit_growth_yoy",
    "eps_growth_yoy",
    "eps_cagr_3y",
    "roe",
    "roce",
    "operating_margin",
    "net_margin",
    "free_cash_flow_cr",
    "cfo_to_pat",
    "debt_to_equity",
    "interest_coverage",
    "pe",
    "pb",
    "peg",
    "dividend_yield",
    "promoter_holding",
    "promoter_pledge",
    "institutional_holding",
    "pe_median_5y",
    "positive_eps_quarters_8",
    # Per-share data from the latest filing; when present, valuation is repriced daily (SPEC §5.2).
    "eps_ttm",
    "book_value_per_share",
    "dps_ttm",
    "shares_outstanding_cr",
)


@dataclass
class Fundamentals:
    as_of: str | None = None
    market_cap_cr: float | None = None
    revenue_growth_yoy: float | None = None
    profit_growth_yoy: float | None = None
    eps_growth_yoy: float | None = None
    eps_cagr_3y: float | None = None
    roe: float | None = None
    roce: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    free_cash_flow_cr: float | None = None
    cfo_to_pat: float | None = None
    debt_to_equity: float | None = None
    interest_coverage: float | None = None
    pe: float | None = None
    pb: float | None = None
    peg: float | None = None
    dividend_yield: float | None = None
    promoter_holding: float | None = None
    promoter_pledge: float | None = None
    institutional_holding: float | None = None
    pe_median_5y: float | None = None
    positive_eps_quarters_8: int | None = None
    quarterly_eps: list[float] | None = None
    eps_ttm: float | None = None  # ₹ per share, trailing four quarters
    book_value_per_share: float | None = None  # ₹
    dps_ttm: float | None = None  # ₹ dividends per share, trailing four quarters
    shares_outstanding_cr: float | None = None  # crore shares


@dataclass(frozen=True)
class Event:
    date: str
    type: str  # EARNINGS | DIVIDEND | SPLIT | BONUS | AGM | REGULATORY | OTHER
    title: str
    symbol: str | None = None


@dataclass
class StockInput:
    security: Security
    bars: Bars
    fundamentals: Fundamentals | None
    events: list[Event] = field(default_factory=list)


@dataclass
class MarketInput:
    as_of: str
    provenance: str  # MOCK | EOD | DELAYED | LIVE
    stocks: list[StockInput]
    nifty: Bars
    bank_nifty: Bars
    india_vix: Bars


def slice_bars(b: Bars, end: str, lookback: int | None = None) -> Bars:
    """Bars dated on or before `end`, optionally only the last `lookback` of them."""
    stop = 0
    for i, d in enumerate(b.dates):
        if d > end:
            break
        stop = i + 1
    start = 0 if lookback is None else max(0, stop - lookback)
    return Bars(dates=b.dates[start:stop], open=b.open[start:stop], high=b.high[start:stop],
                low=b.low[start:stop], close=b.close[start:stop], volume=b.volume[start:stop])


STALE_DAYS = 10


def is_stale(last_bar: str, as_of: str) -> bool:
    """A stock whose latest price is over STALE_DAYS calendar days old (suspended, delisted, or no longer
    refreshed) is left out rather than scored on old prices."""
    return (date.fromisoformat(as_of) - date.fromisoformat(last_bar)).days > STALE_DAYS


@dataclass
class MarketHistory:
    """Full history for point-in-time research (backtests).

    `fundamentals[symbol]` holds snapshots sorted by `as_of`, where `as_of` is the date the
    numbers became public, so a snapshot is usable only on or after that date.
    """

    as_of: str
    provenance: str
    securities: list[Security]
    bars: dict[str, Bars]
    fundamentals: dict[str, list[Fundamentals]]
    events: dict[str, list[Event]]
    nifty: Bars
    bank_nifty: Bars
    india_vix: Bars

    def market_at(self, as_of: str, lookback: int = 300) -> MarketInput:
        """The market exactly as it was knowable at the close of `as_of` (no look-ahead)."""
        stocks = []
        for sec in self.securities:
            bars = slice_bars(self.bars[sec.symbol], as_of, lookback)
            if len(bars) == 0 or is_stale(bars.dates[-1], as_of):
                continue
            known = [f for f in self.fundamentals.get(sec.symbol, []) if f.as_of is not None and f.as_of <= as_of]
            stocks.append(StockInput(
                security=sec,
                bars=bars,
                fundamentals=known[-1] if known else None,
                events=[e for e in self.events.get(sec.symbol, []) if e.date > as_of],
            ))
        return MarketInput(
            as_of=as_of,
            provenance=self.provenance,
            stocks=stocks,
            nifty=slice_bars(self.nifty, as_of, lookback),
            bank_nifty=slice_bars(self.bank_nifty, as_of, lookback),
            india_vix=slice_bars(self.india_vix, as_of, lookback),
        )
