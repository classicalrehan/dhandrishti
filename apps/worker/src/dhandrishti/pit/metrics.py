"""Canonical metric catalogue. Raw reported figures only; ratios are derived later, as of a date.

Each metric fixes its unit and the period types it may have. Flows (P&L, cash flow) cover a period;
INSTANT values (balance sheet, shares, shareholding) are 'as at' period_end. Half-year (H) and full-year
(FY) cash-flow figures are cumulative from the start of the financial year, as Indian filings report them.
"""

from dataclasses import dataclass

FLOW = ("Q", "H", "FY")
INSTANT = ("INSTANT",)


@dataclass(frozen=True)
class Metric:
    unit: str
    period_types: tuple[str, ...]
    statement: str
    description: str


METRICS: dict[str, Metric] = {
    # Income statement (₹ crore, per period)
    "revenue": Metric("INR_CR", FLOW, "income", "Revenue from operations (banks: interest earned + other income)"),
    # EBITDA is not a reported line item; it is derived as
    #   profit_before_exceptional_items + finance_costs + depreciation - other_income
    # from these reported figures (checked on INFY's 31-Mar-2026 filing: both derivations agree).
    "other_income": Metric("INR_CR", FLOW, "income", "Other income (non-operating)"),
    "profit_before_exceptional_items": Metric("INR_CR", FLOW, "income", "Profit before exceptional items and tax"),
    "depreciation": Metric("INR_CR", FLOW, "income", "Depreciation and amortisation"),
    "finance_costs": Metric("INR_CR", FLOW, "income", "Finance costs (interest expense; banks: interest expended)"),
    "profit_before_tax": Metric("INR_CR", FLOW, "income", "Profit before tax, after exceptional items"),
    "net_profit": Metric("INR_CR", FLOW, "income", "Net profit attributable to owners of the company"),
    "eps_basic": Metric("INR_PER_SHARE", FLOW, "income", "Basic EPS for the period (not annualised)"),
    "eps_diluted": Metric("INR_PER_SHARE", FLOW, "income", "Diluted EPS for the period (not annualised)"),
    "dividend_per_share": Metric("INR_PER_SHARE", FLOW, "income", "Dividend declared for the period, per share"),
    # Balance sheet (₹ crore, as at period_end)
    "total_equity": Metric("INR_CR", INSTANT, "balance", "Equity attributable to owners (share capital + other equity)"),
    "total_borrowings": Metric("INR_CR", INSTANT, "balance", "Current + non-current borrowings (banks: borrowings, excl. deposits)"),
    "cash_and_equivalents": Metric("INR_CR", INSTANT, "balance", "Cash and cash equivalents"),
    "total_assets": Metric("INR_CR", INSTANT, "balance", "Total assets"),
    "shares_outstanding": Metric("SHARES_CR", INSTANT, "balance", "Equity shares outstanding, crore"),
    # Cash flow (₹ crore, cumulative from the start of the financial year)
    "cash_from_operations": Metric("INR_CR", ("H", "FY"), "cashflow", "Net cash from operating activities"),
    "capex": Metric("INR_CR", ("H", "FY"), "cashflow", "Purchase of property, plant, equipment and intangibles (positive number)"),
    # Shareholding pattern (% as at quarter end)
    "promoter_holding_pct": Metric("PCT", INSTANT, "shareholding", "Promoter and promoter group holding, % of shares"),
    "promoter_pledged_pct": Metric("PCT", INSTANT, "shareholding", "Promoter shares pledged or encumbered, % of promoter holding"),
    "fii_holding_pct": Metric("PCT", INSTANT, "shareholding", "Foreign portfolio investors, % of shares"),
    "dii_holding_pct": Metric("PCT", INSTANT, "shareholding", "Domestic institutions incl. mutual funds, % of shares"),
}

EBITDA = ("profit_before_exceptional_items", "finance_costs", "depreciation", "other_income")

# Which canonical metrics each existing score input needs (fundamentals_import / SPEC §5.3 definitions).
SCORE_INPUTS: dict[str, tuple[str, ...]] = {
    "roe": ("net_profit", "total_equity"),
    "roce": EBITDA + ("total_equity", "total_borrowings"),
    "operating_margin": EBITDA + ("revenue",),
    "net_margin": ("net_profit", "revenue"),
    "debt_to_equity": ("total_borrowings", "total_equity"),
    "interest_coverage": EBITDA,
    "cfo_to_pat": ("cash_from_operations", "net_profit"),
    "free_cash_flow": ("cash_from_operations", "capex"),
    "promoter_pledge": ("promoter_pledged_pct",),
    "earnings_consistency": ("eps_diluted",),
    "revenue_growth": ("revenue",),
    "profit_growth": ("net_profit",),
    "eps_growth": ("eps_diluted",),
    "eps_cagr_3y": ("eps_diluted",),
    "pe": ("eps_diluted",),
    "pb": ("total_equity", "shares_outstanding"),
    "peg": ("eps_diluted",),
    "dividend_yield": ("dividend_per_share",),
    "pe_median_5y": ("eps_diluted",),
}
# Quarters of history each input needs (TTM = 4; YoY growth = 8; 3-year CAGR = 16; consistency = 12).
HISTORY_QUARTERS = {"revenue_growth": 8, "profit_growth": 8, "eps_growth": 8, "eps_cagr_3y": 16,
                    "earnings_consistency": 12, "pe_median_5y": 20}
