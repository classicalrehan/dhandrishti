# Real universe (Kite database)

Official constituent lists from NSE Indices, downloaded 2026-10-08:

- `nifty200.csv`: https://niftyindices.com/IndexConstituent/ind_nifty200list.csv (the scored universe)
- `nifty-total-market.csv`: https://niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv
  (about 750 companies; used only to add stocks you hold that are outside the NIFTY 200, with their sector)

NSE rebalances these indices twice a year (March and September). To refresh, download both files
again, review the diff, and run `pnpm pipeline:kite`. Stocks that leave the index stay in the database
(their history is kept) and are still scored.

**Backtest caveat (survivorship bias):** backtests apply *today's* list to past dates, so they never
hold a stock that was in the index then but has since dropped out. That flatters past results a little.

Sectors are NSE's industry classification, shortened (`ingestion/nse_universe.py`); banks are split
out of Financial Services as "Banking". The MOCK database keeps its fixed 44-stock universe.
