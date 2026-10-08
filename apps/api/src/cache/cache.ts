/**
 * Cache abstraction. Redis is an accelerator only: every implementation must
 * fail open (a failed get is a miss, a failed set is ignored) so PostgreSQL —
 * the source of truth — always answers when the cache cannot.
 */
import type { Redis } from "ioredis";

export type CacheStatus = "ok" | "unavailable" | "disabled";

export interface Cache {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds: number): Promise<void>;
  status(): Promise<CacheStatus>;
}

export class NoCache implements Cache {
  async get() {
    return null;
  }
  async set() {}
  async status(): Promise<CacheStatus> {
    return "disabled";
  }
}

/** In-process cache for tests and Redis-less development. */
export class MemoryCache implements Cache {
  private readonly store = new Map<string, { value: string; expires: number }>();
  constructor(private readonly now: () => number = Date.now) {}

  async get(key: string) {
    const hit = this.store.get(key);
    if (!hit) return null;
    if (hit.expires <= this.now()) {
      this.store.delete(key);
      return null;
    }
    return hit.value;
  }
  async set(key: string, value: string, ttlSeconds: number) {
    this.store.set(key, { value, expires: this.now() + ttlSeconds * 1000 });
  }
  async status(): Promise<CacheStatus> {
    return "ok";
  }
  keys(): string[] {
    return [...this.store.keys()];
  }
}

export class RedisCache implements Cache {
  constructor(
    private readonly redis: Redis,
    private readonly onError: (op: string, err: unknown) => void = () => {},
  ) {}

  async get(key: string) {
    try {
      return await this.redis.get(key);
    } catch (err) {
      this.onError("get", err);
      return null;
    }
  }
  async set(key: string, value: string, ttlSeconds: number) {
    try {
      await this.redis.set(key, value, "EX", ttlSeconds);
    } catch (err) {
      this.onError("set", err);
    }
  }
  async status(): Promise<CacheStatus> {
    try {
      return (await this.redis.ping()) === "PONG" ? "ok" : "unavailable";
    } catch {
      return "unavailable";
    }
  }
}
