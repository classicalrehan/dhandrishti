# DhanDrishti MCP server

A thin, read-only [Model Context Protocol](https://modelcontextprotocol.io) server that lets
Claude (or any MCP client) query DhanDrishti research data.

```
Claude / MCP client ──stdio──▶ apps/mcp ──HTTP GET──▶ apps/api ──▶ services ──▶ repositories ──▶ PostgreSQL (+ Redis cache)
```

## Design rules
- **Shared catalogue.** Tool names, descriptions, input schemas and field selection live in
  `packages/ai` (`RESEARCH_TOOLS`). The in-app assistant uses the same catalogue, so the two
  cannot drift. MCP plugs in an HTTP-backed `ResearchPort`.
- **No business logic.** Every tool forwards to an API endpoint and passes engine output
  through unchanged. The only shaping is field selection (for example `get_stock_risks` returns
  the risk fields of the stock detail). Tests compare tool output against the golden fixtures
  field by field.
- **No credentials.** The server knows one thing: `DD_API_URL`. It cannot reach PostgreSQL or
  Redis, run SQL, write data or place trades.
- **Read-only.** All tools carry `readOnlyHint: true, destructiveHint: false`.
- **Grounding.** Every result includes `data_provenance`, `as_of`, `model_version` and a `notice`
  (MOCK warning and "not investment advice"). The server's `instructions` tell the model to quote
  values as returned and to say "Data unavailable" for nulls.
- **Honest errors.** Missing data returns `isError` with `Data unavailable: …`. Other failures
  (API unreachable, bad route) return `Error: …`. Inputs are validated before any request.

## Tools
| Tool | API endpoint | Returns |
|---|---|---|
| `get_stock_score` | `/v1/stocks/:symbol` | Full SPEC §11 score (minus technicals) + security |
| `get_stock_fundamentals` | `/v1/stocks/:symbol` | Fundamentals + quality/growth/valuation components |
| `get_stock_technicals` | `/v1/stocks/:symbol` | Technical snapshot + momentum/trend components |
| `get_stock_risks` | `/v1/stocks/:symbol` | Risk level, points, flags, upcoming events |
| `get_score_history` | `/v1/stocks/:symbol/score-history` | Score/rank/confidence/risk by date |
| `get_ranking_history` | `/v1/rankings/history` | Top N per scoring date |
| `get_top_opportunities` | `/v1/opportunities` | Ranked list with optional filters |
| `get_sector_strength` | `/v1/sectors` | Sector ranking |
| `get_market_regime` | `/v1/market/overview` | Regime, factors, breadth, index levels |
| `get_latest_news` | `/v1/news` | Stored news (empty until a provider is connected) |
| `compare_stocks` | `/v1/compare` | 2–5 stocks side by side; unknown symbols in `not_found` |
| `search_stocks` | `/v1/search` | Symbol lookup by name/prefix |

## Running it
The API must be running (`pnpm dev`, or `pnpm --filter @dd/api dev`).

**Claude Code**
```bash
claude mcp add dhandrishti -e DD_API_URL=http://127.0.0.1:4000 -- npx tsx /absolute/path/to/DhanDrishti/apps/mcp/src/server.ts
```

**Claude Desktop** (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "dhandrishti": {
      "command": "npx",
      "args": ["tsx", "/absolute/path/to/DhanDrishti/apps/mcp/src/server.ts"],
      "env": { "DD_API_URL": "http://127.0.0.1:4000" }
    }
  }
}
```

stdout carries the protocol, so the server logs only to stderr.

## Not yet
- stdio only. A Streamable HTTP transport (for remote clients) needs auth on the API first.
- The MCP server sends no user identity to the API. Per-user rate limits and audit logs come
  with API auth.
