# Real prices from Zerodha Kite Connect

DhanDrishti can load **real end-of-day prices** for the NIFTY 200 (plus any listed company you hold; see `packages/quant-spec/universe/README.md`) and the NIFTY 50, NIFTY
BANK and INDIA VIX indices from your Zerodha account, through Kite Connect. This is for
**personal use** under your Kite Connect subscription. Do not share the data or the app with
others.

## What changes with real data
| Part of the score | With Kite |
|---|---|
| Momentum, technical trend, liquidity, sector strength, risk (price-based), market regime | **Real** |
| Fundamental quality, earnings growth, valuation | **Data unavailable**: Kite Connect has no fundamentals API |
| Confidence | **Low** until a fundamentals source is added (about 45% of the score's weight has no data) |
| Labels in the app | `EOD`, not `MOCK` |

Missing fundamentals get the documented neutral treatment and are shown as "Data unavailable". The
app never fills them with mock values. Rankings are therefore driven by price behaviour only, until
we add a fundamentals source.

## One-time setup
1. **Create a Kite Connect app** at https://developers.kite.trade. Check the current pricing
   there: historical data access is required.
   - **Redirect URL:** `http://127.0.0.1:5010/kite/callback`
   - Note the **API key** and **API secret**.
2. **Create a separate database** for real data. The app refuses to mix real and mock data in one
   database:
   ```bash
   pnpm db:create-kite
   ```

## Every day (Kite tokens expire at 6 AM)
```bash
pnpm kite:login        # opens Kite login; asks for API key/secret unless KITE_API_KEY / KITE_API_SECRET are set
pnpm pipeline:kite     # ~1,500 days of EOD prices (first run takes a few minutes at Kite's 3 requests/s), then scores
pnpm dev:kite          # API + web on the Kite database → https://dhandrishti.test (with pnpm proxy)
```
`pnpm pipeline:kite` uses the **last completed session**: today only after 16:30 IST, otherwise
the previous trading day. Plain `pnpm dev` keeps showing the MOCK database. Switch by restarting
with the other command.

Backtest on real prices:
```bash
pnpm backtest:kite --start 2023-10-01 --name "Kite monthly top 10"
```
Without fundamentals, this tests the **price-based** half of the score only. Read results with
that in mind.

## Security
- **Read-only.** The client calls only login, instruments and historical-candle endpoints. There
  is no order placement code.
- **API secret.** It is used once per login to compute the checksum, and is never written to disk
  or logs.
- **Access token.** Saved to `~/.config/dhandrishti/kite_session.json` with permissions 600,
  outside the repository. Override the location with `DD_KITE_SESSION_FILE`.
- **Forged redirects.** The login callback checks a random `state` value, so a stray redirect
  cannot inject a token.
- **Daily manual login.** Login is manual every day, as Zerodha requires. Automating the
  Zerodha login (storing your password or TOTP) is against Kite's terms and is deliberately not
  supported.

## Known gaps
- **Corporate actions.** Kite's documentation does not state whether daily candles are adjusted
  for splits and bonuses. Ingestion warns about any close-to-close move above 35%. Check those
  dates before trusting indicators or backtests around them.
- **Sector classification.** Sectors come from DhanDrishti's own universe list.
- **Missing symbols.** Symbols missing from Kite's instrument list (renamed or delisted) are
  skipped with a warning.
- **Survivorship bias.** The universe is *today's* NIFTY 200, so backtests on real prices carry
  survivorship bias: stocks that rose into the index look investable in the past, and stocks that fell
  out are missing. On 2024–2026 data the equal-weight universe returned +14.6% a year against NIFTY's
  +1.3%, which shows how large this effect is. Judge strategies against the equal-weight universe, and
  by the signal statistics (IC, quintile spread), not by the headline CAGR.
