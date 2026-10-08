"""Import real fundamentals from two CSV files and derive point-in-time snapshots.

quarterly results CSV (one row per symbol per quarter; amounts in ₹ crore, per-share in ₹):
  symbol, period_end, published_on, revenue, operating_profit, net_profit, eps,
  [interest, equity, debt, cfo, capex, dps, shares_cr]
shareholding CSV (one row per symbol per quarter; percentages):
  symbol, period_end, published_on, promoter_pct, [promoter_pledged_pct, fii_pct, dii_pct]

`published_on` is when the numbers became public; a snapshot only uses rows published on or
before its own date, so backtests never see results before their release.

Definitions (SPEC §5.3):
  TTM x            sum of the last 4 quarters (all 4 required)
  growth           TTM / TTM four quarters earlier - 1 (8 quarters); null if the earlier TTM <= 0
  eps_cagr_3y      (TTM EPS / TTM EPS twelve quarters earlier)^(1/3) - 1 (16 quarters; both > 0)
  margins          TTM operating (net) profit / TTM revenue
  roe              TTM net profit / average(equity now, equity a year ago) (latest equity if no older)
  roce             TTM operating profit / (equity + debt)          (operating profit as EBIT proxy)
  interest cover   TTM operating profit / TTM interest
  cash flow        cfo/capex may be quarterly (4 values in the last year) or half-yearly (2 values)
  dps_ttm          dividends per share over the last 4 quarters (blank = no dividend that quarter)
  pe_median_5y     median of PE at each publication date in the previous 5 years
"""

import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from ..models import Fundamentals

QUARTERLY_REQUIRED = ("symbol", "period_end", "published_on", "revenue", "operating_profit", "net_profit", "eps")
QUARTERLY_OPTIONAL = ("interest", "equity", "debt", "cfo", "capex", "dps", "shares_cr")
SHAREHOLDING_REQUIRED = ("symbol", "period_end", "published_on", "promoter_pct")
SHAREHOLDING_OPTIONAL = ("promoter_pledged_pct", "fii_pct", "dii_pct")


class ImportError_(ValueError):
    """Invalid input file; message lists every problem found."""


@dataclass
class Quarter:
    period_end: str
    published_on: str
    revenue: float
    operating_profit: float
    net_profit: float
    eps: float
    interest: float | None = None
    equity: float | None = None
    debt: float | None = None
    cfo: float | None = None
    capex: float | None = None
    dps: float | None = None
    shares_cr: float | None = None


@dataclass
class Holding:
    period_end: str
    published_on: str
    promoter_pct: float
    promoter_pledged_pct: float | None = None
    fii_pct: float | None = None
    dii_pct: float | None = None


@dataclass
class ImportReport:
    symbols: int = 0
    quarters: int = 0
    shareholding_rows: int = 0
    snapshots: int = 0
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ parsing

def _num(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip().replace(",", "")
    return None if v == "" else float(v)


def _date(v: str) -> str:
    return date.fromisoformat(v.strip()).isoformat()


def _read(path: Path, required: tuple, optional: tuple, kind: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = [c.strip() for c in (reader.fieldnames or [])]
        missing = [c for c in required if c not in cols]
        if missing:
            raise ImportError_(f"{kind}: missing required columns {missing} (have {cols})")
        unknown = [c for c in cols if c not in required + optional]
        if unknown:
            raise ImportError_(f"{kind}: unknown columns {unknown}; see docs/fundamentals-import.md")
        return [{k.strip(): v for k, v in row.items()} for row in reader]


def parse_quarterly(path: Path, known: set[str] | None = None) -> dict[str, list[Quarter]]:
    rows = _read(path, QUARTERLY_REQUIRED, QUARTERLY_OPTIONAL, "quarterly results")
    out: dict[str, list[Quarter]] = defaultdict(list)
    errors = []
    for i, r in enumerate(rows, start=2):  # line 1 is the header
        try:
            sym = r["symbol"].strip().upper()
            if known is not None and sym not in known:
                raise ValueError(f"unknown symbol {sym}")
            q = Quarter(period_end=_date(r["period_end"]), published_on=_date(r["published_on"]),
                        **{c: _num(r.get(c)) for c in QUARTERLY_REQUIRED[3:] + QUARTERLY_OPTIONAL})
            if None in (q.revenue, q.operating_profit, q.net_profit, q.eps):
                raise ValueError("revenue, operating_profit, net_profit and eps are required")
            if q.published_on < q.period_end:
                raise ValueError("published_on is before period_end")
            out[sym].append(q)
        except (ValueError, KeyError) as exc:
            errors.append(f"line {i}: {exc}")
    for sym, qs in out.items():
        qs.sort(key=lambda q: q.period_end)
        seen = [q.period_end for q in qs]
        if len(seen) != len(set(seen)):
            errors.append(f"{sym}: duplicate period_end rows")
    if errors:
        raise ImportError_("quarterly results:\n  " + "\n  ".join(errors[:50]))
    return dict(out)


def parse_shareholding(path: Path, known: set[str] | None = None) -> dict[str, list[Holding]]:
    rows = _read(path, SHAREHOLDING_REQUIRED, SHAREHOLDING_OPTIONAL, "shareholding")
    out: dict[str, list[Holding]] = defaultdict(list)
    errors = []
    for i, r in enumerate(rows, start=2):
        try:
            sym = r["symbol"].strip().upper()
            if known is not None and sym not in known:
                raise ValueError(f"unknown symbol {sym}")
            h = Holding(period_end=_date(r["period_end"]), published_on=_date(r["published_on"]),
                        **{c: _num(r.get(c)) for c in SHAREHOLDING_REQUIRED[3:] + SHAREHOLDING_OPTIONAL})
            if h.promoter_pct is None or not 0 <= h.promoter_pct <= 100:
                raise ValueError("promoter_pct must be between 0 and 100")
            out[sym].append(h)
        except (ValueError, KeyError) as exc:
            errors.append(f"line {i}: {exc}")
    if errors:
        raise ImportError_("shareholding:\n  " + "\n  ".join(errors[:50]))
    for hs in out.values():
        hs.sort(key=lambda h: h.period_end)
    return dict(out)


# ------------------------------------------------------------------ derivation

def _ttm(qs: list[Quarter], attr: str, back: int = 0) -> float | None:
    window = qs[len(qs) - 4 - back: len(qs) - back] if len(qs) >= 4 + back else []
    vals = [getattr(q, attr) for q in window]
    return None if len(vals) < 4 or any(v is None for v in vals) else sum(vals)


def _growth(now: float | None, before: float | None) -> float | None:
    return None if now is None or before is None or before <= 0 else (now / before - 1) * 100


def _latest(qs: list[Quarter], attr: str, within: int = 2) -> float | None:
    for q in reversed(qs[-within:]):
        v = getattr(q, attr)
        if v is not None:
            return v
    return None


def _cash_ttm(qs: list[Quarter], attr: str) -> float | None:
    vals = [getattr(q, attr) for q in qs[-4:] if getattr(q, attr) is not None] if len(qs) >= 4 else []
    return sum(vals) if len(vals) in (2, 4) else None  # half-yearly (2) or quarterly (4) reporting


def snapshot(qs: list[Quarter], hold: Holding | None, as_of: str, close: float | None,
             pe_history: list[float]) -> Fundamentals:
    """Fundamentals known on `as_of` from quarters (sorted) and the latest shareholding."""
    rev, op, np_, eps = (_ttm(qs, a) for a in ("revenue", "operating_profit", "net_profit", "eps"))
    eps_4, eps_12 = _ttm(qs, "eps", 4), _ttm(qs, "eps", 12)
    equity, debt = _latest(qs, "equity"), _latest(qs, "debt")
    equity_1y = qs[-5].equity if len(qs) >= 5 and qs[-5].equity is not None else None
    interest = _ttm(qs, "interest")
    cfo, capex = _cash_ttm(qs, "cfo"), _cash_ttm(qs, "capex")
    has_dps = any(q.dps is not None for q in qs)
    dps_ttm = sum((q.dps or 0.0) for q in qs[-4:]) if has_dps and len(qs) >= 4 else None
    shares = _latest(qs, "shares_cr", within=4)
    q_eps = [q.eps for q in qs[-12:]]

    pe = close / eps if close and eps and eps > 0 else (-1.0 if eps is not None and eps <= 0 else None)
    cagr = ((eps / eps_12) ** (1 / 3) - 1) * 100 if eps and eps_12 and eps > 0 and eps_12 > 0 else None
    return Fundamentals(
        as_of=as_of,
        market_cap_cr=round(close * shares, 0) if close and shares else None,
        revenue_growth_yoy=_r(_growth(rev, _ttm(qs, "revenue", 4))),
        profit_growth_yoy=_r(_growth(np_, _ttm(qs, "net_profit", 4))),
        eps_growth_yoy=_r(_growth(eps, eps_4)),
        eps_cagr_3y=_r(cagr),
        roe=_r(np_ / ((equity + equity_1y) / 2 if equity_1y else equity) * 100) if np_ is not None and equity else None,
        roce=_r(op / (equity + (debt or 0)) * 100) if op is not None and equity else None,
        operating_margin=_r(op / rev * 100) if op is not None and rev else None,
        net_margin=_r(np_ / rev * 100) if np_ is not None and rev else None,
        free_cash_flow_cr=_r(cfo - capex, 0) if cfo is not None and capex is not None else None,
        cfo_to_pat=_r(cfo / np_, 3) if cfo is not None and np_ and np_ > 0 else None,
        debt_to_equity=_r(debt / equity, 3) if debt is not None and equity else None,
        interest_coverage=_r(op / interest) if op is not None and interest and interest > 0 else None,
        pe=_r(pe),
        pb=_r(close / (equity / shares)) if close and equity and shares else None,
        peg=_r(pe / cagr, 3) if pe and pe > 0 and cagr else None,
        dividend_yield=_r(dps_ttm / close * 100) if dps_ttm is not None and close else None,
        promoter_holding=hold.promoter_pct if hold else None,
        promoter_pledge=hold.promoter_pledged_pct if hold else None,
        institutional_holding=_r((hold.fii_pct or 0) + (hold.dii_pct or 0))
        if hold and (hold.fii_pct is not None or hold.dii_pct is not None) else None,
        pe_median_5y=_r(statistics.median(pe_history)) if len(pe_history) >= 4 else None,
        positive_eps_quarters_8=sum(q_eps[i] > q_eps[i - 4] for i in range(4, 12)) if len(q_eps) == 12 else None,
        quarterly_eps=q_eps or None,
        eps_ttm=_r(eps, 4),
        book_value_per_share=_r(equity / shares, 4) if equity and shares else None,
        dps_ttm=_r(dps_ttm, 4),
        shares_outstanding_cr=shares,
    )


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, nd)


def build_snapshots(quarters: dict[str, list[Quarter]], holdings: dict[str, list[Holding]],
                    close_on: Callable[[str, str], float | None]) -> dict[str, list[Fundamentals]]:
    """Point-in-time snapshots per symbol, one at every results or shareholding publication date.

    `close_on(symbol, date)` returns the last close on or before `date` (None if unknown).
    """
    out: dict[str, list[Fundamentals]] = {}
    for sym in sorted(set(quarters) | set(holdings)):
        qs, hs = quarters.get(sym, []), holdings.get(sym, [])
        dates = sorted({q.published_on for q in qs} | {h.published_on for h in hs})
        pe_points: list[tuple[str, float]] = []
        snaps = []
        for d in dates:
            known = sorted((q for q in qs if q.published_on <= d), key=lambda q: q.period_end)
            hold = max((h for h in hs if h.published_on <= d), key=lambda h: h.period_end, default=None)
            if not known and hold is None:
                continue
            close = close_on(sym, d)
            five_years_ago = (date.fromisoformat(d) - timedelta(days=5 * 365)).isoformat()
            history = [pe for when, pe in pe_points if five_years_ago <= when < d]
            f = snapshot(known, hold, d, close, history)
            if f.pe is not None and f.pe > 0:
                pe_points.append((d, f.pe))
            snaps.append(f)
        out[sym] = snaps
    return out
