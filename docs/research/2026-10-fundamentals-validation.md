# Fundamentals pilot: validation of imported observations, 9 October 2026

Read-only checks on the 285 observations imported on 2026-10-09 (`dhandrishti_kite.fundamental_observations`).
Nothing was modified.

## Independent sources
**None available locally.** No Infosys or HDFC Bank results documents (company PDF results, annual reports)
were found in the workspace or the usual folders; personal documents were not opened. **No observation is
marked verified against an independent source.**

Two weaker checks were possible and are labelled as such:
- **Transcription**: raw values re-read from the original XBRL by a separate minimal script (by context id,
  not through the reader) and compared with the stored rows. Shows the import copied the filing faithfully;
  says nothing about whether the filing itself is right.
- **NSE summary**: the shareholding listing publishes promoter % per filing. Same origin as the filing, so it
  corroborates, it does not verify.

## Sample
| Company | Period | Basis | Metric | Imported | Source value (raw XBRL) | Source | Diff | Status |
|---|---|---|---|---:|---:|---|---:|---|
| INFY | Q Jan–Mar 2026 | cons. | revenue | 46,402.00 | 46,402.00 | `..._1658040_...` RevenueFromOperations @ OneD | 0 | Matches source file; unverified |
| INFY | Q Jan–Mar 2026 | cons. | net profit (owners) | 8,501.00 | 8,501.00 | ProfitOrLossAttributableToOwnersOfParent @ OneD | 0 | Matches source file; unverified |
| INFY | Q Jan–Mar 2026 | cons. | diluted EPS | 20.98 | 20.98 | DilutedEarnings… @ OneD | 0 | Matches source file; unverified |
| INFY | Q Jan–Mar 2026 | cons. | finance costs | 105.00 | 105.00 | FinanceCosts @ OneD | 0 | Matches source file; unverified |
| INFY | FY 2025-26 | cons. | cash from operations | 33,986.00 | 33,986.00 | CashFlowsFromUsedInOperatingActivities @ FourD | 0 | Matches source file; unverified |
| INFY | 31-Mar-2026 | cons. | equity | 92,852.00 | 92,852.00 | EquityAttributableToOwnersOfParent @ OneI | 0 | Matches source file; unverified |
| INFY | Q Oct–Dec 2024 | cons. | revenue | 41,764.00 | 41,764.00 | `INDAS_117292_...` @ OneD (old format) | 0 | Matches source file; unverified |
| INFY | Q Oct–Dec 2024 | cons. | net profit (owners) | 6,806.00 | 6,806.00 | same | 0 | Matches source file; unverified |
| INFY | Q Jan–Mar 2025 | stand. | diluted EPS | 15.93 | 15.93 | `..._1417992_...` @ OneD | 0 | Matches source file; unverified |
| HDFCBANK | Q Oct–Dec 2025 | cons. | revenue (total income) | 1,26,927.27 | 1,26,927.27 | `..._1603568_...` Income @ OneD | 0 | Matches source file; unverified |
| HDFCBANK | Q Oct–Dec 2025 | cons. | net profit (owners) | 19,806.63 | 19,806.63 | ProfitLossAfterTaxesMinorityInterest… @ OneD | 0 | Matches source file; unverified |
| HDFCBANK | Q Oct–Dec 2025 | cons. | finance costs (interest expended) | 45,821.42 | 45,821.42 | InterestExpended @ OneD | 0 | Matches source file; unverified |
| HDFCBANK | Q Oct–Dec 2025 | cons. | diluted EPS | 12.82 | 12.82 | DilutedEarningsPerShareAfterExtraordinaryItems @ OneD | 0 | Matches source file; unverified |
| HDFCBANK | Q Oct–Dec 2023 | cons. | net profit (owners) | 17,257.87 | 17,257.87 | `BANKING_101079_...` @ OneD (old format) | 0 | Matches source file; unverified |
| HDFCBANK | Q Jan–Mar 2025 | stand. | net profit | 17,616.14 | 17,616.14 | `..._1421434_...` ProfitLossForThePeriod @ OneD | 0 | Matches source file; unverified |
| HDFCBANK | 31-Mar-2025 | stand. | borrowings | 5,47,930.90 | 5,47,930.90 | Borrowings @ OneI | 0 | Matches source file; unverified |
| HDFCBANK | FY 2024-25 | stand. | cash from operations | 1,45,177.31 | 1,45,177.31 | CashFlowsFromUsedInOperatingActivities @ FourD | 0 | Matches source file; unverified |
| INFY | 15 shareholding dates, Mar-23 → Jun-26 | — | promoter % | 15.14 … 13.82 | NSE listing: identical in 15 of 15 | `CF-Shareholding-Pattern-…INFY…csv` | 0 | Corroborated by NSE summary; unverified |

₹ crore except EPS (₹) and %. 18 of 18 figures match their source file; 15 of 15 promoter % match NSE's summary.
Foreign and domestic institutional % have no second NSE value to compare with.

## Coverage (results, by quarter; both companies list 14 quarters, 31-Mar-2023 to 30-Jun-2026)
| | INFY cons. | INFY stand. | HDFCBANK cons. | HDFCBANK stand. |
|---|---|---|---|---|
| Imported quarters | Dec-24, Mar-25, Dec-25, Mar-26 | same 4 | Dec-23, Dec-24, Dec-25, Jun-26 | Dec-23, Dec-24, Mar-25, Dec-25, Jun-26 |
| Held back | — | — | Mar-25, Sep-25, Mar-26 | Mar-26 |
| Not downloaded | 10 | 10 | 7 | 9 |
| Imported / listed | 4 / 14 | 4 / 14 | 4 / 14 | 5 / 14 |

- Duplicate keys: none. Full-year figures: INFY FY2025 and FY2026 (both bases); HDFCBANK FY2025 standalone only.
- Balance sheet and cash flow exist only for March quarters: INFY Mar-25 and Mar-26 (both bases), HDFCBANK Mar-25
  standalone. No consecutive quarters for any company, so trailing-twelve-month and year-on-year figures cannot
  yet be built from stored data.
- Shareholding: INFY 15 of 15 listed filings imported; HDFCBANK none.
- Metrics never available from results filings: dividend per share; for banks also depreciation and profit
  before exceptional items.

## Directly reported vs calculated
| Kind | Metrics | Labelled in the database? |
|---|---|---|
| Single reported line | revenue (Ind-AS), other income, depreciation, finance costs, profit before exceptional items, PBT, net profit, EPS, total assets, cash from operations, cash (Ind-AS), equity (Ind-AS), promoter/FII/DII % | n/a |
| Calculated by DhanDrishti | shares outstanding = paid-up capital ÷ face value (17 rows) | **yes** (suffix in `source_record_id`) |
| Inferred from a yes/no answer | promoter pledged % = 0 when the filing says "no pledge" (15 rows) | **no** |
| Sum of reported lines | capex (2–3 lines), borrowings (Ind-AS: current + non-current), bank equity (capital + reserves), bank cash (2 lines) | **no** |
| Mapping convention | bank "revenue" = total income (interest earned + other income); bank "finance costs" = interest expended | **no** (documented in code only) |

The only label is free text in `source_record_id`; there is no structured field saying how a value was obtained.

## Data-quality risks
1. **No independent verification**: XBRL tagging errors exist (HDFCBANK's held-back filings); a file can be
   self-consistent and still wrong. Every stored value is "as tagged by the filer".
2. **Calculated, summed and inferred values are not consistently labelled** (see table): downstream code cannot
   tell them from reported lines.
3. **Sparse coverage**: 2 of 20 pilot stocks, at most 5 of 14 quarters per basis, no consecutive quarters.
4. **Per-share figures across HDFCBANK's 2025 bonus are not comparable** (no corporate-action adjustment yet).
5. **Shareholding is stored with basis STANDALONE** as a convention (it is company-level).
6. **The listing timestamps are trusted as given**: dissemination times come from NSE's export; XBRL can lag the
   real announcement (conservative) and the lag is not measured.

## Recommended next step
**Obtain the official PDF results for a small, fixed sample (for example INFY and HDFCBANK, quarters Dec-2024 and
Mar-2025, both bases) and verify the 18 sampled values plus the 4 held-back HDFCBANK filings against them.**
This gives the first independent check of the XBRL mapping and settles the held-back figures, and the same
sample then serves as ground truth when any automated provider is evaluated. Before scaling to 20 stocks, add a
structured "how obtained" field (reported / summed / calculated / inferred), which needs a reviewed migration.

---

# Round 2: independent validation against official company documents (9 October 2026)

Read-only. No database change, no import. Official documents were found on the US SEC's EDGAR system, where both
companies furnish their results (Form 6-K). This is a channel independent of the NSE XBRL that was imported.

## Documents used
| Ref | Document | Covers |
|---|---|---|
| A | Infosys, SEC 6-K [0001067491-25-000002 EX-99.3](https://www.sec.gov/Archives/edgar/data/1067491/000106749125000002/exv99w03.htm), "Form of Release to Stock Exchanges", Statement of Consolidated Audited Results (Ind-AS), 16-Jan-2025 | INFY consolidated, quarter ended 31-Dec-2024 |
| A2 | Infosys, SEC 6-K [0001067491-25-000004 EX-99.2](https://www.sec.gov/Archives/edgar/data/1067491/000106749125000004/exv99w02.htm), IFRS INR press release, 16-Jan-2025 | INFY consolidated Q3 FY25 (IFRS; second confirmation of A) |
| B | Infosys, SEC 6-K [0001067491-25-000008 EX-99.3](https://www.sec.gov/Archives/edgar/data/1067491/000106749125000008/exv99w03.htm), Ind-AS results, 17-Apr-2025: consolidated statement, balance sheet, cash flow; standalone in Note 6 | INFY quarter and year ended 31-Mar-2025 |
| C | HDFC Bank, SEC 6-K [0001193125-25-161483 EX-99](https://www.sec.gov/Archives/edgar/data/1144967/000119312525161483/d872330dex99.htm), results for the quarter ended 30-Jun-2025, audited comparative columns for the quarter and year ended 31-Mar-2025 | HDFCBANK standalone and consolidated, Mar-2025 |
| D | HDFC Bank, SEC 6-K [0001193125-24-008877 EX-99](https://www.sec.gov/Archives/edgar/data/1144967/000119312524008877/d870756dex99.htm), results for the quarter ended 31-Dec-2023, 16-Jan-2024 | HDFCBANK Dec-2023 |
| E | HDFC Bank, SEC 6-K [0001193125-25-247585 EX-99](https://www.sec.gov/Archives/edgar/data/1144967/000119312525247585/d41934dex99.htm), consolidated results for the quarter ended 30-Sep-2025 | held-back file |
| F | HDFC Bank, SEC 6-K [0001193125-26-162748 EX-99](https://www.sec.gov/Archives/edgar/data/0001144967/000119312526162748/d133399dex99.htm), outcome of board meeting 18-Apr-2026 with audited results | held-back files, Mar-2026 |

Not obtainable: Infosys's own site (403 to automated access); HDFC Bank's press-release page (now hdfc.bank.in, list
not readable); SEC raw text by script (SEC requires a declared contact email; the user's email was not sent).
Reference values were therefore read through a web-fetch tool that summarises pages; the risk of a misread is
mitigated by requiring verbatim quotes, by two documents agreeing for INFY Dec-2024 (A and A2), and by 52 values
matching to the paisa (a misread would show as a mismatch).

## The 18 sampled observations
| # | Company | Period | Basis | Metric | Imported | Official | Doc | Diff | Status |
|---|---|---|---|---|---:|---:|---|---:|---|
| 1–6 | INFY | Q Jan–Mar 2026 / FY26 / 31-Mar-26 | cons. | revenue, net profit, diluted EPS, finance costs, CFO, equity | as round 1 | — | not obtained (outside the Dec-24/Mar-25 scope) | — | **Unverified** |
| 7 | INFY | Q Oct–Dec 2024 | cons. | revenue | 41,764 | 41,764 | A (A2 agrees) | 0 | **Verified** |
| 8 | INFY | Q Oct–Dec 2024 | cons. | net profit (owners) | 6,806 | 6,806 | A (A2 agrees) | 0 | **Verified** |
| 9 | INFY | Q Jan–Mar 2025 | stand. | diluted EPS | 15.93 | — | B has no standalone EPS | — | **Unverified** |
| 10–13 | HDFCBANK | Q Oct–Dec 2025 | cons. | total income, net profit, interest expended, EPS | as round 1 | — | not obtained (outside scope) | — | **Unverified** |
| 14 | HDFCBANK | Q Oct–Dec 2023 | cons. | net profit (owners) | 17,257.87 | 17,257.87 | D | 0 | **Verified** |
| 15 | HDFCBANK | Q Jan–Mar 2025 | stand. | net profit | 17,616.14 | 17,616.14 | C | 0 | **Verified** |
| 16 | HDFCBANK | 31-Mar-2025 | stand. | borrowings | 5,47,930.90 | 5,47,930.90 | C | 0 | **Verified** |
| 17 | HDFCBANK | FY 2024-25 | stand. | cash from operations | 1,45,177.31 | — | C has no cash-flow statement | — | **Unverified** |
| 18 | INFY | 15 shareholding dates | — | promoter % | — | — | no company document obtained | — | **Unverified** (NSE summary corroborates) |

**Sample: 5 verified, 0 mismatched, 13 unverified.**

## All imported values checkable against documents A–D
52 imported values (the 5 above plus 47 more: INFY Dec-24 and Mar-25 consolidated income statement, Mar-25
balance sheet and cash flow, Mar-25 standalone revenue/PBT/profit for the quarter and year; HDFCBANK Mar-25
standalone quarter and year income statement, EPS, equity, borrowings; HDFCBANK Dec-23 both bases) were compared by
script: **52 verified, 0 mismatched**, differences 0.00 in every case. HDFCBANK Mar-25 values come from the audited
comparative column of a later (July 2025) document; they equal the originally imported XBRL values, so no
restatement is visible.

## The four held-back HDFC Bank filings
| Filing | Period, basis | Why held back (reader) | Official document | Finding |
|---|---|---|---|---|
| `..._1420333_...` | Q Mar-2025, cons. | segment PBT 25,573.39 ≠ PBT 25,123.70; EPS implies 18,840 ≠ owners' profit 18,385.19 | C: no exceptional item; PBT 25,573.39; minority 449.69; owners' profit **18,834.88**; EPS 24.62 | XBRL tagged minority interest as an exceptional item and deducted it twice. Tagged PBT and owners' profit are both wrong (owners' profit understated by ₹449.69 cr). **Hold confirmed.** |
| `..._1553886_...` | Q Sep-2025, cons. | segment PBT 26,658.89 ≠ PBT 25,905.79 | E: no exceptional item; PBT **26,658.89**; minority 753.10; owners' profit 19,610.67 | Minority interest tagged as an exceptional item; **PBT understated by ₹753.10 cr**; owners' profit correct. **Hold confirmed.** |
| `..._1654391_...` | Q Mar-2026, cons. | segment PBT 27,671.63 ≠ PBT 26,948.17 | F: no exceptional item; PBT **27,671.63**; minority 723.46; owners' profit 20,350.76; basic EPS 13.22 | Same pattern: **PBT understated by ₹723.46 cr**; owners' profit correct. Balance-sheet lines agree with F once XBRL breakdown members (policyholders' funds, ESOPs, minority interest) are counted. **Hold confirmed.** |
| `..._1654389_...` | Q Mar-2026, stand. | balance-sheet cash 2,98,466.36 ≠ cash-flow cash 2,97,606.84 | F: cash and RBI balances 2,00,679.37 + bank balances 97,786.99 = 2,98,466.36; cash flow end-of-period cash **2,98,466.36**; PBT 25,193.35; profit 19,221.05; EPS 12.49 | The XBRL **cash-flow cash element is wrong** (₹859.52 cr short); every value the reader would store (incl. balance-sheet cash 2,98,466.36, PBT, profit) matches F. Hold was correct to require review; this file could be accepted. |

Pattern: in 3 of 5 HDFCBANK consolidated filings examined, the XBRL tags minority interest as an exceptional item.
The legal results statements show no exceptional item. The cross-checks caught every case; the arithmetic
identities caught none.

## Status after round 2
- **Verified against official documents:** 52 imported values (INFY Dec-24 cons., Mar-25 cons. and standalone
  headline lines; HDFCBANK Mar-25 standalone, Dec-23 both bases).
- **Mismatched:** none.
- **Unverified:** the remaining 233 imported values, including INFY Dec-25 and Mar-26, HDFCBANK Dec-24, Dec-25 and
  Jun-26, all shareholding percentages, Infosys standalone EPS/finance costs/depreciation/balance sheet (not in the
  documents), HDFCBANK cash-flow figures.

## Proposed design: how each value was obtained (not implemented)
Today the only marker is free text in `source_record_id` (shares outstanding). Proposed:

1. **A separate append-only table**, so `fundamental_observations` stays untouched and the 285 existing rows can be
   described by inserts (the append-only trigger forbids updating them):
   ```sql
   CREATE TABLE fundamental_value_provenance (
     observation_id  bigint PRIMARY KEY REFERENCES fundamental_observations (id),
     how_obtained    text NOT NULL CHECK (how_obtained IN ('REPORTED', 'SUMMED', 'CALCULATED', 'INFERRED')),
     source_elements text[] NOT NULL,          -- exact taxonomy element names used
     derivation      text,                      -- formula; NULL only when REPORTED
     mapping_note    text,                      -- e.g. 'bank revenue = total income'
     CHECK ((how_obtained = 'REPORTED') = (derivation IS NULL)),
     CHECK (how_obtained <> 'REPORTED' OR cardinality(source_elements) = 1)
   );  -- plus the same no-UPDATE/DELETE trigger
   ```
   | Value | Meaning | Current examples |
   |---|---|---|
   | REPORTED | one line, as tagged | revenue (Ind-AS), net profit, EPS, PBT, total assets, CFO, promoter % |
   | SUMMED | sum of lines from the same filing and period | capex, Ind-AS borrowings, bank equity (capital + reserves), bank cash |
   | CALCULATED | other arithmetic | shares outstanding = paid-up capital ÷ face value |
   | INFERRED | number set from a non-numeric statement | promoter pledged % = 0 from "no shares pledged" |
   Mapping conventions (bank "revenue" = total income; bank finance costs = interest expended) stay REPORTED with a
   `mapping_note`, because the value is one reported line; the note records that the canonical name differs.
2. **Readers write it** in the same transaction as each observation; the reader mappings already know the elements.
3. **Point-in-time queries can filter** (e.g. research that excludes INFERRED values).
4. **A sibling append-only table `fundamental_verifications`** (observation_id, reference document and locator,
   reference value, difference, status VERIFIED / MISMATCH, checked_at) would store results like the 52 above,
   so verification is queryable instead of living in reports.

Alternative considered: a `how_obtained` column on `fundamental_observations`. Rejected for existing rows: setting it
needs UPDATE, which the append-only rule forbids, and re-importing as version 2 would misrepresent a metadata
change as a data correction.
