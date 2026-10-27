"""Point-in-time NIFTY 200 universe for research: verified membership plus prices for stocks that have since left.

Membership comes from research/index_membership.py, rebuilt from today's NSE list and the saved NSE Indices notices;
it is verified (0 inconsistencies, every semi-annual review present) only from VERIFIED_FROM on, so nothing earlier
is answered. The price database holds today's members only, so prices for former members are fetched once from
Kite (jobs/former_member_prices.py) into CSV files under data/kite-backfill/ with a manifest. Nothing here writes
to a database.

Kite lists some former members under a later symbol (PRICE_SYMBOLS). Each fetched series is kept only if its first
candle is no later than the first day the stock was a member, so a renamed or merged company's new listing is never
passed off as the old one; anything not priced is reported as a coverage gap, not dropped silently.
"""

import csv
import json
from datetime import date
from pathlib import Path

import numpy as np

from ..models import Bars
from . import index_membership as M

ROOT = Path(__file__).resolve().parents[5]
NOTICES = ROOT / "data" / "index-notices"
TODAY_LIST = ROOT / "packages" / "quant-spec" / "universe" / "nifty200.csv"
TODAY_LIST_DATE = date(2026, 10, 8)
BACKFILL = ROOT / "data" / "kite-backfill"
VERIFIED_FROM = date(2021, 1, 1)

# Membership symbol -> symbol under which Kite lists the same company today (Kite instrument name in brackets).
PRICE_SYMBOLS = {
    "AMARAJABAT": "ARE&M",           # Amara Raja Batteries -> Amara Raja Energy & Mobility ("AMARA RAJA ENERGY MOB")
    "IBULHSGFIN": "SAMMAANCAP",      # Indiabulls Housing Finance -> Sammaan Capital ("SAMMAAN CAPITAL")
    "MOTHERSUMI": "MOTHERSON",       # Motherson Sumi Systems -> Samvardhana Motherson International
}


# Symbols whose verified-window membership is known to be wrong somewhere; left out of studies until resolved.
UNCERTAIN = {
    # Member from 1-Jan-2021 in the rebuild, but listed only on 24-Jun-2021: its NIFTY 200 inclusion (and the
    # matching exclusion of another stock) is in a notice not yet found. Excluded from NIFTY 200 on 30-Mar-2026.
    "SONACOMS": "inclusion notice missing (listed 2021-06-24; first rebuilt as a member on 2021-01-01)",
}


def listing_conflicts(h: M.History, first_trade: dict[str, date], data_start: date) -> list[str]:
    """Members on days before their first trading day: proof of a missing inclusion notice. Stocks whose first
    price is at the start of the price data are not testable (they may have listed earlier)."""
    out = []
    for start, members in h.periods:
        for s in sorted(members):
            listed = first_trade.get(s)
            if listed and listed > data_start and listed > start:
                out.append(f"{s}: member from {start} but first traded {listed}")
    return out


def today_list(path: Path = TODAY_LIST) -> set[str]:
    with open(path, encoding="utf-8-sig") as f:
        return {r["Symbol"] for r in csv.DictReader(f)}


def verified_history(notices: Path = NOTICES) -> M.History:
    h = M.rebuild(today_list(), TODAY_LIST_DATE, M.load_notices(notices), complete_from=VERIFIED_FROM)
    if h.problems:
        raise ValueError(f"membership is not consistent from {VERIFIED_FROM}: {h.problems}")
    return h


def first_member_day(h: M.History) -> dict[str, date]:
    """First day in the verified window on which each symbol is a member."""
    first: dict[str, date] = {}
    for start, members in reversed(h.periods):           # oldest first
        for s in members:
            first.setdefault(s, max(start, h.complete_from))
    return first


def save_backfill(directory: Path, symbol: str, bars: Bars) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / f"{symbol}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for row in zip(bars.dates, bars.open, bars.high, bars.low, bars.close, bars.volume):
            w.writerow(row)


def load_backfill(directory: Path = BACKFILL) -> dict[str, Bars]:
    """Saved series accepted by the manifest (status "ok"), keyed by membership symbol."""
    manifest = directory / "manifest.json"
    if not manifest.exists():
        return {}
    out = {}
    for symbol, info in json.loads(manifest.read_text(encoding="utf-8"))["symbols"].items():
        if info["status"] != "ok":
            continue
        with open(directory / f"{symbol}.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        out[symbol] = Bars([r["date"] for r in rows], *(np.array([float(r[k]) for r in rows])
                                                         for k in ("open", "high", "low", "close", "volume")))
    return out


def coverage(h: M.History, priced: set[str], end: date) -> tuple[float, dict[str, int]]:
    """Share of member-days with prices over the verified window, and unpriced member-days per symbol."""
    total, missing = 0, {}
    for i, (start, members) in enumerate(h.periods):
        stop = min(h.periods[i - 1][0] if i else end, end)
        days = max((stop - start).days, 0)
        total += days * len(members)
        for s in members - priced:
            missing[s] = missing.get(s, 0) + days
    return 1 - sum(missing.values()) / total, dict(sorted(missing.items(), key=lambda kv: -kv[1]))
