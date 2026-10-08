import cors from "@fastify/cors";
import rateLimit from "@fastify/rate-limit";
import Fastify, { type FastifyInstance } from "fastify";
import type { Redis } from "ioredis";
import {
  hasZodFastifySchemaValidationErrors,
  isResponseSerializationError,
  serializerCompiler,
  validatorCompiler,
} from "fastify-type-provider-zod";
import { type Cache, NoCache } from "./cache/cache";
import { CachedMarketRepository } from "./cache/cached-market-repository";
import { AppError } from "./errors";
import type { MarketRepository } from "./repositories/market-repository";
import { type ResearchDeps, researchRoutes } from "./routes/research";
import { v1Routes } from "./routes/v1";
import { MarketService } from "./services/market-service";

export interface RateLimitOptions {
  /** Requests per window per client IP. */
  max: number;
  timeWindowMs: number;
  /** Shared counter store; when omitted, counters are kept in process memory. */
  redis?: Redis;
}

export interface AppDeps {
  repo: MarketRepository;
  /** Read-through cache; omitted means no caching. Must fail open. */
  cache?: Cache;
  /** Cache namespace identifying the database (see CachedMarketRepository). */
  cacheNamespace?: string;
  rateLimit?: RateLimitOptions | false;
  /** Proxies trusted for X-Forwarded-For (see ApiConfig.trustProxy). Default: none. */
  trustProxy?: string | boolean;
  /** Research assistant (Claude). Omitted: the endpoint answers 503 AI_DISABLED. */
  ai?: ResearchDeps;
  corsOrigins?: string[];
  logger?: boolean;
  now?: () => Date;
}

export async function buildApp({
  repo: baseRepo,
  cache = new NoCache(),
  cacheNamespace = "default",
  rateLimit: rl = false,
  ai,
  trustProxy = false,
  corsOrigins = [],
  logger = false,
  now,
}: AppDeps): Promise<FastifyInstance> {
  const app = Fastify({ logger, trustProxy });
  const repo = new CachedMarketRepository(baseRepo, cache, cacheNamespace);
  app.setValidatorCompiler(validatorCompiler);
  app.setSerializerCompiler(serializerCompiler);

  // Data endpoints are GET-only; POST exists solely for the research assistant.
  await app.register(cors, { origin: corsOrigins, methods: ["GET", "POST"] });

  if (rl) {
    await app.register(rateLimit, {
      global: true,
      max: rl.max,
      timeWindow: rl.timeWindowMs,
      redis: rl.redis,
      nameSpace: "dd:rl:",
      skipOnError: true, // Redis down must not take the API down
    });
  }

  app.setErrorHandler((err, req, reply) => {
    if (hasZodFastifySchemaValidationErrors(err)) {
      return reply.code(400).send({ error: { code: "BAD_REQUEST", message: err.message } });
    }
    if ((err as { statusCode?: number }).statusCode === 429) {
      return reply.code(429).send({ error: { code: "RATE_LIMITED", message: (err as Error).message } });
    }
    // PostgreSQL "undefined table/column": this database is behind the code's migrations.
    const pgCode = (err as { code?: string }).code;
    if (pgCode === "42P01" || pgCode === "42703") {
      req.log.error({ err }, "database schema is behind the code");
      return reply.code(503).send({
        error: {
          code: "SCHEMA_OUTDATED",
          message: "This database needs migrating. Run `pnpm db:migrate` (or `pnpm pipeline:kite` for the Kite database).",
        },
      });
    }
    if (err instanceof AppError) {
      return reply.code(err.statusCode).send({ error: { code: err.code, message: err.message } });
    }
    if (isResponseSerializationError(err)) {
      // Engine output did not match the contract: a bug, never something to paper over.
      req.log.error({ err }, "response failed contract validation");
      return reply.code(500).send({ error: { code: "CONTRACT_VIOLATION", message: "Response failed validation" } });
    }
    req.log.error({ err }, "unhandled error");
    return reply.code(500).send({ error: { code: "INTERNAL", message: "Internal server error" } });
  });

  // Health is exempt from rate limiting. Cache trouble degrades nothing but latency,
  // so only the database decides the HTTP status.
  app.setNotFoundHandler((req, reply) =>
    reply.code(404).send({ error: { code: "ROUTE_NOT_FOUND", message: `No route ${req.method} ${req.url.split("?")[0]}` } }),
  );

  app.get("/health", { config: { rateLimit: false } }, async (_req, reply) => {
    const cacheStatus = await cache.status();
    const cacheInfo = { status: cacheStatus, hits: repo.counters.hits, misses: repo.counters.misses };
    try {
      await repo.ping();
      return { status: "ok", database: "ok", cache: cacheInfo };
    } catch {
      return reply.code(503).send({ status: "degraded", database: "unreachable", cache: cacheInfo });
    }
  });

  const service = new MarketService(repo, now);
  await app.register(v1Routes(service), { prefix: "/v1" });
  await app.register(researchRoutes(service, ai), { prefix: "/v1" });
  return app;
}
