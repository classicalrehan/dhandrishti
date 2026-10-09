# Fundamentals pilot, October 2026

**Status: foundation built and tested; pilot data not yet collected.** No real company figures are in
the store, so no data-quality result below is a measurement of real data unless it says so. Nothing here
claims point-in-time safety for any source yet.

## 1. What exists
- Versioned, append-only observation store (migration 0008; design in [../fundamentals-pit.md](../fundamentals-pit.md)).
- Point-in-time query `store.as_of` with strict defaults (exact or dated publication, as-reported values),
  plus a `known_by` axis for "what DhanDrishti had stored".
- Provider-neutral CSV import with validation; quality report (`pnpm pit report`).
- 25 tests (below). Applied to the real database on 2026-10-08: 0 observations, 0 batches.
- Production scoring untouched: the golden scoring fixtures pass unchanged.

## 2. Pilot sample (20 stocks)
Chosen for reporting diversity and known awkward cases, not for returns. All are in the scored universe.

| Stock | Why it is in the pilot |
|---|---|
| HDFCBANK | Bank format; HDFC Ltd merger (July 2023) restates comparatives |
| BANKBARODA | PSU bank |
| BAJFINANCE | Large NBFC |
| SBILIFE | Insurer: revenue and profit concepts differ |
| INFY | Long clean history; consolidated vs standalone differ |
| PERSISTENT | Mid-cap IT |
| ITC | Hotels demerger (2025) changes comparatives |
| MARICO | FMCG |
| MARUTI | Auto; standalone close to consolidated |
| ASHOKLEY | Mid-cap auto; consolidated includes a large finance subsidiary |
| SUNPHARMA | Large exceptional items |
| LAURUSLABS | Mid-cap pharma; volatile earnings |
| RELIANCE | Very large consolidated group |
| ONGC | PSU; listed subsidiaries |
| TATASTEEL | Overseas operations, losses, impairments |
| BHEL | PSU capital goods; loss years |
| ULTRACEMCO | Acquisitions change comparatives |
| DLF | Lumpy revenue recognition |
| IDEA | Persistent losses, negative equity |
| NYKAA | Listed 2021; short history |

## 3. Measured coverage (real database, 2026-10-08)
| Measure | Value |
|---|---|
| Stocks with any observation | 0 of 20 |
| Observations / versions / batches | 0 / 0 / 0 |
| Publication-date coverage | not measurable (no data) |
| Availability-date coverage | not measurable |
| Conflicts, restatements, quarter-sum mismatches | not measurable |
| Score inputs reconstructable point-in-time | 0 of 19 for every pilot stock |

## 4. Why the data is not collected yet
- **NSE terms forbid automated collection**: "User is prohibited to conduct any systematic or automated data
  collection activities (including scraping, data mining, data extraction and data harvesting)". No
  scraper was built. Manual downloads by you are ordinary use of the site.
- Kite Connect has no fundamentals. No figures were typed in or estimated.

## 5. Pilot data plan (final scope, 2026-10-08)
Manual downloads only. **Only original exchange filings with a known publication time are used as
historical observations.** Current or restated values from websites (e.g. Screener) are not collected
for the pilot. Take **Consolidated** results; use Standalone only if a company publishes no consolidated
results. Results for the quarter ended March 2025 onward may sit under "Integrated Filing – Financials".

Period studied: FY2023-24 and FY2024-25, i.e. quarters ended 30-Jun-2023 to 31-Mar-2025 (8 quarters).
Listings cover broadcasts from 01-Apr-2023 to today, so later filings that restate those quarters
(as comparatives) are visible too.

### Batch 1: parser and point-in-time validation (download first, then stop)
| Company | Symbol | File type | Period | NSE page/action | Required? | Why |
|---|---|---|---|---|---|---|
| Infosys | INFY | Financial results listing (CSV) | Broadcasts 01-Apr-2023 to today | Companies → Corporate Filings → Financial Results → INFY → set dates → Download (.csv); repeat under Integrated Filing – Financials | Required | Exact broadcast date/time for every result → `reported_at`, `available_at` |
| Infosys | INFY | Results XBRL (Consolidated) | Quarter ended 31-Mar-2025 (Q4 + FY2024-25 audited) | Same list → row for that period → XBRL | Required | As-reported quarter, full year, balance sheet and cash flow; contains FY2023-24 comparatives |
| Infosys | INFY | Results XBRL (Consolidated) | Quarter ended 31-Mar-2024 | Same list → XBRL | Required | Original figures to compare with the comparatives in the 2025 filing (real versioning test) |
| Infosys | INFY | Results XBRL (Consolidated) | Quarter ended 31-Dec-2024 | Same list → XBRL | Required | A normal (non-year-end) quarter layout and 45-day timing |
| Infosys | INFY | Shareholding pattern listing (CSV) | Submissions 01-Apr-2023 to today | Companies → Corporate Filings → Shareholding Pattern → INFY → Download (.csv) | Required | Shareholding publication dates |
| Infosys | INFY | Shareholding pattern XBRL | Quarter ended 31-Mar-2025 | Same page → row → XBRL | Required | Promoter, pledge, FII and DII parser |
| HDFC Bank | HDFCBANK | Results XBRL (Consolidated) | Quarter ended 31-Mar-2025 | Financial Results → HDFCBANK → XBRL | Optional | Bank results use a different format; finds mapping problems early |

Batch 1 = 6 required files (+1 optional). I write and test the readers on these, import them, and show
the point-in-time results before batch 2 is requested.

### Batch 2: complete pilot (only after batch 1 is validated)
Tier A (deep check: all 8 quarters) is INFY, HDFCBANK, ITC, TATASTEEL, BHEL. Tier B is the other 15.

| Company | Symbol | Tier | Results listing CSV (broadcasts 01-Apr-2023 → today) | Results XBRL, Consolidated | Shareholding | Minimum files | Why this stock |
|---|---|---|---|---|---|---|---|
| HDFC Bank | HDFCBANK | A | Required | 8 quarters, Jun-2023 → Mar-2025 | Listing CSV + XBRL for Mar-2024 and Mar-2025 | 12 | Bank format; HDFC Ltd merger from Jul-2023 |
| Bank of Baroda | BANKBARODA | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | PSU bank |
| Bajaj Finance | BAJFINANCE | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | NBFC format |
| SBI Life Insurance | SBILIFE | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Insurer format |
| Infosys | INFY | A | Required (batch 1) | 8 quarters (3 in batch 1) | Listing CSV + XBRL Mar-2024 and Mar-2025 | 12 | Clean reference company |
| Persistent Systems | PERSISTENT | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Mid-cap IT |
| ITC | ITC | A | Required | 8 quarters | Listing CSV + XBRL Mar-2024 and Mar-2025 | 12 | Hotels demerger changes comparatives |
| Marico | MARICO | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | FMCG |
| Maruti Suzuki | MARUTI | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Auto |
| Ashok Leyland | ASHOKLEY | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Finance subsidiary inside consolidated |
| Sun Pharma | SUNPHARMA | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Exceptional items |
| Laurus Labs | LAURUSLABS | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Mid-cap pharma |
| Reliance Industries | RELIANCE | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Large consolidated group |
| ONGC | ONGC | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | PSU; listed subsidiaries |
| Tata Steel | TATASTEEL | A | Required | 8 quarters | Listing CSV + XBRL Mar-2024 and Mar-2025 | 12 | Overseas operations, impairments |
| BHEL | BHEL | A | Required | 8 quarters | Listing CSV + XBRL Mar-2024 and Mar-2025 | 12 | PSU; weak profits; filing timing |
| UltraTech Cement | ULTRACEMCO | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Acquisitions |
| DLF | DLF | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Lumpy revenue |
| Vodafone Idea | IDEA | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Losses, negative equity |
| FSN E-Commerce (Nykaa) | NYKAA | B | Required | Mar-2024 and Mar-2025 | Listing CSV + XBRL Mar-2025 | 5 | Recent listing |

Total: Tier A 5 × 12 = 60, Tier B 15 × 5 = 75, so **135 files**, of which batch 1 covers 6. If NSE's
listing page can export all companies for a date range without choosing a company, those exports can
replace the 40 per-company listing files; check this during batch 1.

**What the pilot can and cannot validate.** Tier A tests point-in-time correctness over 8 consecutive
quarters, including two corporate events. Tier B tests format coverage and year-end figures only, so
growth and TTM metrics will be reconstructable for Tier A but not Tier B. That is intended: the pilot
validates data correctness and point-in-time logic, not signal research.

## 5a. Batch 1 progress (2026-10-08)
Received: NSE financial-results listings for INFY and HDFCBANK (broadcasts 01-Apr-2023 to 08-Oct-2026),
stored unmodified in `data/pilot/batch1/` (SHA-256 recorded at import). Reader:
`pit/adapters/nse_results_listing.py`, `pnpm pit listing FILE...` (reads only, writes nothing).

Measured from these two files (32 filings, quarters ended 31-Mar-2023 to 31-Dec-2024):
- Every filing has two exact timestamps: received by NSE and disseminated to the market. The
  dissemination time is used as `reported_at`/`available_at`; the gap is at most 6.5 minutes.
- Both bases (consolidated and standalone) exist for all 8 quarters of both companies. They can be
  published hours apart (HDFCBANK, quarter ended 31-Mar-2024: standalone 12:30, consolidated 16:02).
- Publication lag: INFY 11–20 days, HDFCBANK 16–23 days; no filing after the SEBI deadline.
- 2 of 16 INFY and 4 of 16 HDFCBANK filings were published before 15:30 on a trading day, so they are
  usable for that day's decision; HDFCBANK published three quarters on a Sunday.
- The listings stop at the quarter ended 31-Dec-2024: later results are under "Integrated Filing –
  Financials", a separate listing still to be downloaded.
- HDFCBANK files are in the banking (non-Ind-AS) taxonomy (`BANKING_*.xml`), INFY in Ind-AS (`INDAS_*.xml`).

Also received: "Integrated Filing – Financials" listings for INFY and HDFCBANK (quarters ended
31-Mar-2025 to 30-Jun-2026). Second format, read by the same tool. It adds a submission type
(Original / revised), revision time and remarks, which will drive restatement versions; all 24 rows
seen so far are Original, so the revision path is tested on synthetic rows only.

Combined, both companies have **14 consecutive quarters (31-Mar-2023 to 30-Jun-2026), each with
consolidated and standalone results, no gaps, no duplicates, no late filings**. Lag: INFY 11–23 days,
HDFCBANK 16–23 days. Consolidated and standalone were published far apart twice for HDFCBANK: 3.5 hours
(quarter ended 31-Mar-2024) and 42.4 hours (31-Mar-2025: consolidated Saturday 19-Apr 22:42, standalone
Monday 21-Apr 17:08). Per-basis availability in the store handles this. Longest gap between submission and
public dissemination: 14.6 minutes (INFY, 31-Mar-2026).

Issue found and fixed: the NSE holiday file covers only 2026, so the "first usable decision" for older
filings treated holidays as trading days (INFY's 14-Apr-2023 results). The listing tool now uses actual
NIFTY trading days from the database. Backtests, the factor study and the rule replay were not affected:
they already take trading days from the NIFTY price history.

## 5b. First XBRL filing (2026-10-09)
Received: `INTEGRATED_FILING_INDAS_1658041_23042026090203_WEB.xml`, INFY **standalone**, quarter ended
31-Mar-2026 (SEBI Integrated Filing Ind-AS taxonomy, 2026-01-31), published 23-Apr-2026 21:02 IST per the
listing. Reader: `pit/adapters/nse_xbrl.py`; `pnpm pit xbrl FILE --listings DIR` (dry run unless `--import`).

Measured on this file:
- 25 as-reported observations extracted (quarter, financial year, balance sheet at 31-Mar-2026), all
  timestamped with the listing's dissemination time; 6 of 6 consistency checks pass (income = revenue +
  other income; profit before exceptional items = income − expenses; PAT = PBT − tax; EPS × shares ≈ profit
  within 0.02%; assets = equity + liabilities; published after the board meeting ended).
- Values: quarter revenue ₹38,641 cr, net profit ₹7,975 cr, diluted EPS ₹19.65; year revenue ₹1,48,819 cr,
  net profit ₹29,211 cr, cash from operations ₹28,164 cr, capex ₹2,170 cr; equity ₹80,874 cr; borrowings 0;
  shares 405.4 cr (paid-up capital ÷ face value).
- End to end in a throwaway database: invisible to the 23-Apr-2026 decision (published after the close),
  visible from 24-Apr-2026; re-import is a no-op.

Findings that change the plan:
- **Prior-year comparatives are not tagged** in the XBRL (only opening cash). Restatements cannot be
  detected by comparing a later filing's comparatives with the original; they must come from revised
  submissions (listing "TYPE OF SUBMISSION") or from comparing sources.
- **EBITDA is not reported**; it is derived from reported lines. Both derivations agree for this filing
  (₹9,548 cr). The store keeps the ingredients (other income, profit before exceptional items), not EBITDA.
- **Dividend per share is not in the results filing**; dividend yield needs corporate-action data.
- **Consolidated profit must be the owners' share** (EPS is computed on it); the reader refuses to fall
  back to total profit for consolidated results.
- The banking taxonomy (`BANKING_*.xml`) is not read yet; it needs a sample.
- Consolidated filing of the same quarter (`INTEGRATED_FILING_INDAS_1658040_23042026090154_WEB.xml`, published
  21:01, one minute before standalone): 25 observations, 6 of 6 checks pass. Quarter revenue ₹46,402 cr,
  **net profit attributable to owners ₹8,501 cr** (total profit ₹8,509 cr; ₹8 cr minority interest), diluted
  EPS ₹20.98; year revenue ₹1,78,650 cr, owners' profit ₹29,440 cr, CFO ₹33,986 cr; equity ₹92,852 cr.
- **Share count differs by basis**: 404.8 cr consolidated vs 405.4 cr standalone (consolidated nets off
  treasury shares held by the employee trust). Per-share values must use the same basis as the figure.
- INFY quarter ended 31-Mar-2025, standalone (`..._1417992_...`, published 17-Apr-2025 23:30) and consolidated
  (`..._1417999_...`, 23:36): 25 observations each, 6 of 6 checks pass each. Consolidated: quarter revenue
  ₹40,925 cr, owners' profit ₹7,033 cr (total ₹7,038 cr); year revenue ₹1,62,990 cr, owners' profit ₹26,713 cr.
- **Cross-filing check**: the only prior-year figure the 2026 filings tag (cash at 31-Mar-2025) equals the
  original 2025 filings exactly (standalone ₹14,265 cr, consolidated ₹24,455 cr).
- Share count fell from 415.2 to 405.4 cr (standalone) and 414.6 to 404.8 cr (consolidated). The 2026
  standalone filing shows a ₹18,058 cr buyback (`PaymentsToAcquireOrRedeemEntitysShares`); the consolidated
  filing shows ₹0 on that element although its share count fell too. **The same event is tagged differently
  across bases**, so single tags should not be trusted without a cross-check.
- INFY quarter ended 31-Dec-2025, standalone and consolidated (published 14-Jan-2026 20:38): 10 observations
  each (quarter only). Nine-month year-to-date figures are skipped by design. **No balance sheet or cash
  flow in a December quarter** (published half-yearly), so the balance check is N/A, not a failure.
  Exceptional loss in the quarter: profit before exceptional items ₹10,817 cr vs PBT ₹9,671 cr (standalone).
  EPS × period-end shares is 1.7% below profit: EPS uses weighted-average shares, which exceed period-end
  shares during a buyback (implied average ~412.5 cr vs 405.4 cr at quarter end).
- Check design changed after this: accounting identities FAIL and block an import; approximations (EPS ×
  shares) only WARN; statements a filing does not contain are N/A. All six INFY filings: no FAIL, no WARN.
- **Banking format** (HDFCBANK, quarter ended 31-Mar-2025; standalone `..._1421434_...` published 21-Apr-2025
  17:08, consolidated `..._1420333_...` published 19-Apr-2025 22:42): mapped separately (revenue = total
  income; finance costs = interest expended; equity = capital + reserves; borrowings exclude deposits; no
  EBITDA or depreciation lines). 21 observations each.
  - Standalone: 9 of 9 checks pass. Quarter net profit ₹17,616.14 cr; EPS × shares ₹17,623 cr.
  - **Consolidated: tagging error in the official XBRL.** Minority interest (₹449.69 cr in the quarter,
    ₹2,647.92 cr in the year) is also tagged as "exceptional items" (−449.69 / −2,647.92), so it is deducted
    twice: tagged PBT ₹25,123.70 cr vs segment PBT ₹25,573.39 cr; tagged owners' profit ₹18,385.19 cr vs
    EPS ₹24.62 × 765.22 cr shares = ₹18,840 cr (PAT ₹18,834.88 cr). **Every addition in the file balances**:
    only the cross-checks (segment PBT, EPS) catch it. The file is held back from import (`WARN`).
  - Consequence for the design: "as reported in XBRL" is not always "correct". Cross-checks that WARN now
    hold a filing back until a person reviews it (`--accept-warnings`); identities still block outright.
    The legal PDF of the results should be the tie-breaker for held-back filings.
- HDFCBANK quarter ended 31-Dec-2025, standalone and consolidated (both published 17-Jan-2026 21:26): clean,
  8 of 8 applicable checks pass each (no balance sheet in a December quarter). The minority-interest tagging
  error **does not recur**: consolidated PAT ₹20,691.04 cr, owners' profit ₹19,806.63 cr (minority deducted
  once), EPS × shares ₹19,815 cr.
- **Bonus issue between filings**: shares 765.22 cr (31-Mar-2025) → 1,538.46 cr (31-Dec-2025), EPS roughly
  halved. The stored Kite prices are **bonus-adjusted** (no jump in Aug-2025; March–April 2025 closes ₹843–981,
  about half the pre-bonus traded price), while XBRL per-share figures are **as reported**. Consequences for
  the derived layer (not built yet):
  - valuation ratios must put price and per-share figures on the same basis (adjust as-reported EPS, DPS and
    share counts by the cumulative split/bonus factor since the filing, or un-adjust the price); otherwise a
    pre-bonus P/E comes out about half the true value;
  - per-share growth (EPS growth, CAGR) across a split or bonus is meaningless unadjusted (fake −50% here);
    growth in total net profit is unaffected;
  - this needs corporate-action data (ex-date and ratio). Share-count jumps between filings can flag
    candidates, but the ratio and ex-date must come from the corporate action itself.
- HDFCBANK quarter ended 30-Jun-2026, standalone and consolidated (both published 18-Jul-2026 16:01, a
  Saturday; usable from Monday 20-Jul): taxonomy 2026-01-31, read with the same banking mapping; 9 of 9
  applicable checks pass each (segment and EPS cross-checks included). Consolidated owners' profit
  ₹19,244.71 cr (PAT ₹20,382.69 cr). No balance sheet in a June quarter.
- HDFCBANK quarter ended 31-Mar-2026, standalone (`..._1654389_...`, published 18-Apr-2026 19:28) and
  consolidated (`..._1654391_...`, 19:30): all identities pass (including the new check that balance-sheet lines
  sum to each total); **both held back by one cross-check each**:
  - Consolidated: minority interest tagged 0 and exceptional items −₹723.46 cr; tagged PBT ₹26,948.17 cr vs
    segment PBT ₹27,671.63 cr. EPS × shares (₹20,350 cr) matches owners' profit (₹20,350.76 cr), so **owners'
    profit is right but PBT is understated** by the same mis-tagging family as 31-Mar-2025.
  - Standalone: balance-sheet cash ₹2,98,466.36 cr vs cash-flow cash ₹2,97,606.84 cr (₹859.52 cr apart,
    unexplained; the two agreed exactly a year earlier). The company notes that employee stock options
    outstanding (₹4,545.11 cr) are reported within other liabilities, so "equity" (capital + reserves)
    excludes them.
  - Correction to an earlier note in this session: a quick inspection script wrongly suggested the
    consolidated liability lines were ₹6.16 lakh crore short of the total. The script let a breakdown
    (typed-dimension) value overwrite the total; the filing is consistent and the reader handles it correctly.
- HDFCBANK quarter ended 30-Sep-2025, consolidated (`..._1553886_...`, published 18-Oct-2025 20:23; found in
  the download folder): held back, segment PBT ₹26,658.89 cr vs tagged PBT ₹25,905.79 cr (₹753 cr apart), the
  same pattern. HDFCBANK consolidated: Mar-25, Sep-25 and Mar-26 warn; Dec-25 and Jun-26 are clean.
- **File validation (2026-10-09)**: every received XBRL matches its listing row on symbol, basis and period
  end (read from inside the file); no wrong-quarter files; pilot copies are byte-identical to the downloads.
  Re-downloads with "(1)/(2)" suffixes are identical, except one pair 2 bytes apart with **identical facts**
  (formatting only), so file identity should be checked on facts, not bytes.
- **Old format (pre-2025)**: INFY quarter ended 31-Dec-2024 from the "Financial Results" page,
  consolidated `INDAS_117292_...` and standalone `INDAS_117294_...` (published 16-Jan-2025 19:40 / 19:42;
  Ind-AS 2020 taxonomy, namespace in-bse-fin). Same element names as the new format, but **the nine-month
  year-to-date context carries the quarter's dates in its header** (1-Oct to 31-Dec) while the filing's own
  stated period says 1-Apr to 31-Dec. The reader now uses the stated period, notes the disagreement and
  skips the nine-month figures. Both files: all applicable checks pass. Consolidated quarter revenue
  ₹41,764 cr, owners' profit ₹6,806 cr (total ₹6,822 cr); standalone revenue ₹34,915 cr, profit ₹6,358 cr.
- **Old banking format**: HDFCBANK quarter ended 31-Dec-2024, standalone `BANKING_117524_...` and consolidated
  `BANKING_117525_...` (banking taxonomy 2019-09-30; published 23-Jan-2025 12:26 / 12:28). Read unchanged by the
  banking mapping; same mislabelled nine-month context, corrected. All applicable checks pass. Standalone
  quarter profit ₹16,735.50 cr; consolidated owners' profit ₹17,656.61 cr (PAT ₹18,340.11 cr).
- **XBRL time can lag the real announcement**: the board meeting ended 22-Jan-2025 but the XBRL was
  disseminated on 23-Jan at 12:26; the results themselves were most likely announced (as a PDF) on 22-Jan.
  Using the XBRL dissemination time is therefore conservative: figures may be used slightly late, never
  before they were public. Getting the earlier announcement time would need the corporate-announcements
  listing; not required for point-in-time safety.
- HDFCBANK quarter ended 31-Dec-2023, standalone `BANKING_101078_...` and consolidated `BANKING_101079_...`
  (published 16-Jan-2024 17:14 / 17:16, after the July-2023 HDFC Ltd merger): clean; same nine-month header
  correction. Standalone quarter profit ₹16,372.54 cr; consolidated owners' profit ₹17,257.87 cr (PAT
  ₹17,718.00 cr). Shares 759.25 cr → 764.83 cr a year later (stock options) → 1,538 cr after the 2025 bonus.
- Tally so far: 21 real filings across both NSE formats (old 2019/2020 taxonomies; integrated 2025 and 2026
  taxonomies) and both accounting formats (Ind-AS, banking): INFY Dec-24, Mar-25, Dec-25, Mar-26 and HDFCBANK
  Dec-23, Dec-24, Mar-25, Dec-25, Mar-26, Jun-26 (both bases each), plus HDFCBANK Sep-25 consolidated. 17 clean,
  4 held back (HDFCBANK consolidated Mar-25, Sep-25, Mar-26; standalone Mar-26).
- Not yet imported into the real database (dry run only).

## 5c. Shareholding pattern (2026-10-09)
Received: `SHP_1652323_16042026045034_WEB.xml` and `SHP_1693581_15072026065242_WEB.xml`, INFY as on
31-Mar-2026 and 30-Jun-2026 (taxonomy in-bse-shp-2025-10-31). Reader: `pit/adapters/nse_shp.py`;
`pnpm pit shp FILE...` (read-only).
- Holdings are tagged per shareholder category (dimension). Percentages are fractions (0.1438 = 14.38%).
- 31-Mar-2026: promoters 14.38%, foreign institutions 28.45%, domestic institutions 43.38%, non-institutions
  13.53%; total 404.83 cr shares (matches the 404.8 cr in the consolidated results of the same date).
  30-Jun-2026: promoters 13.82%, foreign 27.09%, domestic 42.96%; 404.13 cr shares.
- Promoter pledge: the filing states "no shares pledged" as a yes/no fact, stored as 0%. A filing with
  pledges has not been seen, so "true" is held back with a warning.
- Both identities pass exactly in both files (promoter + public + non-promoter non-public = total;
  public = foreign + domestic institutions + government + non-institutions).
- Percentages are on the regulatory (SCRR) basis, which leaves out shares such as those underlying ADRs
  (INFY: about 30.5 cr held by the depository); promoter shares / total shares gives 13.33%, not the filed
  14.38%. Percentages are stored as filed, not recomputed.
- Six older files received (INFY as on 31-Mar-2023 to 30-Jun-2024; taxonomy in-bse-shp-2022-09-30). The older
  format differs: company-level facts point to contexts not defined in the file (invalid XBRL, read as
  company-level text with a note), percentages are in percent not fractions (detected from the total row),
  the pledge question is "pledged or otherwise encumbered", the government category is spelt "Goverments",
  and the symbol is in the context identifier. After generalising the reader, all files pass both
  identities exactly (11 quarters by 2026-10-09: Mar-23 to Mar-25, Mar-26, Jun-26). Promoters 15.14% (Mar-23) → 14.61% (Jun-24) → 13.82% (Jun-26); foreign institutions
  35.08% → 32.74% → 27.09%; domestic institutions 33.84% → 37.56% → 42.96%; no pledges in any quarter.
- Complete INFY series received: **15 filings, 14 quarter-ends Mar-23 to Jun-26 plus one event filing**, across
  three taxonomy versions (2022-09-30, 2025-05-31, 2025-10-31); all pass both identities.
- **Event-driven filing**: `SHP_1584868_11122025040253_WEB.xml`, as on **04-Dec-2025** (not a quarter end), filed
  11-Dec-2025 after the buyback: shares 414.57 cr (30-Sep-2025) → 403.87 cr, about 10.7 cr cancelled. This
  agrees with the ₹18,058 cr buyback in the 31-Mar-2026 results (≈ ₹1,690 per share). Shareholding snapshots
  can therefore fall on any date, not only quarter ends; the model's INSTANT period handles that.
- Some text fields (TypeOfReport, ShareholdingPatternFiledUnder) are masked as "******" in the public files.
- **Publication times**: the shareholding listing `CF-Shareholding-Pattern-equities-INFY-01-04-2023-to-09-10-2026.csv`
  (received 2026-10-09; reader `pit/adapters/nse_shp_listing.py`) lists all 15 filings with submission and
  dissemination times. It has no symbol column (taken from the file name). It confirms the file-name times
  are a 12-hour clock without AM/PM (`..._16042026045034_...` was published 16-Apr-2026 16:50).
- Every XBRL matched its listing row; as-on dates agree; **the listing's promoter % equals the XBRL's in all 15**.
  Publication 7–21 days after the as-on date (SEBI deadline 21 days). All 15 ready to import (dry run).

## 6. Fields expected to be hard to reconstruct point-in-time (to verify in the pilot)
These are expectations from how Indian filings work, not measurements.
- **Any value from a "currently displayed" source** around mergers, demergers and accounting changes
  (HDFCBANK 2023, ITC 2025): today's figures are restated; the as-reported ones differ.
- **EBITDA**: not a line item in Ind-AS results; it must be derived (revenue − expenses excluding D&A and
  finance costs), and vendors define it differently. Not defined for banks and insurers.
- **Balance sheet and cash flow**: published half-yearly (with Q2 and Q4), so between them only older values exist.
- **Shares outstanding** between filings after splits and bonuses: needs corporate-action data.
- **Exact broadcast times for older periods**: availability in NSE listings for early years is unverified.
- **Bank and insurer mappings**: revenue, EBITDA and interest coverage need sector-specific definitions.

## 7. Production provider evaluation (provisional; decide after the pilot)
| Option | History | NSE coverage | Quarterly / annual / cash flow / shareholding | Publication dates | As-reported values | Cost | Licence / access | Reproducibility |
|---|---|---|---|---|---|---|---|---|
| NSE filings, manual | Many years of filings | Complete | Yes (results XBRL, shareholding filings) | **Exact broadcast time** | **Yes** (original XBRL) | Free | Manual use only; automation prohibited | High (immutable filings) but labour-heavy |
| NSE Corporate Data subscription | Not stated | Complete | Fundamentals, announcements, shareholding | Exact (exchange source) | Yes | **₹10.6 lakh/yr** (Corporate Data, via leased line) or **₹5 lakh/yr** (end-of-day corporate announcements, SFTP); NSE page updated 11/06/2026 | Licensed | High |
| CMIE Prowess | From 1990 | Very wide (100k+ companies) | Yes, incl. shareholding | Not confirmed | "Trace-back to original values" claimed | Institutional pricing, not public | Subscription | Likely high; unverified |
| EODHD | Not confirmed for India | Not confirmed for NSE | Income, balance sheet, cash flow | API has a `filing_date` field (seen for US data); NSE population unverified | Unknown | About $60/month (earlier research) | Commercial API | Unknown; needs a trial on RELIANCE.NSE |
| Screener.in Premium | ~10 years annual, recent quarters | Wide | Yes | **None** | **No**: current, restated figures | ₹4,999/yr (earlier research) | Export is the sanctioned route; terms allow personal, non-commercial use | Low (figures change over time) |
| TrueData | Unknown | NSE vendor | No fundamentals API documented | Unknown | Unknown | Ask | Commercial | Unknown |

**Provisional recommendation.** NSE's licensed feed is the cleanest but costs about ten times the
capital being invested. For a personal system the realistic production route is a **hybrid**: exact
publication dates from NSE result listings (manual, a few files per quarter), values from one commercial
source, and an as-reported check on a sample from NSE XBRL each quarter. Whether commercial values can be
trusted for point-in-time research needs a separate comparison against these as-reported filings later;
the pilot itself uses only original filings with known publication times. If the drift
is limited to known corporate events, those periods can be excluded; if it is widespread, only as-reported
values (NSE XBRL, or Prowess if affordable) are acceptable. No provider should be bought before that result.

## 8. Tests (all passing, 2026-10-08)
`tests/test_pit_fundamentals.py`, 25 tests: the FY2025 scenario (invisible on 2025-04-15, and on
2025-05-15 when broadcast after the close; visible 2025-05-16 and 2025-05-20); date-only publication
usable the next day; estimated and unknown dates excluded by default; currently-displayed values excluded
by default; database rejects UPDATE, DELETE and TRUNCATE; idempotent re-import; corrections versus
restatements; restatement visible only after its publication, including when stored before the original;
`known_by` reconstruction; sources and bases kept apart and reported as conflicts; quarter-by-quarter
historical reconstruction with intraday broadcast times; quarter-sum checks; validation errors with row
numbers; blank values treated as absent; duplicates within a file.

Sources: [NSE terms of use](https://www.nseindia.com/static/nse-terms-of-use),
[NSE corporate data subscription](https://www.nseindia.com/static/market-data/corporate-data-subscription),
[CMIE Prowess user guide](https://library.iimsambalpur.ac.in/uploads/usermanuals/20260416213349_b4e05304_CMIE_Prowess_on_Web_User_Guide-compressed.pdf),
[eodhdR2 README (EODHD fields)](https://cran.ma.imperial.ac.uk/web/packages/eodhdR2/readme/README.html),
[Screener export help](https://support.screener.in/article/28-export-screen-results),
[Screener terms](https://www.screener.in/guides/terms), [TrueData](https://www.truedata.in/about_us).
