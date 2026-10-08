"""NSE trading calendar, backed by the shared holiday file in packages/shared."""

import json
from datetime import date, timedelta
from functools import lru_cache

from .paths import NSE_HOLIDAYS_PATH


@lru_cache(maxsize=1)
def _holidays() -> frozenset[str]:
    data = json.loads(NSE_HOLIDAYS_PATH.read_text(encoding="utf-8"))
    return frozenset(h["date"] for year in data["years"].values() for h in year)


def is_trading_day(d: str) -> bool:
    return date.fromisoformat(d).weekday() < 5 and d not in _holidays()


def trading_days_back(end: str, count: int) -> list[str]:
    """`count` trading dates ending on or before `end`, ascending."""
    out: list[str] = []
    d = date.fromisoformat(end)
    while len(out) < count:
        s = d.isoformat()
        if is_trading_day(s):
            out.append(s)
        d -= timedelta(days=1)
    return out[::-1]


def last_completed_session(now_ist: "datetime | None" = None, settle_minutes: int = 60) -> str:
    """Most recent trading date whose end-of-day data should be available.

    Today counts only once `settle_minutes` have passed after the 15:30 IST close.
    """
    from datetime import datetime, timezone

    now = now_ist or datetime.now(timezone(timedelta(hours=5, minutes=30)))
    d = now.date()
    closed = now.hour * 60 + now.minute >= 15 * 60 + 30 + settle_minutes
    if not (closed and is_trading_day(d.isoformat())):
        d -= timedelta(days=1)
    while not is_trading_day(d.isoformat()):
        d -= timedelta(days=1)
    return d.isoformat()
