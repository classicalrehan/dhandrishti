-- Per-share figures from the latest filing. When present, PE / PB / dividend yield / market cap
-- are recomputed from the scoring day's close instead of being frozen at the filing date.
ALTER TABLE fundamentals
  ADD COLUMN eps_ttm               double precision,
  ADD COLUMN book_value_per_share  double precision,
  ADD COLUMN dps_ttm               double precision,
  ADD COLUMN shares_outstanding_cr double precision;
