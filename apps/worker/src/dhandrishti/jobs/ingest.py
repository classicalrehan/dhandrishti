"""Ingest data from providers into PostgreSQL.

    uv run python -m dhandrishti.jobs.ingest --as-of 2026-10-05 [--start 2025-07-01]

Only the MOCK provider exists today; real providers plug in via the interfaces in
`dhandrishti.providers` once a data licence is in place (docs/compliance.md).
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import psycopg

from ..db import connect
from ..db import market_repository as repo
from ..providers import CorporateActionProvider, FundamentalDataProvider, MarketDataProvider, NewsProvider
from ..providers.mock import INDEX_CODES, MockProvider

log = logging.getLogger(__name__)


@dataclass
class Providers:
    market: MarketDataProvider
    fundamentals: FundamentalDataProvider
    events: CorporateActionProvider
    news: NewsProvider


def mock_providers(**kwargs) -> Providers:
    p = MockProvider(**kwargs)
    return Providers(market=p, fundamentals=p, events=p, news=p)


def kite_providers(client=None) -> Providers:
    """Real end-of-day prices from Zerodha Kite Connect; no fundamentals, events or news."""
    from ..providers.kite import KiteClient, load_session
    from ..providers.kite.provider import KiteMarketData, Unavailable

    market = KiteMarketData(client or KiteClient.from_session(load_session()))
    none = Unavailable("none (Kite has no fundamentals API)", market.provenance)
    return Providers(market=market, fundamentals=none, events=none, news=none)


def extend_universe(conn: psycopg.Connection, providers: Providers) -> None:
    """Real data only: also cover stocks you hold and stocks already stored, so none goes stale."""
    from ..ingestion.nse_universe import real_universe

    if not hasattr(providers.market, "universe") or providers.market.provenance == "MOCK":
        return
    known = {r[0] for r in conn.execute("SELECT symbol FROM securities")}
    if conn.execute("SELECT to_regclass('holding_items')").fetchone()[0]:
        known |= {r[0] for r in conn.execute("SELECT DISTINCT tradingsymbol FROM holding_items WHERE kind = 'HOLDING'")}
    providers.market.universe = real_universe(known)


class MixedProvenanceError(RuntimeError):
    pass


def check_provenance(conn: psycopg.Connection, incoming: str) -> None:
    """Refuse to write real data into a database holding mock data (or vice versa)."""
    existing = {r[0] for r in conn.execute("SELECT DISTINCT provenance FROM securities")}
    if existing and existing != {incoming}:
        raise MixedProvenanceError(
            f"This database holds {', '.join(sorted(existing))} data; refusing to add {incoming} data. "
            "Use a separate database for each source (see docs/kite.md).")


RESTATE_TOLERANCE = 0.002  # 0.2%: closes differing by more than this on the same day mean adjusted history


def restated_symbols(conn: psycopg.Connection, fetched: dict) -> dict[str, str]:
    """Symbols whose fetched closes disagree with stored closes for the same dates.

    Sources adjust past prices after a split, bonus or demerger. A daily refresh covers only recent
    years, so stored rows older than the refresh would stay unadjusted and create a fake jump.
    Returns {symbol: earliest stored date} for symbols that need their full history refetched.
    """
    out = {}
    for sym, b in fetched.items():
        if not len(b):
            continue
        stored = dict(conn.execute(
            "SELECT trade_date::text, close FROM daily_prices WHERE symbol = %s AND trade_date BETWEEN %s AND %s",
            (sym, b.dates[0], b.dates[-1])).fetchall())
        changed = any(abs(c / stored[d] - 1) > RESTATE_TOLERANCE
                      for d, c in zip(b.dates, b.close.tolist()) if stored.get(d))
        if changed:
            first = conn.execute("SELECT min(trade_date)::text FROM daily_prices WHERE symbol = %s", (sym,)).fetchone()[0]
            if first < b.dates[0]:
                out[sym] = first
    return out


def ingest(conn: psycopg.Connection, providers: Providers, as_of: str, start: str,
           event_horizon_days: int = 90) -> dict[str, int]:
    """Idempotent: re-running the same window upserts the same rows. One transaction."""
    m, f, e, n = providers.market, providers.fundamentals, providers.events, providers.news
    horizon = (date.fromisoformat(as_of) + timedelta(days=event_horizon_days)).isoformat()
    check_provenance(conn, m.provenance)
    with conn.transaction():
        secs = m.list_securities()
        symbols = [s.symbol for s in secs]
        bars = m.daily_bars(symbols, start, as_of)
        restated = restated_symbols(conn, bars)
        if restated:
            log.warning("source restated past prices (split/bonus/demerger?) for %s; refetching full history",
                        ", ".join(sorted(restated)))
            bars.update(m.daily_bars(sorted(restated), min(restated.values()), as_of))
        counts = {
            "securities": repo.upsert_securities(conn, secs, m.provenance, m.name),
            "daily_prices": repo.upsert_daily_prices(conn, bars, m.provenance, m.name),
            "index_prices": repo.upsert_index_prices(conn, m.index_bars(INDEX_CODES, start, as_of),
                                                     m.provenance, m.name),
            "fundamentals": repo.upsert_fundamentals(
                conn, f.fundamentals_history(symbols, start, as_of), f.provenance, f.name),
            "events": repo.upsert_events(conn, e.events(symbols, start, horizon), e.provenance, e.name),
            "news": repo.upsert_news(conn, n.news(symbols, start), n.provenance),
        }
    counts["restated"] = len(restated)
    log.info("ingested %s", counts)
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["mock", "kite"], default="mock")
    ap.add_argument("--as-of", help="default: 2026-10-05 for mock, last completed session for kite")
    ap.add_argument("--start", help="first trading date to ingest (default: full mock history / 1500 days for kite)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    providers, as_of, start = resolve(args.source, args.as_of, args.start)
    with connect() as conn:
        extend_universe(conn, providers)
        print(ingest(conn, providers, as_of, start))
    for w in getattr(providers.market, "warnings", []):
        log.warning(w)


def resolve(source: str, as_of: str | None, start: str | None) -> tuple[Providers, str, str]:
    if source == "kite":
        from ..calendar import last_completed_session
        as_of = as_of or last_completed_session()
        start = start or (date.fromisoformat(as_of) - timedelta(days=1500)).isoformat()
        return kite_providers(), as_of, start
    providers = mock_providers()
    return providers, as_of or "2026-10-05", start or providers.market.history_start()


if __name__ == "__main__":
    from ..providers.kite.client import KiteError

    try:
        main()
    except (KiteError, FileNotFoundError) as exc:  # expired/missing Kite session, API errors
        raise SystemExit(f"error: {exc}") from None
