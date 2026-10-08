/**
 * Read-through cache in front of the market repository.
 *
 * Scoring output is immutable per scoring run, so run-scoped keys embed the run id:
 * a new (or re-run) scoring job produces new keys and stale scores can never be served.
 * Only the "which run is latest" lookup relies on a short TTL.
 */
import type { MarketRepository, RunContext } from "../repositories/market-repository";
import type { Cache } from "./cache";

export const CACHE_TTL = {
  latestRun: 15,
  runScoped: 24 * 3600,
  reference: 3600,
  timeSeries: 300,
} as const;

/**
 * Bump CACHE_SCHEMA_VERSION whenever any repository method's return shape changes.
 * The new namespace makes a deploy ignore entries written by the previous code
 * instead of serving them (which would fail contract validation). Old keys expire by TTL.
 *   1: initial
 *   2: score history gained confidence + risk_level; ranking history added
 */
export const CACHE_SCHEMA_VERSION = 2;
const PREFIX = `dd:v${CACHE_SCHEMA_VERSION}`;

export interface CacheCounters {
  hits: number;
  misses: number;
}

export class CachedMarketRepository implements MarketRepository {
  readonly counters: CacheCounters = { hits: 0, misses: 0 };

  private readonly prefix: string;

  /**
   * @param namespace identifies the database behind `inner` (e.g. its name). Run ids restart
   *   at 1 in every database, so without it a MOCK database's cached scores could be served
   *   for a Kite database's run with the same id.
   */
  constructor(
    private readonly inner: MarketRepository,
    private readonly cache: Cache,
    namespace = "default",
  ) {
    this.prefix = `${PREFIX}:${namespace}`;
  }

  private async through<T>(key: string, ttl: number, load: () => Promise<T>): Promise<T> {
    const hit = await this.cache.get(`${this.prefix}:${key}`);
    if (hit != null) {
      try {
        this.counters.hits++;
        return JSON.parse(hit) as T;
      } catch {
        // Corrupt entry: fall through to the database and overwrite it.
      }
    }
    this.counters.misses++;
    const value = await load();
    // Absent results are not cached, so newly ingested data appears immediately.
    if (value != null) await this.cache.set(`${this.prefix}:${key}`, JSON.stringify(value), ttl);
    return value;
  }

  private run(ctx: RunContext, what: string) {
    return `run:${ctx.run_id}:${what}`;
  }

  ping() {
    return this.inner.ping();
  }

  latestRun(onOrBefore?: string) {
    if (onOrBefore) return this.inner.latestRun(onOrBefore);
    return this.through("latest-run", CACHE_TTL.latestRun, () => this.inner.latestRun());
  }

  scores(ctx: RunContext) {
    return this.through(this.run(ctx, "scores"), CACHE_TTL.runScoped, () => this.inner.scores(ctx));
  }

  score(ctx: RunContext, symbol: string) {
    return this.through(this.run(ctx, `score:${symbol}`), CACHE_TTL.runScoped, () => this.inner.score(ctx, symbol));
  }

  sectors(ctx: RunContext) {
    return this.through(this.run(ctx, "sectors"), CACHE_TTL.runScoped, () => this.inner.sectors(ctx));
  }

  regime(ctx: RunContext) {
    return this.through(this.run(ctx, "regime"), CACHE_TTL.runScoped, () => this.inner.regime(ctx));
  }

  scoreHistory(symbol: string, configVersion: string, limit: number) {
    return this.through(`history:${configVersion}:${symbol}:${limit}`, CACHE_TTL.timeSeries, () =>
      this.inner.scoreHistory(symbol, configVersion, limit),
    );
  }

  rankingHistory(configVersion: string, days: number, top: number) {
    return this.through(`rankings:${configVersion}:${days}:${top}`, CACHE_TTL.timeSeries, () =>
      this.inner.rankingHistory(configVersion, days, top),
    );
  }

  news(symbol: string | null, limit: number) {
    // News freshness matters more than its query cost.
    return this.inner.news(symbol, limit);
  }

  indexBars(codes: string[], asOf: string, perIndex: number) {
    return this.through(`index:${asOf}:${perIndex}:${codes.join("|")}`, CACHE_TTL.timeSeries, () =>
      this.inner.indexBars(codes, asOf, perIndex),
    );
  }

  security(symbol: string) {
    return this.through(`security:${symbol}`, CACHE_TTL.reference, () => this.inner.security(symbol));
  }

  search(q: string, limit: number) {
    // Free-text keys are unbounded; search is a cheap indexed query, so it is not cached.
    return this.inner.search(q, limit);
  }

  fundamentals(symbol: string, asOf: string) {
    return this.through(`fundamentals:${symbol}:${asOf}`, CACHE_TTL.timeSeries, () =>
      this.inner.fundamentals(symbol, asOf),
    );
  }

  events(symbol: string, after: string, until: string) {
    return this.through(`events:${symbol}:${after}:${until}`, CACHE_TTL.timeSeries, () =>
      this.inner.events(symbol, after, until),
    );
  }

  // Backtests are written by the worker at any time and read rarely; always read fresh.
  backtestRuns(limit: number) {
    return this.inner.backtestRuns(limit);
  }

  backtest(id: number) {
    return this.inner.backtest(id);
  }

  // Paper portfolios change after every daily run; read fresh.
  paperPortfolios() {
    return this.inner.paperPortfolios();
  }

  paperPortfolio(id: number) {
    return this.inner.paperPortfolio(id);
  }

  // Personal holdings: never cached in Redis, always read fresh.
  holdings() {
    return this.inner.holdings();
  }

  prices(symbol: string, asOf: string, from: string | null) {
    return this.through(`prices:${symbol}:${asOf}:${from ?? "max"}`, CACHE_TTL.timeSeries, () =>
      this.inner.prices(symbol, asOf, from),
    );
  }
}
