-- Highest close since entry, for the optional trailing stop-loss (NULL: not tracked yet).
ALTER TABLE paper_positions ADD COLUMN high_close double precision;
