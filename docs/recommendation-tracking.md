# Recommendation tracking (staged migration 0010)

Status (2026-10-12): implemented, hardened and tested on throwaway databases and production clones only.
`packages/database/migrations-staged/0010_recommendation_tracking.sql` is **not** applied to
`dhandrishti` or `dhandrishti_kite`. Until it is, the recorder does nothing and scoring behaves exactly as before.

## What it records
| Table | One row per | Written by |
|---|---|---|
| `recommendation_runs` | successful scoring run | `run_scoring` → `tracking.recorder.record_if_installed` (own transaction, after the run commits), or `jobs.tracking record RUN_ID` |
| `recommendation_scores` | scored stock per run, with eligibility, exclusion reasons and selection | same |
| `recommendation_outcomes` | stock × horizon × outcome-method evaluation | `jobs.tracking outcomes` |
| `run_verifications` | verification attempt | `jobs.tracking verify` |
| `tracking_failures` | failed attempt to record a run (with a diagnostic) | recorder, retry |
| `price_change_log` | real change to `daily_prices` / `index_prices` (insert, update with a changed value, delete, truncate marker) | triggers |
| `recommendation_policies`, `outcome_methods` | rule version (immutable; a change needs a new version) | registered on first use |

All of them reject UPDATE, DELETE and TRUNCATE (also through `TRUNCATE ... CASCADE` from a referenced table).
Existing tables (`score_history`, paper tables, prices) are not changed; `score_history` keeps its
overwrite-on-rerun behaviour, and the API still reads it.

## Record kinds (only LIVE is the official track record)
A run is **LIVE** only if every check passes:
real (non-MOCK) data; a git commit with a clean working tree (no tracked or untracked changes); inputs read
after 16:30 IST on the signal day; NIFTY 50 updated to the signal day; the next session known to the holiday
calendar; the record written before 09:15 IST on that next session; and it was recorded by the scoring run
itself (not by a retry). Otherwise it is **DEVELOPMENT** (failures listed), or **REPLAY** when it was scored after
the next session had opened. **BACKFILLED** rows are copies of runs that survive in `score_history`; they have no
input manifest and never count as live results. The database enforces the LIVE conditions with CHECK constraints.
A run with no record, or only a failure row, is simply absent from every track record.

Note: `.localdb/` (a PostgreSQL data directory) is tracked in git. If a local server runs from it, the tree is
dirty and no run can qualify as LIVE.

## Tracking failures and retries
- Recording never blocks scoring: `record_if_installed` catches every error after the run has committed.
- On error it logs the traceback with a one-line diagnostic and stores a `tracking_failures` row (stage RECORD).
  Diagnostics name the cause and the action, e.g. "Database connection problem. When the database is reachable,
  retry: `cd apps/worker && uv run python -m dhandrishti.jobs.tracking record 123`", or "An input bar is dated
  after as_of ... Do not retry until the data is explained." If storing the failure row also fails, that is logged.
- `jobs.tracking status` lists every successful scoring run since installation without a record (whether or not a
  failure row exists, so a crash between scoring and recording is still caught), unresolved failures with their
  diagnostics, runs from before installation (backfill candidates), the latest record and the latest LIVE date.
  Exit code 0 = healthy, 1 = attention needed, 2 = tables not installed (usable from a scheduler).
- `jobs.tracking record RUN_ID` retries. It reloads the inputs now, re-scores with the run's configuration and
  records only if the result equals what the run stored in `score_history`; otherwise it refuses (stored as a
  RETRY failure). A retried record always carries `RECORDED_BY_RETRY` and is never LIVE, because its inputs were
  read later than the run's. Retrying an already recorded run returns ALREADY_RECORDED; the primary key on
  `run_id` and an explicit check prevent duplicates.
- A run overwritten in `score_history` by a later run on the same day cannot be retried (its output is gone).

## Recommendation policy 2026.10-top5-v1
Candidates are the top 5 by overall rank. A candidate is RECOMMENDED only if its risk level is at most MEDIUM
(paper portfolio #1's rule); there is no confidence floor, because every score is LOW confidence while
fundamentals are missing. A failing candidate is recorded as EXCLUDED_CANDIDATE with its reasons and is not
replaced by rank 6+. Eligibility is stored for every scored stock, so the paper portfolios' "top 5 eligible"
selection (and their rank buffers) can be analysed from the same records later.

## Three kinds of results: do not mix them
| | Hypothetical recommendation returns | Simulated paper-portfolio returns | Historical backtests |
|---|---|---|---|
| What | each run's recommended stocks, held a fixed number of sessions | the three paper portfolios trading forward by their rules | the score replayed over past data |
| Where | `recommendation_outcomes`; `jobs.tracking summary` (labelled HYPOTHETICAL RECOMMENDATION RETURNS) | `paper_*` tables; `pnpm paper` | `backtest_*` tables; `pnpm backtest`, research studies |
| Time | prospective (LIVE runs) | prospective since each portfolio's start | retrospective, today's universe (survivorship bias) |
| Selection | policy v1: rank ≤ 5 and risk ≤ MEDIUM, no replacement | top 5 eligible (risk ≤ MEDIUM; #3 also ≥ 252 bars), kept while within rank 10/15/20 | top N by score after risk/confidence filters |
| Size | fixed ₹20,000 notional per stock | equal share of portfolio equity per slot (₹1,00,000 start) | equal weight of book value |
| Shares | fractional | whole shares; a stock whose one share exceeds the slot is skipped; a buy shrinks if the open gaps up | fractional |
| Entry / exit | next open; exit at the open after 20/60/120/252 sessions | next open; exit on rebalance, stop-loss, trailing stop or kill switch | next open after each rebalance date |
| Charges | `delivery_charges()` (Zerodha delivery) | same function, per order | flat 15 bps buy / 13.5 bps sell (incl. ~3 bps slippage) |
| Slippage | 3 bps/side assumed; also 0, 10, 25 bps | none (fills at the open price) | inside the flat bps |
| Benchmarks | NIFTY 50 (no costs), equal-weight universe | NIFTY 50 close stored daily | NIFTY 50, equal-weight universe |
The tracking code never reads paper or backtest tables (a test enforces it), and none of these engines changed.

## Outcome method outcome-v1
- Calendar: NIFTY 50 sessions. Entry: open of the session after the signal (up to 3 sessions late if the stock
  has no bar). Exit: open of planned entry + 20/60/120/252 sessions (up to 3 sessions late).
- ₹20,000 notional, fractional shares. Charges: `trading.costs.delivery_charges` (Zerodha delivery, checked
  2026-10-06: STT 0.1% each side, stamp 0.015% on buys, NSE 0.00307%, SEBI ₹10/crore, GST 18% on fees,
  DP ₹15.34 per sell), the same function paper trading pays.
- Slippage: 3 bps per side is an **assumption**, not a measured cost. Each outcome also stores net returns at
  0 bps (what paper trading's fills assume), 10 and 25 bps, and the gross return.
- Benchmarks: NIFTY 50 price index open to open on the stock's own entry and exit sessions (no costs), and the
  equal-weight mean net return of every COMPLETE outcome of the same run.
- Statuses: COMPLETE; SUSPECT_PRICE_JUMP (a >35% close-to-close move, e.g. an unadjusted split: kept, excluded
  from headline figures); BENCHMARK_MISSING; NO_ENTRY_PRICE / NO_EXIT_PRICE (no return stored, never zero).
  PENDING outcomes (horizon plus 3 grace sessions not yet in the calendar) are not stored.
- Max adverse excursion: lowest low from entry to exit relative to entry; flagged unreliable when bars are missing
  or a suspect move occurred.
- Prices restated later: the next evaluation is stored as a new row; earlier rows remain.

## Avoiding look-ahead
Inputs are loaded with `trade_date <= as_of`; the recorder refuses a manifest with a later bar. Entry is the next
session's open (the database requires `entry_session > as_of`). Outcomes are stored only after the exit session
exists (`computed_at >= exit_date`). Scoring, paper trading, backtests and research never read tracking tables
(a test enforces this). There is no REPLAY generation of past dates: re-scoring history now would use today's
universe and today's revised prices.

## Reproducibility and its exact limits
Each record stores the configuration version and hash, the git commit and dirty flag, and an input manifest:
per scored stock a hash of its bars, its `securities` row, the fundamentals snapshot used and the upcoming events
used, plus the three indices, `as_of`, lookback and provenance. Scoring does not modify its inputs (tested), so
the hash taken after scoring describes the inputs. `jobs.tracking verify`:

| Status | Meaning |
|---|---|
| REPRODUCED | the inputs (current, or rebuilt from `price_change_log`) hash to the recorded value **and** re-scoring gives identical results |
| CODE_CHANGED | identical inputs, different results |
| INPUTS_CHANGED | after rebuilding prices, securities, fundamentals or events still differ (not logged) |
| INSUFFICIENT_INPUT_HISTORY | no manifest (BACKFILLED); prices changed and the log does not cover the run (started later, or the table was truncated since); or prices still differ after rebuilding, meaning the log is incomplete (chunks dropped with `drop_chunks`, triggers disabled) |
| VERIFICATION_FAILED | the check could not run |

REPRODUCED is only possible when the recomputed input hash equals the recorded one; there is no other path.
Limits by table (none of these are logged; any change makes affected runs unverifiable, never falsely reproduced):
- **securities**: every ingest upserts name, exchange, sector, industry, is_financial and indices in place; a
  universe refresh can reclassify a sector or change index membership, and `active = false` drops a stock from
  `load_market`. Sector changes also alter sector medians and sector strength for other stocks.
- **fundamentals**: rows are keyed (symbol, as_of) and re-imports overwrite them; a re-import or a new snapshot
  dated on or before a run's as_of changes that run's inputs. (Production has 0 rows today.)
- **corporate_events**: events dated within 90 days after as_of are inputs; an event added, re-dated or retitled
  later changes them. Event rows are upserted, never deleted by the code. (Production has 0 rows today.)
- Prices changed by a session that disabled the triggers, or rows removed by `drop_chunks`/retention, are not in
  the log (no retention policy exists today).
- `inputs_loaded_at` is read just before `load_market`; prices committed between that instant and the load would
  be attributed wrongly by a reconstruction. The hash comparison then fails, so the result is not REPRODUCED.

Why no full input snapshots yet: verification already refuses to report REPRODUCED whenever inputs cannot be
rebuilt, the unlogged tables are empty (fundamentals, events) or rarely change (securities), and full snapshots
would cost about 1–2 MB per run. If fundamentals or events start changing after runs, the smaller step is to add
the same change-log triggers to those three tables, not to store full copies.

## Reading the track record
`jobs.tracking summary --horizon 60` reports, for LIVE runs only by default: runs recorded, matured and pending;
successful scoring runs that have no record (and how many since installation); outcome statuses of recommended
and excluded candidates (with reasons); gross, net (0/3/10/25 bps), excess vs NIFTY and vs the equal-weight
universe; MAE. Statistics are per run (equal-weight basket of recommended stocks), and the headline sample is the
number of **non-overlapping** runs. Below 12 it reports INSUFFICIENT_EVIDENCE and draws no conclusion; 12 is a
display threshold, not a significance test.

## Migration review notes
- Foreign keys: `recommendation_runs` → `scoring_runs`, `scoring_config_versions`, `recommendation_policies`;
  `recommendation_scores` → `recommendation_runs`, `securities`; `recommendation_outcomes` → `recommendation_scores`
  (run, symbol), `outcome_methods`; `run_verifications` → `recommendation_runs`; `tracking_failures` → `scoring_runs`.
  No ON DELETE actions: deleting a referenced scoring run, security or config version is refused. No application
  code deletes or truncates those tables.
- Existing tables gain only the six price-log triggers on `daily_prices` and `index_prices`. No column, constraint,
  index or row of an existing table changes. On Timescale hypertables the row triggers run on chunks (the table
  name is passed as a trigger argument) and are propagated to chunks created later (tested).
- Applying it takes brief locks on the two price tables (CREATE TRIGGER); apply when the daily pipeline is not
  running. It rewrites no table.
- Rollback: `packages/database/rollback/0010_recommendation_tracking.rollback.sql` (outside both migration
  folders). Take a `pg_dump -Fc` first: the rollback deletes all tracking data. It drops only 0010's objects and
  its `schema_migrations` row; tested to restore the exact pre-0010 catalog and leave every existing row as it was,
  after which 0010 can be applied again.

## Commands
```sh
cd apps/worker
uv run python -m dhandrishti.jobs.tracking status
uv run python -m dhandrishti.jobs.tracking record RUN_ID
uv run python -m dhandrishti.jobs.tracking outcomes
uv run python -m dhandrishti.jobs.tracking verify --all
uv run python -m dhandrishti.jobs.tracking summary --horizon 60 [--kind DEVELOPMENT]
uv run python -m dhandrishti.jobs.tracking backfill [--apply]
```
Each needs `DD_DATABASE_URL` pointing at a database where 0010 is applied.
