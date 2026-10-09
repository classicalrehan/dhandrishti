# Financial-data quality controls: design proposal

**Status: proposal for review (9 October 2026). Nothing here is implemented; no database change has been made.**
Builds on `docs/research/2026-10-fundamentals-validation.md` and `docs/fundamentals-pit.md`.

## 1. What the validation taught us
| Finding | Consequence for the design |
|---|---|
| 52 imported values matched official results exactly; 0 mismatches | The XBRL readers transcribe correctly. The risk is in what filers tag, not in parsing. |
| 3 of 5 HDFC Bank consolidated filings tag minority interest as an exceptional item; every arithmetic identity still balances | Identities alone cannot detect classification errors; accounting-aware cross-checks are needed, and their results must be stored. |
| One standalone filing had a single wrong element (cash-flow cash) while every stored value was right | A warning on one element should not condemn a whole filing; flags must attach to the element or value they concern. |
| Held-back filings leave no trace in the database | Filings that are refused or held must be recorded with their flags. |
| Calculated, summed and inferred values are indistinguishable from reported ones | Every value needs recorded provenance. |
| Verification results live only in Markdown | Verifications must be queryable and append-only. |
| Mid-quarter shareholding filings, nine-month contexts with wrong headers, percent vs fraction scales | Period and unit checks must be explicit, with notes recorded rather than silent fixes. |

## 2. Principles
1. **Never edit history.** All new tables are append-only with the same trigger pattern as
   `fundamental_observations`. The existing triggers are not disabled, bypassed or altered.
2. **Flag, don't judge.** A check produces a *flag* with a severity; a person (or a documented rule) records a
   *disposition*. Only data-integrity failures block automatically.
3. **Corrections are new observations from another source**, never edits: e.g. the official HDFC Bank owners'
   profit enters as an observation with `source = 'Company results (SEC 6-K)'`, alongside the XBRL value.
4. **Research reads through a status view** that excludes values with open review flags or rejected dispositions
   by default, and can be relaxed explicitly.

## 3. Proposed migration `0009_fundamental_quality.sql` (draft, not applied)
```sql
-- Registry of every filing seen, imported or not (held-back filings currently leave no trace).
CREATE TABLE fundamental_filings (
  id               bigserial PRIMARY KEY,
  source           text NOT NULL,                  -- 'NSE XBRL (manual download)', 'NSE SHP XBRL ...'
  file_name        text NOT NULL,
  file_sha256      text NOT NULL,
  symbol           text NOT NULL REFERENCES securities (symbol),
  basis            text CHECK (basis IN ('CONSOLIDATED', 'STANDALONE')),
  period_end       date NOT NULL,
  taxonomy         text NOT NULL,                   -- e.g. 'in-capmkt 2026-01-31', 'banking 2019-09-30'
  published_at     timestamptz,                     -- exchange dissemination time (from the listing)
  outcome          text NOT NULL CHECK (outcome IN ('IMPORTED', 'HELD_FOR_REVIEW', 'REFUSED')),
  import_batch_id  bigint REFERENCES fundamental_import_batches (id),   -- set when IMPORTED
  recorded_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (file_sha256)
);

-- How each stored value was obtained (one row per observation).
CREATE TABLE fundamental_value_provenance (
  observation_id   bigint PRIMARY KEY REFERENCES fundamental_observations (id),
  filing_id        bigint REFERENCES fundamental_filings (id),
  how_obtained     text NOT NULL CHECK (how_obtained IN ('REPORTED', 'SUMMED', 'CALCULATED', 'INFERRED')),
  source_concepts  text[] NOT NULL,      -- XBRL concepts used, e.g. {in-capmkt:RevenueFromOperations}
  source_contexts  text[],               -- context ids, e.g. {OneD}; header-vs-stated period notes go in mapping_note
  derivation       text,                  -- e.g. 'PaidUpValueOfEquityShareCapital / FaceValueOfEquityShareCapital'
  mapping_note     text,                  -- accounting interpretation, e.g. 'bank revenue = total income (interest earned + other income)'
  recorded_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((how_obtained = 'REPORTED') = (derivation IS NULL)),
  CHECK (how_obtained <> 'REPORTED' OR cardinality(source_concepts) = 1),
  CHECK (how_obtained <> 'INFERRED' OR mapping_note IS NOT NULL)
);

-- Results of quality checks, per filing and optionally per value.
CREATE TABLE fundamental_quality_flags (
  id               bigserial PRIMARY KEY,
  filing_id        bigint NOT NULL REFERENCES fundamental_filings (id),
  observation_id   bigint REFERENCES fundamental_observations (id),      -- NULL: filing-level flag
  check_code       text NOT NULL,         -- e.g. 'MI-1' (catalogue in section 4)
  check_version    integer NOT NULL,      -- bump when a check's logic or tolerance changes
  severity         text NOT NULL CHECK (severity IN ('BLOCK', 'REVIEW', 'NOTE')),
  observed         jsonb NOT NULL,        -- the numbers compared, e.g. {"segment_pbt": 25573.39, "pbt": 25123.70}
  message          text NOT NULL,
  raised_at        timestamptz NOT NULL DEFAULT now()
);

-- Human (or rule) decisions on flags; the latest disposition per flag wins, earlier ones stay.
CREATE TABLE fundamental_flag_dispositions (
  id               bigserial PRIMARY KEY,
  flag_id          bigint NOT NULL REFERENCES fundamental_quality_flags (id),
  disposition      text NOT NULL CHECK (disposition IN
                     ('ACCEPTED_AS_FILED', 'SUPERSEDED_BY_OFFICIAL_SOURCE', 'EXCLUDED', 'EXPLAINED')),
  reason           text NOT NULL,
  evidence         text,                  -- document reference, e.g. 'HDFC Bank SEC 6-K 0001193125-25-161483 EX-99'
  decided_by       text NOT NULL,         -- 'user' or 'rule:<code>'
  decided_at       timestamptz NOT NULL DEFAULT now()
);

-- Independent verification of stored values against official documents.
CREATE TABLE fundamental_verifications (
  id               bigserial PRIMARY KEY,
  observation_id   bigint NOT NULL REFERENCES fundamental_observations (id),
  reference_doc    text NOT NULL,         -- title, issuer, date, channel (e.g. SEC 6-K accession)
  reference_locator text NOT NULL,        -- table / statement / column
  reference_value  double precision,      -- NULL when the document lacks the line
  difference       double precision,
  status           text NOT NULL CHECK (status IN ('VERIFIED', 'MISMATCH', 'NOT_IN_DOCUMENT')),
  method           text NOT NULL,         -- e.g. 'web-fetch verbatim quote; two documents agree'
  checked_at       timestamptz NOT NULL DEFAULT now()
);

-- Same append-only guard on all five tables (the existing function is reused, not changed).
CREATE TRIGGER fundamental_filings_no_update BEFORE UPDATE OR DELETE ON fundamental_filings
  FOR EACH ROW EXECUTE FUNCTION dd_reject_observation_change();
-- ... identical UPDATE/DELETE and TRUNCATE triggers for the other four tables.

-- What research may use: observation + provenance + flag state.
CREATE VIEW fundamental_observation_status AS
SELECT o.*, p.how_obtained, p.source_concepts, p.derivation, p.mapping_note,
       EXISTS (SELECT 1 FROM fundamental_quality_flags f
               LEFT JOIN LATERAL (SELECT disposition FROM fundamental_flag_dispositions d
                                  WHERE d.flag_id = f.id ORDER BY d.decided_at DESC LIMIT 1) d ON true
               WHERE (f.observation_id = o.id OR (f.observation_id IS NULL AND f.filing_id = p.filing_id))
                 AND f.severity = 'REVIEW' AND d.disposition IS NULL) AS has_open_review,
       EXISTS (SELECT 1 FROM fundamental_quality_flags f
               JOIN LATERAL (SELECT disposition FROM fundamental_flag_dispositions d
                             WHERE d.flag_id = f.id ORDER BY d.decided_at DESC LIMIT 1) d ON true
               WHERE (f.observation_id = o.id OR (f.observation_id IS NULL AND f.filing_id = p.filing_id))
                 AND d.disposition IN ('EXCLUDED', 'SUPERSEDED_BY_OFFICIAL_SOURCE')) AS is_excluded,
       (SELECT v.status FROM fundamental_verifications v WHERE v.observation_id = o.id
        ORDER BY v.checked_at DESC LIMIT 1) AS verification
FROM fundamental_observations o
LEFT JOIN fundamental_value_provenance p ON p.observation_id = o.id;
```
The trigger function message says "fundamental_observations"; the migration would add a generic twin
(`dd_reject_change()`) for the new tables instead of editing the existing function.

### Existing 285 observations (no UPDATE needed)
A one-off backfill job **inserts** filing, provenance and flag rows:
1. For each import batch, re-read its file from `data/pilot/` and require `sha256(file) = batch.file_sha256`;
   otherwise stop (the file on disk is not the one imported).
2. Re-run the reader to regenerate observations and their provenance; match each to the stored row by
   (symbol, metric, basis, period_type, period_end, source, value, reported_at). Every stored row must match exactly one
   regenerated row, otherwise stop and report.
3. Insert `fundamental_filings` rows for the 32 imported filings and the 4 held-back ones (outcome HELD_FOR_REVIEW),
   then the flags each produces, then provenance rows for the 285 observations.
4. Record the 52 round-2 verifications in `fundamental_verifications`.
The four held-back files get dispositions only after review (section 5); none is imported by the backfill.

## 4. Accounting-aware check catalogue
Severity: **BLOCK** = the filing is not imported (data integrity only); **REVIEW** = imported values affected are hidden
from research until a disposition exists; **NOTE** = stored for context, nothing hidden.

| Code | Area | Rule | Severity | Why not an automatic error |
|---|---|---|---|---|
| ID-1 | Identities | Totals equal their components within ₹1 cr (income, PBT, PAT, balance sheet, balance-sheet lines, shareholding categories) | BLOCK | Failure means the file is internally broken; no interpretation fixes it |
| MI-1 | Minority / exceptional | Exceptional items ≈ −minority interest (within ₹1 cr) **and** minority tagged 0 or segment PBT = PBT − exceptional | REVIEW, on PBT and owners' profit only | Real exceptional items can coincide; the pattern is strong evidence, not proof. Message names the probable cause (the HDFC Bank pattern) |
| MI-2 | Minority | Owners' profit = PAT − minority interest + associates (when tagged) | BLOCK if all three tagged, else NOTE | Identity when complete; partial tagging is common |
| MI-3 | Minority | EPS × weighted shares ≈ owners' profit; tolerance 2%, widened to 5% in a quarter with a buyback, issue or split recorded in shareholding/corporate actions | REVIEW (owners' profit, EPS) | Period-end vs weighted shares differ legitimately |
| MI-4 | Segments | Segment PBT total = PBT when unallocable items are 0 | REVIEW (PBT) | Segment totals can include reclassifications |
| CS-1 | Basis | Basis stated in the file = basis in the listing; standalone filings carry no minority interest | BLOCK | Mismatch means the file is not what the listing says |
| CS-2 | Basis | Consolidated revenue ≥ standalone revenue (same period) | NOTE | Intra-group eliminations and holding structures legitimately invert it |
| CS-3 | Basis | Consolidated and standalone share counts within 1% | NOTE | Treasury shares in trusts (INFY: 404.8 vs 405.4 cr) |
| CS-4 | Basis | Bases published more than 24 h apart | NOTE | Both are timestamped separately; informs point-in-time use |
| UP-1 | Units | Monetary unit INR, decimals consistent with LevelOfRounding; per-share unit for EPS; percent scale detected from the total row | BLOCK if unit unknown; NOTE on scale detection | Unknown units cannot be converted safely |
| UP-2 | Magnitude | Value ≥ 10× or ≤ 0.1× the same metric's previous stored quarter | REVIEW | Mergers, demergers and bonus issues cause real jumps |
| UP-3 | Per share | Implied P/E from EPS and that day's close outside 1–500, or per-share values crossing a recorded split/bonus without adjustment | NOTE | Low or loss-making EPS is real; signals adjustment need |
| PD-1 | Periods | Context header period ≠ stated reporting period | NOTE (stated period used) | Known old-format quirk, handled deterministically |
| PD-2 | Periods | Quarter length 89–93 days, half 181–185, year 364–367 | BLOCK | Wrong period cannot be stored correctly |
| YT-1 | Quarter vs YTD | Nine-month and half-year cumulative values are never stored as quarters | BLOCK (programmer error if violated) | — |
| YT-2 | Quarter vs YTD | Q1 + Q2 + Q3 + Q4 = FY for flow metrics when all five are stored (tolerance ₹1 cr or 0.5%) | REVIEW on the FY value | Reclassifications between quarters in the annual audit |
| YT-3 | Quarter vs YTD | Q4 = FY − nine-month YTD (both from filings) | NOTE | Rounding |
| RC-1 | Reconciliation | Calculated shares (paid-up ÷ face value) within 1% of the shareholding filing's total for the same date | NOTE | Treasury shares, timing of allotments |
| RC-2 | Reconciliation | Balance-sheet cash = cash-flow closing cash | REVIEW on the cash value only | Definitions can differ (the HDFC Bank Mar-26 case was a wrong element, not a definition) |
| RC-3 | Reconciliation | SUMMED value equals any reported total of the same concept (e.g. borrowings) | REVIEW | Different groupings across taxonomies |
| MS-1 | Missing | Expected metric absent for the filing type and quarter (no balance sheet in Jun/Dec quarters is N/A, not missing) | NOTE | Absence is information, never imputed |
| MS-2 | Suspicious | Revenue ≤ 0, total assets ≤ 0, percentage outside 0–100, EPS sign ≠ owners' profit sign | REVIEW (BLOCK for impossible: assets ≤ 0, % outside range) | Some signs are legitimate (losses) |
| MS-3 | Suspicious | Pledge flag "true" without a pledged figure | REVIEW | Needs a sample to read pledge correctly |
| TM-1 | Timing | Published before board meeting ended; disseminated before received | BLOCK | Timestamp integrity |
| TM-2 | Timing | Published after the SEBI deadline | NOTE | Late filers are real; timestamps stay exact |
| TM-3 | Revisions | Listing marks a revised submission | NOTE; the import creates a new version | Revisions are history, not errors |

## 5. How flags become decisions (without treating every discrepancy as an error)
1. **Scope**: a REVIEW flag hides only the values it names (e.g. MI-1 hides PBT and owners' profit, not revenue or
   EPS). The rest of the filing is usable.
2. **Explanation**: every flag stores the compared numbers (`observed`) and a message naming the likely cause.
3. **Dispositions** (append-only, latest wins):
   - `ACCEPTED_AS_FILED`: the discrepancy is legitimate (e.g. CS-2 after an elimination); values become usable.
   - `SUPERSEDED_BY_OFFICIAL_SOURCE`: an official document gives the right value; it is imported as a separate observation
     (source = company results), the XBRL value stays in history but is excluded from research.
   - `EXCLUDED`: unresolved or wrong, kept out of research.
   - `EXPLAINED`: NOTE-level context recorded, no change in use.
4. **Rule dispositions** for recurring, well-understood cases only after they have been confirmed by documents; for
   example "MI-1 with official document showing no exceptional item → SUPERSEDED". Recorded with `decided_by = 'rule:MI-1-v1'`.
5. **Versioned checks**: a tolerance change bumps `check_version`; old flags stay as they were raised.
6. **Expected dispositions for the four held-back HDFC Bank filings** (to be confirmed at review): Mar-25, Sep-25, Mar-26
   consolidated → import, MI-1 REVIEW on PBT/owners' profit, `SUPERSEDED_BY_OFFICIAL_SOURCE` with the SEC 6-K values;
   Mar-26 standalone → import, RC-2 REVIEW on the XBRL cash-flow element only (not stored), `ACCEPTED_AS_FILED` for the rest.

## 6. Representative 20-company pilot
### Selection criteria
| Criterion | Why |
|---|---|
| Every reporting format: Ind-AS commercial, banking, NBFC, insurance | Each taxonomy has its own mapping |
| Size: NIFTY 50 and NIFTY Next 50 / midcap | Smaller filers make more tagging mistakes |
| At least 10 NSE sectors | Sector-specific line items (e.g. bank provisions, insurer policyholder funds) |
| Known corporate events: merger, demerger, buyback, bonus/split, losses, negative equity | Exercises versioning, MI checks, per-share adjustment |
| **Independent source available**: at least 5 companies that also file results with the US SEC (6-K) | Free, official verification channel proven in round 2 |
| PSU and private | PSUs differ in disclosure practice |
| Long history (listed before 2015) for most; one recent listing | Point-in-time depth and short-history handling |

### Proposed 20 (changes from the current list marked)
| Format | Company | Why |
|---|---|---|
| Bank | HDFCBANK | Merger, MI tagging pattern, SEC filer |
| Bank | **ICICIBANK (new)** | Large private bank with insurance subsidiaries; SEC filer |
| Bank | BANKBARODA | PSU bank |
| NBFC | BAJFINANCE | NBFC format |
| Insurance | SBILIFE | Insurance taxonomy |
| IT | INFY | Buyback; SEC filer; reference company |
| IT | **WIPRO (new)** | Second IT company; SEC filer; bonus issues |
| IT | PERSISTENT | Midcap IT |
| Pharma | **DRREDDY (new)** | SEC filer; replaces SUNPHARMA |
| Pharma | LAURUSLABS | Midcap, volatile earnings |
| FMCG | ITC | Demerger |
| Auto | MARUTI | Standalone ≈ consolidated |
| Auto | ASHOKLEY | Finance subsidiary, MI |
| Energy | RELIANCE | Large group, MI |
| Energy | ONGC | PSU, listed subsidiaries |
| Metal | TATASTEEL | Losses, impairments, overseas |
| Capital goods | BHEL | PSU, weak profits |
| Cement | ULTRACEMCO | Acquisitions |
| Realty | DLF | Lumpy revenue |
| Telecom | IDEA | Losses, negative equity |
Dropped: SUNPHARMA (pharma covered by DRREDDY with SEC verification), MARICO (FMCG covered by ITC), NYKAA (recent-listing
case; can return as a 21st if short-history handling needs testing). All 20 are in the scored universe.

### Data per company (minimum)
8 consecutive quarters (Jun-2024 to Mar-2026) of results XBRL in the basis that exists (both where both exist), the two
results listings, the shareholding listing and the 8 shareholding XBRL files; for SEC filers, the matching 6-K
exhibits as verification references. Consecutive quarters make YT-2, UP-2 and trailing-twelve-month checks possible,
which the current INFY/HDFC Bank data cannot support.

## 7. Evaluating automated providers with the validated sample
1. **Ground truth** = values with `fundamental_verifications.status = 'VERIFIED'`, plus the official values that
   superseded flagged XBRL values, plus NSE dissemination timestamps. Frozen as a named benchmark set before any
   provider data is seen.
2. **Pre-registered scorecard**, per provider, computed by script:
   | Measure | Pass mark (proposed) |
   |---|---|
   | Value accuracy on ground truth (within rounding) | ≥ 99% |
   | Reproduces known XBRL tagging errors (HDFC Bank MI cases) | reported separately: shows whether the provider uses XBRL raw or official statements |
   | Basis labelling correct (consolidated vs standalone) | 100% |
   | Period alignment (quarter vs YTD, period ends) | 100% |
   | Availability timestamp never earlier than NSE dissemination | 100% (any earlier date = look-ahead risk, disqualifying) |
   | Median timestamp lag after NSE dissemination | reported |
   | Coverage of the 20 companies × 8 quarters × required metrics | ≥ 95% |
   | As-reported vs restated: values for a past quarter unchanged after later filings | reported; restated-only providers cannot be used for strict point-in-time |
   | Licence permits personal automated use and local storage | required |
3. Provider data enters the store only as a separate `source` with `value_vintage` set honestly, so it can be compared
   observation by observation and never overwrites NSE-derived history.

## 8. Tests (to be written with the implementation)
- Migration: tables and view created; UPDATE/DELETE/TRUNCATE rejected on all five new tables; existing triggers on
  `fundamental_observations` unchanged (introspection test).
- Provenance: CHECK constraints (REPORTED ⇔ no derivation, one concept; INFERRED needs a note); every reader mapping
  produces exactly one provenance row per observation with the right `how_obtained`.
- Backfill: refuses when a file hash differs; refuses when a stored row has zero or two matches; idempotent (second
  run inserts nothing); never issues UPDATE (asserted via statement logging).
- Checks: one synthetic test per code, both firing and not firing, including the real patterns: HDFC Bank MI-1 (Mar-25,
  Sep-25, Mar-26 shapes), INFY buyback MI-3 tolerance, old-format PD-1, December-quarter MS-1 N/A, Mar-26 RC-2.
- Severity semantics: BLOCK prevents import; REVIEW hides only the named values in the status view; NOTE hides
  nothing; latest disposition wins; a later disposition does not erase earlier ones.
- Status view: point-in-time `as_of` over the view returns the same rows as today when no flags exist (regression
  against the 11 real-data point-in-time checks).
- Provider scorecard: deterministic on a fixture; an early timestamp fails the run.

## 9. Implementation sequence (each step stops for review)
1. Migration 0009 and its tests, applied to a test database only.
2. Provenance and flag emission in the readers (no import change yet); unit tests.
3. Backfill job, dry run against the real database (prints what it would insert); review the output.
4. Apply migration 0009 to the real database and run the backfill (inserts only).
5. Record the 52 verifications and the four held-back filings as `HELD_FOR_REVIEW` with their flags.
6. Review and record dispositions for the four held-back filings; import them plus the superseding official values.
7. Collect the 20-company pilot data (manual NSE downloads; SEC 6-K references for the five filers).
8. Freeze the benchmark set; only then evaluate one provider against it.
Scoring weights, paper portfolios and trading are untouched throughout; fundamentals reach scoring only through a
separate, later proposal.
