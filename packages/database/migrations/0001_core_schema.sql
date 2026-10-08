-- DhanDrishti core schema (v1).
-- PostgreSQL is the source of truth. TimescaleDB hypertables are used ONLY for
-- high-volume time series; everything else is a plain relational table.
-- If the timescaledb extension is unavailable the same tables stay plain PostgreSQL.

-- ---------------------------------------------------------------- extensions & helpers
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
  ELSE
    RAISE NOTICE 'timescaledb not available: time-series tables remain plain PostgreSQL tables';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION dd_make_hypertable(tbl regclass, time_col text, chunk interval)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    EXECUTE format(
      'SELECT create_hypertable(%L::regclass, by_range(%L, %L::interval), if_not_exists => true, migrate_data => true)',
      tbl, time_col, chunk);
  END IF;
END $$;

CREATE DOMAIN data_provenance AS text
  CHECK (VALUE IN ('MOCK', 'EOD', 'DELAYED', 'LIVE'));

-- ---------------------------------------------------------------- reference data (relational)
CREATE TABLE securities (
  symbol        text PRIMARY KEY,
  name          text NOT NULL,
  exchange      text NOT NULL DEFAULT 'NSE' CHECK (exchange IN ('NSE', 'BSE')),
  sector        text NOT NULL,
  industry      text,
  is_financial  boolean NOT NULL DEFAULT false,
  indices       text[] NOT NULL DEFAULT '{}',
  active        boolean NOT NULL DEFAULT true,
  provenance    data_provenance NOT NULL,
  source        text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX securities_sector_idx ON securities (sector);

CREATE TABLE fundamentals (
  symbol                  text NOT NULL REFERENCES securities (symbol),
  as_of                   date NOT NULL,
  market_cap_cr           double precision,
  revenue_growth_yoy      double precision,
  profit_growth_yoy       double precision,
  eps_growth_yoy          double precision,
  eps_cagr_3y             double precision,
  roe                     double precision,
  roce                    double precision,
  operating_margin        double precision,
  net_margin              double precision,
  free_cash_flow_cr       double precision,
  cfo_to_pat              double precision,
  debt_to_equity          double precision,
  interest_coverage       double precision,
  pe                      double precision,
  pb                      double precision,
  peg                     double precision,
  dividend_yield          double precision,
  promoter_holding        double precision,
  promoter_pledge         double precision,
  institutional_holding   double precision,
  pe_median_5y            double precision,
  positive_eps_quarters_8 smallint CHECK (positive_eps_quarters_8 BETWEEN 0 AND 8),
  quarterly_eps           double precision[],          -- oldest → newest
  provenance              data_provenance NOT NULL,
  source                  text NOT NULL,
  ingested_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, as_of)
);

CREATE TABLE corporate_events (
  id          bigserial PRIMARY KEY,
  symbol      text REFERENCES securities (symbol),       -- NULL = market-wide
  event_date  date NOT NULL,
  event_type  text NOT NULL
              CHECK (event_type IN ('EARNINGS', 'DIVIDEND', 'SPLIT', 'BONUS', 'AGM', 'REGULATORY', 'OTHER')),
  title       text NOT NULL,
  provenance  data_provenance NOT NULL,
  source      text NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (symbol, event_date, event_type, title)
);
CREATE INDEX corporate_events_date_idx ON corporate_events (event_date);

CREATE TABLE news_items (
  id           bigserial PRIMARY KEY,
  symbol       text REFERENCES securities (symbol),
  published_at timestamptz NOT NULL,
  headline     text NOT NULL,
  summary      text,
  url          text NOT NULL UNIQUE,
  provenance   data_provenance NOT NULL,
  source       text NOT NULL,
  ingested_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX news_items_symbol_time_idx ON news_items (symbol, published_at DESC);

-- ---------------------------------------------------------------- scoring metadata (relational)
CREATE TABLE scoring_config_versions (
  version        text PRIMARY KEY,
  config         jsonb NOT NULL,
  config_sha256  text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE scoring_runs (
  id              bigserial PRIMARY KEY,
  as_of           date NOT NULL,
  config_version  text NOT NULL REFERENCES scoring_config_versions (version),
  provenance      data_provenance NOT NULL,
  status          text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
  stock_count     integer,
  error           text,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz
);
CREATE INDEX scoring_runs_as_of_idx ON scoring_runs (as_of DESC, id DESC);

-- ---------------------------------------------------------------- time series (hypertables)
CREATE TABLE daily_prices (
  symbol      text NOT NULL REFERENCES securities (symbol),
  trade_date  date NOT NULL,
  open        double precision NOT NULL,
  high        double precision NOT NULL,
  low         double precision NOT NULL,
  close       double precision NOT NULL,
  volume      bigint NOT NULL,
  provenance  data_provenance NOT NULL,
  source      text NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, trade_date)
);
SELECT dd_make_hypertable('daily_prices', 'trade_date', '1 year');

CREATE TABLE index_prices (
  index_code  text NOT NULL,                 -- 'NIFTY 50', 'NIFTY BANK', 'INDIA VIX', ...
  trade_date  date NOT NULL,
  open        double precision NOT NULL,
  high        double precision NOT NULL,
  low         double precision NOT NULL,
  close       double precision NOT NULL,
  volume      bigint NOT NULL DEFAULT 0,
  provenance  data_provenance NOT NULL,
  source      text NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (index_code, trade_date)
);
SELECT dd_make_hypertable('index_prices', 'trade_date', '1 year');

CREATE TABLE technical_indicators (
  symbol               text NOT NULL REFERENCES securities (symbol),
  as_of                date NOT NULL,
  close                double precision NOT NULL,
  change_pct           double precision,
  sma20                double precision,
  sma50                double precision,
  sma100               double precision,
  sma200               double precision,
  ema20                double precision,
  rsi14                double precision,
  macd                 double precision,
  macd_signal          double precision,
  macd_hist            double precision,
  adx14                double precision,
  plus_di              double precision,
  minus_di             double precision,
  atr14                double precision,
  atr_pct              double precision,
  bb_upper             double precision,
  bb_lower             double precision,
  high_52w             double precision,
  low_52w              double precision,
  dist_from_52w_high   double precision,
  dist_from_sma50      double precision,
  dist_from_sma200     double precision,
  sma200_slope_20d     double precision,
  relative_volume      double precision,
  avg_traded_value_cr  double precision,
  ret_1d               double precision,
  ret_1w               double precision,
  ret_1m               double precision,
  ret_3m               double precision,
  ret_6m               double precision,
  ret_1y               double precision,
  rs_nifty_1m          double precision,
  rs_nifty_3m          double precision,
  rs_nifty_6m          double precision,
  volatility_60d       double precision,
  max_drawdown_1y      double precision,
  gap_moves_60d        integer,
  trend                text NOT NULL,
  detail               jsonb NOT NULL,            -- full snapshot as produced by the engine
  provenance           data_provenance NOT NULL,
  PRIMARY KEY (symbol, as_of)
);
SELECT dd_make_hypertable('technical_indicators', 'as_of', '1 year');

-- One row per (stock, day, config version). Re-running a day with the same config overwrites;
-- run_id records which run produced the row.
CREATE TABLE score_history (
  symbol            text NOT NULL REFERENCES securities (symbol),
  as_of             date NOT NULL,
  config_version    text NOT NULL REFERENCES scoring_config_versions (version),
  run_id            bigint NOT NULL REFERENCES scoring_runs (id),
  total_score       double precision NOT NULL CHECK (total_score BETWEEN 0 AND 100),
  rank              integer NOT NULL,
  confidence        text NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
  data_coverage     double precision NOT NULL,
  risk_level        text NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH')),
  risk_points       double precision NOT NULL,
  key_reason        text NOT NULL,
  component_scores  jsonb NOT NULL,               -- {"fundamentals": 21.4, ...}
  result            jsonb NOT NULL,               -- full SPEC §11 output
  provenance        data_provenance NOT NULL,
  PRIMARY KEY (symbol, as_of, config_version)
);
SELECT dd_make_hypertable('score_history', 'as_of', '1 year');
CREATE INDEX score_history_rank_idx ON score_history (as_of DESC, config_version, rank);

-- Rankings are fully determined by score_history; a view avoids a second copy drifting.
CREATE VIEW ranking_history AS
  SELECT as_of, config_version, rank, symbol, total_score, confidence, risk_level, key_reason, provenance
  FROM score_history;

-- ---------------------------------------------------------------- market-level history (relational, small)
CREATE TABLE sector_strength_history (
  as_of           date NOT NULL,
  sector          text NOT NULL,
  config_version  text NOT NULL REFERENCES scoring_config_versions (version),
  run_id          bigint NOT NULL REFERENCES scoring_runs (id),
  score           integer NOT NULL,
  rank            integer NOT NULL,
  momentum        text NOT NULL,
  breadth         text NOT NULL,
  detail          jsonb NOT NULL,
  provenance      data_provenance NOT NULL,
  PRIMARY KEY (as_of, sector, config_version)
);

CREATE TABLE market_regime_history (
  as_of           date NOT NULL,
  config_version  text NOT NULL REFERENCES scoring_config_versions (version),
  run_id          bigint NOT NULL REFERENCES scoring_runs (id),
  regime          text NOT NULL CHECK (regime IN ('BULLISH', 'NEUTRAL', 'CAUTIOUS', 'BEARISH')),
  composite       double precision NOT NULL,
  confidence      integer NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  factors         jsonb NOT NULL,
  reason          text NOT NULL,
  breadth         jsonb NOT NULL,
  provenance      data_provenance NOT NULL,
  PRIMARY KEY (as_of, config_version)
);
