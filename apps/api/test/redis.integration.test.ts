/**
 * Real Redis: shared cache entries with TTL, rate-limit counters shared across API
 * instances, and fail-open when Redis is unreachable.
 *
 *   DD_TEST_REDIS_URL=redis://127.0.0.1:6379/15 pnpm test
 */
import { randomBytes } from "node:crypto";
import { Redis } from "ioredis";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { buildApp } from "../src/app";
import { RedisCache } from "../src/cache/cache";
import { FixtureRepo } from "./fixture-repo";

const URL_ = process.env.DD_TEST_REDIS_URL;

describe.skipIf(!URL_)("Redis integration", () => {
  let redis: Redis;
  const tag = randomBytes(4).toString("hex");

  beforeAll(() => {
    redis = new Redis(URL_!, { enableOfflineQueue: true, maxRetriesPerRequest: 1 });
  });
  afterAll(async () => {
    const keys = await redis.keys("dd:*");
    if (keys.length) await redis.del(...keys);
    redis.disconnect();
  });

  it("stores entries with a TTL", async () => {
    const cache = new RedisCache(redis);
    await cache.set(`dd:test:${tag}`, "v", 30);
    expect(await cache.get(`dd:test:${tag}`)).toBe("v");
    const ttl = await redis.ttl(`dd:test:${tag}`);
    expect(ttl).toBeGreaterThan(0);
    expect(ttl).toBeLessThanOrEqual(30);
    expect(await cache.status()).toBe("ok");
  });

  it("shares the score cache between API instances", async () => {
    const repoA = new FixtureRepo();
    const repoB = new FixtureRepo();
    repoA.run = repoB.run = { ...repoA.run!, run_id: Number.parseInt(tag, 16) };
    const a = await buildApp({ repo: repoA, cache: new RedisCache(redis) });
    const b = await buildApp({ repo: repoB, cache: new RedisCache(redis) });
    expect((await a.inject({ method: "GET", url: "/v1/opportunities" })).statusCode).toBe(200);
    expect((await b.inject({ method: "GET", url: "/v1/opportunities" })).statusCode).toBe(200);
    expect(repoA.calls.scores).toBe(1);
    expect(repoB.calls.scores ?? 0).toBe(0); // served from the entry instance A wrote
    await a.close();
    await b.close();
  });

  it("shares rate-limit counters between API instances", async () => {
    const rl = { max: 4, timeWindowMs: 60_000, redis };
    const a = await buildApp({ repo: new FixtureRepo(), rateLimit: rl });
    const b = await buildApp({ repo: new FixtureRepo(), rateLimit: rl });
    const codes = [];
    for (const app of [a, b, a, b, a]) codes.push((await app.inject({ method: "GET", url: "/v1/sectors", remoteAddress: `10.0.0.${tag.length}` })).statusCode);
    expect(codes).toEqual([200, 200, 200, 200, 429]);
    await a.close();
    await b.close();
  });

  it("fails open when Redis is unreachable", async () => {
    const dead = new Redis("redis://127.0.0.1:1", {
      enableOfflineQueue: false,
      maxRetriesPerRequest: 1,
      connectTimeout: 200,
      retryStrategy: () => null,
      lazyConnect: true,
    });
    dead.on("error", () => {});
    const app = await buildApp({
      repo: new FixtureRepo(),
      cache: new RedisCache(dead),
      rateLimit: { max: 100, timeWindowMs: 60_000, redis: dead },
    });
    const res = await app.inject({ method: "GET", url: "/v1/opportunities" });
    expect(res.statusCode).toBe(200);
    expect((await app.inject({ method: "GET", url: "/health" })).json().cache.status).toBe("unavailable");
    await app.close();
    dead.disconnect();
  });
});
