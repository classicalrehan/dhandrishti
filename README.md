# DHANDRISHTI

**See the signal. Understand the stock.**

DhanDrishti is an Indian equity intelligence platform (NSE). A transparent, deterministic
quantitative engine ranks stocks and explains *why* each one ranks where it does. It is research
and decision-support software, not investment advice. See [docs/compliance.md](docs/compliance.md).

Built for **personal use** (not a SaaS). Goal: find good stocks at good prices, prove it with paper
trading first, and only then consider real money.

## Where things stand (8 October 2026)

| Area | Status |
|---|---|
| Scoring engine | 8-part, 100-point score with reasons for every number ([SPEC](packages/quant-spec/SPEC.md)) |
| Real prices | Zerodha Kite Connect, end of day: **NIFTY 200 + listed stocks you hold** (201 stocks) |
| Company financials | **Not connected yet.** 55 of 100 points are neutral for every stock. Importer is ready: `pnpm fundamentals:import` ([docs/fundamentals-import.md](docs/fundamentals-import.md)) |
| Web app | Dashboard, Top Opportunities, Market Pulse, Sectors, Risk Radar, stock pages, AI Research, Backtesting, Paper Trading, My Portfolio |
| Backtesting | Point-in-time, with costs. **No proven stock-picking edge yet** (signal IC about 0.01) |
| Rule study | 15% stop, keep while top 20 and 1 year of history helped in train and validation; bear-market cash did not ([report](docs/research/2026-10-rule-study.md)) |
| Paper trading | 3 portfolios of ₹1 lakh running on real prices since 6 to 8 Oct 2026 |
| My Portfolio | Your Zerodha holdings (read-only) next to their scores |
| Orders | **None.** The app cannot place, modify or cancel orders |

### Daily routine (after 16:30 IST)
```bash
pnpm kite:login        # Zerodha login in the browser (token expires 6 AM)
pnpm daily:kite        # prices -> scores -> paper portfolios -> your holdings (~3 min)
pnpm dev:kite          # open https://dhandrishti.test (with `pnpm proxy`) or http://localhost:3100
```

### Safety rules kept throughout
- The Kite API secret is never stored; the session file is private (mode 600). Login is always manual.
- Your holdings never reach the AI assistant or the MCP server (a test enforces this).
- Real data (`dhandrishti_kite` database) and MOCK demo data (`dhandrishti`) never mix.
- Real money only after months of paper results, and only with your explicit decision.

The MOCK database (`pnpm dev`) holds synthetic demo data for 44 stocks and is labelled MOCK everywhere.

## Layout
See [docs/architecture.md](docs/architecture.md).

- `packages/quant-spec`: **source of truth** for formulas and weights (`SPEC.md`, `scoring-config.json`)
- `apps/worker`: Python quant engine (reference implementation)
- `apps/api`: Fastify + Zod read API · `apps/web`: Next.js UI · `apps/mcp`: MCP tools for Claude ([docs/mcp.md](docs/mcp.md))
- `packages/contracts`: Zod HTTP contracts
- `packages/database`: SQL migrations (PostgreSQL + TimescaleDB)
- `packages/config`, `packages/shared`: TypeScript config view, types and calendar

## Getting started
Requirements: Node ≥ 22, pnpm 10, [uv](https://docs.astral.sh/uv/) (installs Python 3.12).

```bash
pnpm install
(cd apps/worker && uv sync)

pnpm test            # TypeScript + Python tests via Turborepo
pnpm typecheck

# Score the MOCK universe and print JSON (no database needed)
cd apps/worker && uv run python -m dhandrishti.jobs.score_universe --as-of 2026-10-05
```

### Run the app
```bash
pnpm infra:up          # TimescaleDB + Redis via Docker Compose
pnpm pipeline:daily    # migrate → ingest MOCK data → score → persist
pnpm dev               # API on :4000, web on http://localhost:3100
pnpm test:integration  # worker + API tests against real Postgres and Redis
pnpm backtest --start 2023-10-01   # point-in-time backtest, view at /backtest (docs/backtesting.md)
```

### Real prices (Zerodha Kite Connect)
```bash
pnpm db:create-kite    # once: separate database for real data
pnpm kite:login        # daily (tokens expire 6 AM)
pnpm pipeline:kite && pnpm dev:kite
```
See [docs/kite.md](docs/kite.md). Kite provides prices only, so fundamentals show "Data unavailable".
The stock list is NSE's official NIFTY 200 file ([packages/quant-spec/universe](packages/quant-spec/universe/README.md)).

### Paper trading (simulated, no real orders)
```bash
pnpm paper create --name "Monthly top 5" --capital 100000 --top-n 5
pnpm kite:login && pnpm daily:kite     # every evening after 16:30 IST
```
See [docs/paper-trading.md](docs/paper-trading.md). Compare rule variants on history with
`pnpm rule-study` ([docs/research/2026-10-rule-study.md](docs/research/2026-10-rule-study.md)).

### My Portfolio (your real holdings, read-only)
```bash
pnpm holdings          # also part of pnpm daily:kite
```
Shows each Zerodha holding with its DhanDrishti score at `/portfolio`. Read-only: nothing is ever
bought or sold. See [docs/holdings.md](docs/holdings.md).

### Local HTTPS domain: https://dhandrishti.test (Caddy)
Caddy sits in front of both servers, so the web app and the API share one origin with no port:
`/v1/*` and `/health` go to the API (:4000), everything else to the web app (:3100).
Apache keeps port 80; Caddy uses only 443.

One-time setup:
```bash
echo "127.0.0.1 dhandrishti.test" | sudo tee -a /etc/hosts      # local domain
pnpm proxy:install                                               # checksum-verified Caddy into .tools/
sudo setcap cap_net_bind_service=+ep .tools/caddy                # allow port 443 without root
pnpm proxy           # first run creates Caddy's local CA; stop it with Ctrl-C
pnpm proxy:trust     # trust that CA in Chrome, Firefox and the system store (sudo for the last)
```
Then, each time:
```bash
pnpm dev             # API :4000 + web :3100
pnpm proxy           # https://dhandrishti.test
```
Without Caddy the app is still reachable at http://localhost:3100.

- **Local only.** Certificates come from Caddy's local CA (`local_certs`), with no internet or
  ACME involved. HTTP-to-HTTPS redirects are off because Apache owns port 80.
- **Client IPs.** The API trusts `X-Forwarded-For` only from a loopback proxy
  (`DD_TRUST_PROXY=loopback`), so per-IP rate limits see real clients behind Caddy.
- **Browser API address.** On an `https:` page, or one without a port, the browser calls the API
  on the same origin. Otherwise it uses the page host on port `NEXT_PUBLIC_DD_API_PORT` (4000).
  `NEXT_PUBLIC_DD_API_URL` overrides both. Server-side calls use `DD_API_URL`
  (default `http://127.0.0.1:4000`).
- **Overrides.** `DD_DOMAIN`, `DD_HTTPS_PORT`, `DD_API_UPSTREAM` and `DD_WEB_UPSTREAM` override the
  Caddyfile defaults.

## Changing the scoring model
1. Edit `packages/quant-spec/scoring-config.json` (and `SPEC.md` if the semantics change).
2. Bump `version`, then regenerate fixtures:
   `cd apps/worker && uv run python -m dhandrishti.jobs.generate_fixtures`
3. Review the fixture diff and record the change in `SPEC.md` §12.
# dhandrishti
