"""NSE 'Corporate Filings → Shareholding Pattern' listing CSV (downloaded manually from nseindia.com).

Format seen 2026-10-09 (file CF-Shareholding-Pattern-equities-<SYMBOL>-<from>-to-<to>.csv, UTF-8 with BOM):
  COMPANY, PROMOTER & PROMOTER GROUP (A), PUBLIC (B), SHARES HELD BY EMPLOYEE TRUSTS (C2), STATUS, AS ON DATE,
  SUBMISSION DATE, REVISION DATE, ACTION (link to the XBRL), BROADCAST DATE/TIME, EXCHANGE DISSEMINATION TIME,
  TIME TAKEN
There is no symbol column: the symbol comes from the file name. The dissemination time is when the market
could see the filing. A revised filing is never treated as public before its revision date. The promoter and
public percentages are a summary used to cross-check the XBRL.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ..availability import IST

HEADER = ["COMPANY", "PROMOTER & PROMOTER GROUP (A)", "PUBLIC (B)", "SHARES HELD BY EMPLOYEE TRUSTS (C2)", "STATUS",
          "AS ON DATE", "SUBMISSION DATE", "REVISION DATE", "ACTION", "BROADCAST DATE/TIME",
          "EXCHANGE DISSEMINATION TIME", "TIME TAKEN"]
FILE_NAME = re.compile(r"^CF-Shareholding-Pattern-equities-(.+)-(\d{2}-\d{2}-\d{4})-to-(\d{2}-\d{2}-\d{4})\.csv$")


class ShpListingError(ValueError):
    pass


@dataclass(frozen=True)
class ShareholdingListing:
    symbol: str
    company: str
    as_on: date
    promoter_pct: float | None
    public_pct: float | None
    xbrl_file: str
    submitted_at: datetime
    disseminated_at: datetime
    revised_on: date | None


def _ts(text: str) -> datetime:
    return datetime.strptime(text.strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)


def _pct(text: str) -> float | None:
    text = text.strip()
    return float(text) if text not in ("", "-") else None


def parse(path: Path) -> list[ShareholdingListing]:
    m = FILE_NAME.match(path.name)
    if not m:
        raise ShpListingError(f"{path.name}: not an NSE shareholding listing file name (CF-Shareholding-Pattern-equities-SYMBOL-...)")
    symbol = m.group(1)
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    if not rows or [c.strip() for c in rows[0]] != HEADER:
        raise ShpListingError(f"{path.name}: unexpected header {rows[0] if rows else '(empty)'}")
    out, errors, seen = [], [], set()
    for n, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        try:
            d = dict(zip(HEADER, (c.strip() for c in r)))
            name = d["ACTION"].rsplit("/", 1)[-1]
            if not name.endswith(".xml"):
                raise ValueError(f"XBRL link {d['ACTION']!r}")
            as_on = datetime.strptime(d["AS ON DATE"], "%d-%b-%Y").date()
            submitted, disseminated = _ts(d["BROADCAST DATE/TIME"]), _ts(d["EXCHANGE DISSEMINATION TIME"])
            revised = datetime.strptime(d["REVISION DATE"], "%d-%b-%Y").date() if d["REVISION DATE"] else None
            if revised is not None and disseminated.date() < revised:
                raise ValueError("revised filing disseminated before its revision date")
            if disseminated < submitted:
                raise ValueError("disseminated before submitted")
            if disseminated.date() < as_on:
                raise ValueError("published before the as-on date")
            if name in seen:
                raise ValueError(f"duplicate XBRL file {name}")
            seen.add(name)
            out.append(ShareholdingListing(symbol, d["COMPANY"], as_on, _pct(d["PROMOTER & PROMOTER GROUP (A)"]),
                                           _pct(d["PUBLIC (B)"]), name, submitted, disseminated, revised))
        except (ValueError, KeyError) as exc:
            errors.append(f"{path.name} row {n}: {exc}")
    if errors:
        raise ShpListingError("\n".join(errors))
    return sorted(out, key=lambda x: x.as_on)
