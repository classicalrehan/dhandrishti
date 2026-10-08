/**
 * POST /v1/research/chat — the AI research assistant, streamed as Server-Sent Events.
 *
 * Events: text (answer deltas), tool_call, tool_result, done (grounding report,
 * provenance, usage), error. The request body carries plain text turns only.
 */
import { ChatRequest, type ResearchEvent, runResearchTurn } from "@dd/ai";
import type Anthropic from "@anthropic-ai/sdk";
import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import { AppError } from "../errors";
import type { MarketService } from "../services/market-service";
import { servicePort } from "../services/service-port";

export interface ResearchDeps {
  client: Pick<Anthropic, "beta">;
  /** Requests per window per IP; AI calls cost money, so this is much lower than the API default. */
  rateLimitMax?: number;
  rateLimitWindowMs?: number;
}

export const researchRoutes =
  (service: MarketService, ai: ResearchDeps | undefined): FastifyPluginAsyncZod =>
  async (app) => {
    app.post(
      "/research/chat",
      {
        schema: { body: ChatRequest },
        config: { rateLimit: { max: ai?.rateLimitMax ?? 10, timeWindow: ai?.rateLimitWindowMs ?? 60_000 } },
      },
      async (req, reply) => {
        if (!ai) {
          throw new AppError(503, "AI_DISABLED", "The research assistant is not configured on this server (no Anthropic credentials).");
        }
        const abort = new AbortController();
        reply.raw.on("close", () => {
          if (!reply.raw.writableEnded) abort.abort();
        });

        reply.hijack();
        reply.raw.writeHead(200, {
          ...(reply.getHeaders() as Record<string, string>),
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-cache, no-transform",
          connection: "keep-alive",
          "x-accel-buffering": "no",
        });
        const send = (e: ResearchEvent) => {
          if (!reply.raw.writableEnded) reply.raw.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`);
        };
        const keepAlive = setInterval(() => reply.raw.write(": keep-alive\n\n"), 15_000);

        const started = Date.now();
        let summary: Record<string, unknown> = {};
        try {
          await runResearchTurn({
            client: ai.client,
            port: servicePort(service),
            messages: req.body.messages,
            signal: abort.signal,
            onEvent: (e) => {
              if (e.type === "tool_call") summary.tools = [...((summary.tools as string[]) ?? []), e.name];
              if (e.type === "done")
                summary = { ...summary, usage: e.usage, unverified: e.grounding.unverified.length, model: e.model, fallback: e.fallback_used };
              if (e.type === "error") summary = { ...summary, error: e.code };
              send(e);
            },
          });
        } catch (err) {
          req.log.error({ err }, "research turn failed");
          send({ type: "error", code: "INTERNAL", message: "Unexpected error while generating the answer." });
        } finally {
          clearInterval(keepAlive);
          // Audit trail without message content: which tools ran, tokens, grounding, latency.
          req.log.info({ research: { ...summary, ms: Date.now() - started, aborted: abort.signal.aborted } }, "research turn");
          reply.raw.end();
        }
      },
    );
  };
