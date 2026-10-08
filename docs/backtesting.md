# Backtesting

Question it answers: **would the DhanDrishti score have picked better stocks in the past?**

```bash
pnpm backtest --start 2023-10-01                          # monthly, top 10, risk ≤ MEDIUM
pnpm backtest --start 2023-10-01 --rebalance quarterly --top-n 5 --max-risk LOW --name "Quarterly low risk"
pnpm backtest --start 2023-10-01 --mock                   # no database: generator in memory, prints JSON
```
Results appear at **/backtest** in the web app (`GET /v1/backtests`, `/v1/backtests/:id`).

## Method (`apps/worker/src/dhandrishti/backtesting/`)
1. **Signal.** On the last trading day of each period (weekly, monthly or quarterly), the engine
   re-scores the universe with `MarketHistory.market_at(date)`. That uses prices up to that close
   and **only fundamentals already published** (each snapshot is dated by its publication date).
   Indicators use the same 300-session window as live scoring.
2. **Select.** Top N by score, after optional filters (`--max-risk`, `--min-confidence`),
   equal-weighted.
3. **Execute.** Trades happen at the **next session's open**, so a signal never trades on the
   close that produced it.
4. **Costs.** Per side, in basis points of traded value:
   - Buy: 15 bps (STT 10 + stamp duty 1.5 + exchange/SEBI/GST ≈ 0.5 + slippage ≈ 3).
   - Sell: 13.5 bps.
   - Brokerage is assumed to be zero (delivery at discount brokers).
   - Change these with `--buy-cost-bps` and `--sell-cost-bps`.
5. **Benchmarks** run on the same dates:
   - **NIFTY 50** (price index).
   - **Equal-weight universe**: every scored stock, with the same schedule and costs. Beating
     this is the real test, because it isolates whether the *score* adds value over simply
     owning the universe.

## Metrics
- **Performance:** CAGR, volatility, Sharpe and Sortino (`--risk-free`, default 0), max
  drawdown and its dates, and Calmar.
- **Relative to each benchmark:** excess CAGR, beta, tracking error, information ratio, and the
  share of periods won.
- **Signal quality:** per rebalance, the forward return of *every* scored stock is grouped into
  score quintiles, and the rank correlation between score and forward return is measured
  (**IC**). Rising quintile bars and a positive, stable IC mean the score carries information.
  On real data, a mean IC of 0.03–0.05 that persists across years is meaningful. Much higher
  values usually mean a bug or look-ahead.

## Safeguards (tested in `tests/test_backtest.py`)
- **Look-ahead canary.** Multiplying every *future* price by random factors must not change the
  stocks picked at an earlier signal.
- **History check.** Runs are refused when there are fewer than 300 sessions of history before
  the first signal.
- **Determinism.** Same inputs give the same JSON output.
- **Database round trip.** History loaded from PostgreSQL gives metrics identical to the
  in-memory generator.

## Known limitations — read before trusting any number
- **MOCK data has a built-in edge.** The generator uses one hidden "quality" factor for both
  fundamentals and future returns, so the score is guaranteed to look predictive on mock data.
  Mock backtests validate the *machinery* only.
- **Survivorship bias.** The real universe is today's NIFTY 200 (the MOCK universe, 44 symbols).
  Unbiased backtests need point-in-time index membership, including delisted and dropped stocks.
- **Price returns only.** Dividends are ignored, and NIFTY is the price index, not the total
  return index.
- **Simplified execution.** Fractional shares, and costs applied as a proportional haircut. A
  stock with no open price on an execution day is not bought, and existing holdings are valued
  at their last price.
- **Data snooping.** The scoring weights were chosen by design, not fitted. If you tune weights
  to improve a backtest, validate on a later period you did not tune on.
- **Market impact.** Liquidity and capacity are not modelled beyond the liquidity score.

## Storage
Migration `0003_backtests.sql` adds three tables: `backtest_runs` (parameters, metrics,
per-period results, status), `backtest_equity` (daily values) and `backtest_holdings` (picks per
rebalance). They are plain tables, because they are small and always read by run.
