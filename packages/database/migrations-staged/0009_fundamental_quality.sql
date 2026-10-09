-- STAGED, NOT FOR PRODUCTION YET (Phase 1, 2026-10-09). Lives outside migrations/ so `migrate()` in the
-- daily jobs never applies it. Applied only to test databases via dhandrishti.db.staged.apply_staged().
-- Design: docs/fundamentals-quality-design.md. Adds data-quality controls around fundamental_observations
-- without changing that table or its append-only triggers.

-- Generic append-only guard for the new tables (the existing dd_reject_observation_change is left untouched).
CREATE FUNCTION dd_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
END $$;

-- Every filing seen, whatever happened to it.
CREATE TABLE fundamental_filings (
  id               bigserial PRIMARY KEY,
  source           text NOT NULL,
  file_name        text NOT NULL,
  file_sha256      text NOT NULL UNIQUE,
  symbol           text NOT NULL REFERENCES securities (symbol),
  basis            text CHECK (basis IN ('CONSOLIDATED', 'STANDALONE')),
  period_end       date NOT NULL,
  taxonomy         text NOT NULL,
  published_at     timestamptz,
  outcome          text NOT NULL CHECK (outcome IN ('IMPORTED', 'REFUSED')),
  import_batch_id  bigint REFERENCES fundamental_import_batches (id),
  recorded_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((outcome = 'IMPORTED') = (import_batch_id IS NOT NULL))
);

-- How each stored value was obtained. One row per observation; the observation itself is never touched.
CREATE TABLE fundamental_value_provenance (
  observation_id   bigint PRIMARY KEY REFERENCES fundamental_observations (id),
  filing_id        bigint REFERENCES fundamental_filings (id),
  how_obtained     text NOT NULL CHECK (how_obtained IN ('REPORTED', 'SUMMED', 'CALCULATED', 'INFERRED')),
  source_concepts  text[] NOT NULL CHECK (cardinality(source_concepts) >= 1),
  source_contexts  text[],
  derivation       text,
  mapping_note     text,
  recorded_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((how_obtained = 'REPORTED') = (derivation IS NULL)),
  CHECK (how_obtained <> 'REPORTED' OR cardinality(source_concepts) = 1),
  CHECK (how_obtained <> 'SUMMED' OR cardinality(source_concepts) >= 2),
  CHECK (how_obtained <> 'INFERRED' OR mapping_note IS NOT NULL)
);

-- Check results. REVIEW always names the value it concerns, so one doubtful value never hides the rest of
-- the filing. BLOCK and NOTE may be filing-level.
CREATE TABLE fundamental_quality_flags (
  id               bigserial PRIMARY KEY,
  filing_id        bigint NOT NULL REFERENCES fundamental_filings (id),
  observation_id   bigint REFERENCES fundamental_observations (id),
  check_code       text NOT NULL,
  check_version    integer NOT NULL CHECK (check_version >= 1),
  severity         text NOT NULL CHECK (severity IN ('BLOCK', 'REVIEW', 'NOTE')),
  observed         jsonb NOT NULL DEFAULT '{}',
  message          text NOT NULL,
  raised_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (severity <> 'REVIEW' OR observation_id IS NOT NULL)
);
CREATE INDEX fundamental_quality_flags_obs_idx ON fundamental_quality_flags (observation_id);

-- Decisions on flags. Latest per flag wins; earlier decisions stay.
CREATE TABLE fundamental_flag_dispositions (
  id               bigserial PRIMARY KEY,
  flag_id          bigint NOT NULL REFERENCES fundamental_quality_flags (id),
  disposition      text NOT NULL CHECK (disposition IN
                     ('ACCEPTED_AS_FILED', 'SUPERSEDED_BY_OFFICIAL_SOURCE', 'EXCLUDED', 'EXPLAINED')),
  reason           text NOT NULL,
  evidence         text,
  decided_by       text NOT NULL,
  decided_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Checks of stored values against official documents.
CREATE TABLE fundamental_verifications (
  id                bigserial PRIMARY KEY,
  observation_id    bigint NOT NULL REFERENCES fundamental_observations (id),
  reference_doc     text NOT NULL,
  reference_locator text NOT NULL,
  reference_value   double precision,
  difference        double precision,
  status            text NOT NULL CHECK (status IN ('VERIFIED', 'MISMATCH', 'NOT_IN_DOCUMENT')),
  method            text NOT NULL,
  checked_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((status = 'NOT_IN_DOCUMENT') = (reference_value IS NULL))
);

CREATE TRIGGER fundamental_filings_no_update BEFORE UPDATE OR DELETE ON fundamental_filings
  FOR EACH ROW EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_filings_no_truncate BEFORE TRUNCATE ON fundamental_filings
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_value_provenance_no_update BEFORE UPDATE OR DELETE ON fundamental_value_provenance
  FOR EACH ROW EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_value_provenance_no_truncate BEFORE TRUNCATE ON fundamental_value_provenance
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_quality_flags_no_update BEFORE UPDATE OR DELETE ON fundamental_quality_flags
  FOR EACH ROW EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_quality_flags_no_truncate BEFORE TRUNCATE ON fundamental_quality_flags
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_flag_dispositions_no_update BEFORE UPDATE OR DELETE ON fundamental_flag_dispositions
  FOR EACH ROW EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_flag_dispositions_no_truncate BEFORE TRUNCATE ON fundamental_flag_dispositions
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_verifications_no_update BEFORE UPDATE OR DELETE ON fundamental_verifications
  FOR EACH ROW EXECUTE FUNCTION dd_reject_change();
CREATE TRIGGER fundamental_verifications_no_truncate BEFORE TRUNCATE ON fundamental_verifications
  FOR EACH STATEMENT EXECUTE FUNCTION dd_reject_change();

-- Observation plus provenance and quality state. A value is usable when it has no REVIEW flag without a
-- disposition and its latest disposition is not EXCLUDED / SUPERSEDED. NOTE flags never affect usability.
CREATE VIEW fundamental_observation_status AS
WITH latest AS (
  SELECT DISTINCT ON (flag_id) flag_id, disposition FROM fundamental_flag_dispositions
  ORDER BY flag_id, decided_at DESC, id DESC
), per_obs AS (
  SELECT f.observation_id,
         bool_or(f.severity = 'REVIEW' AND l.disposition IS NULL) AS open_review,
         bool_or(l.disposition IN ('EXCLUDED', 'SUPERSEDED_BY_OFFICIAL_SOURCE')) AS excluded
  FROM fundamental_quality_flags f LEFT JOIN latest l ON l.flag_id = f.id
  WHERE f.observation_id IS NOT NULL
  GROUP BY f.observation_id
)
SELECT o.*, p.how_obtained, p.source_concepts, p.derivation, p.mapping_note, p.filing_id,
       coalesce(s.open_review, false) AS open_review,
       coalesce(s.excluded, false) AS excluded,
       NOT coalesce(s.open_review, false) AND NOT coalesce(s.excluded, false) AS usable,
       (SELECT v.status FROM fundamental_verifications v WHERE v.observation_id = o.id
        ORDER BY v.checked_at DESC, v.id DESC LIMIT 1) AS verification
FROM fundamental_observations o
LEFT JOIN fundamental_value_provenance p ON p.observation_id = o.id
LEFT JOIN per_obs s ON s.observation_id = o.id;
