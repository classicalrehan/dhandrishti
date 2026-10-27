# DhanDrishti: development status and next steps (started 2026-10-12, updated 2026-10-27)

**Single source of truth.** Section 1 is the current, verified state (checked against the databases and repository on
2026-10-15). Later sections are a dated log; where an older line conflicts with section 1, section 1 wins.
Supporting detail: `2026-10-12-recommendation-tracking-implementation-review.md`,
`2026-10-12-recommendation-tracking-final-review.md`, `2026-10-fundamentals-pilot.md`,
`2026-10-fundamentals-validation.md`. Designs: `docs/recommendation-tracking.md`, `docs/fundamentals-quality-design.md`.

## 1. Current state (verified 2026-10-15)
- **Fundamentals pilot** (`dd_dev_fundamentals`, staged 0009 applied there only): **8 of 20 companies imported**,
  124 filings, 1,780 filed values: **58 verified, 4 mismatched** (replaced by 4 official figures), **17 hidden**, the
  rest unverified. Not connected to scoring.
  | Company | Quarters Jun-2024..Mar-2026 | Bases |
  |---|---|---|
  | INFY, HDFCBANK, ICICIBANK, WIPRO, DRREDDY | 8/8 | consolidated and standalone |
  | BANKBARODA | 5/8 (Mar-2025..Mar-2026) | both |
  | BAJFINANCE | 5/8 consolidated, 4/8 standalone | both |
  | SBILIFE | 4/8 standalone (Dec-2025 file not yet downloaded) | standalone only (no consolidated results) |
  Not imported: PERSISTENT, LAURUSLABS, ITC, MARUTI, ASHOKLEY, RELIANCE, ONGC, TATASTEEL, BHEL, ULTRACEMCO, DLF, IDEA
  (12; all Ind-AS, readers exist). Every reporting format (Ind-AS, banking, NBFC, life insurance) has a reader.
- **Strategy research:** the entry-signal study (section 3h) found **no edge** for pullback, breakout or continuation
  entries over owning the same universe. All price studies are dominated by **survivorship bias** (today's NIFTY 200
  used for the past).
- **Survivorship (section 9):** official NSE Indices change notices exist from Aug-2015 to 2026, but **their contents
  could not be verified here** (automated access to niftyindices.com times out), and nothing was found for 2013–2014.
  No parser or point-in-time universe was built; no study was re-run.
- **Recommendation tracking:** operational in `dd_dev_tracking` only (staged 0010); no LIVE runs (uncommitted tree).
- **Production:** `dhandrishti_kite` and `dhandrishti` have no 0009/0010; scoring weights, paper portfolios and
  order capability unchanged by this work. All work since `7dc55ff` is uncommitted.

## 2. Databases
| Database | Purpose | Migrations | Changed by this work? |
|---|---|---|---|
| `dhandrishti_kite` | real Kite data, paper portfolios, holdings | 0001–0008 | no (read-only checks; your daily pipeline ran at 17:34/17:46) |
| `dhandrishti` | MOCK data, default for `pnpm dev` | 0001–0005 | no |
| `dd_dev_tracking` | recommendation tracking (copy of Kite data, 12 Oct) | 0001–0008 + 0010 | not since its creation |
| `dd_dev_fundamentals` | fundamentals pilot (securities from the repo's NSE index files; no production data) | 0001–0008 + 0009 | yes: imports, verifications, flags |

## 3. Fundamentals pilot
### 3a. What exists now
Before today: readers for Ind-AS, banking and shareholding XBRL (old and new formats), listing parsers with exact NSE
broadcast times, the append-only point-in-time store, the staged 0009 controls, 36 pilot files.
Added today:
| Item | Purpose |
|---|---|
| `docs/research/reference/2026-10-official-documents.csv` (6 SEC 6-K documents) and `2026-10-official-values.csv` (62 values) | Versioned official reference register (52 values checked on 9 Oct, recovered from that session's comparison script, plus 10 official figures for the 4 held-back HDFC filings). Two HDFC EPS figures were left out: basic vs diluted was not recorded |
| `pit/pilot_validation.py` | Import pilot files through the 0009 controls (oldest publication first); apply the register (one verification per stored version; a mismatch stores the official figure as source `official document`, usable the day after the document date); coverage; restatement look-ahead check; **YT-2** quarter-sum check; **readiness** (YoY/TTM support). dd_* databases only; no dispositions recorded |
| `jobs/pit_pilot.py` | CLI: `setup`, `import`, `verify` (register + YT-2), `report`, `readiness` |
| `pit/adapters/nse_xbrl.py` (reader fix) | An element filed twice with **different** values for the same period is no longer fatal for the whole import: it is not used at all and the filing gets a NOTE (MS-1). Identical duplicates still accepted |
| Tests | `test_pit_pilot.py` (17), `test_nse_xbrl.py` (+1); `test_quality_controls.py` now pins the 17 results files of the 9 Oct production import (it previously took "everything in the folder" and broke when files were added) |

### 3b. Imports and validation (verified, `dd_dev_fundamentals`)
The 15 files missing from the 8-quarter window were downloaded manually from NSE by you, copied from `~/Downloads`
into `data/pilot/batch1-xbrl/` (originals left in place) and imported:
| Delivery | Files | Values | Flags |
|---|---|---|---|
| INFY Jun-24, Sep-24 (both bases; old 2020 format) | 4 | 10+10+25+25 | Sep files: 2 NOTE each (corrected period header; ambiguous cash element) |
| HDFCBANK Jun-24, Sep-24 (both bases; old format) | 4 | 8+8+20+20 | Sep files: 2 NOTE each (same) |
| HDFCBANK Jun-25 (both bases) | 2 | 8+8 | none |
| INFY Jun-25 (both bases) | 2 | 10+10 | none |
| HDFCBANK Sep-25 standalone | 1 | 21 | none (your second download of the Sep-25 consolidated file was byte-identical to the stored one and was not re-imported) |
| INFY Sep-25 (both bases) | 2 | 25+25 | none |
- Broadcast times are taken from the listing CSVs (8 Oct) and stored to the second; the NSE web page showed HDFC
  Jun-25 times one second earlier (18:51:50 / 18:46:45 vs 18:51:51 / 18:46:46 in the CSV).
- **Filer error found in all four Sep-2024 files:** `CashAndCashEquivalentsCashFlowStatement` is tagged twice in the
  half-year context (opening and closing cash: INFY standalone 8,191 / 13,917, consolidated 14,786 / 21,799; HDFCBANK
  standalone 2,19,147 / 2,56,340, consolidated 2,28,835 / 2,66,385). The element is now unused; no stored metric
  depends on it (INFY cash is the balance-sheet instant; bank cash is the sum of two balance-sheet lines).
- Re-import: 0 new, 51 already recorded. Restatements: none (NSE XBRL does not tag comparative columns).

Totals now: **INFY 31 filings, 340 values (25 verified, 315 unverified, 0 hidden). HDFCBANK 20 filings, 262 values
(33 verified, 4 mismatched, 225 unverified, 10 hidden), 4 official replacements.** No new values could be checked
against the register: it has no references for the new quarters. "Unverified" means not compared with an official
document; it does not mean wrong.

**YT-2 (Q1+Q2+Q3+Q4 = filed full year, tolerance Rs 1 cr or 0.5%; REVIEW on the FY value), from the design
catalogue, now implemented.** Using trusted quarterly values only (official figures where the filed value is
hidden), 3 full-year values failed and are now hidden:
| Value (HDFCBANK consolidated) | Filed FY | Sum of quarters | Difference |
|---|---:|---:|---:|
| Profit before tax FY2024-25 | 93,594.13 | 95,440.52 | +1.97% |
| Owners' profit FY2024-25 | 68,144.33 | 70,792.25 | +3.89% |
| Profit before tax FY2025-26 | 98,947.96 | 102,141.45 | +3.23% |
All three come from the two year-end filings with the known minority-interest tagging error; the quarterly checks
hid only quarterly values, so these full-year figures had been usable. **Assumption, not verified:** the cause is
the same tagging error; no official full-year consolidated figures are in the register. FY2025-26 owners' profit
passes. Every other full-year value of both companies (revenue, PBT, profit, EPS; both bases) matches its quarters.

### 3c. Readiness: what the trusted data supports (analysis only; not connected to scoring)
Trusted = latest usable filed value, or the official figure where the filed value is hidden or mismatched; hidden
values are never used. A figure is computed only when every input exists; growth needs a positive base; per-share
figures are not compared across a change in implied share count (profit ÷ EPS, tolerance 5%).
| Company, basis | Revenue, PBT, owners' profit | EPS (basic) |
|---|---|---|
| INFY consolidated | 8/8 quarters; YoY for 4 quarters (Jun-25..Mar-26); TTM at 5 quarter-ends; TTM YoY at Mar-26 | same (8/8, YoY 4, TTM 5, TTM YoY) |
| INFY standalone | same | same |
| HDFCBANK standalone | same | 8/8, but the 2025 bonus issue doubles the share base: YoY only for Jun-25; TTM only at Mar-25 and Jun-25; no TTM YoY |
| HDFCBANK consolidated | same; PBT uses 3 official quarterly figures, profit uses 1; full-year cross-check only where the FY value is not hidden | 7/8 (Mar-25 hidden, no official basic EPS): YoY Jun-25 only, no TTM |
Example values (descriptive only, mostly unverified inputs): TTM revenue growth to Mar-26: INFY consolidated
+9.61%, standalone +8.95%; HDFCBANK consolidated +5.21%, standalone +6.91%. TTM owners' profit growth: INFY cons.
+10.21%, HDFCBANK cons. +7.39%. Not computed: TTM YoY before Mar-26 (needs 8 quarters ending there), anything
across the HDFC bonus for per-share figures, and anything using a hidden value.

### 3d. Final pilot universe (decided 2026-10-12)
The design list (`docs/fundamentals-quality-design.md` §6), now recorded in `apps/worker/src/dhandrishti/pit/pilot.py`
(used only by the pilot report commands; scoring and the production universe are untouched):
| Format | Companies |
|---|---|
| Bank | HDFCBANK, ICICIBANK, BANKBARODA |
| NBFC | BAJFINANCE |
| Insurance | SBILIFE |
| Ind-AS commercial | INFY, WIPRO, PERSISTENT, DRREDDY, LAURUSLABS, ITC, MARUTI, ASHOKLEY, RELIANCE, ONGC, TATASTEEL, BHEL, ULTRACEMCO, DLF, IDEA |
Rationale: every reporting format, at least 10 sectors, PSU and private, known corporate events, and **five SEC
filers** (HDFCBANK, ICICIBANK, INFY, WIPRO, DRREDDY) whose figures can be checked through a channel independent of
NSE XBRL. Removed: SUNPHARMA (pharma covered by DRREDDY, verifiable), MARICO (FMCG covered by ITC), NYKAA (recent
listing; can return as a 21st company). Checked in the repository: all 20 are in the NIFTY 200 universe and in
`dd_dev_fundamentals.securities`. One concrete gap, not a reason to change the list: the readers support only the
Ind-AS and banking XBRL formats, so SBILIFE (insurance) needs a new mapping and BAJFINANCE may file in an NBFC format.

### 3e. Verification approach (decided; documents not yet obtained)
Options considered:
| Option | Coverage | Exactness | Verdict |
|---|---|---|---|
| Internal consistency (quarters vs full year, YT-2) | all values | proves additivity only, not correctness | kept as a control; **never counted as verification** |
| SEC 6-K exhibits (as for documents A–F) | 5 of 20 companies | read through a web-fetch summary last time | kept as independent cross-check for SEC filers |
| **Signed results statements, saved manually and read locally** | all 20 companies, both bases in one document | exact text (`pdftotext -layout` is installed; HTML read as text); no summariser | **chosen** |
Why it is the smallest practical step: each quarterly results statement shows the current quarter, the preceding
quarter and the **same quarter of the previous year**; year-end statements add the full year and the balance sheet.
So the **four FY2025-26 releases per company verify, in principle, all eight quarters** (current columns for
Jun-25..Mar-26, comparative columns for Jun-24..Mar-25). 8 documents could cover most of the 540 unverified INFY and
HDFCBANK values (shareholding percentages excepted). Values are typed into the existing register CSV with document,
date and locator, then `pit_pilot verify` applies them; nothing is marked verified without an exact match.
Rules to apply when the documents arrive (not yet implemented, because no comparative column has been entered):
a comparative column is dated by its own (later) document; a comparative that differs from the originally filed
value is recorded as MISMATCH (which already excludes it from trusted values) but **does not** create an official
replacement, because the difference may be a later regrouping rather than an error.

Documents needed (manual download; NSE → Companies → Corporate Filings → Announcements, or the **Details** link on the
Integrated Filing – Financials page; the signed results PDF attached to the board-meeting outcome on these dates):
| Company | Quarter released | NSE broadcast date | Columns it should verify |
|---|---|---|---|
| INFY | Jun-2025 | 23-Jul-2025 | Jun-25, Mar-25, Jun-24 (both bases) |
| INFY | Sep-2025 | 16-Oct-2025 | Sep-25, Jun-25, Sep-24, H1; balance sheet 30-Sep-25 |
| INFY | Dec-2025 | 14-Jan-2026 | Dec-25, Sep-25, Dec-24 |
| INFY | Mar-2026 | 23-Apr-2026 | Mar-26, Dec-25, Mar-25, FY26, FY25; balance sheets; cash flow |
| HDFCBANK | Jun-2025 | 19-Jul-2025 | Jun-25, Mar-25, Jun-24 (both bases) |
| HDFCBANK | Sep-2025 | 18-Oct-2025 | Sep-25, Jun-25, Sep-24, H1; balance sheet 30-Sep-25 |
| HDFCBANK | Dec-2025 | 17-Jan-2026 | Dec-25, Sep-25, Dec-24 |
| HDFCBANK | Mar-2026 | 18-Apr-2026 | Mar-26, Dec-25, Mar-25, FY26, FY25; balance sheets |
Alternative for these two companies: the matching SEC 6-K exhibits (EDGAR, Infosys CIK 0001067491, HDFC Bank CIK
0001144967, Form 6-K filed on or just after the dates above), saved from the browser as HTML. Documents C, E and F in
the register are three of these releases; local copies would let every column be read exactly.

### 3f. Tranche 1 onboarded: ICICIBANK, WIPRO, DRREDDY (2026-10-14, verified in `dd_dev_fundamentals`)
All files downloaded manually by you, collected with `pit_pilot collect`, imported through the 0009 controls with NSE
broadcast times preserved; re-import adds nothing (101 filings recorded in total).
| Company | Filings | Values | Quarters Jun-24..Mar-26 | Findings |
|---|---:|---:|---|---|
| ICICIBANK | 18 (incl. Jun-2026) | 246 | 8/8 both bases | all checks pass, incl. the minority-interest checks; every full year equals its quarters |
| WIPRO | 16 | 280 | 8/8 both bases | full years consistent; implied share base changed (1:1 bonus, Dec-2024), so per-share YoY/TTM across it refused |
| DRREDDY | 16 | 279 | 8/8 both bases | **YT-2 hid FY2024-25 other income** (consolidated 1,097.30 filed vs 1,167.00 sum of quarters; standalone 1,003.40 vs 1,075.20; probably an annual reclassification, not verified); **Jun-2024 consolidated owners' profit not tagged by the filer** (MS-1 note; total profit 1,392.40 exists but is not substituted), so consolidated profit YoY Jun-25 and TTM to Jun-25 are refused; share split in 2024 detected, per-share comparisons across it refused; TTM PBT down ~30% consolidated / ~41% standalone (unverified; check against an official document before use) |
All values of these three companies are **unverified** (no official references yet; all three file 6-Ks).
Sep-2024 filings of all three carry the usual notes (corrected period header; ambiguous cash-flow cash element).

Pilot totals as of 14 Oct: **5 of 20 companies complete** (INFY, HDFCBANK, ICICIBANK, WIPRO, DRREDDY), 8 quarters on both bases;
1,407 values, 58 verified, 4 mismatched (replaced by official figures), 12 hidden.
Formats of the remaining 15 (from their listings): 12 Ind-AS, 1 banking (BANKBARODA), **BAJFINANCE = NBFC** and
**SBILIFE = life insurance (LI)**; the readers support neither yet (mapping to build from their files).

### 3g. Format coverage completed: BANKBARODA, BAJFINANCE, SBILIFE (2026-10-15)
Plan change (your decision): stop expanding the pilot quarter by quarter; one company per remaining reporting format,
last 5 quarters; then the 200-stock universe with annual results only (March 2025 and March 2026, consolidated).
| Company | Format | Filings / values | Result |
|---|---|---|---|
| BANKBARODA | banking (PSU) | 10 / 158, 5 quarters both bases | Mar-2026 consolidated: **EPS × shares = 5,809 vs owners' profit 5,648 (2.8%)**: MI-3 REVIEW hides that quarter's net profit and EPS (cause unknown without the official statement) |
| BAJFINANCE | **NBFC (new reader mapping)** | 9 / 165, consolidated 5, standalone 4 | all Ind-AS identities pass; **YT-2 hid FY2025-26 revenue** (consolidated 81,982.38 filed vs 82,522.46 sum of quarters; standalone 69,850.79 vs 70,378.97, about 0.7%) |
| SBILIFE | **life insurance (new reader mapping)** | 4 / 50 standalone (Dec-2025 not yet downloaded) | all checks pass |
Reader changes (`pit/adapters/nse_xbrl.py`, `pit/controls.py`):
- NBFC: the Ind-AS elements; borrowings = debt securities + borrowings + subordinated liabilities (public deposits
  excluded, as for banks; recorded as a mapping note).
- Life insurance: revenue = net premium income (investment income excluded); net profit = profit after tax; one
  basic-and-diluted EPS; equity = shareholders' funds; total assets = application of funds. Checks (BLOCK on
  failure): PAT = PBT − shareholders' taxes, sources = application of funds (both held in all 4 SBILIFE filings),
  publication after the board meeting. Shares outstanding is not derived (no face value filed).
- `import` now reports and skips a file the reader refuses (e.g. an unmapped format) instead of aborting.
Tests: `test_nse_xbrl.py` (+NBFC, +life insurer incl. a broken filing that must BLOCK), `test_pit_pilot.py` fixture
registers all pilot companies; reader + pilot + quality tests **65 passed**.
Note for downloads: NSE's page filters on the **broadcast** time; the checklist showed SBILIFE Dec-2025 on its
dissemination date (29-Jan) while it was broadcast 28-Jan-2026 22:02.

Pilot status (corrected 2026-10-15): 8 companies imported (INFY, HDFCBANK, ICICIBANK, WIPRO, DRREDDY with 8 quarters; BANKBARODA, BAJFINANCE,
SBILIFE with 4–5); every reporting format now has a reader. 12 Ind-AS companies remain (PERSISTENT, LAURUSLABS, ITC,
MARUTI, ASHOKLEY, RELIANCE, ONGC, TATASTEEL, BHEL, ULTRACEMCO, DLF, IDEA); under the new plan they are covered by the
universe-wide annual step.

### 3h. Entry-signal study: first increment toward an Entry & Exit Engine (2026-10-15)
**State inspected (verified in code and databases, not from earlier summaries):**
- Fundamentals (`dd_dev_fundamentals`): 8 companies imported, 124 filings, 1,780 filed values: 58 verified, 4
  mismatched (replaced by official figures), 17 hidden, the rest unverified. Complete 8 quarters, both bases: INFY,
  HDFCBANK, ICICIBANK, WIPRO, DRREDDY. 4–5 recent quarters: BANKBARODA, BAJFINANCE (+ standalone), SBILIFE
  (standalone; Dec-2025 file pending). Not onboarded: 12 Ind-AS companies. Not connected to scoring.
- Recommendation tracking (`dd_dev_tracking`, 0010 applied there only): 7 runs recorded, each with config hash, code
  commit, input manifest and output hash; earlier verification reproduced every run from current inputs. Not in
  production; no LIVE runs (uncommitted tree).
- Backtest/replay realism: signal at the close, trade at the next open; costs 15/13.5 bps per side incl. ~3 bps
  slippage (backtester) or Zerodha charges with whole shares (paper replay); universe = today's NIFTY 200 for all
  past dates (**survivorship bias**); price returns only (**dividends excluded**). **Corporate actions: Kite candles
  are back-adjusted for splits and bonuses** (checked on DRREDDY's 2024 split and WIPRO's Dec-2024 bonus: no
  discontinuity), but 20 one-day moves above 35% remain in 14 stocks (demergers or unadjusted events).
- Reusable for an Entry & Exit Engine: `indicators.py` (SMA/EMA/RSI/ATR/ADX/Bollinger, all trailing),
  `MarketHistory`/`load_history`, the next-open execution convention, `research/factors.py` (costs, Newey-West),
  `research/replay.py` + `trading/paper.py` (stops, trailing stops, kill switch, whole-share fills) for a later
  portfolio-level test.

**Implemented (research only, isolated):** `apps/worker/src/dhandrishti/research/entry_signals.py`,
`apps/worker/src/dhandrishti/jobs/entry_study.py`, `apps/worker/tests/test_entry_signals.py` (5 tests). It reads prices
in a READ ONLY session from `dd_dev_tracking` by default; no scoring, paper, Kite-database, migration or order code
changed. Three pre-specified rules (no fitting): **pullback** (uptrend and RSI(14) crosses below 40), **breakout**
(close above the previous 55-session high with volume ≥ 1.5× its 20-day average, above SMA200), **continuation**
(uptrend and close crosses back above SMA20); 20-session cooldown per stock; 252 sessions of history required. Entry
at the next open, exit at the open after 5/20/60 sessions; base costs plus a +10 bps/side stress; control = the
equal-weight return of every stock trading over the same dates (excluding suspect windows); statistics clustered by
signal date with Newey-West t; results per period 2013–18, 2019–22, 2023–26; pre-registered verdict: an edge needs
positive excess with t ≥ 2 in both later periods.

**Result (201 stocks, prices to 2026-10-12): no strategy shows an edge.** All nine strategy × horizon verdicts:
NO DEMONSTRATED EDGE.
| Strategy (60 sessions) | Events | Net after costs | Excess vs universe (t) | 2013–18 | 2019–22 | 2023–26 |
|---|---:|---:|---:|---:|---:|---:|
| breakout | 6,882 | +6.14% | +0.53% (1.7) | +0.68% | +0.58% | +0.27% |
| continuation | 9,087 | +5.66% | +0.36% (1.0) | +0.68% | +0.57% | −0.37% |
| pullback | 4,333 | +5.81% | −0.12% (−0.3) | +0.27% | −0.09% | −0.73% |
The large positive net returns (and +3–5% vs NIFTY) are the universe's own drift, inflated by survivorship; the
timing rules add essentially nothing over owning the same stocks. Excluded windows: 24 with suspect jumps, 197 with
missing prices, 490 beyond the data. Full tables: run `uv run python -m dhandrishti.jobs.entry_study`.

Validation requirements (step 3): point-in-time ✓ (tested: adding future bars changes no past signal); costs and
slippage ✓ (base + stress); corporate actions: splits/bonuses adjusted ✓, dividends ✗, 35%-jump windows excluded;
out-of-sample: fixed rules reported per period ✓, no walk-forward fitting needed because nothing was fitted;
benchmarks ✓ (same-date universe, NIFTY); **survivorship ✗** (historical membership not available); **position sizing
and portfolio risk ✗** (event study, not a portfolio; next step would use `research/replay.py`).

## 4. Tests (actual results, final run after the last code change)
| Run | Result |
|---|---|
| Full worker suite with a test database | **327 passed, 0 failed, 0 skipped** (16 min) |
| `npx turbo run typecheck test` | **14/14 tasks successful** |
| **Final, 2026-10-15** (after the NBFC/life-insurance readers and the entry-signal study): full worker suite with a test database | **337 passed, 0 failed, 0 skipped**; `npx turbo run typecheck test` **14/14** |
| `tests/test_entry_signals.py` (new) | 5 passed: signals unchanged when future bars are added; breakout/continuation/cooldown on hand-built prices; next-open entry, costs, stress cost, same-date control (suspect windows excluded), NIFTY excess, MAE; suspect-jump and beyond-data exclusions; date-clustered summary and pre-registered verdicts |
| After `collect`/`todo` and the reader fixes (revision rows with blank broadcast; repeat-download file names): `test_pit_pilot.py` + `test_nse_listing.py` | **31 passed** (full suite last run before these changes: 327 passed) |
| After finalizing `pit/pilot.py` (list change only): `test_pit_pilot.py` + `test_pit_fundamentals.py` | **42 passed** (full suite not re-run for this data-only change) |
| `tests/test_pit_pilot.py` | 17 passed (register, guards, official values dated after the document, coverage, revised filing never visible early, real pilot files, YT-2 hides/needs four quarters/idempotent, readiness refusals: missing input, non-positive base, share-base change) |
| **2026-10-26** (after the revocation/rename/size-change handling in `index_membership.py`): full worker suite with a test database | **345 passed, 0 failed, 0 skipped** (11 min); turbo not re-run (worker-only change) |
| API/Redis integration tests, `ruff` | not run (API unchanged; ruff not installed) |
Failures during the work, all fixed and re-run: the duplicate-element import abort (reader fix above); three tests
that assumed a fixed set of pilot files; my own new tests (period start and publication date missing in synthetic
data; a SQL `DISTINCT ON` parameter mismatch in the readiness query).

## 5. Production safety (verified)
- `dhandrishti_kite`: 0001–0008 only; no 0009/0010 tables; `fundamental_observations` 285 rows with the same content
  and row-version hashes as the Phase 1 baseline. Fingerprint after this work is **identical** to the one taken
  right after your 17:34/17:46 `daily:kite` runs (29/29 fields, including row versions). Those runs, not this work,
  changed prices, scores, paper portfolios (now processed to 2026-10-12) and holdings today.
- `dhandrishti`: identical (25/25). Paper portfolios 1–3: ACTIVE, parameters unchanged.
- Fundamentals are not connected to scoring; scoring weights and formulas unchanged.

## 6. Remaining limitations and open decisions
- **8 of 20 companies imported** (section 1); the other 12 need manual NSE downloads (no scraper, per NSE terms).
- **Verification depth:** 540 of 602 stored values are unverified against official documents. Internal consistency
  is strong (every non-hidden full-year figure matches its four quarters), but that is not an official check.
  Official references exist only for INFY Dec-24/Mar-25 and HDFCBANK Dec-23, Mar-25, Sep-25 (partly), Mar-26 (partly).
- **Hidden but correct values:** 6 HDFC values verified correct remain hidden because no disposition has been
  recorded (decision b). The 3 YT-2 values are probably wrong but not officially confirmed.
- Restated history cannot come from NSE XBRL comparatives; only separately filed revisions would create versions.
- Shareholding coverage is unchanged (INFY only; HDFCBANK shareholding not downloaded).
- Open decisions: (a) ~~the final 20~~ resolved: design list (section 3d); (b) who may record flag dispositions;
  (c) promotion of 0009 and 0010 (not requested); (d) commit of all uncommitted work (needed before any LIVE run).

## 7. Next tranche: manual download routine (decided 2026-10-12)
You chose manual NSE downloads (no automated NSE collection, per NSE's terms). Two helper commands were added so a
session is only clicks plus two commands (`jobs/pit_pilot.py`, `pit/pilot_validation.py`; 19 pilot tests pass):
| Command | What it does |
|---|---|
| `pit_pilot --db dd_dev_fundamentals collect` | Copies NSE listing CSVs and named XBRL files from `~/Downloads` into `data/pilot/listings/` and `data/pilot/xbrl/`. Copies only; never overwrites (a same-named file with different content is reported as a conflict); originals stay in Downloads; XBRL not named in any listing is skipped and reported |
| `pit_pilot --db dd_dev_fundamentals todo [SYMBOL ...] [--both-bases]` | Lists every results XBRL still needed for Jun-2024..Mar-2026, with NSE page, broadcast time and exact file name, from the listing CSVs; consolidated only unless `--both-bases` or the company has no consolidated results |
Then `import`, `verify`, `report`, `readiness` as before.

**Session 1 (listing CSVs, about 15 minutes):**
1. Integrated Filing – Financials: Company **blank (all companies)**, Custom **01-04-2025** to **today**, Download (.csv).
   This export has a SYMBOL column, so one file covers Mar-2025..Mar-2026 for every company. If it looks truncated,
   fall back to one export per company.
2. Financial Results: for each of the 18 companies not yet covered (ICICIBANK, BANKBARODA, BAJFINANCE, SBILIFE,
   WIPRO, PERSISTENT, DRREDDY, LAURUSLABS, ITC, MARUTI, ASHOKLEY, RELIANCE, ONGC, TATASTEEL, BHEL, ULTRACEMCO, DLF,
   IDEA): Company = that company, Period Ended = Quarterly, Custom **01-07-2024** to **28-02-2025**, Download (.csv).
   This page's export has no symbol column, so one file per company (the symbol is taken from NSE's file name).
Then: `collect`, and `todo` prints the exact XBRL list for session 2 (8 consolidated files per company; 144 for 18
companies, 288 with `--both-bases`).

Onboarding order after that: ICICIBANK, WIPRO, DRREDDY first (existing readers; SEC-verifiable), then the other
Ind-AS and bank companies, then SBILIFE and BAJFINANCE (reader mappings to build when their files are in hand).
No company is onboarded until its files are imported and checked.

Still incomplete: 18 companies; 540 INFY/HDFCBANK values unverified (the 8 results PDFs of section 3e can come in any
later session); insurance/NBFC mappings; flag-disposition and promotion decisions (section 6); uncommitted work.

## 8. Single recommended next action (updated 2026-10-27, after section 9i)
**Current (your decision):** either stop the notice hunt and use the verified 2021–2026 universe for the next
study, or keep searching for the five missing pre-2021 ad hoc notices (section 9i). Recommended: stop here.
The text below is the original 2026-10-15 action, already completed (9a).

**Save two NSE Indices press releases from your browser into `~/Downloads`** (open each link, then save the PDF):
1. Recent: https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf (22-Aug-2025, "Replacements in indices")
2. Old: https://niftyindices.com/Press_Release/ind_prs12082015.pdf (12-Aug-2015)
I will read them locally (`pdftotext`, exact text) and confirm what they contain: which indices are listed, whether
NIFTY 100 and NIFTY Midcap 100 (hence NIFTY 200) inclusions and exclusions are given with symbols, and the effective
date. Only if both confirm the structure is a parser worth building; the full list of notices (periodic and ad hoc)
would follow. No strategy study is re-run before the universe is complete and checked.

## 9. Survivorship bias: source investigation (2026-10-15)
**Question:** can NIFTY 200 membership since 2013 be reconstructed from official NSE Indices notices?

**What was checked (web search, 3 fetch attempts):**
- NSE Indices publishes each index change as a press release PDF at `niftyindices.com/Press_Release/ind_prsDDMMYYYY.pdf`
  (sometimes with a suffix, e.g. `_1`, `_2`). Search engines index releases for **Aug-2015, Feb-2016, Aug-2016,
  Apr-2017, May-2018, Aug-2020, Sep-2021, Feb-2022, Jul-2022, Jul-2023, Aug-2023, Feb-2024, Aug-2024, Feb-2025,
  Aug-2025, Jun-2026, Aug-2026** (titles such as "Replacements in indices").
- Per the NIFTY 200 methodology document (nsearchives.nseindia.com/content/indices/ind_nifty_200.pdf, via search
  summary): NIFTY 200 = NIFTY 100 + NIFTY Midcap 100; changes in those two indices are carried into NIFTY 200;
  semi-annual reviews with cut-offs 31 January and 31 July and four weeks' notice. So NIFTY 200 changes can be
  derived from the NIFTY 100 and NIFTY Midcap 100 sections of each release.
- Search summaries of individual releases mention NIFTY 100 exclusions/inclusions (e.g. Aug-2024: BHEL, JSW Energy,
  Macrotech, NHPC, Union Bank in; Berger Paints, Colgate-Palmolive, Marico, SRF out). **These are search-engine
  summaries, not verified reads.**

**What could not be verified:**
- **Document contents.** Fetching `ind_prs10082026.pdf`, `ind_prs22022016_2.pdf` and `ind_prs15092021.pdf` timed out
  three times: niftyindices.com does not serve these PDFs to automated requests. No workaround was attempted.
- **2013–2014.** No niftyindices release was found (the indices were then branded "CNX"; only news reports turned
  up). Coverage before Aug-2015 is unknown.
- **Completeness between reviews.** Membership also changes outside the semi-annual reviews (mergers, delistings,
  suspensions, demergers; e.g. the Jul-2023 release around the HDFC Ltd merger). Every such notice is needed; a single
  missed change corrupts all earlier dates when reconstructing backward from today's list.
- **An independent check.** No historical constituent snapshot (e.g. a dated NIFTY 200 list from an old factsheet)
  has been found to validate a reconstruction.

**Conclusion:** sufficiency is **not demonstrated**. The notices look like the right authoritative source for
Aug-2015 onward, but nothing has been read and confirmed, 2013–2014 is uncovered, and ad hoc changes make
completeness hard to prove. Therefore no parser, no point-in-time universe table and no re-run of the strategy
studies were done in this increment. Additional known gap regardless of notices: companies that left the index and
are no longer listed cannot be priced from Kite, so even a perfect membership table leaves some survivorship.

**What would make it sufficient:** (1) two read-and-confirmed notices (section 8); (2) the full list of releases from
the niftyindices.com press-release page in a browser (periodic and ad hoc), saved manually; (3) a dated historical
constituent list for at least one past date, to check the backward reconstruction; (4) a decision on the start date
(Aug-2015 if 2013–2014 stays uncovered).

Implementation and tests in this increment: none (by design; documentation only). Sources consulted:
[ind_prs10082026](https://niftyindices.com/Press_Release/ind_prs10082026.pdf),
[ind_prs22082025](https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf),
[ind_prs23082024](https://www.niftyindices.com/Press_Release/ind_prs23082024.pdf),
[ind_prs28022024](https://www.niftyindices.com/Press_Release/ind_prs28022024.pdf),
[ind_prs20082020](https://www.niftyindices.com/Press_Release/ind_prs20082020.pdf),
[ind_prs12082015](https://niftyindices.com/Press_Release/ind_prs12082015.pdf),
[ind_prs04072023](https://www.niftyindices.com/Press_Release/ind_prs04072023.pdf),
[NIFTY 200 methodology](https://nsearchives.nseindia.com/content/indices/ind_nifty_200.pdf) (all via search results;
the PDFs themselves were not readable by automated fetch).

### 9a. Two notices read and confirmed (2026-10-26)
You saved `ind_prs12082015.pdf` (8 pages) and `ind_prs22082025.pdf` (35 pages); copies with their extracted text
(`pdftotext -layout`) are in `data/index-notices/`.
| Notice | Release date | Effective | NIFTY 200 section | Changes |
|---|---|---|---|---|
| ind_prs12082015 | 12-Aug-2015 (IISL) | 28-Sep-2015 (close of 24-Sep-2015) | yes, as "CNX 200 Index" | 9 excluded, 9 included, company names and NSE symbols |
| ind_prs22082025 | 22-Aug-2025 (NSE Indices) | 30-Sep-2025 (close of 29-Sep-2025) | yes, "12) Nifty 200" | 9 excluded, 9 included, names and symbols |
Both state the effective date in the opening paragraph and list NIFTY 200 directly (no need to derive it from NIFTY
100 + Midcap 100). The 2025 notice is split into sections A–F (broad, sectoral, thematic, strategy...); NIFTY 200 sits
in section A. Consistency with today's list (`packages/quant-spec/universe/nifty200.csv`): 7 of the 9 Aug-2025
inclusions are still members (COROMANDEL and ITCHOTELS have left since) and 8 of 9 exclusions are still out
(MAHABANK has returned), so later notices carry further changes, as expected.
**Verdict:** the notice format is sufficient to extract additions, deletions and effective dates. Full reconstruction
still needs **every** notice from Aug-2015 to today (semi-annual and ad hoc); 2013–2014 remains unchecked.
**Next action (you):** from the niftyindices.com press-release page, save every "Replacements in indices" /
index-change release from Aug-2015 onward into `~/Downloads` (about two per year plus off-cycle ones; names look like
`ind_prsDDMMYYYY.pdf`). Already known to exist: 22-Feb-2016, 12-Aug-2016, 27-Apr-2017, 24-May-2018, 20-Aug-2020,
15-Sep-2021, 24-Feb-2022, 11-Jul-2022, 04-Jul-2023, 17-Aug-2023, 28-Feb-2024, 23-Aug-2024, 21-Feb-2025, 10-Jun-2026,
10-Aug-2026. **Next action (me):** a parser for these notices plus a point-in-time membership table, tested on the two
confirmed notices; the reconstruction is checked against today's list once the full set is in.

### 9b. 2026 notices received and checked (2026-10-26)
You saved 21 press releases from 2026 (from www.niftyindices.com/press-release, year 2026); copies and extracted text
are in `data/index-notices/` (23 notices in total with the two from 9a).
- **Format confirmed for off-cycle notices too.** Every notice lists each affected index by name in a numbered
  section with "excluded"/"included" tables (name + NSE symbol) and an effective date ("effective from <date> (close
  of <date>)"). A notice changes NIFTY 200 only if it has a "Nifty 200" (or, in 2015, "CNX 200 Index") section.
- **In 2026 only the two semi-annual reviews change NIFTY 200:** 23-Feb-2026 (effective 30-Mar-2026: 11 out, 11 in)
  and 10-Aug-2026 (effective 30-Sep-2026: 7 out, 7 in). The 19 off-cycle 2026 notices (mergers, e.g. Gujarat State
  Petronet into Gujarat Gas; ESG and Shariah reviews; thematic reviews) touch other indices only.
- **Chain check:** applying 22-Aug-2025 → 23-Feb-2026 → 10-Aug-2026 in order gives, for all **49 stocks** they mention,
  exactly the membership in today's list (`packages/quant-spec/universe/nifty200.csv`): 49 consistent, 0 inconsistent.
- **Coverage now:** 30-Sep-2025 to today, provided no off-cycle notice between Sep-2025 and Dec-2025 changes NIFTY 200
  (2025 notices other than 22-Aug-2025 have not been downloaded yet). Before Sep-2025: only the single Aug-2015 notice.
- Still needed: every equity "Replacement(s) in indices" / inclusion / exclusion notice for **2025 back to 2015** (and
  2013–2014 if the year list offers them). Parser and membership table: not built yet (next increment, with the
  three checked notices as test fixtures).

### 9c. 2025 notices checked; membership parser built (2026-10-26)
You saved 47 notices for 2025 (most are fixed-income releases, which the parser ignores). Copies and text:
`data/index-notices/` (70 notices in total).
- NIFTY 200 changes in 2025: only the two semi-annual reviews. **21-Feb-2025** (effective 28-Mar-2025; this notice
  numbers sections with letters, "l) Nifty 200": 11 out, 11 in) and **22-Aug-2025** (effective 30-Sep-2025: 9 out,
  9 in). The off-cycle 2025 notices (Kesoram/UltraTech and Quess demergers, ICICI Securities suspension, Piramal and
  Dhani amalgamations, ESG/thematic/strategy reviews) list no NIFTY 200 section; the stocks involved were not members.
- **Implemented** (research only, reads the saved text): `apps/worker/src/dhandrishti/research/index_membership.py`
  parses the NIFTY 200 section of each notice (headings "12) Nifty 200", "l) Nifty 200", "4) CNX 200 Index"; strategy
  indices such as "Nifty200 Quality 30" excluded) with release and effective dates, and rebuilds membership backwards
  from today's NSE list, checking every undo and reporting inconsistencies, counting duplicate notices once, and
  refusing to answer for dates before the stated completeness date.
- **Result:** rebuilt from today's list back to 1-Jan-2025 through four changes (28-Mar-2025, 30-Sep-2025,
  30-Mar-2026, 30-Sep-2026): **0 inconsistencies**, exactly 200 members in every period. Coverage is therefore
  demonstrated from **1-Jan-2025** only.
- Tests: `apps/worker/tests/test_index_membership.py`, **6 passed** (section parsing incl. page breaks and other
  indices, lettered and CNX headings, notice without NIFTY 200, missing effective date, boundaries and duplicates,
  inconsistency reporting, real 2025–2026 notices consistent with today's list).
- Not done (by design): no strategy study re-run; the universe covers only 2025–2026 so far.
- **Next action (you):** the same download for **2024, 2023, ... back to 2015** (and 2013–2014 if listed). Each year
  adds one more year of verified history; the parser will report any inconsistency as you go.
- Known gaps to watch as older years arrive: **symbol renames** (e.g. ZOMATO → ETERNAL) will surface as
  inconsistencies and need a small rename table; short-lived inclusions of demerged entities if a notice does not
  name NIFTY 200; companies no longer listed cannot be priced from Kite.

### 9d. 2024, 2023 and 2022 notices checked; revocations and renames handled (2026-10-26)
You saved 64 (2024), 27 (2023) and 30 (2022) notices; `data/index-notices/` now holds 191 PDFs with text.
- **First 2024 rebuild: 4 inconsistencies, 202 members at 1-Jan-2024.** All four were traced to the source:
  - **IREDA (28-Mar-2024):** `ind_prs19032024` revokes IREDA's inclusion (SEBI impact-cost norm) and includes
    **BSE** in its place.
  - **IDEA and CENTRALBK (30-Sep-2024):** `ind_prs25092024` revokes Vodafone Idea's exclusion, and with it
    Central Bank of India's inclusion.
  - **GMRINFRA:** renamed **GMRAIRPORT** between `ind_prs25092024` (still "GMR Airports Infrastructure Ltd.",
    GMRINFRA) and `ind_prs11122024` ("GMR Airports Ltd.", GMRAIRPORT); today's list has the same company and ISIN.
- **2023 added one more: Tata Motors DVR.** TATAMTRDVR was included on 29-Sep-2023 (8 in, 7 out) and excluded
  without replacement on 30-Aug-2024 (`ind_prs23082024_1`: DVR shares cancelled). That notice lists the indices
  instead of numbered sections. NIFTY 200 therefore had **201 securities from 29-Sep-2023 to 29-Aug-2024**; two
  independent notices agree.
- **Implemented** (`research/index_membership.py`):
  - **Revocation tables:** these centre the index cell across its rows, so they cannot be split by index
    mechanically. Instead, the NIFTY 200 rows of the remarks-table and index-list notices are transcribed in
    `AMENDMENTS` (4 notices with rows, 2 reviewed with none). Each transcribed row and date is checked against the
    notice text, and a typo fails loudly.
  - **New notices:** any other notice with a remarks table, or naming NIFTY 200 outside a numbered section, is
    reported as *unreviewed*, so a new one cannot slip through. At present none are unreviewed.
  - **Revocation checks:** a revocation cancels the announced change. A revocation with nothing to cancel is
    reported.
  - **Symbols and sizes:** `RENAMES` reports history in today's symbols. `SIZE_CHANGES` turns the two DVR size
    changes into notes; any other size change is still a problem.
- **Result:** rebuilt from today's list back to 1-Jan-2022 through 13 change dates. There are **0 inconsistencies**
  and 0 duplicates. Every period has 200 members, except the 201 above.
- **Gap found: the March-2022 semi-annual review notice is missing.** Every other half-year from Sep-2022 to
  Sep-2026 has its review notice (Feb/Aug). Of the 2022 files, the Feb–Mar ones are NIFTY SME EMERGE releases and one
  thematic review (`ind_prs08032022`), none of which covers the broad-market indices. A missing notice does not show
  up as an inconsistency in a backward walk, so "0 problems" alone does not prove completeness. **Coverage is
  demonstrated from 31-Mar-2022 onward**, not 1-Jan-2022.
- `_1` file names: 25 notices exist only as `..._1.pdf`. That is NSE's naming when there is more than one release on
  a day, so it is not by itself a sign that a notice is missing. It is not counted as a gap.
- Tests: `tests/test_index_membership.py`, **8 passed**. The two new tests cover:
  - checked transcriptions, revocation effect, unreviewed detection for both formats, a transcription typo, and a
    revocation with nothing to cancel;
  - renames in today's symbols, and known size changes reported as notes.

  The real-data test now covers 2023–2026: 0 problems, 2 notes, 200/201 members, and BSE, IREDA and GMRAIRPORT at
  the right dates.
- Not done (by design): no strategy study re-run (verified history is 4.5 years so far).
- **Next action (you):**
  1. On www.niftyindices.com/press-release (year 2022), look for a **late-February 2022 "Replacements in indices"**
     notice, effective **March 31, 2022**, and save it.
  2. Then continue with **2021 → 2015**, as before.

### 9e. March-2022 review found; 2022 complete (2026-10-27)
- The missing notice is **`ind_prs24022022_1`** (24-Feb-2022, "Revision in criteria and replacements in indices",
  effective 31-Mar-2022), located by web search and saved by you. It was not in the 2022 files saved earlier. Its
  "12) NIFTY 200" section has 14 out and 14 in, 28 changes, and the parser read it unchanged.
- It produced one problem, a rename: **ZOMATO → ETERNAL**. The notices say "Zomato Ltd." ZOMATO up to
  `ind_prs21022025` and "Eternal Ltd." ETERNAL from `ind_prs06062025`. Added to `RENAMES`.
- **Result:** rebuilt from today's list back to **1-Jan-2022** through 14 change dates, with **0 inconsistencies** and
  0 duplicates. There are 200 members in every period except 201 from 29-Sep-2023 to 29-Aug-2024 (Tata Motors DVR,
  9d). Each year's semi-annual reviews are all present from Mar-2022 to Sep-2026. **Coverage is demonstrated from
  1-Jan-2022** (4 years 9 months).
- Tests: `tests/test_index_membership.py` **8 passed**; the real-data test now covers 2022–2026.
- Known limitation for later pricing: stocks excluded under an old symbol that is not in today's list (e.g.
  AMARAJABAT, since renamed) stay under the symbol in the notice. They need mapping to Kite instrument history when
  the study uses them.
- **Next action (you):** the notices for **2021**, then 2020 → 2015. Check each year's list for both semi-annual
  reviews (late Feb and late Aug), because missing ones are not caught by the rebuild (9d).

### 9f. 2021 verified; 2020 one notice short; 2017–2019 incomplete (2026-10-27)
Notices saved so far per year: 2026: 21, 2025: 48, 2024: 64, 2023: 27, 2022: 31, 2021: 22, 2020: 11, 2019: 6,
2018: 8, 2017: 4, 2015: 1.
- **2021: verified.**
  - The Aug-2021 review (`ind_prs23082021`) is an **image-only PDF**: pdftotext returned nothing, so the parser
    silently saw no changes.
  - I OCR'd it (tesseract, 300 dpi), checked its "10) NIFTY 200" table (6 out, 6 in) against the page image, and
    transcribed it in `AMENDMENTS`. The OCR text is saved as the notice's `.txt`, with a header saying so.
  - The parser now **flags any notice with (almost) no text** as unreviewed, so this cannot happen silently again;
    it already caught a 2018 image-only notice (`ind_prs24092018`, NIFTY CPSE only).
  - Rebuilt back to **1-Jan-2021: 0 problems**, with both reviews present (Mar and Sep).
- **2020: one notice missing.**
  - Renames added: ADANIGAS → ATGL, ADANITRANS → ADANIENSOL and NIITTECH → COFORGE (evidence notices in `RENAMES`).
  - One problem remains: ADANIGREEN is included on 27-Mar-2020 and again on 25-Sep-2020, with no exclusion in
    between. A web search found **`ind_prs16032020`** (16-Mar-2020, "Replacement in indices"), which lists
    ADANIGREEN and is not among the saved files. It is the likely revocation; not yet confirmed.
- **2017–2019: far fewer notices than the site has.**
  - None of the saved 2019 or 2018 notices contains a broad-market review.
  - A web search shows at least **`ind_prs28082019`** (Aug-2019 review, effective 27-Sep-2019) and
    **`ind_prs13062019`** exist but were not saved.
  - 2017 has a GRASIM inconsistency (excluded 26-May-2017 but still a member), consistent with missing notices.
  - **No coverage is claimed before 1-Jan-2021.**
- Tests: `tests/test_index_membership.py` **8 passed**. The real-data test covers 2021–2026, including the
  transcribed image-only notice, and a new assertion checks that a textless notice is flagged.
- **Next action (you):**
  1. Save `ind_prs16032020.pdf`.
  2. On the press-release page, recheck the **2019, 2018 and 2017** lists. They should hold roughly 20–50 notices
     each, including a late-Feb and a late-Aug review. If the page shows only a few, a screenshot of the list
     helps.

### 9g. Older notices: the site list is sparse, so use direct links (2026-10-27)
- **What the site shows:** for 2016 the press-release page shows one notice (a G-Sec index; saved, no NIFTY 200),
  and for 2015 none. Yet older PDFs exist at direct links: `ind_prs12082015` was saved that way.
- **Notices located by web search and not yet saved:**
  - 2020: `ind_prs16032020`, `ind_prs19032020`
  - 2019: `ind_prs28082019` (Aug review), `ind_prs13062019`
  - 2018: `ind_prs21022018` (Feb review), `ind_prs28082018` (Aug review), `ind_prs24052018`, `ind_prs14122018`
  - 2017: `ind_prs16022017` (Feb review; it sits under `/docs/default-source/press-release-upload/`),
    `ind_prs28082017` (Aug review), `ind_prs30032017`, `ind_prs03112017`
- **Not yet located:**
  - the Feb-2019 review: the site title is "Change in Indices w.e.f. March 29, 2019";
  - the 2016 reviews: entries are dated 22-Feb-2016 and 17-Oct-2016;
  - the Aug-2016 and Feb/Aug-2015 reviews.
- The rebuild's consistency check will point at any remaining missing ad hoc notice, as it did for 2020.

### 9h. 2017–2020 notices added; three still missing (2026-10-27)
- **Saved by direct link:** all 12 notices from 9g. Every Feb and Aug review is now present for 2017, 2018 and
  Aug-2019; the Feb-2019 review is not.
- **March 2020 (Yes Bank):**
  - `ind_prs16032020` removed Yes Bank from all indices on 19-Mar-2020 and brought ADANITRANS's NIFTY 200 entry
    forward from 27-Mar to 19-Mar.
  - `ind_prs19032020` says in prose that PVR joins NIFTY 200 on 27-Mar instead of Yes Bank.
  - Both are transcribed in `AMENDMENTS`, which now accepts a row-specific effective date (tested).
- **Renames added:** RNAM → NAM-INDIA and LTI → LTIM, with evidence notices in `RENAMES`.
- **Still inconsistent:**
  1. ADANIGREEN and PVR both join NIFTY 200 on 27-Mar-2020, but no saved notice removes either before
     25-Sep-2020, when ADANIGREEN is included again. The saved 2020 files jump from 19-Mar to 2-Jul. The likely
     missing notice is `ind_prs02072020`: only `ind_prs02072020_1` is saved.
  2. The Feb-2019 review is missing. The site lists "Change in Indices w.e.f. March 29, 2019", dated 25-Feb-2019,
     probably `ind_prs25022019`. The 2018 and 2017 problems (AVANTIFEED, NIACL, LTIM, LALPATHLAB, GSKCONS, LTTS,
     QUESS, RELCAPITAL, PFIZER, ...) cannot be judged until it and the 2020 notice are in.
- Verified coverage is unchanged: **from 1-Jan-2021**. Tests: `tests/test_index_membership.py` **8 passed**.
- **Next action (you):** save `ind_prs02072020.pdf` and `ind_prs25022019.pdf` by direct link, and check the 2020
  list for any notice dated between 20-Mar and 1-Jul-2020.

### 9i. Feb-2019 review found; a parser gap fixed; ad hoc notices before 2021 still missing (2026-10-27)
- **New notices:**
  - **`ind_prs25022019`** is the Feb-2019 review (effective 29-Mar-2019; NIFTY 200: 5 out, 5 in). It resolved
    AVANTIFEED, GSKCONS, LTTS and PFIZER.
  - `ind_prs02072020` is a bond-index launch, so the mid-2020 gap remains.
- **Renames:**
  - LTIMindtree was renamed again. Today's list has "LTM Ltd." LTM (ISIN INE214T01019), so LTI → LTM and
    LTIM → LTM.
  - IBVENTURES → DHANI (Indiabulls Ventures → Dhani Services).
- **Parser gap fixed:** 2015–2018 notices write "6) NIFTY 200 Index". The parser accepted only "CNX 200 Index", so
  it skipped the NIFTY 200 section of `ind_prs24052018` (effective 29-Jun-2018, including QUESS out). Headings are
  now compared without a trailing "Index", with a new test. Total: **9 passed**.
- **Remaining inconsistencies (all before 2021), each implying an unsaved ad hoc notice:**
  | Stock | What the saved notices show | Missing event, window |
  |---|---|---|
  | ADANIGREEN, PVR | in 27-Mar-2020; ADANIGREEN in again 25-Sep-2020 | exit, Apr–Sep 2020 |
  | NIACL | in 28-Sep-2018; not in the list since | exit, Oct 2018 – Dec 2020 |
  | LALPATHLAB | out 2-Apr-2018; out again 30-Sep-2024 | re-entry, Apr 2018 – Dec 2020 |
  | FRETAIL | in 29-Sep-2017; in again 29-Jun-2018 | exit, Oct 2017 – Jun 2018 |
  | RELCAPITAL | out 5/29-Sep-2017; out again 27-Sep-2019 | re-entry, Oct 2017 – Sep 2019 |

  The site's year lists show few notices before 2020, and web search finds individual PDFs only by luck.
  **Verified coverage stays at 1-Jan-2021 onward.**
