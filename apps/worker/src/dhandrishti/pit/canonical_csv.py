"""Provider-neutral import format: one observation per row (docs/fundamentals-pit.md).

Columns
  required  symbol, metric, value, basis, period_type, period_end, filing_type, value_vintage
  optional  period_start (required unless INSTANT), reported_at, availability_basis, unit,
            currency, source_record_id

reported_at: 'YYYY-MM-DD HH:MM[:SS]' (IST unless an offset is given) = exchange broadcast time, or
'YYYY-MM-DD' when only the date is known. availability_basis defaults from it: a time gives
EXCHANGE_TIMESTAMP, a date gives REPORTED_DATE, empty gives STATUTORY_DEADLINE for results and
shareholding filings, UNKNOWN otherwise. Blank `value` cells are skipped (absent, not zero).
"""

import csv
from datetime import date, datetime
from pathlib import Path

from .availability import IST, available_at
from .metrics import METRICS
from .store import Observation

REQUIRED = ("symbol", "metric", "value", "basis", "period_type", "period_end", "filing_type", "value_vintage")
OPTIONAL = ("period_start", "reported_at", "availability_basis", "unit", "currency", "source_record_id")
FILING_TYPES = ("QUARTERLY_RESULT", "ANNUAL_RESULT", "ANNUAL_REPORT", "SHAREHOLDING_PATTERN", "OTHER")
MAX_QUARTER_DAYS = (89, 92)


class CanonicalImportError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} problem(s):\n  " + "\n  ".join(errors[:50]))
        self.errors = errors


def parse_reported_at(text: str) -> tuple[datetime | None, bool]:
    """(timestamp, has_time). Naive values are IST."""
    text = text.strip()
    if not text:
        return None, False
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), datetime.min.time(), IST), False
    ts = datetime.fromisoformat(text.replace("T", " "))
    return (ts if ts.tzinfo else ts.replace(tzinfo=IST)), True


def _period_ok(period_type: str, start: date | None, end: date) -> str | None:
    if period_type == "INSTANT":
        return None if start is None else "period_start must be empty for INSTANT"
    if start is None:
        return "period_start is required"
    days = (end - start).days
    expected = {"Q": MAX_QUARTER_DAYS, "H": (180, 184), "FY": (363, 366)}[period_type]
    if not expected[0] <= days <= expected[1]:
        return f"{period_type} period of {days + 1} days ({start} to {end})"
    return None


def parse(path: Path, source: str, known_symbols: set[str] | None = None) -> list[Observation]:
    errors: list[str] = []
    out: list[Observation] = []
    seen: dict[tuple, tuple[int, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = [c.strip() for c in reader.fieldnames or []]
        missing = [c for c in REQUIRED if c not in cols]
        unknown = [c for c in cols if c not in REQUIRED + OPTIONAL]
        if missing or unknown:
            raise CanonicalImportError([f"missing columns {missing}" if missing else "",
                                        f"unknown columns {unknown}" if unknown else ""])
        for n, raw in enumerate(reader, start=2):
            r = {k.strip(): (v or "").strip() for k, v in raw.items()}
            if not r["value"]:
                continue
            where = f"row {n} ({r['symbol']} {r['metric']} {r['period_end']})"
            try:
                m = METRICS.get(r["metric"])
                if m is None:
                    raise ValueError(f"unknown metric {r['metric']!r}")
                if known_symbols is not None and r["symbol"] not in known_symbols:
                    raise ValueError(f"unknown symbol {r['symbol']!r}")
                if r["period_type"] not in m.period_types:
                    raise ValueError(f"{r['metric']} cannot have period_type {r['period_type']} (allowed {m.period_types})")
                if r.get("unit") and r["unit"] != m.unit:
                    raise ValueError(f"unit {r['unit']} but {r['metric']} is {m.unit}")
                if r["basis"] not in ("CONSOLIDATED", "STANDALONE"):
                    raise ValueError(f"basis must be CONSOLIDATED or STANDALONE, not {r['basis']!r}")
                if r["filing_type"] not in FILING_TYPES:
                    raise ValueError(f"filing_type must be one of {FILING_TYPES}")
                if r["value_vintage"] not in ("AS_REPORTED", "AS_CURRENTLY_DISPLAYED"):
                    raise ValueError("value_vintage must be AS_REPORTED or AS_CURRENTLY_DISPLAYED")
                value = float(r["value"].replace(",", ""))
                if m.unit == "PCT" and not 0 <= value <= 100:
                    raise ValueError(f"percentage {value} outside 0-100")
                end = date.fromisoformat(r["period_end"])
                start = date.fromisoformat(r["period_start"]) if r.get("period_start") else None
                if problem := _period_ok(r["period_type"], start, end):
                    raise ValueError(problem)
                reported, has_time = parse_reported_at(r.get("reported_at", ""))
                if reported is not None and reported.astimezone(IST).date() < end:
                    raise ValueError(f"reported_at {reported.date()} is before period_end {end}")
                basis = r.get("availability_basis") or (
                    "EXCHANGE_TIMESTAMP" if has_time else "REPORTED_DATE" if reported
                    else "STATUTORY_DEADLINE" if r["filing_type"] in ("QUARTERLY_RESULT", "ANNUAL_RESULT", "SHAREHOLDING_PATTERN")
                    else "UNKNOWN")
                if basis == "EXCHANGE_TIMESTAMP" and not has_time:
                    raise ValueError("EXCHANGE_TIMESTAMP needs a broadcast time, not just a date")
                avail = available_at(basis, reported, end, r["period_type"], r["filing_type"])
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                continue
            o = Observation(symbol=r["symbol"], metric=r["metric"], value=value, unit=m.unit, basis=r["basis"],
                            period_type=r["period_type"], period_start=start, period_end=end,
                            filing_type=r["filing_type"], reported_at=reported, available_at=avail,
                            availability_basis=basis, value_vintage=r["value_vintage"], source=source,
                            source_record_id=r.get("source_record_id") or None, currency=r.get("currency") or "INR")
            k = o.key() + (o.reported_at,)
            if k in seen:
                first, v = seen[k]
                if v != value:
                    errors.append(f"{where}: conflicts with row {first} ({v}) for the same figure and publication")
                continue  # exact repeat inside the file: keep the first
            seen[k] = (n, value)
            out.append(o)
    if errors:
        raise CanonicalImportError(errors)
    return out
