-- Per-day indicator series for charts (SMA/EMA/RSI/MACD/Bollinger overlays).
-- Computed by the Python worker (single quant implementation); the API only reads it.
CREATE TABLE indicator_series (
  symbol       text NOT NULL REFERENCES securities (symbol),
  trade_date   date NOT NULL,
  sma20        double precision,
  sma50        double precision,
  sma200       double precision,
  ema20        double precision,
  rsi14        double precision,
  macd         double precision,
  macd_signal  double precision,
  macd_hist    double precision,
  bb_upper     double precision,
  bb_lower     double precision,
  provenance   data_provenance NOT NULL,
  PRIMARY KEY (symbol, trade_date)
);
SELECT dd_make_hypertable('indicator_series', 'trade_date', '1 year');
