"""When does a figure become usable? One conservative rule per availability basis.

Times are IST. A decision on trading day D is taken at D's close (15:30 IST), so a result
broadcast during or after market hours on D is usable from D+1's decision, never D's.

  EXCHANGE_TIMESTAMP  exact exchange broadcast time        available_at = reported_at
  REPORTED_DATE       date known, time not                 available_at = next day 00:00 (never same day)
  STATUTORY_DEADLINE  no date: latest legal filing date    available_at = deadline day + 1, 00:00 (ESTIMATED;
                      (SEBI LODR: results 45 days after      late filers break it, so it is excluded from
                      quarter end, 60 for the year;          strict point-in-time queries)
                      shareholding pattern 21 days)
  UNKNOWN             nothing reliable                     available_at = NULL (never used)
"""

from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE = time(15, 30)
STRICT_BASES = ("EXCHANGE_TIMESTAMP", "REPORTED_DATE")
ALL_BASES = STRICT_BASES + ("STATUTORY_DEADLINE",)


def decision_time(day: str) -> datetime:
    """The moment a decision on trading day `day` is made: that day's close."""
    return datetime.combine(date.fromisoformat(day), MARKET_CLOSE, IST)


def _midnight(d: date) -> datetime:
    return datetime.combine(d, time(0, 0), IST)


def statutory_deadline(period_end: date, period_type: str, filing_type: str) -> date | None:
    if filing_type == "SHAREHOLDING_PATTERN":
        return period_end + timedelta(days=21)
    if filing_type in ("QUARTERLY_RESULT", "ANNUAL_RESULT"):
        year_end = period_type == "FY" or (period_end.month, period_end.day) == (3, 31)
        return period_end + timedelta(days=60 if year_end else 45)
    return None


def available_at(basis: str, reported_at: datetime | None, period_end: date, period_type: str,
                 filing_type: str) -> datetime | None:
    if basis == "EXCHANGE_TIMESTAMP":
        if reported_at is None:
            raise ValueError("EXCHANGE_TIMESTAMP needs reported_at with a time")
        return reported_at
    if basis == "REPORTED_DATE":
        if reported_at is None:
            raise ValueError("REPORTED_DATE needs reported_at")
        return _midnight(reported_at.astimezone(IST).date() + timedelta(days=1))
    if basis == "STATUTORY_DEADLINE":
        d = statutory_deadline(period_end, period_type, filing_type)
        if d is None:
            raise ValueError(f"no statutory deadline for {filing_type}")
        return _midnight(d + timedelta(days=1))
    if basis == "UNKNOWN":
        return None
    raise ValueError(f"unknown availability basis {basis!r}")
