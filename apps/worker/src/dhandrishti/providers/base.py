from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..models import Bars, Event, Fundamentals, Security

# From least to most "live". A mixed dataset is labelled with its least-live member,
# so MOCK can never be presented as anything else.
PROVENANCE_ORDER = ("MOCK", "EOD", "DELAYED", "LIVE")


def least_live(provenances: Iterable[str]) -> str:
    seen = set(provenances)
    unknown = seen - set(PROVENANCE_ORDER)
    if unknown:
        raise ValueError(f"unknown provenance: {sorted(unknown)}")
    if not seen:
        raise ValueError("no provenance supplied")
    return min(seen, key=PROVENANCE_ORDER.index)


@dataclass(frozen=True)
class NewsItem:
    published_at: str  # ISO-8601 with timezone
    headline: str
    url: str
    source: str
    symbol: str | None = None
    summary: str | None = None


class _Provider(Protocol):
    name: str
    provenance: str  # one of PROVENANCE_ORDER


@runtime_checkable
class MarketDataProvider(_Provider, Protocol):
    def list_securities(self) -> list[Security]: ...

    def daily_bars(self, symbols: Sequence[str], start: str, end: str) -> dict[str, Bars]:
        """Adjusted daily OHLCV per symbol for trading dates in [start, end]."""
        ...

    def index_bars(self, codes: Sequence[str], start: str, end: str) -> dict[str, Bars]: ...


@runtime_checkable
class FundamentalDataProvider(_Provider, Protocol):
    def fundamentals(self, symbols: Sequence[str], as_of: str) -> dict[str, Fundamentals]:
        """Latest fundamentals known on `as_of` (no look-ahead)."""
        ...

    def fundamentals_history(self, symbols: Sequence[str], start: str, end: str) -> dict[str, list[Fundamentals]]:
        """Every snapshot published in [start, end], each dated by its publication date (`as_of`)."""
        ...


@runtime_checkable
class CorporateActionProvider(_Provider, Protocol):
    def events(self, symbols: Sequence[str], start: str, end: str) -> list[Event]: ...


@runtime_checkable
class NewsProvider(_Provider, Protocol):
    def news(self, symbols: Sequence[str], since: str) -> list[NewsItem]: ...
