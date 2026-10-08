"""The real universe: NIFTY 200 constituents plus any listed company you hold.

Lists come from NSE Indices CSVs in packages/quant-spec/universe (see its README).
"""

import csv
from dataclasses import replace
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from ..models import Security
from ..paths import UNIVERSE_DIR

NIFTY200 = UNIVERSE_DIR / "nifty200.csv"
TOTAL_MARKET = UNIVERSE_DIR / "nifty-total-market.csv"

# NSE industry -> DhanDrishti sector label. Unknown industries fail loudly so a new NSE label is noticed.
SECTORS = {
    "Financial Services": "Financial Services",
    "Information Technology": "IT",
    "Oil Gas & Consumable Fuels": "Energy",
    "Automobile and Auto Components": "Auto",
    "Fast Moving Consumer Goods": "FMCG",
    "Healthcare": "Healthcare",
    "Metals & Mining": "Metal",
    "Telecommunication": "Telecom",
    "Construction": "Infra",
    "Construction Materials": "Cement",
    "Power": "Power",
    "Utilities": "Power",
    "Consumer Durables": "Consumer Durables",
    "Realty": "Realty",
    "Capital Goods": "Capital Goods",
    "Chemicals": "Chemicals",
    "Services": "Services",
    "Consumer Services": "Consumer Services",
    "Textiles": "Textiles",
    "Media Entertainment & Publication": "Media",
    "Forest Materials": "Materials",
    "Diversified": "Diversified",
}


def _name(company: str) -> str:
    return company.removesuffix(" Ltd.").removesuffix(" Limited").strip()


def _security(row: dict[str, str]) -> Security:
    industry = row["Industry"].strip()
    if industry not in SECTORS:
        raise ValueError(f"unknown NSE industry {industry!r} for {row['Symbol']}; add it to SECTORS")
    name = _name(row["Company Name"])
    financial = industry == "Financial Services"
    sector = "Banking" if financial and "Bank" in name.split() else SECTORS[industry]
    return Security(symbol=row["Symbol"].strip(), name=name, sector=sector, is_financial=financial,
                    industry=industry)


@lru_cache(maxsize=4)
def load_list(path: Path) -> tuple[Security, ...]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("Series", "EQ").strip() == "EQ"]
    return tuple(_security(r) for r in rows)


def real_universe(extra: Iterable[str] = ()) -> list[Security]:
    """NIFTY 200, plus `extra` symbols (stocks you hold, stocks already in the database) found in the
    NIFTY Total Market list. ETFs, unlisted shares and anything else outside that list are skipped."""
    base = [replace(s, indices=("NIFTY 200",)) for s in load_list(NIFTY200)]
    have = {s.symbol for s in base}
    lookup = {s.symbol: s for s in load_list(TOTAL_MARKET)}
    added = sorted({x for x in extra if x not in have and x in lookup})
    return base + [lookup[x] for x in added]
