# Point-in-time fundamentals

A provider-neutral, versioned, append-only store of raw company financial figures, built so a
backtest can ask "what could a decision on this date legitimately use?" and an audit can ask "what did
DhanDrishti actually hold on this date?". Migration 0008, code in `apps/worker/src/dhandrishti/pit/`.

**Status (2026-10-08): foundation built and tested; no real data loaded; not read by production
scoring.** The existing `fundamentals` table and `pnpm fundamentals:import` (one derived snapshot per
publication date, overwritten on re-import) are unchanged and still feed scoring when used.

## Model: one row per figure, per publication, per version
| Field | Meaning |
|---|---|
| `symbol` | NSE symbol (must exist in `securities`) |
| `metric` | Canonical name from `pit/metrics.py` (20 raw metrics; ratios are never stored) |
| `value`, `unit`, `currency` | The figure. Units: `INR_CR`, `INR_PER_SHARE`, `PCT`, `SHARES_CR`. A figure that was not reported is an absent row, never NULL or 0 |
| `basis` | `CONSOLIDATED` or `STANDALONE` (Indian companies report both; they can differ a lot) |
| `period_type` | `Q` quarter, `H` half year, `FY` financial year, `INSTANT` balance sheet / shareholding "as at" |
| `period_start`, `period_end` | The period covered; for `INSTANT`, `period_end` is the "as at" date. Indian H and FY cash flows are cumulative from 1 April |
| `filing_type` | `QUARTERLY_RESULT`, `ANNUAL_RESULT`, `ANNUAL_REPORT`, `SHAREHOLDING_PATTERN`, `OTHER` |
| `reported_at` | When the issuer/exchange published this figure (exchange broadcast time when known). NULL if unknown |
| `available_at` | The earliest moment DhanDrishti may legitimately use the figure in a decision. Derived by the rule below, never typed in. NULL = never usable |
| `availability_basis` | How `available_at` was established: `EXCHANGE_TIMESTAMP`, `REPORTED_DATE`, `STATUTORY_DEADLINE`, `UNKNOWN` |
| `value_vintage` | `AS_REPORTED` (from the original filing) or `AS_CURRENTLY_DISPLAYED` (a website/vendor's current figure, which may include later restatements) |
| `source`, `source_record_id` | Who supplied it, and their id / filing reference |
| `import_batch_id`, `ingested_at` | Which import stored it, and when DhanDrishti stored it |
| `data_version`, `supersedes_id`, `is_restatement` | Versioning (below) |

### The four dates
```
period_end    2025-03-31            the financial year ends
reported_at   2025-05-15 16:30 IST  the company's results are broadcast on NSE
available_at  2025-05-15 16:30 IST  DhanDrishti may use them from here on
ingested_at   2026-10-12 10:05 IST  the figure is loaded into DhanDrishti (can be years later)
```
A decision on trading day D is taken at D's close, **15:30 IST** (`decision_time`). A result broadcast
at 16:30 on 15 May is therefore usable for the 16 May decision, not the 15 May one.

| availability_basis | available_at | Used in strict point-in-time research? |
|---|---|---|
| `EXCHANGE_TIMESTAMP` | = reported_at (exact broadcast time) | yes |
| `REPORTED_DATE` | next day 00:00 IST (time unknown, so never the same day) | yes |
| `STATUTORY_DEADLINE` | day after the SEBI LODR deadline: 45 days after a quarter, 60 after the year, 21 for shareholding | no (estimated: a late filer would leak) |
| `UNKNOWN` | NULL | never |

Strict queries also require `value_vintage = AS_REPORTED`. Both relaxations are explicit options.

## Append-only and versions
- The database rejects `UPDATE`, `DELETE` and `TRUNCATE` on `fundamental_observations` (trigger).
- Versioning key: `(symbol, metric, basis, period_type, period_end, source)`.
  - Identical to the current version (value, reported_at, vintage, unit): skipped as a duplicate, so
    re-importing a file is harmless.
  - Different: stored as `data_version` n+1 with `supersedes_id` pointing at the previous version.
    `is_restatement` is true when the new figure was **published later** (`reported_at` later); otherwise it
    is a correction of how the figure was captured.
- Different sources and bases are never merged: disagreements are kept and reported as conflicts.

## Point-in-time query
`store.as_of(conn, symbol, decision, bases=STRICT, vintages=("AS_REPORTED",), known_by=None)` returns, for
each key, the most recently **published** version with `available_at <= decision` (corrections of the same
publication: highest version). A restatement published in 2026 is invisible to a 2025 decision.
`known_by` adds the second time axis: only rows DhanDrishti had stored by then.

```bash
pnpm pit as-of INFY 2024-06-30                 # what a decision at that close could use
pnpm pit as-of INFY 2024-06-30 --known-by 2024-07-01
pnpm pit history INFY net_profit 2024-03-31    # every version of one figure
```

## Import format (provider-neutral)
CSV, one observation per row; providers get small adapters that write this format.
Required: `symbol, metric, value, basis, period_type, period_end, filing_type, value_vintage`.
Optional: `period_start` (required unless INSTANT), `reported_at` (`YYYY-MM-DD HH:MM[:SS]` IST = broadcast
time; `YYYY-MM-DD` = date only), `availability_basis` (inferred from `reported_at` when absent), `unit`,
`currency`, `source_record_id`.

```bash
pnpm pit import pilot/nse_q1.csv --source "NSE filing (manual)" --dry-run
pnpm pit import pilot/nse_q1.csv --source "NSE filing (manual)"
pnpm pit report --out docs/research/pilot-quality.md
```
Validation rejects the whole file, listing row numbers: unknown symbol or metric, period type not allowed
for the metric, wrong unit, percentages outside 0–100, quarters/halves/years of the wrong length,
publication before period end, an exact timestamp claimed without a time, and two different values for
the same figure and publication in one file.

## Metrics
Income (Q/H/FY): `revenue, other_income, depreciation, finance_costs, profit_before_exceptional_items,
profit_before_tax, net_profit, eps_basic,
eps_diluted, dividend_per_share`. Balance sheet (INSTANT): `total_equity, total_borrowings,
cash_and_equivalents, total_assets, shares_outstanding`. Cash flow (H/FY, cumulative): `cash_from_operations,
capex`. Shareholding (INSTANT): `promoter_holding_pct, promoter_pledged_pct, fii_holding_pct, dii_holding_pct`.
EBITDA is not reported in results filings, so it is not stored: it is derived when needed as
`profit_before_exceptional_items + finance_costs + depreciation - other_income`.
`SCORE_INPUTS` in `pit/metrics.py` maps every current score input (ROE, ROCE, margins, D/E, interest cover,
CFO/PAT, FCF, pledge, EPS consistency, growth, CAGR, PE, PB, PEG, dividend yield, PE median) to the raw metrics
it needs. Banks and insurers report in different formats (no EBITDA; "revenue" = interest earned + other
income); their mapping is a pilot question.
