"""Data-provider interfaces. The scoring engine never talks to a provider:
providers feed ingestion, ingestion writes PostgreSQL, scoring reads PostgreSQL."""

from .base import (
    PROVENANCE_ORDER,
    CorporateActionProvider,
    FundamentalDataProvider,
    MarketDataProvider,
    NewsItem,
    NewsProvider,
    least_live,
)

__all__ = [
    "PROVENANCE_ORDER",
    "CorporateActionProvider",
    "FundamentalDataProvider",
    "MarketDataProvider",
    "NewsItem",
    "NewsProvider",
    "least_live",
]
