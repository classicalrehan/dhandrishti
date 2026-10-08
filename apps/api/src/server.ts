import Anthropic from "@anthropic-ai/sdk";
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Redis } from "ioredis";
import pg from "pg";
import { buildApp } from "./app";
import { type Cache, NoCache, RedisCache } from "./cache/cache";
import { loadConfig } from "./config";
import { PgMarketRepository } from "./repositories/pg-market-repository";

const config = loadConfig();
const pool = new pg.Pool({ connectionString: config.databaseUrl, max: 10 });

// Fail fast while Redis is down (no offline queue, one attempt per command) and keep
// reconnecting in the background; the cache and rate limiter both fail open.
const redis = config.redisUrl
  ? new Redis(config.redisUrl, {
      enableOfflineQueue: false,
      maxRetriesPerRequest: 1,
      connectTimeout: 1_000,
      retryStrategy: (times) => Math.min(times * 500, 5_000),
    })
  : null;

// Redis can error before the app (and its logger) exists, so start with console.
let warn: (obj: object, msg: string) => void = (obj, msg) => console.warn(msg, obj);
let lastRedisWarning = 0;
const warnRedis = (op: string, err: unknown) => {
  if (Date.now() - lastRedisWarning < 30_000) return; // at most one warning per 30 s
  lastRedisWarning = Date.now();
  warn({ op, err: String(err) }, "redis unavailable; serving from PostgreSQL");
};
redis?.on("error", (err) => warnRedis("connection", err));

const aiEnabled =
  config.aiMode === "on" ||
  (config.aiMode === "auto" && Boolean(process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN));

const cache: Cache = redis ? new RedisCache(redis, warnRedis) : new NoCache();
/** Database name from the connection URL: keeps each database's cache entries separate. */
function databaseName(url: string): string {
  return url.match(/^postgres(?:ql)?:\/\/[^/]*\/([^?]+)/)?.[1] ?? "default";
}

const app = await buildApp({
  repo: new PgMarketRepository(pool),
  cache,
  cacheNamespace: databaseName(config.databaseUrl),
  rateLimit: { max: config.rateLimitMax, timeWindowMs: config.rateLimitWindowMs, redis: redis ?? undefined },
  ai: aiEnabled ? { client: new Anthropic(), rateLimitMax: config.aiRateLimitMax } : undefined,
  corsOrigins: config.corsOrigins,
  trustProxy: config.trustProxy,
  logger: true,
});
warn = (obj, msg) => app.log.warn(obj, msg);
app.log.info({ ai: aiEnabled ? "enabled" : "disabled (set ANTHROPIC_API_KEY or DD_AI=on)" }, "research assistant");

const shutdown = async () => {
  await app.close();
  await pool.end();
  redis?.disconnect();
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

await app.listen({ port: config.port, host: config.host });

// Warn (don't fail) when the database is behind the code's migrations.
try {
  const dir = fileURLToPath(new URL("../../../packages/database/migrations/", import.meta.url));
  const files = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();
  const { rows } = await pool.query("SELECT filename FROM schema_migrations");
  const applied = new Set(rows.map((r) => r.filename));
  const missing = files.filter((f) => !applied.has(f));
  if (missing.length) {
    app.log.warn({ missing, database: databaseName(config.databaseUrl) },
      "database is missing migrations; run `pnpm db:migrate` (or `pnpm pipeline:kite` for the Kite database)");
  }
} catch (err) {
  app.log.warn({ err: String(err) }, "could not check database migrations");
}
