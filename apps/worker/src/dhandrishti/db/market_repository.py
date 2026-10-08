"""Market data persistence: write ingested data, read engine input back."""

from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
import psycopg

from ..models import (FUNDAMENTAL_FIELDS, Bars, Event, Fundamentals, MarketInput, Security, StockInput,
                      is_stale)
from ..providers.base import NewsItem, least_live

REGIME_INDICES = {"nifty": "NIFTY 50", "bank_nifty": "NIFTY BANK", "india_vix": "INDIA VIX"}


# ---------------------------------------------------------------- writes

def upsert_securities(conn: psycopg.Connection, securities: list[Security], provenance: str, source: str) -> int:
    rows = [(s.symbol, s.name, s.exchange, s.sector, s.industry, s.is_financial, list(s.indices),
             provenance, source) for s in securities]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO securities (symbol, name, exchange, sector, industry, is_financial, indices, provenance, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO UPDATE SET
              name = EXCLUDED.name, exchange = EXCLUDED.exchange, sector = EXCLUDED.sector,
              industry = EXCLUDED.industry, is_financial = EXCLUDED.is_financial, indices = EXCLUDED.indices,
              provenance = EXCLUDED.provenance, source = EXCLUDED.source, updated_at = now()""", rows)
    return len(rows)


def _bar_rows(key: str, b: Bars, provenance: str, source: str):
    for i, d in enumerate(b.dates):
        yield (key, d, float(b.open[i]), float(b.high[i]), float(b.low[i]), float(b.close[i]),
               int(b.volume[i]), provenance, source)


def upsert_daily_prices(conn, bars: dict[str, Bars], provenance: str, source: str) -> int:
    rows = [r for sym, b in bars.items() for r in _bar_rows(sym, b, provenance, source)]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO daily_prices (symbol, trade_date, open, high, low, close, volume, provenance, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
              open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
              volume = EXCLUDED.volume, provenance = EXCLUDED.provenance, source = EXCLUDED.source,
              ingested_at = now()""", rows)
    return len(rows)


def upsert_index_prices(conn, bars: dict[str, Bars], provenance: str, source: str) -> int:
    rows = [r for code, b in bars.items() for r in _bar_rows(code, b, provenance, source)]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO index_prices (index_code, trade_date, open, high, low, close, volume, provenance, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (index_code, trade_date) DO UPDATE SET
              open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
              volume = EXCLUDED.volume, provenance = EXCLUDED.provenance, source = EXCLUDED.source,
              ingested_at = now()""", rows)
    return len(rows)


_FCOLS = FUNDAMENTAL_FIELDS + ("quarterly_eps",)


def upsert_fundamentals(conn, data: "dict[str, Fundamentals | list[Fundamentals]]", provenance: str,
                        source: str) -> int:
    """Upsert one snapshot or a list of point-in-time snapshots per symbol (keyed by symbol + as_of)."""
    cols = ", ".join(_FCOLS)
    placeholders = ", ".join(["%s"] * (len(_FCOLS) + 4))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _FCOLS)
    rows = []
    for sym, snaps in data.items():
        for f in snaps if isinstance(snaps, list) else [snaps]:
            if f.as_of is None:
                raise ValueError(f"fundamentals for {sym} have no as_of date")
            d = asdict(f)
            rows.append((sym, f.as_of, *[d[c] for c in _FCOLS], provenance, source))
    with conn.cursor() as cur:
        cur.executemany(f"""
            INSERT INTO fundamentals (symbol, as_of, {cols}, provenance, source)
            VALUES ({placeholders})
            ON CONFLICT (symbol, as_of) DO UPDATE SET {updates},
              provenance = EXCLUDED.provenance, source = EXCLUDED.source, ingested_at = now()""", rows)
    return len(rows)


def upsert_events(conn, events: list[Event], provenance: str, source: str) -> int:
    rows = [(e.symbol, e.date, e.type, e.title, provenance, source) for e in events]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO corporate_events (symbol, event_date, event_type, title, provenance, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, event_date, event_type, title) DO UPDATE SET
              provenance = EXCLUDED.provenance, source = EXCLUDED.source, ingested_at = now()""", rows)
    return len(rows)


def upsert_news(conn, items: list[NewsItem], provenance: str) -> int:
    rows = [(n.symbol, n.published_at, n.headline, n.summary, n.url, provenance, n.source) for n in items]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO news_items (symbol, published_at, headline, summary, url, provenance, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING""", rows)
    return len(rows)


# ---------------------------------------------------------------- reads

def _bars_from_rows(rows: list[tuple]) -> Bars:
    """rows: (trade_date, open, high, low, close, volume) ascending."""
    return Bars(
        dates=[r[0].isoformat() for r in rows],
        open=np.array([r[1] for r in rows], dtype=float),
        high=np.array([r[2] for r in rows], dtype=float),
        low=np.array([r[3] for r in rows], dtype=float),
        close=np.array([r[4] for r in rows], dtype=float),
        volume=np.array([r[5] for r in rows], dtype=float),
    )


def load_market(conn: psycopg.Connection, as_of: str, lookback_bars: int = 300,
                event_horizon_days: int = 90) -> MarketInput:
    """Engine input as known on `as_of` (no look-ahead for prices or fundamentals)."""
    provenances: set[str] = set()

    secs = conn.execute("""
        SELECT symbol, name, exchange, sector, industry, is_financial, indices, provenance
        FROM securities WHERE active ORDER BY symbol""").fetchall()
    if not secs:
        raise LookupError("no active securities; run ingestion first")

    price_rows: dict[str, list[tuple]] = {}
    for row in conn.execute("""
        SELECT symbol, trade_date, open, high, low, close, volume, provenance FROM (
          SELECT p.*, row_number() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn
          FROM daily_prices p WHERE trade_date <= %s) t
        WHERE rn <= %s ORDER BY symbol, trade_date""", (as_of, lookback_bars)):
        price_rows.setdefault(row[0], []).append(row[1:7])
        provenances.add(row[7])

    index_rows: dict[str, list[tuple]] = {}
    for row in conn.execute("""
        SELECT index_code, trade_date, open, high, low, close, volume, provenance FROM (
          SELECT p.*, row_number() OVER (PARTITION BY index_code ORDER BY trade_date DESC) AS rn
          FROM index_prices p WHERE trade_date <= %s AND index_code = ANY(%s)) t
        WHERE rn <= %s ORDER BY index_code, trade_date""",
                            (as_of, list(REGIME_INDICES.values()), lookback_bars)):
        index_rows.setdefault(row[0], []).append(row[1:7])
        provenances.add(row[7])
    missing_idx = [c for c in REGIME_INDICES.values() if c not in index_rows]
    if missing_idx:
        raise LookupError(f"missing index history on or before {as_of}: {missing_idx}")

    cols = ", ".join(("as_of",) + _FCOLS)
    fund: dict[str, Fundamentals] = {}
    for row in conn.execute(f"""
        SELECT DISTINCT ON (symbol) symbol, provenance, {cols}
        FROM fundamentals WHERE as_of <= %s ORDER BY symbol, as_of DESC""", (as_of,)):
        values = dict(zip(("as_of",) + _FCOLS, row[2:]))
        values["as_of"] = values["as_of"].isoformat()
        if values["quarterly_eps"] is not None:
            values["quarterly_eps"] = list(values["quarterly_eps"])
        fund[row[0]] = Fundamentals(**values)
        provenances.add(row[1])

    horizon = (date.fromisoformat(as_of) + timedelta(days=event_horizon_days)).isoformat()
    events: dict[str, list[Event]] = {}
    for sym, d, typ, title in conn.execute("""
        SELECT symbol, event_date, event_type, title FROM corporate_events
        WHERE symbol IS NOT NULL AND event_date > %s AND event_date <= %s
        ORDER BY symbol, event_date, event_type, title""", (as_of, horizon)):
        events.setdefault(sym, []).append(Event(date=d.isoformat(), type=typ, title=title, symbol=sym))

    stocks = []
    for sym, name, exch, sector, industry, fin, indices, prov in secs:
        if sym not in price_rows or is_stale(price_rows[sym][-1][0].isoformat(), as_of):
            continue  # no recent price history: cannot be scored
        provenances.add(prov)
        stocks.append(StockInput(
            security=Security(symbol=sym, name=name, sector=sector, is_financial=fin, exchange=exch,
                              industry=industry, indices=tuple(indices)),
            bars=_bars_from_rows(price_rows[sym]),
            fundamentals=fund.get(sym),
            events=events.get(sym, []),
        ))

    return MarketInput(
        as_of=as_of,
        provenance=least_live(provenances),
        stocks=stocks,
        nifty=_bars_from_rows(index_rows["NIFTY 50"]),
        bank_nifty=_bars_from_rows(index_rows["NIFTY BANK"]),
        india_vix=_bars_from_rows(index_rows["INDIA VIX"]),
    )


def load_history(conn: psycopg.Connection, end: str) -> "MarketHistory":
    """Everything stored up to `end`: full price history and every fundamentals snapshot.

    Point-in-time correctness is enforced later by `MarketHistory.market_at`.
    """
    from ..models import MarketHistory

    provenances: set[str] = set()
    secs = conn.execute("""
        SELECT symbol, name, exchange, sector, industry, is_financial, indices, provenance
        FROM securities WHERE active ORDER BY symbol""").fetchall()
    if not secs:
        raise LookupError("no active securities; run ingestion first")

    price_rows: dict[str, list[tuple]] = {}
    for row in conn.execute("""
        SELECT symbol, trade_date, open, high, low, close, volume, provenance FROM daily_prices
        WHERE trade_date <= %s ORDER BY symbol, trade_date""", (end,)):
        price_rows.setdefault(row[0], []).append(row[1:7])
        provenances.add(row[7])

    index_rows: dict[str, list[tuple]] = {}
    for row in conn.execute("""
        SELECT index_code, trade_date, open, high, low, close, volume, provenance FROM index_prices
        WHERE trade_date <= %s AND index_code = ANY(%s) ORDER BY index_code, trade_date""",
                            (end, list(REGIME_INDICES.values()))):
        index_rows.setdefault(row[0], []).append(row[1:7])
        provenances.add(row[7])
    missing_idx = [c for c in REGIME_INDICES.values() if c not in index_rows]
    if missing_idx:
        raise LookupError(f"missing index history: {missing_idx}")

    cols = ", ".join(("as_of",) + _FCOLS)
    fund: dict[str, list[Fundamentals]] = {}
    for row in conn.execute(f"""
        SELECT symbol, provenance, {cols} FROM fundamentals WHERE as_of <= %s
        ORDER BY symbol, as_of""", (end,)):
        values = dict(zip(("as_of",) + _FCOLS, row[2:]))
        values["as_of"] = values["as_of"].isoformat()
        if values["quarterly_eps"] is not None:
            values["quarterly_eps"] = list(values["quarterly_eps"])
        fund.setdefault(row[0], []).append(Fundamentals(**values))
        provenances.add(row[1])

    securities, bars = [], {}
    for sym, name, exch, sector, industry, fin, indices, prov in secs:
        if sym not in price_rows:
            continue
        provenances.add(prov)
        securities.append(Security(symbol=sym, name=name, sector=sector, is_financial=fin, exchange=exch,
                                   industry=industry, indices=tuple(indices)))
        bars[sym] = _bars_from_rows(price_rows[sym])

    return MarketHistory(
        as_of=end,
        provenance=least_live(provenances),
        securities=securities,
        bars=bars,
        fundamentals=fund,
        events={},
        nifty=_bars_from_rows(index_rows["NIFTY 50"]),
        bank_nifty=_bars_from_rows(index_rows["NIFTY BANK"]),
        india_vix=_bars_from_rows(index_rows["INDIA VIX"]),
    )
