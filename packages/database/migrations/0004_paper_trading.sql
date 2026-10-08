-- Paper trading: simulated portfolios that follow real trading rules (no real orders).
CREATE TABLE paper_portfolios (
  id              bigserial PRIMARY KEY,
  name            text NOT NULL UNIQUE,
  params          jsonb NOT NULL,
  status          text NOT NULL CHECK (status IN ('ACTIVE', 'HALTED', 'CLOSED')),
  halt_reason     text,
  cash            double precision NOT NULL,
  peak_equity     double precision NOT NULL,
  start_date      date NOT NULL,
  last_processed  date NOT NULL,
  provenance      data_provenance NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE paper_positions (
  portfolio_id  bigint NOT NULL REFERENCES paper_portfolios (id) ON DELETE CASCADE,
  symbol        text NOT NULL REFERENCES securities (symbol),
  qty           integer NOT NULL CHECK (qty > 0),
  avg_price     double precision NOT NULL,
  entry_date    date NOT NULL,
  last_close    double precision NOT NULL,
  PRIMARY KEY (portfolio_id, symbol)
);

CREATE TABLE paper_orders (
  id            bigserial PRIMARY KEY,
  portfolio_id  bigint NOT NULL REFERENCES paper_portfolios (id) ON DELETE CASCADE,
  created_on    date NOT NULL,
  side          text NOT NULL CHECK (side IN ('BUY', 'SELL')),
  symbol        text NOT NULL REFERENCES securities (symbol),
  qty           integer NOT NULL,
  reason        text NOT NULL CHECK (reason IN ('INITIAL', 'REBALANCE', 'STOP_LOSS', 'KILL_SWITCH')),
  status        text NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED')),
  fill_date     date,
  fill_price    double precision,
  charges       double precision NOT NULL DEFAULT 0,
  note          text,
  attempts      integer NOT NULL DEFAULT 0
);
CREATE INDEX paper_orders_portfolio_idx ON paper_orders (portfolio_id, created_on DESC, id DESC);

CREATE TABLE paper_daily (
  portfolio_id    bigint NOT NULL REFERENCES paper_portfolios (id) ON DELETE CASCADE,
  trade_date      date NOT NULL,
  cash            double precision NOT NULL,
  holdings_value  double precision NOT NULL,
  equity          double precision NOT NULL,
  drawdown_pct    double precision NOT NULL,
  nifty_close     double precision,
  events          jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (portfolio_id, trade_date)
);
