-- Backtest results (relational: small, queried by run).
CREATE TABLE backtest_runs (
  id              bigserial PRIMARY KEY,
  name            text,
  params          jsonb NOT NULL,
  config_version  text NOT NULL REFERENCES scoring_config_versions (version),
  provenance      data_provenance NOT NULL,
  status          text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
  metrics         jsonb,
  periods         jsonb,               -- per-rebalance returns, IC, quantile returns, picks
  error           text,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz
);
CREATE INDEX backtest_runs_started_idx ON backtest_runs (started_at DESC);

CREATE TABLE backtest_equity (
  run_id        bigint NOT NULL REFERENCES backtest_runs (id) ON DELETE CASCADE,
  trade_date    date NOT NULL,
  strategy      double precision NOT NULL,
  nifty         double precision NOT NULL,
  universe_ew   double precision NOT NULL,
  drawdown_pct  double precision NOT NULL,
  PRIMARY KEY (run_id, trade_date)
);

CREATE TABLE backtest_holdings (
  run_id          bigint NOT NULL REFERENCES backtest_runs (id) ON DELETE CASCADE,
  signal_date     date NOT NULL,
  execution_date  date NOT NULL,
  symbol          text NOT NULL,
  rank            integer NOT NULL,
  total_score     double precision NOT NULL,
  risk_level      text NOT NULL,
  confidence      text NOT NULL,
  weight          double precision NOT NULL,
  entry_price     double precision NOT NULL,
  PRIMARY KEY (run_id, execution_date, symbol)
);
