"""Deterministic description of a scoring run's inputs and outputs.

The manifest lists, per category, a SHA-256 of each item exactly as the engine received it (prices as
stored doubles, dates as ISO strings, symbols sorted). `input_hash` is the SHA-256 of the whole manifest.
A hash proves two input sets are identical; it cannot recreate the data. Recreating it is the job of the
price change log (see verify.py).
"""

import dataclasses
import hashlib
import json
from typing import Any

from ..models import Bars, MarketInput

MANIFEST_VERSION = 1
INDEX_FIELDS = (("NIFTY 50", "nifty"), ("NIFTY BANK", "bank_nifty"), ("INDIA VIX", "india_vix"))


def canonical(obj: Any) -> str:
    """JSON with sorted keys and no whitespace. Python floats serialise as their shortest round-trip repr."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=True)


def sha(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _bars(b: Bars) -> dict:
    return {"first": b.dates[0] if len(b) else None, "last": b.dates[-1] if len(b) else None, "n": len(b),
            "sha256": sha({"d": list(b.dates), "o": [float(x) for x in b.open], "h": [float(x) for x in b.high],
                           "l": [float(x) for x in b.low], "c": [float(x) for x in b.close],
                           "v": [float(x) for x in b.volume]})}


def build_manifest(market: MarketInput, lookback_bars: int) -> dict:
    stocks = {}
    for s in sorted(market.stocks, key=lambda s: s.security.symbol):
        stocks[s.security.symbol] = {
            "security": sha(dataclasses.asdict(s.security)),
            "bars": _bars(s.bars),
            "fundamentals": sha(dataclasses.asdict(s.fundamentals)) if s.fundamentals is not None else None,
            "events": sha([dataclasses.asdict(e) for e in s.events]),
        }
    return {
        "manifest_version": MANIFEST_VERSION,
        "as_of": market.as_of,
        "lookback_bars": lookback_bars,
        "provenance": market.provenance,
        "indices": {code: _bars(getattr(market, attr)) for code, attr in INDEX_FIELDS},
        "stocks": stocks,
    }


def input_hash(manifest: dict) -> str:
    return sha(manifest)


def result_hash(stock_result: dict) -> str:
    return sha(stock_result)


def output_hash(result: dict) -> str:
    """Every stock's result hash plus the market-level outputs."""
    return sha({"stocks": {s["symbol"]: result_hash(s) for s in result["stocks"]},
                "regime": result["regime"], "breadth": result["breadth"], "sectors": result["sectors"]})


def latest_bar(manifest: dict) -> str | None:
    dates = [v["bars"]["last"] for v in manifest["stocks"].values() if v["bars"]["last"]]
    dates += [v["last"] for v in manifest["indices"].values() if v["last"]]
    return max(dates) if dates else None


def diff(recorded: dict, current: dict) -> dict:
    """Which categories and items differ between two manifests (for verification reports)."""
    out: dict[str, Any] = {}
    for key in ("as_of", "lookback_bars", "provenance"):
        if recorded.get(key) != current.get(key):
            out[key] = {"recorded": recorded.get(key), "current": current.get(key)}
    idx = sorted(k for k in set(recorded["indices"]) | set(current["indices"])
                 if recorded["indices"].get(k) != current["indices"].get(k))
    if idx:
        out["indices"] = idx
    rs, cs = recorded["stocks"], current["stocks"]
    if set(rs) - set(cs):
        out["stocks_missing_now"] = sorted(set(rs) - set(cs))
    if set(cs) - set(rs):
        out["stocks_added_now"] = sorted(set(cs) - set(rs))
    for cat in ("bars", "security", "fundamentals", "events"):
        changed = sorted(s for s in set(rs) & set(cs) if rs[s][cat] != cs[s][cat])
        if changed:
            out[cat] = changed
    return out
