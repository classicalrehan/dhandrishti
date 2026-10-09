"""NSE shareholding-pattern XBRL (Regulation 31) → canonical shareholding observations.

Written against SHP_1652323_16042026045034_WEB.xml and SHP_1693581_15072026065242_WEB.xml (INFY, as on
31-Mar-2026 and 30-Jun-2026; taxonomy in-bse-shp-2025-10-31), downloaded manually 2026-10-09:
  - holdings are facts in contexts with a CategoryOfShareholdersAxis member (promoter group, public,
    foreign / domestic institutions, government, non-institutions, non-promoter non-public, total)
  - percentages are fractions (0.1438 = 14.38%) → stored in PCT
  - promoter pledge is a yes/no fact; when "false" the pledged share is reported as 0
  - DateOfReport is the "as on" date; there is no standalone/consolidated distinction (stored as
    STANDALONE: it describes the listed entity)

Older files (taxonomy in-bse-shp-2022-09-30, e.g. INFY 2023-2024) differ: company-level facts point to
contexts that are not defined in the file (read as document-level text, with a note), percentages are in
percent (14.71) instead of fractions (detected from the total row), the pledge question is "pledged or
otherwise encumbered", the government category is spelt "Goverments", and the symbol is also in the
context entity identifier (scheme NSESymbol).

The file has no publication time of its own (its file name holds a submission time on a 12-hour clock
without AM/PM). Observations are only built with a publication time supplied from the shareholding
listing; without one nothing is importable.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ..store import Observation
from .nse_xbrl import XI, XbrlError, _safe_root

XDI = "{http://xbrl.org/2006/xbrldi}"
SOURCE = "NSE SHP XBRL (manual download)"
PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
SHARES = "NumberOfFullyPaidUpEquityShares"
CATEGORY = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroupMember",
    "public": "PublicShareholdingMember",
    "non_promoter_non_public": "SharesHeldByNonPromoterNonPublicShareholdersMember",
    "total": "ShareholdingPatternMember",
    "fii": "InstitutionsForeignMember",
    "dii": "InstitutionsDomesticMember",
    "government": ("GovernmentsMember", "GovermentsMember"),
    "non_institutions": "NonInstitutionsMember",
}
PLEDGE_FLAG = "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"
PLEDGE_FLAGS = (PLEDGE_FLAG, "WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered")


@dataclass
class ShareholdingFiling:
    symbol: str
    as_on: date
    pct: dict[str, float]        # category -> percent (0-100)
    shares: dict[str, float]     # category -> number of shares
    promoter_pledged: bool | None
    checks: list[tuple[str, str, str]]
    notes: list[str]

    def observations(self, published_at: datetime, record_id: str) -> list[Observation]:
        def obs(metric, value):
            return Observation(symbol=self.symbol, metric=metric, value=round(value, 6), unit="PCT", basis="STANDALONE",
                               period_type="INSTANT", period_start=None, period_end=self.as_on,
                               filing_type="SHAREHOLDING_PATTERN", reported_at=published_at, available_at=published_at,
                               availability_basis="EXCHANGE_TIMESTAMP", value_vintage="AS_REPORTED", source=SOURCE,
                               source_record_id=record_id)
        out = [obs(m, self.pct[k]) for m, k in (("promoter_holding_pct", "promoter"), ("fii_holding_pct", "fii"),
                                                ("dii_holding_pct", "dii")) if k in self.pct]
        if self.promoter_pledged is False:
            out.append(obs("promoter_pledged_pct", 0.0))
        return out


def parse(path: Path) -> ShareholdingFiling:
    root = _safe_root(path)
    member_of: dict[str, str | None] = {}
    entity_symbols = set()
    for c in root.iter(XI + "context"):
        mems = [(m.text or "").strip().split(":")[-1] for m in c.iter(XDI + "explicitMember")]
        typed = c.find(f".//{XDI}typedMember") is not None
        member_of[c.get("id")] = None if typed or len(mems) > 1 else (mems[0] if mems else "")
        ident = c.find(f".//{XI}identifier")
        if ident is not None and (ident.get("scheme") or "").endswith("NSESymbol"):
            entity_symbols.add((ident.text or "").strip())
    notes = []
    undefined = set()
    plain_text: dict[str, set[str]] = defaultdict(set)
    by_member: dict[str, dict[str, float]] = defaultdict(dict)
    for e in root:
        cid = e.get("contextRef")
        if cid is None:
            continue
        name, value = e.tag.split("}", 1)[1], (e.text or "").strip()
        if cid not in member_of:          # older files: company-level facts point to undefined contexts
            undefined.add(cid)
            if not e.get("unitRef"):
                plain_text[name].add(value)
            continue
        if member_of[cid] is None:
            continue
        if member_of[cid] == "":
            plain_text[name].add(value)
        elif e.get("unitRef") and value:
            by_member[member_of[cid]][name] = float(value)
    if undefined:
        notes.append(f"facts refer to contexts not defined in the file ({', '.join(sorted(undefined))}); "
                     "read as company-level text")

    def one(name):
        vals = plain_text.get(name, set())
        if len(vals) != 1:
            raise XbrlError(f"{path.name}: expected one {name}, found {sorted(vals)}")
        return next(iter(vals))

    symbol = next(iter(plain_text["Symbol"])) if len(plain_text.get("Symbol", ())) == 1 else None
    if symbol is None and len(entity_symbols) == 1:
        symbol = next(iter(entity_symbols))
    if symbol is None:
        raise XbrlError(f"{path.name}: company symbol not found")
    if entity_symbols and entity_symbols != {symbol}:
        raise XbrlError(f"{path.name}: symbol {symbol} but context identifiers say {sorted(entity_symbols)}")
    as_on = date.fromisoformat(one("DateOfReport"))
    flag = next((next(iter(plain_text[f])) for f in PLEDGE_FLAGS if len(plain_text.get(f, ())) == 1), None)
    pledged = {"false": False, "true": True}.get(flag)

    def member(k):
        names = CATEGORY[k] if isinstance(CATEGORY[k], tuple) else (CATEGORY[k],)
        return next((by_member[n] for n in names if by_member.get(n)), {})

    raw_pct = {k: member(k)[PCT] for k in CATEGORY if PCT in member(k)}
    shares = {k: member(k)[SHARES] for k in CATEGORY if SHARES in member(k)}
    if not {"promoter", "total"} <= set(shares):
        raise XbrlError(f"{path.name}: promoter or total shareholding not found")
    total_pct = raw_pct.get("total")
    if total_pct is None or not (abs(total_pct - 1) < 1e-6 or abs(total_pct - 100) < 1e-6):
        raise XbrlError(f"{path.name}: total shareholding percentage {total_pct} is neither 1 nor 100")
    scale = 100.0 if abs(total_pct - 1) < 1e-6 else 1.0
    pct = {k: v * scale for k, v in raw_pct.items()}

    checks = []

    def identity(name, a, b, level="FAIL", tol=0.5):
        if a is None or b is None:
            checks.append((name, "N/A", "not in this filing"))
        else:
            checks.append((name, "PASS" if abs(a - b) <= tol else level, f"{a:,.0f} vs {b:,.0f}"))

    s = shares.get
    identity("promoter + public + non-promoter non-public shares = total",
             None if None in (s("promoter"), s("public")) else s("promoter") + s("public") + (s("non_promoter_non_public") or 0),
             s("total"))
    parts = [s(k) for k in ("fii", "dii", "non_institutions")]
    identity("public = foreign + domestic institutions + government + non-institutions",
             None if None in parts else sum(parts) + (s("government") or 0), s("public"))
    # Percentages are kept as filed. They use the regulatory basis (SCRR 1957), which leaves out shares such
    # as those underlying depository receipts, so promoter shares / total shares does not reproduce them
    # (INFY 31-Mar-2026: 13.33% vs the filed 14.38%). No recomputation check is made.
    if pledged is not False:
        checks.append(("promoter pledge stated", "WARN",
                       f"pledge flag is {flag!r}: the pledged share is not read yet (needs a sample with pledges)"))
    return ShareholdingFiling(symbol, as_on, pct, shares, pledged, checks, notes)
