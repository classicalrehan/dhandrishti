# Recommendation tracking: final review (2026-10-12)

Project: DhanDrishti, a personal NSE equity research system (Python worker, PostgreSQL/TimescaleDB).
Task: append-only records of every scoring run, forward outcomes of recommendations (20/60/120/252 trading
sessions), and verification that past runs can be reproduced. Delivered as **staged migration 0010** plus worker
code. Detailed records: `docs/recommendation-tracking.md` (design, current) and
`docs/research/2026-10-12-recommendation-tracking-implementation-review.md` (implementation steps A–H; written
before the hardening round below, so its test counts and table list are out of date).

## 1. Final status
- Implemented, hardened and tested on throwaway databases and on two restored copies of production.
- **Migration 0010 is staged only.** It is not applied to the production databases (`dhandrishti_kite`, real
  data; `dhandrishti`, mock data). Until it is, the new code does nothing in production.
- No scoring weights, formulas, paper portfolios, paper orders, paper parameters, API or UI were changed.
  PIT fundamentals are not connected to scoring. No order-execution code exists.
- All work is **uncommitted** in git (branch `20stock`, HEAD `7dc55ff`).

## 2. Files changed
Recommendation tracking (this task):
| File | State |
|---|---|
| `packages/database/migrations-staged/0010_recommendation_tracking.sql` | new (staged migration) |
| `packages/database/rollback/0010_recommendation_tracking.rollback.sql` | new (manual rollback script, outside all migration folders) |
| `apps/worker/src/dhandrishti/tracking/` (`manifest.py`, `policy.py`, `recorder.py`, `outcomes.py`, `verify.py`, `summary.py`, `__init__.py`) | new |
| `apps/worker/src/dhandrishti/jobs/tracking.py` | new CLI: `status`, `record`, `outcomes`, `verify`, `summary`, `backfill` |
| `apps/worker/tests/test_tracking.py` | new, 67 tests |
| `apps/worker/src/dhandrishti/jobs/run_scoring.py` | +5 lines: read the DB clock before loading inputs; call the recorder after the run commits |
| `apps/worker/src/dhandrishti/db/migrate.py`, `db/staged.py` | optional `only=[...]` filter so 0009 and 0010 can be applied separately (default behaviour unchanged) |
| `docs/recommendation-tracking.md`, the two `docs/research/2026-10-12-*.md` reports | new |

Also uncommitted, from the earlier fundamentals-quality task (Phase 1, staged migration 0009):
`pit/adapters/nse_shp.py`, `pit/adapters/nse_xbrl.py`, `tests/test_nse_xbrl.py` (modified), `pit/backfill.py`,
`pit/controls.py`, `tests/test_quality_controls.py` (new; its fixtures were changed in this task to apply only 0009).

## 3. What 0010 adds
- 8 append-only tables (UPDATE, DELETE and TRUNCATE rejected by triggers, including via `TRUNCATE ... CASCADE`):
  `recommendation_runs`, `recommendation_scores`, `recommendation_outcomes`, `run_verifications`,
  `tracking_failures`, `price_change_log`, `recommendation_policies`, `outcome_methods`; view
  `recommendation_outcome_latest`.
- 6 triggers on the existing price tables `daily_prices` and `index_prices` that log real changes only
  (identical re-upserts by the daily refetch are not logged). No column, constraint or row of an existing table
  changes.
- Record kinds: **LIVE** (official track record; database CHECKs require real data, a clean git commit, inputs
  read after 16:30 IST, recorded before the next session's 09:15 open, not a retry), **DEVELOPMENT**, **REPLAY**
  (scored after the next open), **BACKFILLED** (copied from old score history; no inputs manifest).
- Recommendation policy v1: overall rank ≤ 5 and risk ≤ MEDIUM; failing candidates recorded with reasons.
- Outcomes are hypothetical: next-open entry, fixed ₹20,000 notional, fractional shares, Zerodha delivery
  charges, 3 bps/side slippage assumed (also 0/10/25 bps), versus NIFTY 50 and the equal-weight universe.
  Reports label them "HYPOTHETICAL RECOMMENDATION RETURNS", separate from paper-portfolio and backtest results.
- Verification statuses: REPRODUCED, CODE_CHANGED, INPUTS_CHANGED, INSUFFICIENT_INPUT_HISTORY,
  VERIFICATION_FAILED. REPRODUCED requires the recomputed input hash to equal the recorded one.
- Recorder failures never break scoring; they are stored with a diagnostic, reported by `jobs.tracking status`
  (exit code 1 when a run since installation has no record), and can be retried without duplicates. A retried
  record is never LIVE.

## 4. Tests executed (actual results)
| Run | Result |
|---|---|
| Worker suite with database, final | **308 passed, 0 failed, 0 skipped** (241 pre-existing + 67 new) |
| Scoring, paper, golden-fixture, pipeline and tracking tests together, final | **131 passed** |
| `npx turbo run typecheck test` (all packages), final | **14/14 tasks successful** |
| API/Redis integration tests (`pnpm test:integration`) | **not run** (Redis stopped; API code unchanged) |
| Lint (`ruff`) | **not run** (not installed in the worker environment) |

Failures encountered during the work (all fixed and re-run; none remain):
1. First smoke test of 0010 failed: on TimescaleDB hypertables, row triggers run on chunks, so the logged table
   name was a chunk name. Fixed by passing the table name as a trigger argument.
2. An isolation test falsely matched `tracking_error_pct` in backtest metrics; pattern tightened.
3. Rollback test compared `schema_migrations` content, which the rollback is meant to change; corrected.
4. A `drop_chunks` test dropped chunks outside the run's inputs, so REPRODUCED was correct; the test now drops
   the chunk that holds the inputs (result: INSUFFICIENT_INPUT_HISTORY).

Warnings: `pg_dump` of production printed a TimescaleDB "circular foreign-key constraints" notice
(`continuous_agg`); the restore succeeded and both copies matched production exactly.

## 5. Production database safety (verified)
- Method: read-only fingerprints of every table (row count, content MD5, row-version MD5) plus tables, views,
  triggers and functions.
- `dhandrishti_kite`: **identical (29/29 fields)** at every comparison, from before the clone tests through the
  end of the hardening review, including row versions (no row was rewritten). `dhandrishti`: identical (25/25).
- `schema_migrations` in production: 0001–0008 only. Tracking tables: 0. Price-log triggers: 0.
- Production reads only: fingerprints, two settings queries, one `pg_dump` (for the clones, which were then
  dropped), and one in-memory re-scoring inside a READ ONLY transaction. No `dd_*` test databases remain.
- The production command `jobs.tracking summary` refuses with "tracking tables are not installed" (exit 2).

## 6. Scoring and paper portfolios unchanged (verified)
- Re-scoring production's 2026-10-09 inputs with the final code reproduces stored **run 5 exactly: 201/201
  stocks, same regime** (BEARISH, 16.5, confidence 67).
- On the production copies, the copy with 0010 and the copy without it produced identical scores, identical
  paper-engine results for a synthetic extra session, and identical one-year paper replays (portfolios #1, #3).
- Paper portfolios 1–3 in production: same parameters and cash, ACTIVE, last processed 2026-10-09; paper tables
  identical by fingerprint. `trading/`, `jobs/paper.py`, `scoring.py` and the scoring config are untouched (git).

## 7. Verified facts vs assumptions
Verified: the items in sections 4–6; the hand-calculated outcome values; the append-only, foreign-key and LIVE
constraints; trigger behaviour on old and new hypertable chunks; that the rollback restores the exact
pre-0010 schema and keeps all existing rows; that 0009 and 0010 apply in either order.

Assumptions and untested items:
- The 3 bps slippage is an assumption, not a measured cost. Zerodha charges were last checked 2026-10-06.
- Price-log volume in production (~205 rows per normal day) is an estimate; a provider re-adjusting long
  histories could add many more rows.
- The migration's lock on the price tables is expected to be brief (it creates triggers, rewrites nothing);
  not measured on production.
- 0010 has never run against live Kite ingestion; behaviour with a real daily refetch is inferred from tests.

## 8. Remaining issues and risks
- **No LIVE run is possible yet**: the git tree must be clean. Everything is uncommitted, and `.localdb/`
  (a PostgreSQL data directory) is tracked in git and becomes dirty if a local server runs from it.
- Reproducibility: securities, fundamentals and corporate events are not logged; any later change makes affected
  runs unverifiable (reported as INPUTS_CHANGED, never REPRODUCED). Backfilled runs cannot be rebuilt.
  Scoring run 3 (2026-10-08) was overwritten before this work and is lost.
- The holiday calendar only covers 2026; runs whose next session falls in 2027 cannot be LIVE until it is
  extended.
- Evidence takes time: first 20-session outcomes about 4 weeks after the first LIVE run; 12 non-overlapping
  periods (the display threshold, not a significance test) take months to years.
- Measurement biases: today's NIFTY 200 universe (survivorship), price-only returns, scores currently price-only
  (fundamentals neutral, all LOW confidence), policy v1 differs from the paper portfolios' "top 5 eligible with
  rank buffer".
- Rollback deletes all tracking data (take a backup first).
- `jobs.tracking status`/`outcomes` are not scheduled.

## 9. Decisions requiring your approval
1. Commit the work (this task and Phase 1) and decide what to do about the tracked `.localdb/` directory.
2. Promote 0010 to production: `pg_dump -Fc` backup of `dhandrishti_kite`, move the file into
   `packages/database/migrations/`, run `pnpm db:migrate` with the pipeline stopped, compare fingerprints.
3. Whether to copy the surviving runs 1, 2, 4 and 5 as BACKFILLED (`jobs.tracking backfill --apply`).
4. Whether to add `jobs.tracking status` and `outcomes` to the daily job (`pnpm daily:kite`).
5. Whether to extend the NSE holiday calendar to 2027.

## 10. Recommended next step
Commit the uncommitted work on a branch and resolve `.localdb/` (decision 1). Then approve the production
promotion of 0010 with the backup-and-fingerprint procedure above, so the first LIVE records start accumulating.
Leave scheduling (decision 4) until after a few days of manual `jobs.tracking status` checks.
