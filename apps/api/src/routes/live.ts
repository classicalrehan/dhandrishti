import { ApiError, LiveQuotes } from "@dd/contracts";
import { z } from "zod";
import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import { AppError } from "../errors";
import type { LiveQuoteSource } from "../live/live-quote-service";
import { buildLiveQuotes, type EodClose } from "../live/quote-view";
import type { MarketRepository } from "../repositories/market-repository";

export interface LiveDeps {
  /** null: live feed turned off; quotes then fall back to end-of-day closes. */
  source: LiveQuoteSource | null;
  /** The configured watchlist: the only symbols this endpoint answers for. */
  watchlist: string[];
  freshSeconds: number;
}

const LiveQuery = z.object({
  symbols: z
    .string()
    .transform((s) => [...new Set(s.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean))])
    .pipe(z.array(z.string().regex(/^[A-Z0-9&-]{1,20}$/)).min(1).max(50))
    .optional(),
});

/** GET /v1/live/quotes: latest quotes for the watchlist, with freshness, source and connection health. */
export const liveRoutes =
  (repo: MarketRepository, deps: LiveDeps, now: () => Date = () => new Date()): FastifyPluginAsyncZod =>
  async (app) => {
    app.get(
      "/live/quotes",
      {
        schema: {
          querystring: LiveQuery,
          response: { 200: z.object({ data: LiveQuotes }), 400: ApiError },
        },
      },
      async (req, reply) => {
        const symbols = req.query.symbols ?? deps.watchlist;
        const outside = symbols.filter((s) => !deps.watchlist.includes(s));
        if (outside.length) throw new AppError(400, "NOT_IN_WATCHLIST", `Not in the live watchlist: ${outside.join(", ")}`);
        let eod: EodClose[] = [];
        try {
          eod = await repo.latestCloses(symbols);
        } catch (err) {
          req.log.warn({ err: String(err) }, "end-of-day fallback unavailable");
        }
        // Quotes change every second: never let a cache serve an old answer as current.
        reply.header("cache-control", "no-store");
        return { data: buildLiveQuotes(deps.source, symbols, eod, now().getTime(), deps.freshSeconds) };
      },
    );
  };
