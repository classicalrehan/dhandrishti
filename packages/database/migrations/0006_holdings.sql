-- Real Zerodha holdings, fetched read-only from Kite Connect (personal data: local database only).
-- One snapshot per date; fetching again on the same date replaces it, so the evening fetch wins.
CREATE TABLE holdings_snapshots (
  as_of             date PRIMARY KEY,
  fetched_at        timestamptz NOT NULL,
  value             double precision NOT NULL,   -- holdings at last price
  invested          double precision NOT NULL,   -- holdings at average buy price
  period_return_pct double precision,            -- time-weighted change since the previous snapshot
  twr_index         double precision NOT NULL,   -- 100 at the first snapshot, chained period returns
  nifty_close       double precision
);

CREATE TABLE holding_items (
  as_of          date NOT NULL REFERENCES holdings_snapshots (as_of) ON DELETE CASCADE,
  kind           text NOT NULL CHECK (kind IN ('HOLDING', 'POSITION')),
  tradingsymbol  text NOT NULL,   -- not a foreign key: holdings outside the scored universe are kept
  exchange       text NOT NULL,
  product        text NOT NULL,
  isin           text,
  qty            integer NOT NULL,
  t1_qty         integer NOT NULL DEFAULT 0,
  avg_price      double precision NOT NULL,
  last_price     double precision NOT NULL,
  close_price    double precision,
  pnl            double precision NOT NULL,
  PRIMARY KEY (as_of, kind, exchange, tradingsymbol, product)
);
