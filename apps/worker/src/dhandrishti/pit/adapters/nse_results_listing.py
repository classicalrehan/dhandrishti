"""NSE results listings (downloaded manually from nseindia.com). Two formats, detected by header.

1. 'Corporate Filings → Financial Results' (quarters ended up to 31-Dec-2024).
   Format seen 2026-10-08 (file CF-FR-equities-<SYMBOL>-<from>-to-<to>.csv, UTF-8 with BOM):
  COMPANY NAME, AUDITED / UNAUDITED, CUMULATIVE / NON-CUMULATIVE, CONSOLIDATED / NON-CONSOLIDATED,
  IND AS/ NON IND AS, PERIOD, PERIOD ENDED, RELATING TO, ** XBRL, Exchange Received Time,
  Exchange Dissemination Time, Time Taken

No figures, only publication metadata. The dissemination time is when the market could see the
filing, so it becomes `reported_at` / `available_at` (EXCHANGE_TIMESTAMP) for figures read from the
linked XBRL file. Results for quarters ended March 2025 onward are listed under "Integrated Filing –
Financials" instead and are not in this file.

2. 'Integrated Filing – Financials' (quarters ended 31-Mar-2025 onward). Format seen 2026-10-08
   (file CF-Integrated-Filing-equities-Integrated Filing- Financials-<SYMBOL>-...csv; headers carry a
   trailing space):
     SYMBOL, COMPANY NAME, QUARTER END DATE, TYPE OF SUBMISSION, AUDITED / UNAUDITED,
     CONSOLIDATED / STANDALONE, DETAILS (iXBRL page), XBRL, BROADCAST DATE/TIME, REVISED DATE/TIME,
     REVISION REMARKS, EXCHANGE DISSEMINATION TIME, TIME TAKEN
   BROADCAST is the company's submission (= received), DISSEMINATION the public release. All rows are
   quarterly. TYPE OF SUBMISSION is 'Original' or a revision; a revised row is published no earlier than
   its REVISED DATE/TIME. No revised row has been seen yet, so that path is checked only on synthetic data.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ..availability import IST, statutory_deadline

HEADER = ["COMPANY NAME", "AUDITED / UNAUDITED", "CUMULATIVE / NON-CUMULATIVE", "CONSOLIDATED / NON-CONSOLIDATED",
          "IND AS/ NON IND AS", "PERIOD", "PERIOD ENDED", "RELATING TO", "** XBRL", "Exchange Received Time",
          "Exchange Dissemination Time", "Time Taken"]
FILE_NAME = re.compile(r"^CF-FR-equities-(.+)-(\d{2}-\d{2}-\d{4})-to-(\d{2}-\d{2}-\d{4})\.csv$")
INTEGRATED_HEADER = ["SYMBOL", "COMPANY NAME", "QUARTER END DATE", "TYPE OF SUBMISSION", "AUDITED / UNAUDITED",
                     "CONSOLIDATED / STANDALONE", "DETAILS", "XBRL", "BROADCAST DATE/TIME", "REVISED DATE/TIME",
                     "REVISION REMARKS", "EXCHANGE DISSEMINATION TIME", "TIME TAKEN"]
BASIS = {"Consolidated": "CONSOLIDATED", "Non-Consolidated": "STANDALONE", "Standalone": "STANDALONE"}
PERIODS = {"Quarterly": "Q", "Half-Yearly": "H", "Annual": "FY"}


class ListingError(ValueError):
    pass


@dataclass(frozen=True)
class ResultFiling:
    symbol: str
    company: str
    period_end: date
    period_type: str          # Q | H | FY
    relating_to: str          # e.g. "Fourth Quarter"
    basis: str                # CONSOLIDATED | STANDALONE
    audited: bool
    cumulative: bool
    accounting: str           # NSE label, e.g. "Ind-AS New", "Non-Ind-AS"
    taxonomy: str             # from the XBRL file name: INDAS, BANKING, ...
    xbrl_url: str
    xbrl_file: str            # NSE file name; downloaded XBRL files keep it, which links them to this row
    received_at: datetime
    disseminated_at: datetime
    source_page: str = "Financial Results"
    submission: str = "Original"       # 'Original', or the revision type
    revised_at: datetime | None = None
    revision_remarks: str | None = None

    @property
    def lag_days(self) -> int:
        return (self.disseminated_at.date() - self.period_end).days

    @property
    def after_deadline(self) -> bool:
        deadline = statutory_deadline(self.period_end, self.period_type, "QUARTERLY_RESULT")
        return deadline is not None and self.disseminated_at.date() > deadline


def _ts(text: str) -> datetime:
    return datetime.strptime(text.strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)


def symbol_from_name(path: Path) -> str:
    m = FILE_NAME.match(path.name)
    if not m:
        raise ListingError(f"{path.name}: not an NSE financial-results listing file name (CF-FR-equities-SYMBOL-...)")
    return m.group(1)


def parse(path: Path, symbol: str | None = None) -> list[ResultFiling]:
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    if rows and [c.strip() for c in rows[0]] == INTEGRATED_HEADER:
        return _parse_integrated(path, rows, symbol)
    symbol = symbol or symbol_from_name(path)
    if not rows or [c.strip() for c in rows[0]] != HEADER:
        raise ListingError(f"{path.name}: unexpected header {rows[0] if rows else '(empty)'}")
    out, errors, seen = [], [], set()
    for n, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        try:
            d = dict(zip(HEADER, (c.strip() for c in r)))
            if d["CONSOLIDATED / NON-CONSOLIDATED"] not in BASIS:
                raise ValueError(f"basis {d['CONSOLIDATED / NON-CONSOLIDATED']!r}")
            if d["PERIOD"] not in PERIODS:
                raise ValueError(f"period {d['PERIOD']!r}")
            url = d["** XBRL"]
            name = url.rsplit("/", 1)[-1]
            if not name.endswith(".xml"):
                raise ValueError(f"XBRL link {url!r}")
            received, disseminated = _ts(d["Exchange Received Time"]), _ts(d["Exchange Dissemination Time"])
            end = datetime.strptime(d["PERIOD ENDED"], "%d-%b-%Y").date()
            if disseminated < received:
                raise ValueError("disseminated before received")
            if disseminated.date() < end:
                raise ValueError("published before the period ended")
            if name in seen:
                raise ValueError(f"duplicate XBRL file {name}")
            seen.add(name)
            out.append(ResultFiling(
                symbol=symbol, company=d["COMPANY NAME"], period_end=end, period_type=PERIODS[d["PERIOD"]],
                relating_to=d["RELATING TO"], basis=BASIS[d["CONSOLIDATED / NON-CONSOLIDATED"]],
                audited=d["AUDITED / UNAUDITED"].lower() == "audited",
                cumulative=d["CUMULATIVE / NON-CUMULATIVE"].lower() == "cumulative",
                accounting=d["IND AS/ NON IND AS"], taxonomy=name.split("_", 1)[0], xbrl_url=url, xbrl_file=name,
                received_at=received, disseminated_at=disseminated))
        except (ValueError, KeyError) as exc:
            errors.append(f"{path.name} row {n}: {exc}")
    if errors:
        raise ListingError("\n".join(errors))
    return sorted(out, key=lambda f: (f.period_end, f.basis))


def _parse_integrated(path: Path, rows: list[list[str]], symbol: str | None) -> list[ResultFiling]:
    out, errors, seen = [], [], set()
    for n, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        try:
            d = dict(zip(INTEGRATED_HEADER, (c.strip() for c in r)))
            if symbol and d["SYMBOL"] != symbol:
                raise ValueError(f"symbol {d['SYMBOL']} in a file for {symbol}")
            if d["CONSOLIDATED / STANDALONE"] not in BASIS:
                raise ValueError(f"basis {d['CONSOLIDATED / STANDALONE']!r}")
            url = d["XBRL"]
            name = url.rsplit("/", 1)[-1]
            if not name.endswith(".xml"):
                raise ValueError(f"XBRL link {url!r}")
            end = datetime.strptime(d["QUARTER END DATE"], "%d-%b-%Y").date()
            received, disseminated = _ts(d["BROADCAST DATE/TIME"]), _ts(d["EXCHANGE DISSEMINATION TIME"])
            revised = _ts(d["REVISED DATE/TIME"]) if d["REVISED DATE/TIME"] else None
            original = d["TYPE OF SUBMISSION"].lower() == "original"
            if not original and revised is None:
                raise ValueError("revised submission without REVISED DATE/TIME")
            if revised is not None and revised > disseminated:
                disseminated = revised  # never treat a revision as public before it was made
            if disseminated < received:
                raise ValueError("disseminated before received")
            if disseminated.date() < end:
                raise ValueError("published before the period ended")
            if name in seen:
                raise ValueError(f"duplicate XBRL file {name}")
            seen.add(name)
            out.append(ResultFiling(
                symbol=d["SYMBOL"], company=d["COMPANY NAME"], period_end=end, period_type="Q",
                relating_to="", basis=BASIS[d["CONSOLIDATED / STANDALONE"]],
                audited=d["AUDITED / UNAUDITED"].lower() == "audited", cumulative=False, accounting="",
                taxonomy=name.removeprefix("INTEGRATED_FILING_").split("_", 1)[0], xbrl_url=url, xbrl_file=name,
                received_at=received, disseminated_at=disseminated, source_page="Integrated Filing - Financials",
                submission=d["TYPE OF SUBMISSION"], revised_at=revised, revision_remarks=d["REVISION REMARKS"] or None))
        except (ValueError, KeyError) as exc:
            errors.append(f"{path.name} row {n}: {exc}")
    if errors:
        raise ListingError("\n".join(errors))
    return sorted(out, key=lambda f: (f.period_end, f.basis))
