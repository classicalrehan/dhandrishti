-- Point-in-time fundamentals: provider-neutral, versioned, append-only raw observations.
-- Semantics of every column: docs/fundamentals-pit.md. Not read by production scoring yet.

CREATE TABLE fundamental_import_batches (
  id             bigserial PRIMARY KEY,
  source         text NOT NULL,                 -- provider / origin, e.g. 'NSE filing (manual)', 'Screener export'
  file_name      text,
  file_sha256    text,
  started_at     timestamptz NOT NULL DEFAULT now(),
  rows_read      integer NOT NULL DEFAULT 0,
  rows_inserted  integer NOT NULL DEFAULT 0,    -- new keys (version 1)
  rows_versioned integer NOT NULL DEFAULT 0,    -- new versions of existing keys
  rows_duplicate integer NOT NULL DEFAULT 0,    -- identical to the current version: skipped
  notes          text
);

CREATE TABLE fundamental_observations (
  id                 bigserial PRIMARY KEY,
  symbol             text NOT NULL REFERENCES securities (symbol),
  metric             text NOT NULL,              -- canonical name (dhandrishti.pit.metrics)
  value              double precision NOT NULL,  -- absent data is an absent row, never NULL or 0
  unit               text NOT NULL,              -- INR_CR | INR_PER_SHARE | PCT | SHARES_CR
  currency           text NOT NULL DEFAULT 'INR',
  basis              text NOT NULL CHECK (basis IN ('CONSOLIDATED', 'STANDALONE')),
  period_type        text NOT NULL CHECK (period_type IN ('Q', 'H', 'FY', 'INSTANT')),
  period_start       date,                       -- NULL for INSTANT (balance sheet, shareholding)
  period_end         date NOT NULL,              -- last day covered, or the 'as at' date for INSTANT
  filing_type        text NOT NULL CHECK (filing_type IN
                       ('QUARTERLY_RESULT', 'ANNUAL_RESULT', 'ANNUAL_REPORT', 'SHAREHOLDING_PATTERN', 'OTHER')),
  reported_at        timestamptz,                -- when the issuer/exchange published it (NULL: unknown)
  available_at       timestamptz,                -- earliest moment DhanDrishti may use it in a decision
  availability_basis text NOT NULL CHECK (availability_basis IN
                       ('EXCHANGE_TIMESTAMP', 'REPORTED_DATE', 'STATUTORY_DEADLINE', 'UNKNOWN')),
  value_vintage      text NOT NULL CHECK (value_vintage IN ('AS_REPORTED', 'AS_CURRENTLY_DISPLAYED')),
  source             text NOT NULL,
  source_record_id   text,                       -- provider's id, filing URL or file reference
  import_batch_id    bigint NOT NULL REFERENCES fundamental_import_batches (id),
  ingested_at        timestamptz NOT NULL DEFAULT now(),
  data_version       integer NOT NULL CHECK (data_version >= 1),
  supersedes_id      bigint REFERENCES fundamental_observations (id),
  is_restatement     boolean NOT NULL DEFAULT false,  -- true: the issuer published a changed figure later
  CHECK (period_type = 'INSTANT' OR period_start IS NOT NULL),
  CHECK (period_start IS NULL OR period_start <= period_end),
  CHECK (reported_at IS NULL OR (reported_at AT TIME ZONE 'Asia/Kolkata')::date >= period_end),
  CHECK (available_at IS NULL OR reported_at IS NULL OR available_at >= reported_at),
  CHECK ((availability_basis = 'UNKNOWN') = (available_at IS NULL)),
  CHECK ((data_version = 1) = (supersedes_id IS NULL)),
  UNIQUE (symbol, metric, basis, period_type, period_end, source, data_version)
);
CREATE INDEX fundamental_observations_pit_idx
  ON fundamental_observations (symbol, available_at, metric);

-- Append-only: history is corrected by adding a version, never by editing or deleting.
CREATE FUNCTION dd_reject_observation_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'fundamental_observations is append-only (% rejected); add a new data_version instead', TG_OP
    USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER fundamental_observations_no_update BEFORE UPDATE OR DELETE ON fundamental_observations
  FOR EACH ROW EXECUTE FUNCTION dd_reject_observation_change();
CREATE TRIGGER fundamental_observations_no_truncate BEFORE TRUNCATE ON fundamental_observations
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_observation_change();
