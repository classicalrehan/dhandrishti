# Paper trading

Simulated portfolios that trade the DhanDrishti score **with real trading rules, but no real
orders**. Use them to build confidence over months before risking real money.

## Daily routine (after 16:30 IST)
```bash
pnpm kite:login     # Kite tokens expire at 6 AM daily
pnpm daily:kite     # loads today's real prices, then processes every paper portfolio
pnpm dev:kite       # view at https://dhandrishti.test/paper (with pnpm proxy)
```
If you skip days, the next run catches up every missed session, in order.

## Managing portfolios
```bash
pnpm paper create --name "Monthly top 5" --capital 100000 --top-n 5 \
    [--rebalance monthly|weekly|quarterly] [--max-risk MEDIUM] [--min-confidence HIGH] \
    [--stop-loss 10] [--rank-buffer 10] [--kill-switch 18]
pnpm paper list
pnpm paper resume <id>   # after a kill switch; drawdown is then measured from that day's value
pnpm paper close <id>    # stop it; history is kept
```

## Rules (`apps/worker/src/dhandrishti/trading/paper.py`)
1. **Signal.** Decisions use the close of the last session of each week, month or quarter, with
   point-in-time scores (the same path as the backtester).
2. **Fill.** Orders fill at the **next session's real open**. Sells go first, then buys, in
   whole shares. If the open gaps above the plan, the buy shrinks to what cash allows. A stock
   with no price is retried for up to 3 sessions, then cancelled.
3. **Charges.** Zerodha equity-delivery charges, per `trading/costs.py`:
   - STT: 0.1% on buy and sell.
   - Stamp duty: 0.015% on buys.
   - NSE transaction charge: 0.00307%.
   - SEBI fee: ₹10 per crore.
   - GST: 18% on the transaction and SEBI charges.
   - DP charge: ₹15.34 per stock sold.
   - Brokerage: ₹0.
4. **Rank buffer.** A holding is kept while it stays within the top `rank_buffer` eligible
   stocks. Only empty slots are filled, and existing holdings are not resized. This means fewer
   trades and lower charges.
5. **Stop-loss.** If a close is `stop_loss`% below the average buy price, the position is sold at
   the next open.
6. **Kill switch.** At a drawdown of `kill_switch`% from peak value, every holding is sold at the
   next open and buying stops until you resume.

## Reading the results
- **Benchmark.** Compare with **NIFTY over the same days**, which the page shows next to the
  return. Beating it by a meaningful margin, after charges, for several months, through both
  rising and falling markets, is the bar before real money.
- **Small capital.** At ₹1 lakh, whole shares leave some cash idle. A ₹6,000+ stock in a ₹20,000
  slot buys only 3 shares. This is realistic, not a bug.
- **Price-only scores.** The current Kite data has no fundamentals, so the score is price-based.
  The real-data backtest found **no edge** for that version (docs/backtesting.md). Watch the
  variants side by side while the model improves.

## Universe change (2026-10-08)
From 2026-10-08 the real database scores the NIFTY 200 (plus listed stocks you hold) instead of the
original 44 large caps. Portfolios #1 and #2 started on 2026-10-06 with 44 stocks; their next
rebalance picks from the larger list. Bear this in mind when reading their first days.

## Optional rules (added 2026-10-08)
`pnpm paper create` also accepts:
- `--trailing-stop 15`: sell on a close 15% below the highest close since buying
- `--min-history 252`: skip stocks with less than about a year of price history
- `--regime-slots "BEARISH=0,CAUTIOUS=3"`: cap holdings by market regime (the rest stays cash)

They are off by default. Which of them helped is in [research/2026-10-rule-study.md](research/2026-10-rule-study.md):
portfolio #3 uses `--stop-loss 15 --rank-buffer 20 --min-history 252`. Regime caps did not help.
Compare rules with `pnpm rule-study` (about 4 minutes).
