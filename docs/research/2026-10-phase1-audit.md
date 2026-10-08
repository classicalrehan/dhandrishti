# Phase 1 audit: scoring engine, data and research framework

Read-only audit, 8 October 2026, against the real database (`dhandrishti_kite`, scoring run 4,
201 stocks as of 2026-10-08). Nothing was changed to produce it.

## 1. Score calculation path
`jobs/daily` → `ingest` (Kite prices) → `run_scoring` → `scoring.score_universe(market)`:
`compute_technicals` per stock → `valuation.reprice` (needs per-share fundamentals) →
`sector_contexts` / `sector_strengths` → `score_stock` (8 × `score_component`) → rank by total →
`finalize_stock` rounding → `score_history` (full result JSON per stock). The same function scores
backtests (`MarketHistory.market_at`) and paper trading, so live and research share one path.

## 2. Components, weights and data dependence
| Component | Points | Inputs | Needs fundamentals |
|---|---:|---|---|
| Fundamental Quality | 25 | ROE, ROCE*, margin vs sector*, net margin, D/E*, interest cover*, CFO/PAT, FCF>0*, pledge, EPS consistency | **yes, entirely** |
| Earnings Growth | 20 | revenue, profit, EPS YoY; EPS 3Y CAGR; TTM EPS growth | **yes, entirely** |
| Momentum | 15 | returns 1M/3M/6M/1Y, RS vs NIFTY 3M/6M, up/down volume, acceleration | no |
| Technical Trend | 15 | above SMA50/200, SMA50>200, SMA200 slope, directional ADX, RSI, MACD, distance from 52W high | no |
| Valuation | 10 | PE vs sector, PE vs own 5Y median, PEG, PB vs sector, dividend yield | **yes, entirely** |
| Liquidity | 5 | 20D average traded value | no |
| Sector Strength | 5 | sector median RS 3M/1M, % above SMA50, median profit growth | partly (profit growth) |
| Risk | 5 | penalty points from flags | partly (D/E, interest cover, pledge, PE vs sector flags) |

\* skipped for financial companies (`non_financial_only`). Metric weights inside a component are in
`scoring-config.json`.

## 3. Missing-data behaviour (measured on run 4)
Two different rules apply, and they behave differently:

- **Whole component missing → fixed 0.5 (neutral).** Today Quality, Growth and Valuation are missing
  for every stock, so every stock gets exactly 12.5 + 10 + 5 = **27.5 constant points**. Because it is
  constant it does not change the ranking today; the ranking is driven entirely by the other 45
  points. It will create bias as soon as fundamentals cover some stocks and not others: a covered stock
  can score anywhere from 0 to 55 on them, an uncovered one always gets 27.5.
- **Some metrics missing → weights re-normalised over the metrics that exist.** A component with 3 of
  8 metrics is scored on those 3 at full weight. This **does bias the ranking today**: the 8 stocks
  with less than a year of history (no 1-year return, no SMA200) average rank **63 vs 103** for the
  rest and score **55.2 vs 48.1**; 4 of the top 15 are such recent listings (MEESHO #1, LENSKART #5,
  LGEINDIA #7, GROWW #15). Their scores rest on short-window momentum only.
- **Fundamental risk flags cannot fire** (debt, pledge, PE vs sector), so Risk is understated for
  every stock.
- A per-stock **`data_coverage`** already exists (weighted share of metrics present) and drives the
  confidence label: today 0.30 to 0.45, so **all 201 stocks are LOW confidence**. It is not split into
  fundamental and technical completeness.

## 4. Data storage, provenance and dates
| Data | Storage | Provenance / dates | Gaps |
|---|---|---|---|
| Daily prices | `daily_prices` hypertable, 201 symbols, 2022-08-29 to 2026-10-08 | `provenance`, `source`, `ingested_at` | Only ~4 years; refetched in full daily (overwritten, unversioned) |
| Indices | `index_prices`: NIFTY 50, NIFTY BANK, INDIA VIX | same | No NIFTY 200 / sector indices |
| Fundamentals | `fundamentals`: one row of **derived metrics** per (symbol, `as_of`) | `as_of` = publication date, `provenance`, `source`, `ingested_at` | **0 rows.** No raw line items (assets, cash, EBITDA, EBIT, EV); one date only (no separate reported/available time); **re-import overwrites** (PK symbol+as_of); no `data_version` |
| Corporate actions | `corporate_events` table | | **0 rows.** No split/bonus/demerger adjustment of our own; we rely on Kite's adjusted candles. A >35% one-day move is only flagged (NMDC 2022 flagged) |
| Holdings, paper, backtests, scores | own tables, migrations 0003/0004/0006/0007 | dated per run | fine |
| MOCK vs real | separate databases; ingest refuses mixed provenance; importer and holdings refuse MOCK | | fine |

## 5. Universe
Today's NIFTY 200 (NSE file, 8 Oct 2026) plus listed held stocks, applied to all past dates.
**Survivorship bias is large**: equal-weight universe +14.6%/yr vs NIFTY 50 +1.3%/yr (2024–26).
Kite's instrument list contains only currently traded symbols, so **delisted or renamed stocks
cannot be fetched from Kite at all**; historical index membership is not stored anywhere.

## 6. Backtest and research code
- `backtesting/engine.py`: signal at a period's last close, trade at the next open, proportional costs
  (15/13.5 bps), fractional shares; benchmarks NIFTY and equal-weight universe. Leakage guards:
  `market_at` slices prices and fundamentals by date; look-ahead canary test; trades-next-session test.
- **IC today**: one Spearman IC of the *composite* score per rebalance period, horizon = the
  rebalance interval, plus quintile mean returns and a t-stat. **No per-factor IC, no multiple
  horizons, no regime/sector/size breakdown, no rank-stability measures.**
- `research/replay.py` + `jobs/rule_study.py`: replays the live paper engine; one fixed train /
  validation split; benchmarks NIFTY and equal-weight.
- **Market-cap buckets are not possible yet**: no shares outstanding without fundamentals. Index
  membership (NIFTY 100 vs Midcap) would only be today's membership.
- Regime is recomputed point-in-time inside every `score_universe` call, so regime splits are
  available for research.

## 7. Paper trading
Engine (`trading/paper.py`) with whole shares, Zerodha charges, next-open fills, stop / trailing
stop, rank buffer, kill switch, optional regime caps and history filter. Evaluation shown: equity vs
NIFTY, drawdown, charges. **Not shown**: equal-weight benchmark, hit rate, per-trade attribution,
holding periods, turnover.

## 8. Tests
Worker 145 (incl. DB integration), API 46, AI 16, MCP 9, config 2; all pass. Gaps: the fundamentals
importer's **database path** (`jobs/import_fundamentals.run`) has no test; no test that scores are
unchanged when an unrelated stock's data is missing (missing-data invariance).

## 9. What limits statistical power
- **About 4 years of prices**, of which ~3 are usable after the 300-bar lookback: roughly 34 monthly
  cross-sections. A real IC of 0.03 needs far more than that to separate from zero. Kite serves daily
  candles back well over a decade, so extending to ~2012 is cheap; survivorship then grows unless
  historical index membership is reconstructed.
- **No fundamentals**: 55 points of the design are untested.

## 10. Recommended order (for review)
1. **Fundamentals source** (decision needed): raw quarterly and annual line items **with real
   publication timestamps**. If a source has no timestamps, use a conservative statutory lag (SEBI
   LODR: 45 days after quarter end, 60 days for Q4) and mark those rows `ESTIMATED`, excluded from
   strict point-in-time experiments.
2. **Versioned raw observation store** (symbol, metric, value, period, reported_at, available_at,
   source, ingested_at, data_version), append-only; derived snapshots built from it per date.
3. Fix the missing-data rules before fundamentals arrive: split `data_completeness` into fundamental
   and technical; decide (documented in SPEC) between a minimum-history eligibility rule and a
   coverage penalty.
4. Extend price history and add historical index membership to reduce survivorship.
5. Factor research harness: per-factor IC / rank IC / ICIR / hit rate at 5, 20, 60, 120, 252 days,
   split by regime, sector, period; composite bucket analysis; rank stability.
6. ML only if the above shows stable out-of-sample signal worth combining.
