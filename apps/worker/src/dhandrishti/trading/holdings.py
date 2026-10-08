"""Real-portfolio maths for read-only Zerodha holdings snapshots.

Returns are time-weighted: each period applies the previous snapshot's quantities to the price
change since then, so buying more shares or adding money does not count as profit.
"""

from collections.abc import Callable
from datetime import datetime, time

from ..calendar import is_trading_day, last_completed_session
from ..providers.kite.client import PortfolioItem

MARKET_OPEN = time(9, 15)


def snapshot_date(now_ist: datetime) -> str:
    """Today once the market has opened on a trading day, else the last completed session."""
    d = now_ist.date().isoformat()
    if is_trading_day(d) and now_ist.time() >= MARKET_OPEN:
        return d
    return last_completed_session(now_ist)


def totals(items: list[PortfolioItem]) -> tuple[float, float]:
    """(value, invested) of the holdings (positions excluded)."""
    hs = [i for i in items if i.kind == "HOLDING" and i.qty > 0]
    return sum(i.qty * i.last_price for i in hs), sum(i.qty * i.avg_price for i in hs)


def period_return(prev: list[PortfolioItem], cur: list[PortfolioItem],
                  close_on: Callable[[str], float | None]) -> float | None:
    """Percent change of the previous holdings, valued at today's prices.

    A holding sold since then is priced with its database close (`close_on`) when we have one,
    otherwise left out of both sides. Returns None when nothing can be priced.
    """
    now = {(i.exchange, i.tradingsymbol): i.last_price for i in cur if i.kind == "HOLDING" and i.last_price > 0}
    by_symbol = {i.tradingsymbol: i.last_price for i in cur if i.kind == "HOLDING" and i.last_price > 0}
    start = end = 0.0
    for i in prev:
        if i.kind != "HOLDING" or i.qty <= 0 or i.last_price <= 0:
            continue
        p = now.get((i.exchange, i.tradingsymbol)) or by_symbol.get(i.tradingsymbol) or close_on(i.tradingsymbol)
        if p is None:
            continue
        start += i.qty * i.last_price
        end += i.qty * p
    return (end / start - 1) * 100 if start else None
