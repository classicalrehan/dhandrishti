"""NSE results XBRL (SEBI Ind-AS taxonomy) → canonical observations, as originally reported.

Written against INTEGRATED_FILING_INDAS_1658041_23042026090203_WEB.xml (INFY standalone, quarter ended
31-Mar-2026, taxonomy in-capmkt 2026-01-31), downloaded manually 2026-10-09. Facts found there:
  - contexts without dimensions carry the statements: the quarter, the financial year to date, the
    balance-sheet date (and opening cash only for the prior year: comparatives are NOT tagged)
  - amounts in rupees (unit INR, decimals -7 = rounded to the crore) → stored in ₹ crore
  - EPS in INRPerShare; Symbol, NatureOfReportStandaloneConsolidated, DateOfEndOfReportingPeriod and
    board-meeting times as text facts
  - no EBITDA and no dividend per share

Every file must be matched, by its NSE file name, to a row of a results listing: that row supplies
the exchange dissemination time (`reported_at` = `available_at`, EXCHANGE_TIMESTAMP). A file without a
listing row is refused, never imported undated.

Old format (pre-2025 "Financial Results" page, Ind-AS 2020 taxonomy, e.g. INDAS_117292_...): same element
names; contexts may carry wrong period dates in their header, corrected from the filing's stated period.

Banking taxonomy (BANKING_*.xml; first sample HDFCBANK quarter ended 31-Mar-2025, 2025-01-31 taxonomy):
interest earned / interest expended / provisions instead of revenue / finance costs / EBITDA, a bank balance
sheet (deposits, advances) and profit after minority interest. Mapped separately (BANKING below).
That sample showed why cross-checks matter: minority interest was also tagged as an exceptional item, so
profit attributable to owners is understated while every addition in the file still balances. Only the
EPS and segment cross-checks reveal it; such filings WARN and need review before import.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..controls import Provenance
from ..store import Observation
from .nse_results_listing import ResultFiling

XI = "{http://www.xbrl.org/2003/instance}"
XDI = "{http://xbrl.org/2006/xbrldi}"
CRORE = 1e7
SOURCE = "NSE XBRL (manual download)"

# canonical metric -> (taxonomy elements, combine). "first": first element present; "sum": add all present.
FLOWS = {
    "revenue": (("RevenueFromOperations",), "first"),
    "other_income": (("OtherIncome",), "first"),
    "depreciation": (("DepreciationDepletionAndAmortisationExpense",), "first"),
    "finance_costs": (("FinanceCosts",), "first"),
    "profit_before_exceptional_items": (("ProfitBeforeExceptionalItemsAndTax",), "first"),
    "profit_before_tax": (("ProfitBeforeTax",), "first"),
    "eps_basic": (("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",), "first"),
    "eps_diluted": (("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",), "first"),
}
# Net profit attributable to owners: for consolidated results only the owners' share is acceptable.
OWNERS_PROFIT = ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent")
CASHFLOWS = {
    "cash_from_operations": (("CashFlowsFromUsedInOperatingActivities",), "first"),
    "capex": (("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
               "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
               "PurchaseOfIntangibleAssetsUnderDevelopment"), "sum"),
}
INSTANTS = {
    "total_equity": (("EquityAttributableToOwnersOfParent",), "first"),
    "total_borrowings": (("BorrowingsCurrent", "BorrowingsNoncurrent"), "sum"),
    "cash_and_equivalents": (("CashAndCashEquivalents",), "first"),
    "total_assets": (("Assets",), "first"),
}
BASIS = {"Standalone": "STANDALONE", "Consolidated": "CONSOLIDATED"}

# Banking taxonomy. 'revenue' for banks = total income (interest earned + other income), per the catalogue.
BANK_FLOWS = {
    "revenue": (("Income",), "first"),
    "other_income": (("OtherIncome",), "first"),
    "finance_costs": (("InterestExpended",), "first"),
    "profit_before_tax": (("ProfitLossFromOrdinaryActivitiesBeforeTax",), "first"),
    "eps_basic": (("BasicEarningsPerShareAfterExtraordinaryItems",), "first"),
    "eps_diluted": (("DilutedEarningsPerShareAfterExtraordinaryItems",), "first"),
}
BANK_OWNERS_PROFIT = ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",)
BANK_CASHFLOWS = {
    "cash_from_operations": (("CashFlowsFromUsedInOperatingActivities",), "first"),
    "capex": (("PurchaseOfTangibleAssetsClassifiedAsInvestingActivities",
               "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"), "sum"),
}
BANK_INSTANTS = {
    "total_equity": (("Capital", "ReservesAndSurplus"), "sum"),
    "total_borrowings": (("Borrowings",), "first"),  # excludes deposits, per the catalogue
    "cash_and_equivalents": (("CashAndBalancesWithReserveBankOfIndia", "BalancesWithBanksAndMoneyAtCallAndShortNotice"), "sum"),
    "total_assets": (("Assets",), "first"),
}
BANK_LIABILITY_LINES = ("Capital", "ReservesAndSurplus", "Deposits", "Borrowings", "OtherLiabilitiesAndProvisions")
BANK_ASSET_LINES = ("CashAndBalancesWithReserveBankOfIndia", "BalancesWithBanksAndMoneyAtCallAndShortNotice",
                    "Investments", "Advances", "FixedAssets", "OtherAssets")
# NBFC taxonomy (Ind-AS for NBFCs): the Ind-AS statement elements, but the balance sheet has no current/non-current
# split and debt is filed as separate lines. Public deposits are kept out of borrowings, as for banks.
NBFC_INSTANTS = {**INSTANTS,
                 "total_borrowings": (("DebtSecurities", "Borrowings", "SubordinatedLiabilities"), "sum")}
# Life-insurance taxonomy (IRDAI formats): revenue account (policyholders) and profit and loss account
# (shareholders). Investment income swings with markets, so revenue = net premium income.
LI_EPS = "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized"
LI_FLOWS = {
    "revenue": (("NetPremiumIncome",), "first"),
    "profit_before_tax": (("ProfitLossBeforeTax",), "first"),
    "eps_basic": ((LI_EPS,), "first"),
    "eps_diluted": ((LI_EPS,), "first"),
}
LI_CASHFLOWS = {"cash_from_operations": (("CashFlowsFromUsedInOperatingActivities",), "first")}
LI_INSTANTS = {
    "total_equity": (("ShareholdersFunds",), "first"),
    "total_borrowings": (("Borrowings",), "first"),
    "cash_and_equivalents": (("CashAndBankBalances",), "first"),
    "total_assets": (("ApplicationOfFunds",), "first"),
}
MAPPING_NOTES = {
    "LI": {
        "revenue": "life insurer revenue = net premium income (investment income excluded)",
        "eps_basic": "insurer files one basic-and-diluted EPS",
        "eps_diluted": "insurer files one basic-and-diluted EPS",
        "total_equity": "life insurer equity = shareholders' funds",
        "cash_and_equivalents": "life insurer cash = cash and bank balances",
        "total_assets": "life insurer total = application of funds (balance-sheet total)",
    },
    "NBFC": {
        "total_borrowings": "NBFC borrowings = debt securities + borrowings + subordinated liabilities (deposits excluded)",
    },
    "BANKING": {
        "revenue": "bank revenue = total income (interest earned + other income)",
        "finance_costs": "bank finance costs = interest expended",
        "total_equity": "bank equity = capital + reserves and surplus (ESOPs outstanding excluded)",
        "total_borrowings": "borrowings exclude deposits",
        "cash_and_equivalents": "cash and balances with RBI + balances with banks and money at call",
    },
}
MAPS = {
    "INDAS": (FLOWS, OWNERS_PROFIT, "ProfitLossForPeriod", CASHFLOWS, INSTANTS),
    "BANKING": (BANK_FLOWS, BANK_OWNERS_PROFIT, "ProfitLossForThePeriod", BANK_CASHFLOWS, BANK_INSTANTS),
    "NBFC": (FLOWS, OWNERS_PROFIT, "ProfitLossForPeriod", CASHFLOWS, NBFC_INSTANTS),
    "LI": (LI_FLOWS, (), "ProfitLossAfterTaxAndExtraordinaryItems", LI_CASHFLOWS, LI_INSTANTS),
}


class XbrlError(ValueError):
    pass


@dataclass
class ParsedFiling:
    symbol: str
    basis: str
    period_end: date
    observations: list[Observation]
    checks: list[tuple[str, str, str]]    # (name, PASS | FAIL | WARN | N/A, detail); only FAIL blocks an import
    notes: list[str]
    provenance: list[Provenance] = field(default_factory=list)   # one per observation, same order
    taxonomy: str = ""


def _period_type(start: date, end: date) -> str | None:
    days = (end - start).days + 1
    for ptype, (lo, hi) in {"Q": (89, 93), "H": (181, 185), "FY": (364, 367)}.items():
        if lo <= days <= hi:
            return ptype
    return None  # e.g. nine-month year-to-date figures: not part of the canonical model


def _safe_root(path: Path) -> ET.Element:
    head = path.read_bytes()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise XbrlError(f"{path.name}: DOCTYPE/ENTITY declarations are not accepted")
    return ET.fromstring(head)


def parse(path: Path, filing: ResultFiling) -> ParsedFiling:
    if path.name != filing.xbrl_file:
        raise XbrlError(f"{path.name} does not match listing file {filing.xbrl_file}")
    if filing.taxonomy not in MAPS:
        raise XbrlError(f"{path.name}: taxonomy {filing.taxonomy} not supported yet (examined: {', '.join(MAPS)})")
    flows, owners_els, period_profit, cashflows, instants = MAPS[filing.taxonomy]
    root = _safe_root(path)

    periods: dict[str, tuple[date | None, date]] = {}
    for c in root.iter(XI + "context"):
        if c.find(f".//{XDI}explicitMember") is not None or c.find(f".//{XDI}typedMember") is not None:
            continue
        p = c.find(XI + "period")
        inst = p.find(XI + "instant")
        if inst is not None:
            periods[c.get("id")] = (None, date.fromisoformat(inst.text.strip()))
        else:
            periods[c.get("id")] = (date.fromisoformat(p.find(XI + "startDate").text.strip()),
                                    date.fromisoformat(p.find(XI + "endDate").text.strip()))

    # The filer states each context's period as text (DateOfStart/EndOfReportingPeriod). Old-format files
    # (Ind-AS 2020 taxonomy, e.g. INFY 31-Dec-2024) label the nine-month year-to-date context with the
    # quarter's dates, so the stated period wins and any disagreement is noted.
    notes = []
    stated: dict[str, dict[str, str]] = defaultdict(dict)
    for e in root:
        name = e.tag.split("}", 1)[-1]
        if e.get("contextRef") in periods and name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"):
            stated[e.get("contextRef")][name] = (e.text or "").strip()
    for cid, d in stated.items():
        start, end_ = periods[cid]
        if start is None or len(d) != 2:
            continue
        real = (date.fromisoformat(d["DateOfStartOfReportingPeriod"]), date.fromisoformat(d["DateOfEndOfReportingPeriod"]))
        if real != (start, end_):
            notes.append(f"context {cid}: header says {start}..{end_}, filing states {real[0]}..{real[1]}; using the stated period")
            periods[cid] = real

    num: dict[tuple[str, tuple], float] = {}
    ambiguous: set[tuple[str, tuple]] = set()  # elements filed twice with different values: never used
    text: dict[str, set[str]] = defaultdict(set)
    qname: dict[str, str] = {}                     # local name -> prefix:name (prefix = last segment of the namespace)
    ctx_ids: dict[tuple, list[str]] = defaultdict(list)
    for cid, per in periods.items():
        ctx_ids[per].append(cid)
    for e in root:
        ctx = e.get("contextRef")
        if ctx not in periods:
            continue
        name = e.tag.split("}", 1)[1]
        qname.setdefault(name, e.tag[1:].split("}", 1)[0].rstrip("/").rsplit("/", 1)[-1] + ":" + name)
        value = (e.text or "").strip()
        if e.get("unitRef"):
            v = float(value) / (CRORE if e.get("unitRef") == "INR" else 1)
            key = (name, periods[ctx])
            if key in ambiguous:
                continue
            if key in num and num[key] != v:
                # e.g. opening and closing cash both tagged with the period's context: which is which is not stated,
                # so neither is used (values depending on it are absent) and the filing gets a note.
                ambiguous.add(key)
                start, end_ = periods[ctx]
                notes.append(f"{name} has two different values for {start}..{end_} ({num.pop(key):g} and {v:g}); "
                             "element not used")
                continue
            num[key] = v
        else:
            text[name].add(value)

    def one(name: str) -> str:
        vals = text.get(name, set())
        if len(vals) != 1:
            raise XbrlError(f"{path.name}: expected one {name}, found {sorted(vals)}")
        return next(iter(vals))

    symbol, nature, end = one("Symbol"), one("NatureOfReportStandaloneConsolidated"), date.fromisoformat(one("DateOfEndOfReportingPeriod"))
    problems = []
    if symbol != filing.symbol:
        problems.append(f"symbol {symbol} vs listing {filing.symbol}")
    if BASIS.get(nature) != filing.basis:
        problems.append(f"basis {nature} vs listing {filing.basis}")
    if end != filing.period_end:
        problems.append(f"period end {end} vs listing {filing.period_end}")
    if problems:
        raise XbrlError(f"{path.name} does not match its listing row: {'; '.join(problems)}")

    obs, prov = [], []

    def provenance(used, per, derivation=None, mapping_note=None, how=None):
        concepts = [qname.get(u, u) for u in used]
        how = how or ("REPORTED" if len(used) == 1 and derivation is None else "SUMMED")
        if how == "SUMMED" and derivation is None:
            derivation = "sum: " + " + ".join(used)
        return Provenance(how, concepts, sorted(ctx_ids.get(per, [])), derivation, mapping_note)

    def emit(metric, value, unit, ptype, start, end_, p, note=None):
        prov.append(p)
        obs.append(Observation(
            symbol=symbol, metric=metric, value=round(value, 6), unit=unit, basis=filing.basis, period_type=ptype,
            period_start=start, period_end=end_, filing_type="QUARTERLY_RESULT", reported_at=filing.disseminated_at,
            available_at=filing.disseminated_at, availability_basis="EXCHANGE_TIMESTAMP", value_vintage="AS_REPORTED",
            source=SOURCE, source_record_id=path.name + (f" ({note})" if note else "")))

    def pick(elements, how, per):
        used = [el for el in elements if (el, per) in num]
        if not used:
            return None, []
        if how == "first":
            return num[(used[0], per)], used[:1]
        return sum(num[(el, per)] for el in used), used

    note_for = MAPPING_NOTES.get(filing.taxonomy, {})

    flow_periods = sorted({p for (_, p) in num if p[0] is not None and p[1] == end})
    for per in flow_periods:
        ptype = _period_type(*per)
        if ptype is None:
            notes.append(f"skipped period {per[0]}..{per[1]} (not a quarter, half or year)")
            continue
        for metric, (els, how) in flows.items():
            v, used = pick(els, how, per)
            if v is not None:
                emit(metric, v, "INR_PER_SHARE" if metric.startswith("eps") else "INR_CR", ptype, *per,
                     provenance(used, per, mapping_note=note_for.get(metric)))
        owners, used = pick(owners_els, "first", per)
        note = None
        if owners is None and filing.basis == "STANDALONE":
            owners, used = pick((period_profit,), "first", per)
            note = "standalone: profit for the period (no minority interest to deduct)"
        if owners is not None:
            emit("net_profit", owners, "INR_CR", ptype, *per, provenance(used, per, mapping_note=note))
        elif (period_profit, per) in num:
            notes.append(f"net_profit not stored for {per}: consolidated profit attributable to owners not tagged")
        if ptype in ("H", "FY"):
            for metric, (els, how) in cashflows.items():
                v, used = pick(els, how, per)
                if v is not None:
                    emit(metric, v, "INR_CR", ptype, *per, provenance(used, per, mapping_note=note_for.get(metric)))
    bs = (None, end)
    for metric, (els, how) in instants.items():
        v, used = pick(els, how, bs)
        note = note_for.get(metric)
        if v is None and metric == "total_equity" and filing.basis == "STANDALONE" and filing.taxonomy in ("INDAS", "NBFC"):
            v, used = pick(("Equity",), "first", bs)
            note = "standalone total equity (no non-controlling interest)"
        if v is not None:
            emit(metric, v, "INR_CR", "INSTANT", None, end, provenance(used, bs, mapping_note=note))
    quarter = next((p for p in flow_periods if _period_type(*p) == "Q"), None)
    paid, face = (num.get(("PaidUpValueOfEquityShareCapital", quarter)), num.get(("FaceValueOfEquityShareCapital", quarter))) if quarter else (None, None)
    if paid and face:
        emit("shares_outstanding", paid / face, "SHARES_CR", "INSTANT", None, end,
             provenance(["PaidUpValueOfEquityShareCapital", "FaceValueOfEquityShareCapital"], quarter,
                        derivation="PaidUpValueOfEquityShareCapital / FaceValueOfEquityShareCapital", how="CALCULATED",
                        mapping_note="shares outstanding at period end; differs from weighted shares used for EPS"),
             "derived: paid-up equity capital / face value")

    checks = {"BANKING": _bank_checks, "LI": _li_checks}.get(filing.taxonomy, _checks)(num, quarter, bs, filing, text)
    return ParsedFiling(symbol, filing.basis, end, obs, checks, notes, prov, filing.taxonomy)


def _checks(num, q, bs, filing, text) -> list[tuple[str, str, str]]:
    """Checks the filing must satisfy. Accounting identities FAIL (and block the import) when broken;
    approximations only WARN; statements a filing does not contain are N/A (e.g. no balance sheet in a
    June or December quarter). Tolerance for identities: one crore of rounding."""
    out = []

    def identity(name, a, b, tol=1.0):
        if a is None or b is None:
            out.append((name, "N/A", "not in this filing"))
        else:
            out.append((name, "PASS" if abs(a - b) <= tol else "FAIL", f"{a:,.2f} vs {b:,.2f}"))

    g = lambda el, per=q: num.get((el, per))  # noqa: E731
    if q:
        rev, oi, inc, exp = g("RevenueFromOperations"), g("OtherIncome"), g("Income"), g("Expenses")
        identity("income = revenue + other income", (rev or 0) + (oi or 0) if rev is not None else None, inc)
        identity("profit before exceptional items = income - expenses",
                 inc - exp if inc is not None and exp is not None else None, g("ProfitBeforeExceptionalItemsAndTax"))
        pbt, tax, pat = g("ProfitBeforeTax"), g("TaxExpense"), g("ProfitLossForPeriod")
        identity("profit after tax = PBT - tax (continuing)", pbt - tax if pbt is not None and tax is not None else None,
                 g("ProfitLossForPeriodFromContinuingOperations"))
        # EPS uses the weighted-average share count, period-end shares differ after buybacks or issues:
        # an approximation, so it warns instead of blocking.
        paid, face, eps = g("PaidUpValueOfEquityShareCapital"), g("FaceValueOfEquityShareCapital"), \
            g("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations")
        owners = next((g(el) for el in OWNERS_PROFIT if g(el) is not None), pat)
        if paid and face and eps is not None and owners is not None:
            implied = eps * paid / face
            ok = abs(implied - owners) <= 0.02 * abs(owners) + 1
            out.append(("EPS x period-end shares ≈ owners' profit (2%)", "PASS" if ok else "WARN",
                        f"{implied:,.0f} vs {owners:,.0f}"))
        out.append(_minority_as_exceptional(g("ExceptionalItemsBeforeTax"), g("ProfitOrLossAttributableToNonControllingInterests"),
                                            None, g("ProfitBeforeTax")))
    identity("assets = equity + liabilities", g("Assets", bs), g("EquityAndLiabilities", bs))
    meeting = next(iter(text.get("DateOfEndOfBoardMeeting", [])), None)
    if meeting:
        ok = date.fromisoformat(meeting) <= filing.disseminated_at.date()
        out.append(("published on/after the board meeting", "PASS" if ok else "FAIL",
                    f"meeting ended {meeting}, published {filing.disseminated_at:%Y-%m-%d %H:%M}"))
    return out


def _bank_checks(num, q, bs, filing, text) -> list[tuple[str, str, str]]:
    """Banking taxonomy: identities FAIL; cross-checks between independent figures WARN."""
    out = []

    def identity(name, a, b, tol=1.0, level="FAIL"):
        if a is None or b is None:
            out.append((name, "N/A", "not in this filing"))
        else:
            out.append((name, "PASS" if abs(a - b) <= tol else level, f"{a:,.2f} vs {b:,.2f}"))

    g = lambda el, per=q: num.get((el, per))  # noqa: E731
    add = lambda *xs: None if any(x is None for x in xs) else sum(xs)  # noqa: E731
    sub = lambda a, b: None if a is None or b is None else a - b  # noqa: E731
    if q:
        identity("income = interest earned + other income", add(g("InterestEarned"), g("OtherIncome")), g("Income"))
        identity("operating profit = income - expenditure excl. provisions",
                 sub(g("Income"), g("ExpenditureExcludingProvisionsAndContingencies")),
                 g("OperatingProfitBeforeProvisionAndContingencies"))
        identity("PBT = operating profit - provisions + exceptional items",
                 add(sub(g("OperatingProfitBeforeProvisionAndContingencies"), g("ProvisionsOtherThanTaxAndContingencies")),
                     g("ExceptionalItems") or 0.0), g("ProfitLossFromOrdinaryActivitiesBeforeTax"))
        identity("PAT = PBT - tax", sub(g("ProfitLossFromOrdinaryActivitiesBeforeTax"), g("TaxExpense")),
                 g("ProfitLossFromOrdinaryActivitiesAfterTax"))
        seg, unalloc = g("SegmentProfitBeforeTax"), g("OtherUnallocableExpenditureNetOffUnAllocableIncome")
        out.append(_minority_as_exceptional(g("ExceptionalItems"), g("ProfitLossOfMinorityInterest"),
                                            seg if (unalloc or 0) == 0 else None,
                                            g("ProfitLossFromOrdinaryActivitiesBeforeTax")))
        if seg is not None and (unalloc or 0) == 0:
            identity("segment profit before tax = PBT (cross-check)", seg, g("ProfitLossFromOrdinaryActivitiesBeforeTax"),
                     level="WARN")
        paid, face, eps = g("PaidUpValueOfEquityShareCapital"), g("FaceValueOfEquityShareCapital"), \
            g("BasicEarningsPerShareAfterExtraordinaryItems")
        owners = next((g(el) for el in BANK_OWNERS_PROFIT if g(el) is not None), g("ProfitLossForThePeriod"))
        if paid and face and eps is not None and owners is not None:
            implied = eps * paid / face
            ok = abs(implied - owners) <= 0.02 * abs(owners) + 1
            out.append(("EPS x period-end shares ≈ owners' profit (2%)", "PASS" if ok else "WARN",
                        f"{implied:,.0f} vs {owners:,.0f}"))
    identity("assets = capital and liabilities", g("Assets", bs), g("CapitalAndLiabilities", bs))
    # Each side must also equal the sum of its lines (totals can agree while lines do not).
    identity("liability lines sum to capital and liabilities",
             add(*(g(el, bs) for el in BANK_LIABILITY_LINES)), g("CapitalAndLiabilities", bs))
    identity("asset lines sum to assets", add(*(g(el, bs) for el in BANK_ASSET_LINES)), g("Assets", bs))
    identity("balance-sheet cash = cash-flow cash (cross-check)",
             add(g("CashAndBalancesWithReserveBankOfIndia", bs), g("BalancesWithBanksAndMoneyAtCallAndShortNotice", bs)),
             g("CashAndCashEquivalentsCashFlowStatement", bs), level="WARN")
    meeting = next(iter(text.get("DateOfEndOfBoardMeeting", [])), None)
    if meeting:
        ok = date.fromisoformat(meeting) <= filing.disseminated_at.date()
        out.append(("published on/after the board meeting", "PASS" if ok else "FAIL",
                    f"meeting ended {meeting}, published {filing.disseminated_at:%Y-%m-%d %H:%M}"))
    return out


def _li_checks(num, q, bs, filing, text) -> list[tuple[str, str, str]]:
    """Life-insurance taxonomy: the two identities that hold in every SBILIFE filing examined (2026-10-15)."""
    out = []

    def identity(name, a, b, tol=1.0):
        out.append((name, "N/A", "not in this filing") if a is None or b is None
                   else (name, "PASS" if abs(a - b) <= tol else "FAIL", f"{a:,.2f} vs {b:,.2f}"))

    g = lambda el, per=q: num.get((el, per))  # noqa: E731
    if q:
        pbt, pat = g("ProfitLossBeforeTax"), g("ProfitLossAfterTaxAndExtraordinaryItems")
        taxes = None if g("CurrentTaxes") is None else g("CurrentTaxes") + (g("DefferedTaxes") or 0.0)
        identity("insurer PAT = PBT - shareholders' taxes", None if pbt is None or taxes is None else pbt - taxes, pat)
    identity("sources of funds = application of funds", g("SourcesOfFunds", bs), g("ApplicationOfFunds", bs))
    meeting = next(iter(text.get("DateOfEndOfBoardMeeting", [])), None)
    if meeting:
        ok = date.fromisoformat(meeting) <= filing.disseminated_at.date()
        out.append(("published on/after the board meeting", "PASS" if ok else "FAIL",
                    f"meeting ended {meeting}, published {filing.disseminated_at:%Y-%m-%d %H:%M}"))
    return out


def _minority_as_exceptional(exceptional, minority, segment_pbt, pbt) -> tuple[str, str, str]:
    """MI-1: an exceptional item that equals minority interest is probably minority interest tagged twice
    (HDFC Bank consolidated, quarters ended 31-Mar-2025, 30-Sep-2025 and 31-Mar-2026, confirmed against the
    official results). Evidence: exceptional = -minority, or minority tagged 0 and segment PBT = PBT - exceptional."""
    name = "exceptional item looks like minority interest (MI-1)"
    if not exceptional:
        return (name, "N/A", "no exceptional item")
    if minority and abs(exceptional + minority) <= 1:
        return (name, "WARN", f"exceptional {exceptional:,.2f} = -minority interest {minority:,.2f}")
    if not minority and segment_pbt is not None and pbt is not None and abs(segment_pbt - (pbt - exceptional)) <= 1:
        return (name, "WARN", f"minority tagged 0; segment PBT {segment_pbt:,.2f} = PBT {pbt:,.2f} - exceptional {exceptional:,.2f}")
    return (name, "PASS", f"exceptional {exceptional:,.2f} not explained by minority interest")
