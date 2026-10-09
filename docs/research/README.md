# Research

Studies that decide whether a signal or rule deserves to reach paper trading, and later real money.
Production scoring never changes because of a study alone: a change goes through `SPEC.md`, a config
version bump and the golden fixtures.

## Tools
| Command | Question it answers | Code |
|---|---|---|
| `pnpm factor-study` | Does each score component, and the composite, predict forward returns? At 5/20/60/120/252 sessions, by regime, period, size proxy and sector; composite buckets; rank stability; missing-data variants | `research/factors.py`, `jobs/factor_study.py` |
| `pnpm rule-study` | Do trading rules (stops, rank buffer, regime caps, history filter) help in train and validation? | `research/replay.py`, `jobs/rule_study.py` |
| `pnpm backtest:kite` | How would one rule set have traded, with costs, against NIFTY and the equal-weight universe? | `backtesting/` |

## Experiments
`factor-study` writes every run to `.research/runs/<timestamp>-<name>/` (not committed):
- `config.json`: parameters, scoring-config version and hash, a hash of the worker code, and a data
  fingerprint (database, row counts, date range, last ingestion times).
- `results.json`: every computed number. `report.md`: the generated tables.
- `.research/runs/index.jsonl`: one line per run, for comparing runs over time.

The scored panel is cached in `.research/panels/` by the same fingerprints, so re-running analysis on
unchanged code and data takes seconds; any change to code, config or data rebuilds it.

## Rules for reading results
- **Point in time.** Factors use `MarketHistory.market_at(date)`: prices to that close, fundamentals
  published by then. Forward returns start at the next session's open.
- **Survivorship bias.** The universe is today's NIFTY 200 applied to the past. It flatters factors
  that buy past winners. Until historical membership exists, compare factors with each other and look
  for consistency across periods and regimes, not at absolute levels.
- **Multiple testing.** Ten factors at five horizons give fifty numbers; a few will look significant by
  chance. Trust results that hold across periods, regimes and neighbouring horizons.
- **Overlap.** Weekly samples with 20 to 252-session horizons overlap; t-stats use Newey-West.

## Reports
- [2026-10 Phase 1 audit](2026-10-phase1-audit.md)
- [2026-10 Rule study](2026-10-rule-study.md)
- [2026-10 Price-factor study](2026-10-price-factor-study.md)
- [2026-10 Fundamentals pilot](2026-10-fundamentals-pilot.md) (2 of 20 stocks; 32 filings imported)
- [2026-10 Fundamentals validation](2026-10-fundamentals-validation.md) (read-only checks of the import)
