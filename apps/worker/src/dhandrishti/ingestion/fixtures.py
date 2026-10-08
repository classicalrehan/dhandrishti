"""Language-neutral JSON (de)serialization of MarketInput for golden fixtures."""

import json
from dataclasses import asdict
from pathlib import Path

from ..models import Bars, Event, Fundamentals, MarketInput, Security, StockInput


def market_to_json(m: MarketInput) -> dict:
    return {
        "as_of": m.as_of,
        "data_provenance": m.provenance,
        "dates": m.nifty.dates,
        "indices": {
            "NIFTY 50": m.nifty.to_columns(),
            "NIFTY BANK": m.bank_nifty.to_columns(),
            "INDIA VIX": m.india_vix.to_columns(),
        },
        "stocks": [
            {
                "security": {**asdict(s.security), "indices": list(s.security.indices)},
                "bars": s.bars.to_columns(),
                "fundamentals": None if s.fundamentals is None else asdict(s.fundamentals),
                "events": [asdict(e) for e in s.events],
            }
            for s in m.stocks
        ],
    }


def market_from_json(d: dict) -> MarketInput:
    dates = d["dates"]
    stocks = []
    for s in d["stocks"]:
        sec = dict(s["security"])
        sec["indices"] = tuple(sec.get("indices", ()))
        stocks.append(StockInput(
            security=Security(**sec),
            bars=Bars.from_columns(dates, s["bars"]),
            fundamentals=None if s["fundamentals"] is None else Fundamentals(**s["fundamentals"]),
            events=[Event(**e) for e in s["events"]],
        ))
    idx = d["indices"]
    return MarketInput(
        as_of=d["as_of"],
        provenance=d["data_provenance"],
        stocks=stocks,
        nifty=Bars.from_columns(dates, idx["NIFTY 50"]),
        bank_nifty=Bars.from_columns(dates, idx["NIFTY BANK"]),
        india_vix=Bars.from_columns(dates, idx["INDIA VIX"]),
    )


def load_market(path: str | Path) -> MarketInput:
    return market_from_json(json.loads(Path(path).read_text(encoding="utf-8")))
