# DhanDrishti — Architecture

_Last updated: 2026-10-06 (Increment 6: AI research assistant)_

DhanDrishti is a **modular monorepo**, not a set of microservices. The project started greenfield on
2026-10-05; no earlier codebase existed, so there is no legacy code to migrate.

## 1. Target architecture

```
                ┌──────────────┐
  Browser ────▶ │  apps/web    │  Next.js · React · Tailwind · shadcn/ui · Recharts / Lightweight Charts
                └──────┬───────┘
                       │ HTTP (typed contracts, Zod)
                ┌──────▼───────┐        ┌───────────────┐
                │  apps/api    │◀──────▶│ Redis (cache, │
                │  Fastify     │        │ rate limits,  │
                │  services +  │        │ job queue)    │
                │  repositories│        └───────▲───────┘
                └──────┬───────┘                │ jobs
                       │ SQL (read-mostly)      │
                ┌──────▼──────────────────┐     │
                │ PostgreSQL + TimescaleDB│◀────┤
                │ (source of truth)       │     │
                └──────▲──────────────────┘     │
                       │ writes scores, indicators, rankings
                ┌──────┴───────┐                │
                │ apps/worker  │────────────────┘
                │ Python quant │  pandas · NumPy · (SciPy for backtesting stats) · pytest
                └──────▲───────┘
                       │ MarketDataProvider / FundamentalDataProvider / NewsProvider / CorporateActionProvider
                  data providers (MOCK today; licensed feeds later)

  Claude ─▶ AI tools (apps/api, packages/ai) ─▶ application services ─▶ repositories ─▶ DB
  MCP client ─▶ apps/mcp (thin TS tool layer) ─▶ same application services (via API) ─▶ DB
```

### Responsibilities
| Layer | Owns | Must not |
|---|---|---|
| `packages/quant-spec` | Formulas, normalization, weights (`scoring-config.json`), output contract, golden fixtures | — |
| `apps/worker` (Python) | Ingestion, indicators, scoring, risk, sector, regime, ranking, backtesting; writes results to Postgres | Serve end-user HTTP traffic |
| `apps/api` (Fastify) | Auth, authorization, Zod validation, orchestration, caching, DB reads, AI tools | Heavy quantitative computation |
| `apps/web` | Presentation; MOCK/LIVE labelling; disclaimers | Compute scores |
| `apps/mcp` | Thin MCP tool definitions that call API services | Contain business logic or touch the DB directly |
| `packages/ai` | Claude client, tool schemas, grounding prompts | Invent data, modify scores, run SQL, place trades |
| Redis | Caches (market overview, Top Opportunities, stock scores), rate limiting, job queue | Be a source of truth |
| PostgreSQL / Timescale | Source of truth | — |

### Storage plan
TimescaleDB hypertables apply only to high-volume time series: `daily_prices`, `intraday_prices`,
`technical_indicators`, `score_history`, `ranking_history`, `index_prices`. Relational data
(`securities`, `sectors`, `fundamentals`, `corporate_events`, `users`, `watchlists`, `portfolios`,
`alerts`, `scoring_config_versions`) stays in plain PostgreSQL tables.

## 2. Key decisions

1. **Python is the single quant implementation.** Because there was no existing TypeScript engine,
   no logic is duplicated across languages. The TypeScript indicator code drafted early in this
   session was removed before anything depended on it, and its tests were ported to pytest. Any
   future second implementation must pass the golden fixtures.
2. **Spec first.** `packages/quant-spec/SPEC.md` defines semantics and `scoring-config.json` holds every
   number. Python (`dhandrishti.config`) and TypeScript (`@dd/config`) both read that one JSON file.
3. **Determinism.** The engine takes `as_of` as an input and makes no clock or network calls.
   Mock data uses PCG64 streams seeded from `crc32("<seed>:<stream>")`. Golden fixtures store
   the generated *inputs*, so tests do not depend on RNG stream stability across NumPy versions.
4. **Explicit provenance.** Every result carries `data_provenance` (`MOCK | EOD | DELAYED | LIVE`).
   Today it is always `MOCK`, and the UI must show it.
5. **Shared calendar data.** The NSE holiday list is one JSON file
   (`packages/shared/src/nse-holidays.json`) read by both TypeScript and Python. It is marked
   `verified: false` until it is checked against the official NSE circular.

## 3. Current state vs target (gap analysis)

| Area | Target | Current (Increment 6) | Status |
|---|---|---|---|
| Monorepo | pnpm + Turborepo | pnpm 10, Turborepo 2; `turbo run test` covers TypeScript and Python | ✅ |
| Quant spec | Single source of truth | `SPEC.md` + `scoring-config.json` + golden fixtures | ✅ |
| Indicators | Python | SMA/EMA/RSI/MACD/ATR/ADX/Bollinger, returns, volatility, drawdown, 52W, RS, trend | ✅ |
| Scoring | Python, configurable weights | 8 components, reasons, confidence, value-trap guard, ranking | ✅ |
| Risk engine | Python | 12 flags, points, levels | ✅ |
| Sector / regime | Python | Sector strength + ranking; 6-factor regime with bounded confidence | ✅ |
| Mock data | Deterministic, labelled | 44-symbol universe, indices, VIX, fundamentals, events; `MOCK` | ✅ |
| Provider interfaces | MarketData / Fundamental / News / CorporateAction | `dhandrishti.providers` Protocols; `MockProvider` implements all four (news intentionally empty); **Zerodha Kite Connect** for real EOD prices + indices ([docs/kite.md](kite.md)); fundamentals source still needed | ✅ prices · ⏳ fundamentals |
| Database | Postgres + Timescale | SQL migrations in `packages/database`; 5 hypertables, relational tables, `ranking_history` view; checksum-guarded runner | ✅ (Timescale path awaiting first Docker run) |
| Worker jobs | Python jobs writing to DB | `ingest` (providers → DB), `run_scoring` (DB → engine → DB), `daily` (migrate + both) | ✅ |
| API | Fastify + Zod | `apps/api`: 8 read-only GET endpoints; every response validated against `@dd/contracts`; service + repository layers; no quant logic | ✅ (no auth yet; read-only) |
| Redis | Caching, jobs, rate limit | Read-through cache (run-scoped keys) + Redis-backed rate limiting; both fail open. Job queue not needed yet | ✅ caching, rate limit · ⏳ jobs |
| Web | Next.js dashboard | `apps/web`: Dashboard, Top Opportunities, Stock Research (8 tabs, interactive chart), Sectors, Market Pulse, Risk Radar; MOCK banner on every data page | ✅ |
| MCP | Thin TS server | `apps/mcp`: 12 read-only tools over the HTTP API, stdio transport, no credentials ([docs/mcp.md](mcp.md)) | ✅ |
| AI assistant | Claude via app tools | `packages/ai` (shared tool catalogue, tool loop, grounding check) + `POST /v1/research/chat` (SSE) + `/research` page ([docs/ai-assistant.md](ai-assistant.md)) | ✅ (live model not yet exercised: no credentials) |
| Paper trading | Simulated trading with real rules | `trading/` (Zerodha charges, paper engine), migration 0004, `pnpm paper` / `pnpm daily:kite`, `/paper` page ([docs/paper-trading.md](paper-trading.md)) | ✅ |
| My Portfolio | Real Zerodha holdings next to their scores (read-only, private) | `providers/kite` portfolio reads, `trading/holdings.py`, migration 0006, `pnpm holdings`, `/v1/holdings`, `/portfolio` page; not exposed to AI/MCP ([docs/holdings.md](holdings.md)) | ✅ |
| Backtesting | Python | `backtesting/` point-in-time engine: next-open execution, Indian costs, NIFTY + equal-weight benchmarks, quintile/IC tests; `/backtest` page ([docs/backtesting.md](backtesting.md)) | ✅ (MOCK only) |
| Infra | Docker Compose | `docker-compose.yml`: TimescaleDB 2.30.2-pg17, Redis 8.8 (cache-only config) | ✅ |

## 4. Increment plan

Each increment ends with green tests and a review pause.

1. ✅ **Quant foundation**: spec, config, Python indicators/scoring/risk/sector/regime, mock data,
   golden fixtures.
2. ✅ **Persistence**: Docker Compose (Postgres+Timescale, Redis), schema migrations, provider
   interfaces in the worker, and a job that scores the universe and writes `score_history` /
   `ranking_history` / `daily_prices`.
3. ✅ **API + web**: Fastify read endpoints (Zod contracts mirroring SPEC §11), then the Next.js
   dashboard, Top Opportunities, Stock Research, Sectors, Market Pulse and Risk Radar, all
   reading from the API with a visible MOCK banner.
4. ✅ **Caching**: Redis caching for overview, opportunities and scores, plus rate limiting.
5. ✅ **MCP**: tools such as `get_stock_score` that call the API service layer.
6. ✅ **AI research assistant**: Claude with read-only application tools and strict grounding.

## 5. Data flow (as built)

```
MockProvider ──(MarketData/Fundamental/CorporateAction/News interfaces)──▶ jobs.ingest
      ──upsert──▶ securities · daily_prices* · index_prices* · fundamentals · corporate_events · news_items
jobs.run_scoring ──load_market(as_of, no look-ahead)──▶ score_universe() (pure, deterministic)
      ──▶ scoring_runs · score_history* · technical_indicators* · sector_strength_history · market_regime_history
                                                         (* = TimescaleDB hypertable)
```

- **Decoupling.** The scoring engine reads only `MarketInput`, which is loaded from PostgreSQL. It
  never calls a provider.
- **Provenance.** Every row stores `data_provenance`. A loaded dataset is labelled with its
  least-live member (`MOCK < EOD < DELAYED < LIVE`), so mixing in mock data can never yield a
  `LIVE` label.
- **Config versions.** Each run stores the full scoring config under its version, with a SHA-256.
  A changed config without a version bump is rejected.
- **Re-runs.** Scoring the same day and config again overwrites `score_history` rows (the PK is
  symbol + as_of + config_version). `scoring_runs` keeps every attempt, including failures.
- **Fallback.** Without the timescaledb extension, the migration leaves time-series tables as
  plain PostgreSQL tables. The integration tests exercise this path.
- **Rankings.** `ranking_history` is a view over `score_history` rather than a second copy.
- **Not yet created.** `intraday_prices` waits until there is an intraday data source.
- **Redis.** Redis runs in Compose but nothing uses it yet (Increment 4).

### API and web (Increment 3)

```
apps/web (server components) ──GET──▶ apps/api /v1/*  ──▶ MarketService ──▶ PgMarketRepository ──▶ PostgreSQL
apps/web (chart range, search) ──GET from browser (CORS: GET only)──┘
```

- **Contracts.** `packages/contracts` holds the Zod schemas for every response. The API validates
  its output against them, so an engine output that drifts from SPEC §11 returns `500
  CONTRACT_VIOLATION` instead of bad data. The web app imports the inferred types.
- **No quant in the API.** The API passes engine JSON through from `score_history.result`.
  Chart overlays come from `indicator_series`, which the worker computes (migration 0002). The
  only derivation is the momentum *label* (Strong/Moderate/Weak), taken from the spec's
  `reason_thresholds`.
- **Failure states.** No scoring run returns `503 NO_DATA`, an unknown symbol returns 404, and an
  unreachable API shows a "API unavailable" page. The web app never falls back to bundled numbers.
- **Endpoints.** `/health`, `/v1/market/overview`, `/v1/opportunities`, `/v1/stocks/:symbol`,
  `/v1/stocks/:symbol/prices?range=1M|3M|6M|1Y|MAX`, `/v1/sectors`, `/v1/risk`, `/v1/search`,
  `/v1/scoring/config`.
- **UI.** shadcn-style primitives (cva + tailwind-merge) live in `apps/web/src/components/ui` and
  move to `packages/ui` when a second consumer exists. The price chart uses TradingView
  Lightweight Charts (Apache-2.0; attribution logo kept). Chart line colours were validated for
  colour-vision deficiency and contrast on the chart surface.
- **Not built yet.** Auth (the API is read-only and public on localhost), Redis caching
  (Increment 4), and the Screener, Signals, Watchlist, AI Research, Backtest, News, Portfolio,
  Alerts, Data Health and Settings pages, which appear as "Soon" in the nav.

### Caching and rate limiting (Increment 4)

```
MarketService ──▶ CachedMarketRepository ──hit──▶ Redis
                         └──miss──▶ PgMarketRepository ──▶ PostgreSQL ──▶ write back to Redis (TTL)
```

| Key | TTL | Why it is safe |
|---|---|---|
| `dd:v1:latest-run` | 15 s | The only key that can be stale: a new run appears within 15 s |
| `dd:v1:run:{run_id}:scores · score:{SYM} · sectors · regime` | 24 h | Scoring output never changes within a run, and a re-run gets a new `run_id` |
| `dd:v1:index:* · prices:* · fundamentals:* · events:* · history:*` | 5 min | Re-ingestion shows up within 5 min |
| `dd:v1:security:{SYM}` | 1 h | Reference data |
| `dd:rl:{ip}` | window | Rate-limit counters, shared by all API instances |

- **What is cached.** This covers the market overview, Top Opportunities and stock scores; the
  overview is assembled from cached parts.
- **Not cached.** Search, because free-text keys are unbounded and the query is cheap. Empty
  results, so newly ingested data shows up at once.
- **Fail open.** ioredis runs with no offline queue and one attempt per command. Cache errors
  count as misses; the rate limiter uses `skipOnError`. If Redis is down, the API serves from
  PostgreSQL and logs at most one warning per 30 s. `/health` reports the cache status and hit
  counts, but only the database decides its HTTP status.
- **Rate limit.** `DD_RATE_LIMIT_MAX` per IP per `DD_RATE_LIMIT_WINDOW_MS` (default 300/min).
  Exceeding it returns `429 RATE_LIMITED` with `retry-after` and `x-ratelimit-*` headers.
  `/health` is exempt.
- **Behind a proxy.** Per-IP limiting needs Fastify's `trustProxy` configured for the real client
  IP. This is not set yet.
- **Cache schema version.** Keys are prefixed `dd:v{CACHE_SCHEMA_VERSION}`. Bump the version
  whenever a repository return shape changes. This was found the hard way: after score history
  gained fields, cached entries in the old shape failed contract validation until the
  namespace changed. A regression test covers it.
- **Job queue.** The Redis job queue is deferred. The pipeline is a single `daily` command that
  cron or a scheduler can run. A queue becomes worthwhile once there are on-demand jobs, such as
  backtests requested from the UI.

## 6. Repository layout (current)

```
apps/
  api/                    Fastify API: routes/, services/, repositories/, cache/ (+ vitest unit & integration)
  mcp/                    MCP server: HTTP-backed ResearchPort + shared tool catalogue, stdio entry
  web/                    Next.js 16 app router, Tailwind 4, Lightweight Charts
  worker/                 Python quant engine (uv project)
    src/dhandrishti/
      indicators.py technicals.py normalize.py config.py stats.py
      fundamentals.py momentum.py valuation.py sector.py risk.py regime.py scoring.py
      calendar.py models.py paths.py
      ingestion/          mock.py (deterministic MOCK generator), universe.py, fixtures.py
      providers/          base.py (4 provider Protocols, provenance rules), mock.py (MockProvider)
      db/                 connect, migrate.py, market_repository.py, score_repository.py
      jobs/               ingest, run_scoring, daily, score_universe (no DB), generate_fixtures
    tests/                pytest (unit, rules, determinism, golden, DB integration)
packages/
  quant-spec/             SPEC.md, scoring-config.json, fixtures/{inputs,expected}
  database/               SQL migrations (schema source of truth)
  contracts/              Zod HTTP contracts shared by API, web and MCP
  ai/                     Research tool catalogue (shared by MCP + assistant), ResearchPort, Claude tool loop, grounding check
  config/                 Typed TS view of scoring-config.json
  shared/                 Domain types, IST/NSE calendar, formatting
docs/
```

The worker uses flat modules rather than the `ingestion/ indicators/ … jobs/` folder tree. That
tree would currently hold one file per folder. Modules will move into subpackages when they grow
(for example `backtesting/`).
