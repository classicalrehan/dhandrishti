# Recommendation tracking: implementation and verification review (2026-10-12)

Scope: steps A–H of the approved plan (staged migration 0010, recorder, outcomes, verification, clone tests,
fingerprints). Design reference: `docs/recommendation-tracking.md`.

**Status: implemented and verified on throwaway `dd_*` test databases and two production clones only.
Migration 0010 is staged and has NOT been applied to `dhandrishti_kite` or `dhandrishti`.**

Constraints followed: no change to scoring weights or formulas; PIT fundamentals not connected to scoring;
paper portfolios, orders and parameters untouched; no order execution; no API change; no migration applied to
production; replay results excluded from the LIVE track record; existing records preserved.

---

## 1. Step A: conflicts between the plan and the repository

| # | Area | Finding in the code | Resolution |
|---|---|---|---|
| 1 | Migration numbering / staging | `apply_staged()` (`db/staged.py`) applied every file in `migrations-staged/`, so 0010 could not be tested without 0009. | Added an optional `only` filter to `migrate()`/`pending()`/`apply_staged()`. Default behaviour unchanged. Phase 1 tests now apply only `0009_fundamental_quality.sql`; tracking tests apply only `0010_recommendation_tracking.sql`. |
| 2 | Transaction boundary | `run_scoring` sets autocommit, commits the RUNNING row in `start_run`, then saves results, indicator series and `finish_run` in one transaction. The plan's "same transaction" would let a recorder bug fail production scoring, and production has no tracking tables. | Recorder runs in its **own transaction after the run commits** (`record_if_installed`). It returns without writing when the tables are absent and catches every exception (logged). A missing record is reported by the summary as "successful scoring runs without record". |
| 3 | Cost-model interface | `trading.costs.delivery_charges(side, value)` rounds to paise, adds a flat DP charge (₹15.34 per sell). Paper trading (`trading/paper.py`) uses whole shares and fills at the open with no slippage. The backtester uses flat 15 / 13.5 bps (≈3 bps slippage included). | Outcomes reuse `delivery_charges()` on a ₹20,000 notional with fractional shares, and store gross, net at 0 bps (paper-equivalent fills), net at 3 bps (base assumption), 10 and 25 bps. Differences are documented. |
| 4 | D7 recommendation definition vs paper portfolios | All three paper portfolios buy the top 5 **eligible** stocks (risk ≤ MEDIUM; #3 also ≥ 252 bars), keep holdings within rank 10/15/20, and have `min_confidence = null`. Every current score is LOW confidence, so any confidence floor gives zero recommendations. | Policy `2026.10-top5-v1`: candidate = overall rank ≤ 5; RECOMMENDED if risk ≤ MEDIUM (portfolio #1's documented rule), no confidence floor; otherwise EXCLUDED_CANDIDATE with reasons, not replaced by rank 6+. Eligibility and reasons are recorded for **every** scored stock, so "top 5 eligible" can be derived later. |
| 5 | Trading calendar | `packages/shared/src/nse-holidays.json` covers 2026 only. | `next_session()` returns None when the year is not covered → failure `CALENDAR_UNKNOWN` (cannot be LIVE). |
| 6 | Clean git tree (D4) | Phase 1 files are uncommitted. `.localdb/` (a full PostgreSQL data directory) is tracked in git; if a local server runs from it the tree is dirty. | Flagged, not changed. Every run is DEVELOPMENT/REPLAY until the tree is clean. |
| 7 | Price writes | Daily ingest refetches ~1,500 days × 201 stocks and upserts, resetting `ingested_at` every time. `daily_prices` and `index_prices` are Timescale hypertables (uncompressed), no existing triggers. | Update trigger fires only when open/high/low/close/volume/provenance/source change; inserts and deletes are logged; a truncate leaves a marker. On hypertables row triggers fire on chunks (`TG_TABLE_NAME` = chunk name, which failed the first smoke test), so the table name is passed as a trigger argument. |
| 8 | Accuracy of `docs/research/2026-10-phase1-audit.md` (8 Oct) | States prices from 2022 (now 2012-01-02 to 2026-10-09) and no per-factor IC (`research/factors.py` now has it). Nothing else checked conflicted. | Noted only. |
| 9 | Paper-trading path | `jobs/paper.py` re-scores from `load_market`/`load_history` and calls `score_universe` directly; it never reads `score_history` or other score tables. Only shared surface: `daily_prices`/`index_prices`. | Paper code untouched; the only change in its data path (price-log triggers) exists only where 0010 is applied. Verified in §6. |

Readers of the score tables (unchanged): API `apps/api/src/repositories/pg-market-repository.ts` (by `as_of` +
config version), `jobs/holdings.py` (by run id), AI/MCP via the API.

Production paper portfolio parameters read (2026-10-12):

| id | name | params (relevant) | status | last processed |
|---|---|---|---|---|
| 1 | Monthly top 5 | top_n 5, max_risk MEDIUM, min_confidence null, rank_buffer 10, stop 10% | ACTIVE | 2026-10-09 |
| 2 | Quarterly top 5 (low turnover) | top_n 5, max_risk MEDIUM, min_confidence null, rank_buffer 15, stop 10% | ACTIVE | 2026-10-09 |
| 3 | Refined: 15% stop, keep top 20, 1y history | top_n 5, max_risk MEDIUM, min_confidence null, rank_buffer 20, stop 15%, min_history_bars 252 | ACTIVE | 2026-10-09 |

---

## 2. Implementation

### 2.1 Files

New:
- `packages/database/migrations-staged/0010_recommendation_tracking.sql`
- `apps/worker/src/dhandrishti/tracking/__init__.py`
- `apps/worker/src/dhandrishti/tracking/manifest.py`: canonical JSON, per-item SHA-256, `build_manifest`, `input_hash`, `result_hash`, `output_hash`, `diff`
- `apps/worker/src/dhandrishti/tracking/policy.py`: `POLICY_V1`, `exclusion_reasons`, `select`, `register`
- `apps/worker/src/dhandrishti/tracking/recorder.py`: `code_info`, `next_session`, `qualify`, `record_run`, `record_if_installed`, `backfill_from_score_history`
- `apps/worker/src/dhandrishti/tracking/outcomes.py`: `METHOD_V1`, `net_return`, `evaluate`, `update`
- `apps/worker/src/dhandrishti/tracking/verify.py`: `log_coverage`, reconstruction via temporary shadow tables, `verify_run`
- `apps/worker/src/dhandrishti/tracking/summary.py`: `track_record`, `format_report`
- `apps/worker/src/dhandrishti/jobs/tracking.py`: CLI `outcomes | verify | summary | backfill`
- `apps/worker/tests/test_tracking.py` (50 tests)
- `docs/recommendation-tracking.md`

Modified:
- `apps/worker/src/dhandrishti/db/migrate.py`: optional `only` argument (raises `FileNotFoundError` for unknown names).
- `apps/worker/src/dhandrishti/db/staged.py`: `apply_staged(conn, only=None)`.
- `apps/worker/src/dhandrishti/jobs/run_scoring.py`: reads `clock_timestamp()` before `load_market`; after the run commits, calls `record_if_installed(...)`. No other change.
- `apps/worker/tests/test_quality_controls.py` (Phase 1, untracked): fixtures apply only 0009.

Not modified: `scoring.py`, `scoring-config.json`, `trading/`, `jobs/paper.py`, `backtesting/`, `research/`,
`db/market_repository.py`, `db/score_repository.py`, all API/web/AI/MCP code, migrations 0001–0008, staged 0009.

### 2.2 Migration 0010 contents
- Function `dd_reject_tracking_change()` (separate from 0009's `dd_reject_change`).
- `price_change_log` + function `dd_log_price_change(table)` + 6 triggers:
  `daily_prices_log_insert_delete`, `daily_prices_log_update` (WHEN values distinct), `daily_prices_log_truncate`,
  and the same three on `index_prices`. Two `LOG_START` rows are inserted by the migration.
- `recommendation_policies`, `outcome_methods` (versioned, hash-checked).
- `recommendation_runs`: `run_id` (FK `scoring_runs`), `record_kind` LIVE/DEVELOPMENT/REPLAY/BACKFILLED,
  `qualification_failures`, `as_of`, `decision_at` (as_of 15:30 IST), `inputs_loaded_at`, `scored_at`,
  `entry_session`, `entry_deadline` (09:15 IST), config version + SHA-256, `code_commit`, `code_dirty`,
  `lookback_bars`, `input_hash`, `input_manifest`, `output_hash`, provenance, counts, regime/breadth/sectors,
  `policy_version`. CHECKs: LIVE ⇔ no failures; non-BACKFILLED needs manifest, hashes and load time; LIVE needs
  commit, clean tree, non-MOCK, inputs after the close, recorded before the entry deadline; `entry_session > as_of`.
- `recommendation_scores`: per stock rank, scores, confidence, coverage, risk, component scores and coverage,
  `last_bar_date`, `eligible`, `exclusion_reasons`, `selection` (RECOMMENDED / EXCLUDED_CANDIDATE /
  NOT_CANDIDATE), full `result` and its hash. CHECKs tie eligibility, reasons and selection together.
- `recommendation_outcomes`: per stock × horizon (20/60/120/252) × method × `evaluation_hash`; status
  COMPLETE / SUSPECT_PRICE_JUMP / BENCHMARK_MISSING / NO_ENTRY_PRICE / NO_EXIT_PRICE; entry/exit, sessions held,
  gross, net, net without slippage, slippage sensitivity, charges, NIFTY return and excess, universe return and
  excess, MAE + reliability, detail. CHECKs: no return for missing prices; COMPLETE needs the benchmark;
  exit after entry; `computed_at >= exit_date`.
- View `recommendation_outcome_latest`.
- `run_verifications`: status REPRODUCED / INPUTS_CHANGED / CODE_CHANGED / INSUFFICIENT_INPUT_HISTORY /
  VERIFICATION_FAILED, inputs source CURRENT / RECONSTRUCTED, code commit, detail.
- 14 append-only triggers (UPDATE/DELETE and TRUNCATE) on the 7 tables.

### 2.3 Record qualification (D4)
Failures: `MOCK_DATA`, `NO_GIT_COMMIT`, `UNCOMMITTED_CODE` (any tracked or untracked change), `INPUTS_BEFORE_SETTLEMENT`
(before 16:30 IST on as_of), `NIFTY_NOT_UPDATED`, `CALENDAR_UNKNOWN`, `SCORED_AFTER_NEXT_OPEN` (→ REPLAY).
No failures → LIVE; otherwise DEVELOPMENT (or REPLAY).

### 2.4 Outcome method `outcome-v1` (D6)
NIFTY 50 session calendar; entry = open of the session after as_of (up to 3 sessions late if no bar); exit = open of
planned entry + h (up to 3 sessions late); a horizon is evaluated only once planned exit + 3 sessions exist, all
stocks at once. ₹20,000 notional, fractional shares, `delivery_charges()` (STT 0.1% each side, stamp 0.015% buy,
NSE 0.00307%, SEBI ₹10/crore, GST 18% on fees, DP ₹15.34 per sell; checked 2026-10-06). Slippage 3 bps/side is an
assumption; sensitivity at 0, 10, 25 bps. Benchmarks: NIFTY 50 price index open-to-open on the stock's own dates
(no costs); equal-weight mean net return of the run's COMPLETE outcomes. Suspect move threshold 35%.

### 2.5 Verification (D2)
1. Load inputs from current tables; compare manifest hash.
2. If different: require price-log coverage (LOG_START before `inputs_loaded_at`, no TRUNCATE after) or report
   INSUFFICIENT_INPUT_HISTORY; otherwise rebuild `daily_prices`/`index_prices` as of `inputs_loaded_at` into
   `ON COMMIT DROP` temporary tables that shadow the real ones, reload with the unchanged `load_market`, compare.
   Still different → INPUTS_CHANGED (unlogged tables: securities, fundamentals, events).
3. Re-score with the recorded config (file config or stored copy, whichever matches the recorded SHA-256);
   identical output hash → REPRODUCED, else CODE_CHANGED with differing symbols.
Requires an autocommit connection (otherwise VERIFICATION_FAILED). Nothing is written except the
`run_verifications` row.

### 2.6 Track-record summary (D5, D7)
LIVE runs only by default (other kinds labelled "NOT the official track record"). Per run, equal-weight basket
of RECOMMENDED stocks; headline sample = non-overlapping runs (entry ≥ previous entry + h sessions). Fewer than
12 → `INSUFFICIENT_EVIDENCE`, "No conclusion can be drawn". Reports matured/pending runs, scoring runs without a
record, statuses of recommended and excluded candidates, exclusion reasons, gross / net (0, 3, 10, 25 bps) /
excess vs NIFTY / excess vs universe / MAE, simple t over non-overlapping runs and Newey-West t over all runs,
and listed limitations.

---

## 3. Tests: commands and actual results

Database server: `dhandrishti-postgres-1` (Docker), test databases `dd_*` created and dropped per test.

| Command | Result |
|---|---|
| Smoke test of 0010 alone on a throwaway DB (first version) | **Failed**: `price_change_log_table_name_check` violated, table name was the chunk `_hyper_1_1_chunk`. Fixed (trigger argument). |
| Smoke test after fix | Passed: LOG_START ×2, INSERT ×2, identical re-upsert not logged, UPDATE 1.5→1.6, DELETE, TRUNCATE marker. |
| `cd apps/worker && DD_TEST_DATABASE_URL=postgresql://dhandrishti:dhandrishti_dev@localhost:5432/postgres uv run pytest -o addopts="" -x -q tests/test_tracking.py` (first run) | 49 passed, **1 failed**: `test_decisions_never_read_tracking_data` matched `tracking_error_pct` in `backtesting/metrics.py` (false positive). Pattern tightened. |
| same, after the fix | **50 passed in 118.87s** |
| `cd apps/worker && DD_TEST_DATABASE_URL=… uv run pytest -o addopts="" -q -rs` | **291 passed in 181.91s** (241 existing + 50 new), 0 skipped |
| `npx turbo run typecheck test` (repo root) | **Tasks: 14 successful, 14 total** |
| API Redis/pg integration tests (`pnpm test:integration`) | **Not run** (Redis container stopped; API code unchanged). |

Tests in `apps/worker/tests/test_tracking.py`:
- Schema: `test_0010_is_staged_and_independent_of_0009`; `test_staged_migration_refuses_research_databases`
  [dhandrishti, dhandrishti_kite, research]; `test_only_filter_rejects_unknown_files`;
  `test_tracking_tables_are_append_only` (UPDATE/DELETE/TRUNCATE on all 7 tables); `test_run_constraints` (5 cases);
  `test_live_run_requires_every_condition`; `test_score_and_outcome_constraints`;
  `test_price_log_records_real_changes_only`.
- Recorder: `test_scoring_is_unchanged_and_unrecorded_without_0010`; `test_rerunning_a_day_keeps_both_records`;
  `test_recording_failure_never_fails_scoring`; `test_qualification` (8 cases);
  `test_next_session_uses_the_holiday_calendar`; `test_live_record_end_to_end`;
  `test_input_hash_is_deterministic_and_names_what_changed`; `test_prices_after_as_of_change_nothing`;
  `test_recorder_refuses_inputs_dated_after_as_of`; `test_policy_selection`;
  `test_every_scored_stock_is_recorded_with_eligibility`; `test_policy_version_cannot_change_silently`.
- Outcomes (hand-built prices): `test_outcome_matches_hand_calculation` (gross 10%, net by hand formula, charges,
  NIFTY 5%, excess, MAE −10%, universe mean, slippage ordering); `test_outcome_is_pending_until_the_grace_sessions_exist`;
  `test_invalid_outcomes_are_labelled_not_filled` (NO_ENTRY_PRICE, NO_EXIT_PRICE, SUSPECT_PRICE_JUMP, late entry);
  `test_missing_benchmark_is_labelled`; `test_outcomes_are_idempotent_and_revisions_append`;
  `test_outcome_method_cannot_change_silently`; `test_outcome_charges_are_the_paper_trading_charges`.
- Summary: `test_summary_counts_only_non_overlapping_live_runs`; `test_summary_reports_excluded_candidates`.
- Verification: `test_verify_reproduces_from_current_inputs`; `test_verify_reconstructs_restated_prices`;
  `test_verify_reports_unlogged_input_changes`; `test_verify_detects_code_changes`;
  `test_verify_never_claims_reproduction_after_a_truncate`; `test_verify_backfilled_and_broken_records`;
  `test_verify_requires_autocommit`.
- Isolation: `test_decisions_never_read_tracking_data` (scoring, market repository, paper job, trading,
  backtesting, research).

---

## 4. Production fingerprints (`dhandrishti_kite`)

Method: read-only REPEATABLE READ transaction; per public table row count, MD5 of all rows (sorted text), MD5 of
row versions (`xmin`); plus table, view, trigger and `dd_*` function lists. Taken before step G and after step H.
Result: **IDENTICAL (29 fields compared)**, including every row version. Mock database `dhandrishti`:
**IDENTICAL (25 fields compared)**.

| Table | Rows | Content MD5 | Row-version MD5 | Unchanged |
|---|---:|---|---|---|
| backtest_equity | 2742 | c16fe0891b25de95644c794dde689463 | d44f933b4b6dff858de35930cf535aaa | yes |
| backtest_holdings | 1020 | c1ce0b9887300fd82379527f9e955155 | 30338310130e9ff15e543aeb1fad232c | yes |
| backtest_runs | 4 | 2d8db489ff1b78d6028f22632e8aacf8 | 80911d7194437a7783a29db3f0b77a8c | yes |
| corporate_events | 0 | d41d8cd98f00b204e9800998ecf8427e | d41d8cd98f00b204e9800998ecf8427e | yes |
| daily_prices | 613718 | bdb0352ec6b38d6898f2a7b8760fb435 | 94f2b8d264cdbd439ebef01707f0efe6 | yes |
| fundamental_import_batches | 32 | c330d4777c73454c6a5e13d5d848d50a | c5aac828c0f8f428b44053f8cd799fce | yes |
| fundamental_observations | 285 | 5d71fa28b94d58aad9d7fb0664854160 | 370b11c70ec3c55d9dc69b46b87176c5 | yes |
| fundamentals | 0 | d41d8cd98f00b204e9800998ecf8427e | d41d8cd98f00b204e9800998ecf8427e | yes |
| holding_items | 16 | c579882fe0b88c223e879e4513db2638 | 297fd762521110fa7b4bdfdf5ac03ca7 | yes |
| holdings_snapshots | 2 | 502619b4d7a4849ee37152f3b3cd6bf4 | d0e081984454842ff6bd599ac1470ce6 | yes |
| index_prices | 10977 | a8bbab45f1498c060035dab3f6e067b4 | 1658953d33f7ebf252893a55f1ee953f | yes |
| indicator_series | 59839 | bcf49dcdbde23be135e69286bf524ca3 | d3fc76e3193a564604957d4095270bb9 | yes |
| market_regime_history | 4 | bc499fef7704609bb010768944b39814 | 5394dfc2e952143b01c560a7f4c54dac | yes |
| news_items | 0 | d41d8cd98f00b204e9800998ecf8427e | d41d8cd98f00b204e9800998ecf8427e | yes |
| paper_daily | 10 | d5566b6de0fe20c8f589e05414977c7f | 2e5bed44a9685db074632a8101783bac | yes |
| paper_orders | 15 | 5a3b1a492a5cd423cac2260a4401faa5 | 847acb493df98711783afed5e2f1df29 | yes |
| paper_portfolios | 3 | 6816d7e707ea7aff479077aebccea800 | 044a1d7acdb26c4bc35fd66dcc5639ee | yes |
| paper_positions | 15 | 96890b810989ba4821c0b4d9d34ffb58 | cec48bb12f6a2f876132b26cb6397bcb | yes |
| schema_migrations | 8 | 3027dcc8ebd6f6fa4ff066b744dd41ab | f0e94de2b7a895c0a8d7fc94ebc490f0 | yes |
| score_history | 490 | 866e65bf4612dc1c41b81675ca4bae5d | 9999156e243c849a0b69b2e0c6e793db | yes |
| scoring_config_versions | 1 | b3d1a982ecce7c990137e6aaa7bfdf02 | b0b183c207f46f0cca7dc63b2604f5cc | yes |
| scoring_runs | 5 | 3cd02b3c123c62bcde310bd0abdda3e6 | 5c1315b700dce45fec24d13b4806a71f | yes |
| sector_strength_history | 67 | f1603888be9de84b4c866ff653d1ded4 | 62a845ee29af003f31d29ac41e5a313e | yes |
| securities | 201 | c137e18ff1559c41b96068da09b1fdbf | b60a722e758ec403ff542e20f94bb737 | yes |
| technical_indicators | 490 | 3fd8f320e4fe649974418f53e1b134fa | 9999156e243c849a0b69b2e0c6e793db | yes |

`dd_*` functions: `dd_make_hypertable` 76bc48856a2c24706e9f4bb830cc8540, `dd_reject_observation_change`
f19d50591c26009ebf58611f8d4a8134 (unchanged since Phase 1). `fundamental_observations` row versions
`370b11c7…` equal the Phase 1 baseline.

Direct checks after step H: `schema_migrations` = 0001–0008 only; tracking tables 0; price-log triggers 0;
paper portfolios `1:ACTIVE:2026-10-09, 2:ACTIVE:2026-10-09, 3:ACTIVE:2026-10-09`.
`DD_DATABASE_URL=…/dhandrishti_kite uv run python -m dhandrishti.jobs.tracking summary` →
`error: tracking tables are not installed in 'dhandrishti_kite' (staged migration 0010)`, exit 2 (read-only check).

Production reads performed: fingerprints, the paper-portfolio parameter query, and one `pg_dump -Fc` for the clones.

---

## 5. Database-clone comparisons (step G)

Clones restored from `pg_dump -Fc dhandrishti_kite` with `timescaledb_pre_restore()` / `timescaledb_post_restore()`:
`dd_clone_a` (control: current schema) and `dd_clone_b` (0010 applied via `apply_staged(only=[0010])`).
Experiment script refused any database other than these two.

| Check | Result |
|---|---|
| Clone A vs production (content) | IDENTICAL (29 fields) |
| Clone B vs production (content) | IDENTICAL (29 fields) |
| Scoring 2026-10-09 with the new code: A vs B engine output | identical |
| A vs B stored `score_history` rows (201) | identical |
| New run vs **production run 5** stored results | **identical, 201/201, 0 differences** |
| Clone A tracking tables | none (recorder skipped) |
| A vs production, ignoring run ids and `scoring_runs` timestamps | only `scoring_runs` (one added row, run 6) |
| B vs production, same exclusions | `schema_migrations` (0010 row) and `scoring_runs` (run 6) |
| A vs B, same exclusions | only `schema_migrations` |
| B extra objects | 7 tables, 20 triggers (6 price-log, 14 append-only) |
| B records | runs 1, 2, 4, 5 BACKFILLED (failures `[BACKFILLED]`, 44/44/201/201 stocks); run 6 REPLAY (`UNCOMMITTED_CODE`, `SCORED_AFTER_NEXT_OPEN`), 201 stocks. Run 3 absent: overwritten in `score_history` before this work. |
| B selection | each run: 5 RECOMMENDED, rest NOT_CANDIDATE, 0 EXCLUDED_CANDIDATE |
| B run 6 recommended | 1 MEESHO (MEDIUM risk), 2 NYKAA, 3 LENSKART, 4 DIVISLAB, 5 KOTAKBANK (LOW risk); all LOW confidence |
| B recorded scores vs `score_history` for run 6 | 201/201 equal |
| Outcomes update on B | evaluated 0, pending 20, rows 0 (no horizon matured) |
| Summary on B | LIVE: 0 runs, INSUFFICIENT_EVIDENCE, 0 non-overlapping; REPLAY: 1 run, 1 pending |
| Price log on B after scoring | LOG_START ×2 only |

---

## 6. Paper-portfolio regression checks

| Check | Result |
|---|---|
| Paper tables (portfolios, positions, orders, daily) in A and B after scoring vs production | identical content |
| Identical synthetic session 2026-10-12 inserted in both clones (prices derived from 2026-10-09 closes, source `synthetic-test`), then `jobs.paper.run` on each | identical output: #1 and #2 equity ₹96,437 (−3.56%), #3 ₹98,805 (−1.20%), 0 fills, 5 holdings each, ACTIVE (synthetic prices: not a performance figure) |
| Paper tables A vs B after that run | identical: paper_daily 13/13 (production 10), paper_orders 15/15, paper_portfolios 3/3, paper_positions 15/15 |
| Price log on B for the synthetic day | INSERT 201 (daily) + 3 (index) |
| One-year replay (2025-10-01 to 2026-10-09) of portfolio #1 and #3 rules via `research.replay`, A vs B | identical equity series, trades and charges (final ₹115,328.28 and ₹120,189.82; survivorship-biased replay, not evidence of performance) |
| Paper code | not modified (git) |

---

## 7. Reproducibility tests

| Scenario | Where | Status |
|---|---|---|
| Fresh recorded run, unchanged data | clone B run 6; test | REPRODUCED (CURRENT) |
| Prices of one stock halved before 2026-06-30 (simulated split restatement, 135 rows) | clone B (MEESHO); test (with a deleted bar) | REPRODUCED (RECONSTRUCTED) |
| Sector of that stock renamed afterwards | clone B; test | INPUTS_CHANGED (`security: [symbol]`) |
| Scoring function altered | test | CODE_CHANGED (1 stock differs) |
| TRUNCATE + reinsert of `daily_prices` after the run | test | INSUFFICIENT_INPUT_HISTORY ("truncated after the run") |
| BACKFILLED runs | clone B runs 1, 2, 4, 5; test | INSUFFICIENT_INPUT_HISTORY |
| Recorded config hash matching nothing | test | VERIFICATION_FAILED |
| Non-autocommit connection | test | VERIFICATION_FAILED |
| Clone B verification log | | 6 REPRODUCED/CURRENT; 1, 2, 4, 5 INSUFFICIENT; 6 REPRODUCED/RECONSTRUCTED; 6 INPUTS_CHANGED |

---

## 8. Known limitations and risks

Reproducibility:
- Only `daily_prices` and `index_prices` are logged. Changes to `securities`, `fundamentals` or `corporate_events`
  after a run make it unverifiable (INPUTS_CHANGED).
- Runs before the log started (all BACKFILLED runs) cannot be rebuilt; a TRUNCATE after a run ends reconstruction.
- A hash proves equality; it cannot restore data. Full input snapshots are not stored (per D2).
- Run 3 (2026-10-08) is permanently lost.
- Change timestamps use `clock_timestamp()` inside the writing transaction; an ingest overlapping a scoring run
  could be misattributed. The hash comparison then reports a mismatch rather than a false REPRODUCED.

Track record:
- No LIVE record is possible yet: needs a clean committed tree (Phase 1 and this work are uncommitted; `.localdb/`
  is tracked), real data, and the pipeline finishing between 16:30 IST and the next 09:15 IST.
- First 20-session outcomes about four weeks after the first LIVE run; 12 non-overlapping 252-session periods
  take about 12 years. The 12-period threshold is for display, not significance.
- Holiday calendar ends 2026: late-December runs become `CALENDAR_UNKNOWN` until 2027 holidays are added.

Measurement and bias:
- Universe is today's NIFTY 200: the equal-weight benchmark carries survivorship bias.
- Returns are price-only; NIFTY 50 price index, no costs on the benchmark.
- Slippage 3 bps/side is assumed, not measured. Fractional shares vs paper's whole shares.
- A late entry does not move the exit; delayed rows hold slightly fewer sessions.
- Policy v1 (rank ≤ 5 and eligible) differs from the paper portfolios (top 5 eligible plus rank buffers).
- Scores are price-only (fundamentals neutral) and all LOW confidence.

Operational:
- Price-log volume ~205 rows per normal day; a provider re-adjusting long histories could add many more.
- `record_if_installed` swallows errors by design; failures appear in logs and as unrecorded runs in the summary.
- API/UI do not expose tracking yet (out of scope this phase).

---

## 9. Reviewing and applying the staged migration

Review and test (throwaway databases only):
```sh
less packages/database/migrations-staged/0010_recommendation_tracking.sql
docker compose up -d postgres
cd apps/worker
DD_TEST_DATABASE_URL=postgresql://dhandrishti:dhandrishti_dev@localhost:5432/postgres \
  uv run pytest -o addopts="" tests/test_tracking.py
docker exec dhandrishti-postgres-1 createdb -U dhandrishti dd_review
uv run python -c "import psycopg; from dhandrishti.db.staged import apply_staged; \
c = psycopg.connect('postgresql://dhandrishti:dhandrishti_dev@localhost:5432/dd_review', autocommit=True); \
print(apply_staged(c, only=['0010_recommendation_tracking.sql']))"
```

Production promotion (NOT done; requires explicit approval): `pg_dump -Fc` backup of `dhandrishti_kite`;
move the file into `packages/database/migrations/`; `pnpm db:migrate` against `dhandrishti_kite`; optionally
`jobs.tracking backfill --apply`; compare fingerprints. Rollback: revert the code commit (recording stops; existing
tables were always written as before), drop the new tables/view/triggers/functions with a forward migration, or
restore the backup.

---

## 10. State at the end of the session
- Clones `dd_clone_a`, `dd_clone_b` dropped; dump file removed; 0 `dd_*` databases left.
- Postgres container stopped again (it was stopped when the session started); Redis stopped throughout.

### Git status (branch `20stock`, HEAD `7dc55ff Add 20-stock validation and staged db support`), captured immediately before this report file was created
```
 M apps/worker/src/dhandrishti/db/migrate.py
 M apps/worker/src/dhandrishti/db/staged.py
 M apps/worker/src/dhandrishti/jobs/run_scoring.py
 M apps/worker/src/dhandrishti/pit/adapters/nse_shp.py
 M apps/worker/src/dhandrishti/pit/adapters/nse_xbrl.py
 M apps/worker/tests/test_nse_xbrl.py
?? apps/worker/src/dhandrishti/jobs/tracking.py
?? apps/worker/src/dhandrishti/pit/backfill.py
?? apps/worker/src/dhandrishti/pit/controls.py
?? apps/worker/src/dhandrishti/tracking/
?? apps/worker/tests/test_quality_controls.py
?? apps/worker/tests/test_tracking.py
?? docs/recommendation-tracking.md
?? packages/database/migrations-staged/0010_recommendation_tracking.sql
```
This report adds one more untracked file:
`docs/research/2026-10-12-recommendation-tracking-implementation-review.md`.
The `nse_shp.py`, `nse_xbrl.py`, `test_nse_xbrl.py`, `pit/backfill.py`, `pit/controls.py` and
`test_quality_controls.py` entries are Phase 1 (fundamentals quality) work, also uncommitted.
