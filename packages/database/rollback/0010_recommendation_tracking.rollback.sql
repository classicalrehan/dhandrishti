-- Rollback for migration 0010_recommendation_tracking.sql. NOT a migration: kept outside migrations/ and
-- migrations-staged/ so no runner applies it. Run by hand, in one transaction, only after taking a backup:
--
--   pg_dump -Fc -d <db> -f before-0010-rollback.dump      # keeps the tracking data, which this script destroys
--   psql -d <db> -v ON_ERROR_STOP=1 -f packages/database/rollback/0010_recommendation_tracking.rollback.sql
--
-- Removes only what 0010 created: the price-log triggers on daily_prices / index_prices, the tracking tables and
-- view, their functions, and the schema_migrations row. Rows in existing tables are not touched. The append-only
-- triggers block UPDATE/DELETE/TRUNCATE, not DROP. Stop the daily pipeline first (dropping triggers takes a
-- short lock on the price tables); with the tables gone, run_scoring's recorder simply skips again.

BEGIN;

DROP TRIGGER IF EXISTS daily_prices_log_insert_delete ON daily_prices;
DROP TRIGGER IF EXISTS daily_prices_log_update ON daily_prices;
DROP TRIGGER IF EXISTS daily_prices_log_truncate ON daily_prices;
DROP TRIGGER IF EXISTS index_prices_log_insert_delete ON index_prices;
DROP TRIGGER IF EXISTS index_prices_log_update ON index_prices;
DROP TRIGGER IF EXISTS index_prices_log_truncate ON index_prices;

DROP VIEW IF EXISTS recommendation_outcome_latest;
DROP TABLE IF EXISTS run_verifications;
DROP TABLE IF EXISTS recommendation_outcomes;
DROP TABLE IF EXISTS recommendation_scores;
DROP TABLE IF EXISTS recommendation_runs;
DROP TABLE IF EXISTS outcome_methods;
DROP TABLE IF EXISTS recommendation_policies;
DROP TABLE IF EXISTS tracking_failures;
DROP TABLE IF EXISTS price_change_log;

DROP FUNCTION IF EXISTS dd_log_price_change();
DROP FUNCTION IF EXISTS dd_reject_tracking_change();

DELETE FROM schema_migrations WHERE filename = '0010_recommendation_tracking.sql';

COMMIT;
