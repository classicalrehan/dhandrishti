import { describe, expect, it } from "vitest";
import type { Redis } from "ioredis";
import { buildApp } from "../src/app";
import { MemoryCache, RedisCache } from "../src/cache/cache";
import { CACHE_TTL, CachedMarketRepository } from "../src/cache/cached-market-repository";
import { FixtureRepo } from "./fixture-repo";

describe("CachedMarketRepository", () => {
  it("serves run-scoped reads from cache after the first load", async () => {
    const inner = new FixtureRepo();
    const repo = new CachedMarketRepository(inner, new MemoryCache());
    const ctx = (await repo.latestRun())!;
    const a = await repo.scores(ctx);
    const b = await repo.scores(ctx);
    expect(b).toEqual(a);
    expect(inner.calls.scores).toBe(1);
    expect(repo.counters).toEqual({ hits: 1, misses: 2 });
  });

  it("keys scores by scoring run, so a new run is never served stale data", async () => {
    const inner = new FixtureRepo();
    const cache = new MemoryCache();
    const repo = new CachedMarketRepository(inner, cache);
    await repo.scores({ ...inner.run!, run_id: 1 });
    await repo.scores({ ...inner.run!, run_id: 2 });
    expect(inner.calls.scores).toBe(2);
    expect(cache.keys()).toEqual(expect.arrayContaining(["dd:v2:default:run:1:scores", "dd:v2:default:run:2:scores"]));
  });

  it("re-checks the latest run after its short TTL", async () => {
    let t = 0;
    const inner = new FixtureRepo();
    const repo = new CachedMarketRepository(inner, new MemoryCache(() => t));
    await repo.latestRun();
    await repo.latestRun();
    expect(inner.calls.latestRun).toBe(1);
    t += CACHE_TTL.latestRun * 1000 + 1;
    await repo.latestRun();
    expect(inner.calls.latestRun).toBe(2);
  });

  it("does not cache missing results", async () => {
    const inner = new FixtureRepo();
    const cache = new MemoryCache();
    const repo = new CachedMarketRepository(inner, cache);
    expect(await repo.score(inner.run!, "NOPE")).toBeNull();
    expect(cache.keys().some((k) => k.includes("NOPE"))).toBe(false);
  });

  it("falls through to the database when a cached entry is corrupt", async () => {
    const inner = new FixtureRepo();
    const cache = new MemoryCache();
    await cache.set("dd:v2:default:run:1:scores", "{not json", 60);
    const repo = new CachedMarketRepository(inner, cache);
    expect((await repo.scores(inner.run!)).length).toBe(3);
    expect(inner.calls.scores).toBe(1);
  });
});

describe("RedisCache fails open", () => {
  const broken = {
    get: () => Promise.reject(new Error("ECONNREFUSED")),
    set: () => Promise.reject(new Error("ECONNREFUSED")),
    ping: () => Promise.reject(new Error("ECONNREFUSED")),
  } as unknown as Redis;

  it("treats errors as misses, ignores failed writes and reports unavailable", async () => {
    const errors: string[] = [];
    const cache = new RedisCache(broken, (op) => errors.push(op));
    expect(await cache.get("k")).toBeNull();
    await expect(cache.set("k", "v", 10)).resolves.toBeUndefined();
    expect(await cache.status()).toBe("unavailable");
    expect(errors).toEqual(["get", "set"]);
  });

  it("keeps the API serving from the database", async () => {
    const repo = new FixtureRepo();
    const app = await buildApp({ repo, cache: new RedisCache(broken) });
    const res = await app.inject({ method: "GET", url: "/v1/opportunities" });
    expect(res.statusCode).toBe(200);
    const health = await app.inject({ method: "GET", url: "/health" });
    expect(health.statusCode).toBe(200);
    expect(health.json().cache.status).toBe("unavailable");
    await app.close();
  });
});

describe("API with cache", () => {
  it("answers repeated overview requests from cache", async () => {
    const repo = new FixtureRepo();
    const app = await buildApp({ repo, cache: new MemoryCache() });
    for (let i = 0; i < 3; i++) expect((await app.inject({ method: "GET", url: "/v1/market/overview" })).statusCode).toBe(200);
    expect(repo.calls.scores).toBe(1);
    expect(repo.calls.latestRun).toBe(1);
    await app.close();
  });
});

describe("rate limiting", () => {
  it("returns 429 RATE_LIMITED past the limit, with standard headers", async () => {
    const app = await buildApp({ repo: new FixtureRepo(), rateLimit: { max: 3, timeWindowMs: 60_000 } });
    const statuses: number[] = [];
    let last;
    for (let i = 0; i < 4; i++) {
      last = await app.inject({ method: "GET", url: "/v1/sectors" });
      statuses.push(last.statusCode);
    }
    expect(statuses).toEqual([200, 200, 200, 429]);
    expect(last!.json().error.code).toBe("RATE_LIMITED");
    expect(last!.headers["retry-after"]).toBeDefined();
    await app.close();
  });

  it("never limits /health", async () => {
    const app = await buildApp({ repo: new FixtureRepo(), rateLimit: { max: 1, timeWindowMs: 60_000 } });
    for (let i = 0; i < 5; i++) expect((await app.inject({ method: "GET", url: "/health" })).statusCode).toBe(200);
    await app.close();
  });
});

describe("cache schema versioning", () => {
  it("ignores entries written under an older schema version", async () => {
    const inner = new FixtureRepo();
    const cache = new MemoryCache();
    // An entry in the old (v1) shape, as left behind by the previous deploy.
    await cache.set("dd:v1:history:2026.10-v1:HDFCBANK:60", JSON.stringify([{ as_of: "2026-10-05", total_score: 1, rank: 1 }]), 300);
    const repo = new CachedMarketRepository(inner, cache);
    const rows = await repo.scoreHistory("HDFCBANK", "2026.10-v1", 60);
    expect(rows[0]).toHaveProperty("confidence");
  });
});

describe("rate limiting behind a proxy", () => {
  it("keys limits on X-Forwarded-For only when the proxy is trusted", async () => {
    const trusted = await buildApp({ repo: new FixtureRepo(), trustProxy: "loopback", rateLimit: { max: 1, timeWindowMs: 60_000 } });
    const hit = (app: typeof trusted, ip: string) =>
      app.inject({ method: "GET", url: "/v1/sectors", remoteAddress: "127.0.0.1", headers: { "x-forwarded-for": ip } });
    // Two different users behind the same local proxy get separate buckets.
    expect((await hit(trusted, "203.0.113.1")).statusCode).toBe(200);
    expect((await hit(trusted, "203.0.113.2")).statusCode).toBe(200);
    expect((await hit(trusted, "203.0.113.1")).statusCode).toBe(429);
    await trusted.close();

    // Without trust, a client cannot dodge the limit by forging the header.
    const untrusted = await buildApp({ repo: new FixtureRepo(), rateLimit: { max: 1, timeWindowMs: 60_000 } });
    expect((await hit(untrusted, "198.51.100.1")).statusCode).toBe(200);
    expect((await hit(untrusted, "198.51.100.2")).statusCode).toBe(429);
    await untrusted.close();
  });
});

describe("cache namespaces", () => {
  it("never serves one database's cached scores for another database's run with the same id", async () => {
    const cache = new MemoryCache();
    const mockDb = new FixtureRepo();
    const kiteDb = new FixtureRepo();
    kiteDb.scoresOverride = [{ ...(await mockDb.scores())[0]!, symbol: "KITEONLY" }];
    const ctx = (await mockDb.latestRun())!; // run_id 1 in both databases
    await new CachedMarketRepository(mockDb, cache, "dhandrishti").scores(ctx);
    const fromKite = await new CachedMarketRepository(kiteDb, cache, "dhandrishti_kite").scores(ctx);
    expect(fromKite.map((s) => s.symbol)).toEqual(["KITEONLY"]);
    expect(kiteDb.calls.scores).toBe(1);
  });
});
