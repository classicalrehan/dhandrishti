# My Portfolio: real Zerodha holdings (read-only)

`pnpm holdings` fetches your demat holdings and open positions from Kite Connect and saves a
snapshot in the Kite database. The **My Portfolio** page (`/portfolio`, on `pnpm dev:kite`) shows each
holding next to its latest DhanDrishti score. `pnpm daily:kite` runs it after the paper portfolios.

## What is called, and what is not
- Only `GET /portfolio/holdings` and `GET /portfolio/positions`, with the session from `pnpm kite:login`.
- The client has no order, modify, cancel or GTT methods (a test checks this).
- Snapshots live only in the local `dhandrishti_kite` database. The command refuses the MOCK database.
- The holdings endpoint is **not** in the AI research tool catalogue or the MCP server, so Claude never
  sees your portfolio. The API listens on 127.0.0.1 only and never caches holdings in Redis.

## Snapshots
- One per date. A fetch after 09:15 IST on a trading day is dated today; earlier or on a holiday,
  the last completed session. Fetching again the same day replaces it, so the evening fetch wins.
- Holdings quantity = settled + T1 (bought, not yet in demat). Positions are shown separately and not scored.

## "Since tracking began" return (time-weighted)
Each period applies the **previous** snapshot's quantities to today's prices:

    period return = Σ qty_prev × price_now / Σ qty_prev × price_prev − 1

and the periods are chained (index = 100 at the first snapshot). Buying more, adding money or new
stocks therefore does not count as profit. A holding sold since the previous snapshot is priced with
its database close when it is in the universe, otherwise left out of that period. NIFTY 50 is shown over
the same dates.

## "Worth a look" notes
Fixed display rules over the engine's output (`WATCH` in `apps/api/src/services/market-service.ts`),
not advice:
- rank in the bottom third of the scored stocks
- HIGH or VERY_HIGH risk level (with the top risk flags)
- price in a downtrend (DOWNTREND / STRONG_DOWNTREND)
- down 10% or more from your average buy price (the paper portfolios' stop-loss level)
- more than 25% of the portfolio in one stock

Stocks outside the scored universe (ETFs, unlisted shares, companies outside the NIFTY Total Market list) show "Not scored", with their value and P&L.
