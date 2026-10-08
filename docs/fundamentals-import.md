# Importing real fundamentals

Kite Connect has prices only, so Fundamental Quality (25), Earnings Growth (20) and Valuation (10)
are neutral for every stock until company financials are imported. This importer reads two CSV
files from any source (Screener.in export, TrueData, NSE filings typed up by hand) into the Kite
database.

```bash
pnpm fundamentals:import --quarterly results.csv --shareholding shareholding.csv --source "Screener.in" --dry-run
pnpm fundamentals:import --quarterly results.csv --shareholding shareholding.csv --source "Screener.in"
pnpm pipeline:kite      # re-score with the new numbers
```

Paths are relative to where you run the command. `--dry-run` validates and prints coverage per
stock without writing. The importer refuses the MOCK database.

## File formats
Templates with the headers: `docs/templates/fundamentals_quarterly.csv` and `docs/templates/shareholding.csv`.

**Quarterly results** (one row per stock per quarter; amounts in ₹ crore, per-share values in ₹)

| Column | Required | Meaning |
|---|---|---|
| `symbol` | yes | NSE symbol, as in the app |
| `period_end` | yes | quarter end, `YYYY-MM-DD` |
| `published_on` | yes | date the results were announced (not before `period_end`) |
| `revenue`, `operating_profit`, `net_profit`, `eps` | yes | the quarter's figures |
| `interest`, `equity`, `debt` | no | interest cost; balance-sheet equity and debt at quarter end |
| `cfo`, `capex` | no | cash from operations and capital spending (quarterly or half-yearly rows) |
| `dps` | no | dividend per share declared that quarter (blank = none) |
| `shares_cr` | no | shares outstanding, in crore |

**Shareholding** (one row per stock per quarter; percentages)

| Column | Required | Meaning |
|---|---|---|
| `symbol`, `period_end`, `published_on` | yes | as above |
| `promoter_pct` | yes | promoter holding |
| `promoter_pledged_pct`, `fii_pct`, `dii_pct` | no | pledge, foreign and domestic institutions |

## How numbers are derived
- **No look-ahead.** A snapshot is created at each `published_on` date and uses only rows published
  by then, so backtests and paper trading see results only after they were public.
- **TTM** is the sum of the last 4 quarters. Growth compares TTM with the TTM a year earlier
  (needs 8 quarters); 3-year EPS CAGR needs 16 quarters. Too few quarters gives "Data unavailable",
  never a guess.
- ROE uses average equity; ROCE uses operating profit as an EBIT proxy over equity + debt.
- **Valuation follows the price.** When EPS, book value and dividends per share are known, P/E,
  P/B, PEG, dividend yield and market cap are recomputed from each scoring day's close
  (`valuation.reprice`), so valuation is never stale between quarterly results.
- The 5-year median P/E uses the P/E at earlier publication dates (needs at least 4).

Full definitions: the module docstring in `apps/worker/src/dhandrishti/ingestion/fundamentals_import.py`
and SPEC §5.
