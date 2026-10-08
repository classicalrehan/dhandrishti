# AI Research Assistant

`/research` in the web app. Claude (`claude-opus-5-5`) answers questions about stocks, sectors
and the market **using only DhanDrishti's application tools**.

```
Browser ──POST /v1/research/chat (plain text turns)──▶ apps/api
   ◀── SSE: text · tool_call · tool_result · done · error ──┘
apps/api: runResearchTurn (packages/ai)
   Claude ⇄ tool_use ──▶ research tool catalogue ──▶ servicePort ──▶ MarketService ──▶ repositories ──▶ PostgreSQL / Redis
```

## Guarantees and how they are enforced
| Rule | Mechanism |
|---|---|
| Claude never touches the database | Tools go through `ResearchPort` → application services. There is no SQL tool, and no credentials reach the model. |
| The engine owns the score | Tools return engine output unchanged (tests compare it with the golden fixtures). The system prompt forbids adjusting or re-ranking. |
| No invented data | The system prompt says to quote tool values exactly and to answer "Data unavailable" for gaps. A **grounding check** matches every substantive number in the answer against that turn's tool results and shows any that don't match in the UI. |
| Clients cannot forge "DhanDrishti data" | The request body accepts only plain-text `user`/`assistant` turns (Zod-validated). Tool results exist only on the server, inside the turn. |
| No advice, no trading | The system prompt forbids buy/sell/hold calls and price predictions. The tools are read-only, and there are no trading tools. |
| MOCK is never presented as real | Every tool payload carries `data_provenance` and a notice. The UI shows a MOCK badge on answers built from mock data. |

### Grounding check (`packages/ai/src/grounding.ts`)
A heuristic safety net, not a proof. A number is verified if any numeric value in the turn's tool
data equals it at the precision shown, or equals it ×100 (for ratios shown as percentages).

- **Ignored:** dates, model versions, indicator names (50 DMA, RSI(14), 52-week, 3M), and small
  integers ≤ 10 (counts and ordinals).
- **Flagged:** derived figures such as differences, averages and targets, by design.
- **Limitation:** it cannot prove that a correct number was attached to the right label.

## Model usage (per the Claude API guidance)
- **Model and effort:** `claude-opus-5-5` with adaptive thinking (default) and effort `medium`,
  set explicitly (it is also that model's default). Responses are streamed, `max_tokens` is
  16000, and a turn is capped at 6 tool rounds.
- **Refusal fallback:** `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`). If Opus
  5.5's safety classifier declines, the API re-runs the request on Anthropic's recommended
  fallback model. The answer footer shows when a fallback model answered. A `refusal` stop is
  shown as "declined", never as an answer.
- **Preserved thinking.** Within a turn, history is append-only: assistant content goes back
  exactly as received, followed by one user message with all tool results. Across turns, only
  text is resent, with no thinking blocks (the valid stripped form).
- **Prompt caching.** The system prompt and tools are byte-identical across requests, with
  `cache_control` on the system block.

## Cost and abuse controls
- **Rate limit:** `DD_AI_RATE_LIMIT_MAX` requests per IP per minute (default 10), separate from
  and stricter than the data API.
- **Request limits:** up to 30 turns, 8,000 characters per turn, 60,000 in total. 6 tool rounds
  per answer.
- **Disconnects:** closing the browser tab aborts the Anthropic request.
- **Audit log:** each turn logs tool names, token usage, grounding result, fallback use and
  latency. Message content is not logged.
- **No auth yet.** Do not expose the API publicly with AI enabled until API auth exists, because
  anyone who can reach it can spend tokens.

## Enabling it
```bash
export ANTHROPIC_API_KEY=...     # or: ant auth login, then DD_AI=on
pnpm dev    # open https://dhandrishti.test (with pnpm proxy) or http://localhost:3100
```
Through Caddy, `flush_interval -1` streams answers without buffering. `DD_AI=auto` (default) enables the assistant when `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`
is set. `on` forces it (for an `ant` profile), and `off` disables it. When disabled, the endpoint
returns `503 AI_DISABLED` and the page says so.

## Tests
- `packages/ai`: grounding cases, tool argument validation (no extra keys, symbol format),
  generated JSON schemas, and the full tool loop against a scripted Claude client. That covers
  append-only history, tool errors returned as errors, refusal, fallback and the tool budget.
- `apps/api`: the SSE endpoint through the real service layer, rejection of injected tool or
  system turns, AI disabled, and the stricter AI rate limit.

All automated tests use a scripted model. **The live model has not been exercised yet**, because
no Anthropic credentials were available during development. The first live session should check
answer quality and the grounding badge on real questions.
