-- STAGED, NOT FOR PRODUCTION YET (2026-10-12). Lives outside migrations/ so `migrate()` in the daily jobs
-- never applies it. Applied only to test databases via dhandrishti.db.staged.apply_staged(only=[...]).
-- Independent of staged 0009 (no shared objects). Design: docs/recommendation-tracking.md.
--
-- Adds, without changing any existing table or row:
--   * append-only records of every scoring run (inputs manifest + hashes, code commit, per-stock scores,
--     recommendation selection with exclusion reasons)
--   * append-only forward outcomes (20/60/120/252 sessions) and verification results
--   * an append-only log of changes to daily_prices / index_prices, so past inputs can be reconstructed

-- Append-only guard for the tables below (separate from 0009's dd_reject_change on purpose).
CREATE FUNCTION dd_reject_tracking_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
END $$;

-- ---------------------------------------------------------------- price change log
-- One row per real change to a stored bar. Re-upserting identical values (the daily refetch) logs nothing.
-- INSERT rows mark when a bar first existed; UPDATE/DELETE rows keep the values that were replaced.
-- LOG_START marks when logging began; TRUNCATE marks a break after which history cannot be reconstructed.
CREATE TABLE price_change_log (
  id             bigserial PRIMARY KEY,
  table_name     text NOT NULL CHECK (table_name IN ('daily_prices', 'index_prices')),
  op             text NOT NULL CHECK (op IN ('LOG_START', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')),
  key            text,                -- symbol (daily_prices) or index_code (index_prices)
  trade_date     date,
  old_open double precision, old_high double precision, old_low double precision, old_close double precision,
  old_volume bigint, old_provenance text, old_source text,
  new_open double precision, new_high double precision, new_low double precision, new_close double precision,
  new_volume bigint, new_provenance text, new_source text,
  changed_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((op IN ('LOG_START', 'TRUNCATE')) = (key IS NULL AND trade_date IS NULL)),
  CHECK (op NOT IN ('UPDATE', 'DELETE') OR old_close IS NOT NULL),
  CHECK (op NOT IN ('INSERT', 'UPDATE') OR new_close IS NOT NULL)
);
CREATE INDEX price_change_log_lookup_idx ON price_change_log (table_name, key, trade_date, changed_at);

-- The table name comes from the trigger argument: on a hypertable the row triggers fire on chunks, where
-- TG_TABLE_NAME is the chunk's name.
CREATE FUNCTION dd_log_price_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  tbl text := TG_ARGV[0];
  k text;
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    INSERT INTO price_change_log (table_name, op) VALUES (tbl, 'TRUNCATE');
    RETURN NULL;
  END IF;
  IF TG_OP = 'DELETE' THEN
    k := CASE WHEN tbl = 'daily_prices' THEN to_jsonb(OLD) ->> 'symbol' ELSE to_jsonb(OLD) ->> 'index_code' END;
    INSERT INTO price_change_log (table_name, op, key, trade_date, old_open, old_high, old_low, old_close, old_volume,
                                  old_provenance, old_source)
    VALUES (tbl, 'DELETE', k, OLD.trade_date, OLD.open, OLD.high, OLD.low, OLD.close, OLD.volume,
            OLD.provenance::text, OLD.source);
    RETURN NULL;
  END IF;
  k := CASE WHEN tbl = 'daily_prices' THEN to_jsonb(NEW) ->> 'symbol' ELSE to_jsonb(NEW) ->> 'index_code' END;
  IF TG_OP = 'INSERT' THEN
    INSERT INTO price_change_log (table_name, op, key, trade_date, new_open, new_high, new_low, new_close, new_volume,
                                  new_provenance, new_source)
    VALUES (tbl, 'INSERT', k, NEW.trade_date, NEW.open, NEW.high, NEW.low, NEW.close, NEW.volume,
            NEW.provenance::text, NEW.source);
  ELSE
    INSERT INTO price_change_log (table_name, op, key, trade_date, old_open, old_high, old_low, old_close, old_volume,
                                  old_provenance, old_source, new_open, new_high, new_low, new_close, new_volume,
                                  new_provenance, new_source)
    VALUES (tbl, 'UPDATE', k, NEW.trade_date, OLD.open, OLD.high, OLD.low, OLD.close, OLD.volume,
            OLD.provenance::text, OLD.source, NEW.open, NEW.high, NEW.low, NEW.close, NEW.volume,
            NEW.provenance::text, NEW.source);
  END IF;
  RETURN NULL;
END $$;

-- Both price tables: log inserts and deletes, and updates only when a stored value really changes
-- (ingested_at alone changing on the daily refetch is not a revision).
CREATE TRIGGER daily_prices_log_insert_delete AFTER INSERT OR DELETE ON daily_prices
  FOR EACH ROW EXECUTE FUNCTION dd_log_price_change('daily_prices');
CREATE TRIGGER daily_prices_log_update AFTER UPDATE ON daily_prices
  FOR EACH ROW WHEN ((OLD.open, OLD.high, OLD.low, OLD.close, OLD.volume, OLD.provenance, OLD.source)
                     IS DISTINCT FROM (NEW.open, NEW.high, NEW.low, NEW.close, NEW.volume, NEW.provenance, NEW.source))
  EXECUTE FUNCTION dd_log_price_change('daily_prices');
CREATE TRIGGER daily_prices_log_truncate AFTER TRUNCATE ON daily_prices
  FOR EACH STATEMENT EXECUTE FUNCTION dd_log_price_change('daily_prices');
CREATE TRIGGER index_prices_log_insert_delete AFTER INSERT OR DELETE ON index_prices
  FOR EACH ROW EXECUTE FUNCTION dd_log_price_change('index_prices');
CREATE TRIGGER index_prices_log_update AFTER UPDATE ON index_prices
  FOR EACH ROW WHEN ((OLD.open, OLD.high, OLD.low, OLD.close, OLD.volume, OLD.provenance, OLD.source)
                     IS DISTINCT FROM (NEW.open, NEW.high, NEW.low, NEW.close, NEW.volume, NEW.provenance, NEW.source))
  EXECUTE FUNCTION dd_log_price_change('index_prices');
CREATE TRIGGER index_prices_log_truncate AFTER TRUNCATE ON index_prices
  FOR EACH STATEMENT EXECUTE FUNCTION dd_log_price_change('index_prices');

INSERT INTO price_change_log (table_name, op) VALUES ('daily_prices', 'LOG_START'), ('index_prices', 'LOG_START');

-- ---------------------------------------------------------------- policies and methods (versioned, immutable)
-- Which scored stocks count as recommendations. Changing the rules means a new version.
CREATE TABLE recommendation_policies (
  version        text PRIMARY KEY,
  params         jsonb NOT NULL,
  params_sha256  text NOT NULL,
  description    text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- How outcomes are measured (entry/exit rule, notional, charges, slippage). Changing any of it means a new version.
CREATE TABLE outcome_methods (
  version        text PRIMARY KEY,
  params         jsonb NOT NULL,
  params_sha256  text NOT NULL,
  description    text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- scoring-run records
-- One row per successful scoring run, written once. record_kind:
--   LIVE         prospective run that passed every qualification check (the official track record)
--   DEVELOPMENT  prospective but disqualified (uncommitted code, MOCK data, data not settled, ...)
--   REPLAY       scored after the next session had already opened (retrospective)
--   BACKFILLED   reconstructed from score_history; no input manifest
CREATE TABLE recommendation_runs (
  run_id                 bigint PRIMARY KEY REFERENCES scoring_runs (id),
  record_kind            text NOT NULL CHECK (record_kind IN ('LIVE', 'DEVELOPMENT', 'REPLAY', 'BACKFILLED')),
  qualification_failures text[] NOT NULL,
  as_of                  date NOT NULL,           -- signal session: inputs end at this close
  decision_at            timestamptz NOT NULL,    -- as_of 15:30 IST (information cutoff)
  inputs_loaded_at       timestamptz,             -- database clock when the inputs were read
  scored_at              timestamptz NOT NULL,
  entry_session          date,                    -- next trading session, when the calendar knows it
  entry_deadline         timestamptz,             -- 09:15 IST on entry_session
  config_version         text NOT NULL REFERENCES scoring_config_versions (version),
  config_sha256          text NOT NULL,
  code_commit            text,
  code_dirty             boolean,
  lookback_bars          integer,
  input_hash             text,
  input_manifest         jsonb,
  output_hash            text,
  data_provenance        data_provenance NOT NULL,
  scored_count           integer NOT NULL,
  regime                 jsonb NOT NULL,
  breadth                jsonb NOT NULL,
  sectors                jsonb NOT NULL,
  policy_version         text NOT NULL REFERENCES recommendation_policies (version),
  recorded_at            timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((record_kind = 'LIVE') = (cardinality(qualification_failures) = 0)),
  CHECK (record_kind = 'BACKFILLED' OR (input_hash IS NOT NULL AND input_manifest IS NOT NULL
                                        AND inputs_loaded_at IS NOT NULL AND output_hash IS NOT NULL)),
  CHECK (record_kind <> 'LIVE' OR (code_commit IS NOT NULL AND code_dirty = false AND data_provenance <> 'MOCK'
                                   AND inputs_loaded_at >= decision_at AND entry_deadline IS NOT NULL
                                   AND scored_at < entry_deadline)),
  CHECK (entry_session IS NULL OR entry_session > as_of)
);
CREATE INDEX recommendation_runs_as_of_idx ON recommendation_runs (as_of, record_kind);

-- One row per scored stock per run, written once. selection:
--   RECOMMENDED         candidate under the policy (rank <= top_n) and eligible
--   EXCLUDED_CANDIDATE  candidate but not eligible (reasons recorded)
--   NOT_CANDIDATE       outside the candidate ranks (eligibility still recorded)
CREATE TABLE recommendation_scores (
  run_id              bigint NOT NULL REFERENCES recommendation_runs (run_id),
  symbol              text NOT NULL REFERENCES securities (symbol),
  rank                integer NOT NULL,
  total_score         double precision NOT NULL,
  confidence          text NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
  data_coverage       double precision NOT NULL,
  risk_level          text NOT NULL,
  risk_points         double precision NOT NULL,
  component_scores    jsonb NOT NULL,
  component_coverage  jsonb NOT NULL,
  last_bar_date       date,
  eligible            boolean NOT NULL,
  exclusion_reasons   text[] NOT NULL,
  selection           text NOT NULL CHECK (selection IN ('RECOMMENDED', 'EXCLUDED_CANDIDATE', 'NOT_CANDIDATE')),
  result              jsonb NOT NULL,
  result_sha256       text NOT NULL,
  PRIMARY KEY (run_id, symbol),
  CHECK (eligible = (cardinality(exclusion_reasons) = 0)),
  CHECK (selection <> 'RECOMMENDED' OR eligible),
  CHECK (selection <> 'EXCLUDED_CANDIDATE' OR NOT eligible)
);

-- ---------------------------------------------------------------- outcomes
-- Forward outcome of one scored stock at one horizon. A later re-evaluation (e.g. prices restated) is a new
-- row with a different evaluation_hash; earlier rows stay. PENDING outcomes are never stored.
CREATE TABLE recommendation_outcomes (
  id                    bigserial PRIMARY KEY,
  run_id                bigint NOT NULL,
  symbol                text NOT NULL,
  horizon               smallint NOT NULL CHECK (horizon IN (20, 60, 120, 252)),
  method_version        text NOT NULL REFERENCES outcome_methods (version),
  evaluation_hash       text NOT NULL,       -- all prices used for this run and horizon
  price_data_hash       text NOT NULL,       -- this stock's prices in the window
  status                text NOT NULL CHECK (status IN ('COMPLETE', 'SUSPECT_PRICE_JUMP', 'BENCHMARK_MISSING',
                                                        'NO_ENTRY_PRICE', 'NO_EXIT_PRICE')),
  entry_date date, entry_price double precision,
  exit_date date, exit_price double precision,
  sessions_held         integer,
  gross_return          double precision,
  net_return            double precision,    -- after charges and the method's base slippage
  net_return_no_slippage double precision,   -- charges only (paper-trading fills)
  slippage_sensitivity  jsonb,               -- {"10": net at 10 bps/side, "25": ...}
  charges_inr           double precision,
  nifty_return          double precision,
  excess_vs_nifty       double precision,
  universe_return       double precision,    -- mean net_return of this run's COMPLETE outcomes
  excess_vs_universe    double precision,
  max_adverse_excursion double precision,
  mae_reliable          boolean,
  detail                text,
  computed_at           timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (run_id, symbol) REFERENCES recommendation_scores (run_id, symbol),
  UNIQUE (run_id, symbol, horizon, method_version, evaluation_hash),
  CHECK ((status IN ('NO_ENTRY_PRICE', 'NO_EXIT_PRICE')) = (gross_return IS NULL)),
  CHECK ((gross_return IS NULL) = (net_return IS NULL)),
  CHECK (status <> 'COMPLETE' OR (nifty_return IS NOT NULL AND mae_reliable IS NOT NULL)),
  CHECK (status <> 'BENCHMARK_MISSING' OR nifty_return IS NULL),
  CHECK (exit_date IS NULL OR entry_date < exit_date),
  CHECK (exit_date IS NULL OR computed_at >= exit_date)
);
CREATE INDEX recommendation_outcomes_run_idx ON recommendation_outcomes (run_id, horizon, method_version);

-- Latest evaluation per (run, stock, horizon, method).
CREATE VIEW recommendation_outcome_latest AS
SELECT DISTINCT ON (run_id, symbol, horizon, method_version) *
FROM recommendation_outcomes
ORDER BY run_id, symbol, horizon, method_version, computed_at DESC, id DESC;

-- ---------------------------------------------------------------- verification results
CREATE TABLE run_verifications (
  id             bigserial PRIMARY KEY,
  run_id         bigint NOT NULL REFERENCES recommendation_runs (run_id),
  status         text NOT NULL CHECK (status IN ('REPRODUCED', 'INPUTS_CHANGED', 'CODE_CHANGED',
                                                 'INSUFFICIENT_INPUT_HISTORY', 'VERIFICATION_FAILED')),
  inputs_source  text CHECK (inputs_source IN ('CURRENT', 'RECONSTRUCTED')),
  code_commit    text,
  code_dirty     boolean,
  detail         jsonb NOT NULL,
  verified_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (status NOT IN ('REPRODUCED', 'CODE_CHANGED') OR inputs_source IS NOT NULL)
);

-- ---------------------------------------------------------------- recorder failures
-- One row per failed attempt to record a scoring run (the run itself is unaffected). A later successful record
-- (normally via `jobs.tracking record RUN_ID`) resolves it; the failure row stays.
CREATE TABLE tracking_failures (
  id             bigserial PRIMARY KEY,
  run_id         bigint NOT NULL REFERENCES scoring_runs (id),
  stage          text NOT NULL CHECK (stage IN ('RECORD', 'RETRY')),
  error_type     text NOT NULL,
  error_message  text NOT NULL,
  diagnostic     text NOT NULL,
  code_commit    text,
  occurred_at    timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX tracking_failures_run_idx ON tracking_failures (run_id);

-- ---------------------------------------------------------------- append-only enforcement
CREATE TRIGGER price_change_log_no_update BEFORE UPDATE OR DELETE ON price_change_log
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER price_change_log_no_truncate BEFORE TRUNCATE ON price_change_log
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_policies_no_update BEFORE UPDATE OR DELETE ON recommendation_policies
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_policies_no_truncate BEFORE TRUNCATE ON recommendation_policies
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER outcome_methods_no_update BEFORE UPDATE OR DELETE ON outcome_methods
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER outcome_methods_no_truncate BEFORE TRUNCATE ON outcome_methods
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_runs_no_update BEFORE UPDATE OR DELETE ON recommendation_runs
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_runs_no_truncate BEFORE TRUNCATE ON recommendation_runs
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_scores_no_update BEFORE UPDATE OR DELETE ON recommendation_scores
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_scores_no_truncate BEFORE TRUNCATE ON recommendation_scores
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_outcomes_no_update BEFORE UPDATE OR DELETE ON recommendation_outcomes
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER recommendation_outcomes_no_truncate BEFORE TRUNCATE ON recommendation_outcomes
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER run_verifications_no_update BEFORE UPDATE OR DELETE ON run_verifications
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER run_verifications_no_truncate BEFORE TRUNCATE ON run_verifications
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER tracking_failures_no_update BEFORE UPDATE OR DELETE ON tracking_failures
  FOR EACH ROW EXECUTE FUNCTION dd_reject_tracking_change();
CREATE TRIGGER tracking_failures_no_truncate BEFORE TRUNCATE ON tracking_failures
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_tracking_change();
