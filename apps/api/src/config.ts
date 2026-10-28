export interface ApiConfig {
  port: number;
  host: string;
  databaseUrl: string;
  /** null disables Redis (no shared cache; in-process rate-limit counters). */
  redisUrl: string | null;
  rateLimitMax: number;
  rateLimitWindowMs: number;
  corsOrigins: string[];
  /**
   * Which proxies may set X-Forwarded-For (so rate limits see the real client IP).
   * Default "loopback": only a proxy on this machine, such as the local Caddy.
   */
  trustProxy: string | boolean;
  /** auto: on when ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is set; on: always (e.g. `ant auth login` profile); off. */
  aiMode: "auto" | "on" | "off";
  aiRateLimitMax: number;
  live: LiveConfig;
}

export interface LiveConfig {
  /** On when a watchlist is set, unless DD_LIVE=off. */
  enabled: boolean;
  watchlist: string[];
  /** A live quote older than this (while connected) is shown as QUIET, not FRESH. */
  freshSeconds: number;
  maxSymbols: number;
  /** Kite session written by `pnpm kite:login`; null = the worker's default location. */
  sessionFile: string | null;
}

/**
 * Where the web app may be opened locally: the dhandrishti.test domain, localhost, or the loopback IP,
 * on the web port (DD_WEB_PORT, default 3100; the same variable sets the Next.js port).
 */
const defaultWebOrigins = (port: string) =>
  [
    "https://dhandrishti.test", // via the Caddy proxy (same origin; listed for completeness)
    `http://dhandrishti.test:${port}`,
    `http://localhost:${port}`,
    `http://127.0.0.1:${port}`,
  ].join(",");

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ApiConfig {
  const redis = env.DD_REDIS_URL ?? "redis://127.0.0.1:6379/0";
  return {
    port: Number(env.DD_API_PORT ?? 4000),
    host: env.DD_API_HOST ?? "127.0.0.1",
    databaseUrl: env.DD_DATABASE_URL ?? "postgresql://dhandrishti:dhandrishti_dev@localhost:5432/dhandrishti",
    redisUrl: redis === "off" ? null : redis,
    rateLimitMax: Number(env.DD_RATE_LIMIT_MAX ?? 300),
    rateLimitWindowMs: Number(env.DD_RATE_LIMIT_WINDOW_MS ?? 60_000),
    aiMode: (["auto", "on", "off"].includes(env.DD_AI ?? "") ? env.DD_AI : "auto") as ApiConfig["aiMode"],
    aiRateLimitMax: Number(env.DD_AI_RATE_LIMIT_MAX ?? 10),
    trustProxy: env.DD_TRUST_PROXY === "false" ? false : (env.DD_TRUST_PROXY ?? "loopback"),
    corsOrigins: (env.DD_WEB_ORIGIN ?? defaultWebOrigins(env.DD_WEB_PORT ?? "3100")).split(",").map((s) => s.trim()),
    live: loadLiveConfig(env),
  };
}

export function loadLiveConfig(env: NodeJS.ProcessEnv = process.env): LiveConfig {
  const watchlist = [
    ...new Set((env.DD_LIVE_WATCHLIST ?? "").split(",").map((s) => s.trim().toUpperCase()).filter((s) => /^[A-Z0-9&-]{1,20}$/.test(s))),
  ];
  const positive = (v: string | undefined, dflt: number) => (Number(v) > 0 ? Number(v) : dflt);
  return {
    enabled: env.DD_LIVE !== "off" && watchlist.length > 0,
    watchlist,
    freshSeconds: positive(env.DD_LIVE_FRESH_SECONDS, 60),
    maxSymbols: Math.min(positive(env.DD_LIVE_MAX_SYMBOLS, 50), 500),
    sessionFile: env.DD_KITE_SESSION_FILE ?? null,
  };
}
