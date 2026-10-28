import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LiveQuotes } from "@dd/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildApp } from "../src/app";
import { RedisCache } from "../src/cache/cache";
import { loadConfig, loadLiveConfig } from "../src/config";
import { checkSession, KiteAuthError, loadCredentials, parseInstruments, sessionExpired } from "../src/live/kite-session";
import {
  BACKOFF_MAX_MS,
  LiveQuoteService,
  type LiveState,
  type StoredQuote,
  type TickerSocket,
} from "../src/live/live-quote-service";
import { buildLiveQuotes, sessionStatus } from "../src/live/quote-view";
import { parseBinary, parseText } from "../src/live/ticker-packets";
import { FixtureRepo } from "./fixture-repo";
import { encodeMessage, encodePacket } from "./ticker-fixtures";

// NSE tokens end in segment byte 1 (e.g. 738561 = 0x0B4501).
const RELIANCE = 738561;
const TCS = 2953217;
const OTHER = 408065;
const TOKEN = "secret-access-token-123";
const NOW = new Date("2026-10-27T05:00:00Z"); // Tuesday 10:30 IST, market open

const CSV = [
  "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange",
  `${RELIANCE},2885,RELIANCE,"RELIANCE INDUSTRIES, LTD",0,,0,0.1,1,EQ,NSE,NSE`,
  `${TCS},11536,TCS,TATA CONSULTANCY SERV LT,0,,0,0.1,1,EQ,NSE,NSE`,
  `256265,0,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE`,
  `${OTHER},1594,INFY,INFOSYS,0,,0,0.1,1,EQ,NSE,NSE`,
].join("\n");

class FakeSocket implements TickerSocket {
  binaryType = "";
  onopen: TickerSocket["onopen"] = null;
  onmessage: TickerSocket["onmessage"] = null;
  onclose: TickerSocket["onclose"] = null;
  onerror: TickerSocket["onerror"] = null;
  sent: unknown[] = [];
  closed = false;
  constructor(readonly url: string) {}
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.({});
  }
  drop() {
    this.onerror?.({});
    this.onclose?.({});
  }
  heartbeat() {
    this.onmessage?.({ data: new Uint8Array([0]).buffer });
  }
  tick(...packets: Uint8Array[]) {
    this.onmessage?.({ data: encodeMessage(packets) });
  }
}

function sessionFile(loginTime = "2026-10-27 08:00:00"): string {
  const dir = mkdtempSync(join(tmpdir(), "dd-live-"));
  const path = join(dir, "kite_session.json");
  writeFileSync(path, JSON.stringify({ api_key: "key1", access_token: TOKEN, user_id: "AB1234", login_time: loginTime }));
  return path;
}

function fakeFetch(profileStatus = () => 200) {
  const calls: string[] = [];
  const fn = (async (url: string | URL) => {
    const u = String(url);
    calls.push(u);
    if (u.endsWith("/user/profile")) return new Response("{}", { status: profileStatus() });
    if (u.endsWith("/instruments/NSE")) return new Response(CSV, { status: 200 });
    return new Response("", { status: 404 });
  }) as typeof fetch;
  return { fn, calls };
}

function makeService(opts: { watchlist?: string[]; file?: string; profile?: () => number } = {}) {
  const sockets: FakeSocket[] = [];
  const f = fakeFetch(opts.profile);
  const svc = new LiveQuoteService({
    watchlist: opts.watchlist ?? ["RELIANCE", "TCS", "reliance"],
    sessionFile: opts.file ?? sessionFile(),
    socketFactory: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    fetchFn: f.fn,
    random: () => 0.5,
  });
  return { svc, sockets, fetchCalls: f.calls };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("ticker packets", () => {
  it("parses ltp, quote and full packets in paise, and recognises heartbeats", () => {
    const msg = encodeMessage([
      encodePacket({ token: RELIANCE, ltp: 250050 }, "ltp"),
      encodePacket({ token: TCS, ltp: 410025, volume: 1200, open: 400000, high: 412000, low: 399000, close: 405000 }, "quote"),
      encodePacket({ token: OTHER, ltp: 150000, close: 149000, lastTradeSec: 1_793_000_000 }, "full"),
    ]);
    const { ticks, skipped } = parseBinary(msg);
    expect(skipped).toBe(0);
    expect(ticks[0]).toMatchObject({ token: RELIANCE, mode: "ltp", ltpPaise: 250050, closePaise: null });
    expect(ticks[1]).toMatchObject({ mode: "quote", volume: 1200, highPaise: 412000, closePaise: 405000, exchangeTimeMs: null });
    expect(ticks[2]).toMatchObject({ mode: "full", exchangeTimeMs: 1_793_000_000_000 });
    expect(parseBinary(new Uint8Array([0]).buffer)).toEqual({ ticks: [], heartbeat: true, skipped: 0 });
  });

  it("skips malformed, zero-price and non-equity-segment packets instead of mis-scaling them", () => {
    const currency = 0x0b4503; // segment 3 (CDS): different price divisor
    const msg = encodeMessage([
      encodePacket({ token: currency, ltp: 100 }, "ltp"),
      encodePacket({ token: RELIANCE, ltp: 0 }, "ltp"),
      new Uint8Array(12),
      encodePacket({ token: TCS, ltp: 1 }, "ltp"),
    ]);
    const res = parseBinary(msg);
    expect(res.ticks.map((t) => t.token)).toEqual([TCS]);
    expect(res.skipped).toBe(3);
    const truncated = msg.slice(0, msg.byteLength - 3);
    expect(parseBinary(truncated).skipped).toBeGreaterThan(0);
    expect(parseText('{"type":"error","data":"Invalid token"}')).toEqual({ type: "error", message: "Invalid token" });
    expect(parseText("not json")).toBeNull();
  });
});

describe("kite session", () => {
  it("expires at 6 AM IST after login", () => {
    expect(sessionExpired("2026-10-27 08:00:00", new Date("2026-10-28T00:29:00Z"))).toBe(false); // 05:59 IST
    expect(sessionExpired("2026-10-27 08:00:00", new Date("2026-10-28T00:30:00Z"))).toBe(true);
    expect(sessionExpired("2026-10-27 05:00:00", new Date("2026-10-27T00:30:00Z"))).toBe(true); // before 6 AM login
    expect(sessionExpired(null, new Date())).toBe(false);
  });

  it("maps only NSE equities, handling quoted names", () => {
    const m = parseInstruments(CSV);
    expect([...m]).toEqual([["RELIANCE", RELIANCE], ["TCS", TCS], ["INFY", OTHER]]);
  });

  it("reports a missing session and a rejected token as authentication problems", async () => {
    await expect(loadCredentials("/nonexistent/kite.json")).rejects.toBeInstanceOf(KiteAuthError);
    const creds = await loadCredentials(sessionFile());
    await expect(checkSession(creds, fakeFetch(() => 403).fn)).rejects.toBeInstanceOf(KiteAuthError);
  });

  it("allows the browser origin on the configured web port", () => {
    expect(loadConfig({ DD_WEB_PORT: "3200" }).corsOrigins).toContain("http://localhost:3200");
    expect(loadConfig({}).corsOrigins).toContain("http://localhost:3100");
    expect(loadConfig({ DD_WEB_PORT: "3200", DD_WEB_ORIGIN: "http://x:1" }).corsOrigins).toEqual(["http://x:1"]);
  });

  it("reads the watchlist configuration without code changes", () => {
    expect(loadLiveConfig({ DD_LIVE_WATCHLIST: "reliance, TCS,TCS,bad symbol!" })).toMatchObject({
      enabled: true, watchlist: ["RELIANCE", "TCS"], freshSeconds: 60, maxSymbols: 50,
    });
    expect(loadLiveConfig({ DD_LIVE_WATCHLIST: "TCS", DD_LIVE: "off" }).enabled).toBe(false);
    expect(loadLiveConfig({}).enabled).toBe(false);
  });
});

describe("live quote service", () => {
  it("connects once, subscribes deduplicated tokens in quote mode and keeps credentials out of state", async () => {
    const { svc, sockets } = makeService();
    await Promise.all([svc.start(), svc.start()]);
    expect(sockets).toHaveLength(1);
    sockets[0]!.open();
    expect(sockets[0]!.binaryType).toBe("arraybuffer");
    expect(sockets[0]!.sent).toEqual([{ a: "subscribe", v: [RELIANCE, TCS] }, { a: "mode", v: ["quote", [RELIANCE, TCS]] }]);
    expect(svc.state().status).toBe("CONNECTED");
    expect(JSON.stringify({ ...svc.state(), tokens: [...svc.state().tokens] })).not.toContain(TOKEN);
    await svc.start();
    expect(sockets).toHaveLength(1);
    await svc.stop();
  });

  it("stores normalized quotes for subscribed instruments only and rejects out-of-order updates", async () => {
    const { svc, sockets } = makeService();
    await svc.start();
    const ws = sockets[0]!;
    ws.open();
    ws.tick(
      encodePacket({ token: RELIANCE, ltp: 250050, volume: 10, close: 248000, lastTradeSec: 2000 }, "full"),
      encodePacket({ token: TCS, ltp: 410000, close: 405000 }, "quote"),
      encodePacket({ token: OTHER, ltp: 150000 }, "quote"), // not ours
    );
    expect(svc.quote("RELIANCE")?.tick.ltpPaise).toBe(250050);
    expect(svc.quote("TCS")?.tick.closePaise).toBe(405000);
    expect(svc.quote("INFY")).toBeNull();
    ws.tick(encodePacket({ token: RELIANCE, ltp: 249000, lastTradeSec: 1999 }, "full")); // older trade
    expect(svc.quote("RELIANCE")?.tick.ltpPaise).toBe(250050);
    expect(svc.counters.outOfOrder).toBe(1);
    ws.onmessage?.({ data: '{"type":"error","data":"Too many subscriptions"}' });
    expect(svc.state()).toMatchObject({ lastError: "PROTOCOL", reason: "Kite: Too many subscriptions" });
    await svc.stop();
  });

  it("reports watchlist symbols Kite does not list, and stays unconfigured when none resolve", async () => {
    const some = makeService({ watchlist: ["TCS", "GONE"] });
    await some.svc.start();
    expect(some.svc.state()).toMatchObject({ unresolved: ["GONE"] });
    expect([...some.svc.state().tokens.keys()]).toEqual(["TCS"]);
    await some.svc.stop();
    const none = makeService({ watchlist: ["GONE"] });
    await none.svc.start();
    expect(none.svc.state()).toMatchObject({ status: "NOT_CONFIGURED", lastError: "CONFIG" });
    expect(none.sockets).toHaveLength(0);
    const empty = makeService({ watchlist: [] });
    await empty.svc.start();
    expect(empty.svc.state().status).toBe("NOT_CONFIGURED");
    expect(empty.fetchCalls).toHaveLength(0);
  });

  it("reconnects with bounded jittered backoff and restores the subscription", async () => {
    const { svc, sockets } = makeService();
    await svc.start();
    sockets[0]!.open();
    sockets[0]!.drop();
    expect(svc.state()).toMatchObject({ status: "RECONNECTING", lastError: "NETWORK", reconnectAttempts: 1 });
    await vi.advanceTimersByTimeAsync(749); // attempt 1: 1 s base, jitter 0.5 -> 750 ms
    expect(sockets).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(sockets).toHaveLength(2);
    sockets[1]!.open();
    expect(sockets[1]!.sent[0]).toEqual({ a: "subscribe", v: [RELIANCE, TCS] });
    for (let t = 0; t < 30; t++) {
      sockets[1]!.heartbeat(); // Kite sends one per second
      await vi.advanceTimersByTimeAsync(1_000);
    }
    expect(svc.state()).toMatchObject({ status: "CONNECTED", reconnectAttempts: 0 }); // stable: counter reset
    for (let i = 0; i < 12; i++) {
      sockets.at(-1)!.drop();
      await vi.advanceTimersByTimeAsync(BACKOFF_MAX_MS);
    }
    expect(sockets.length).toBe(14); // one reconnect per drop, never a burst
    await svc.stop();
  });

  it("closes a silent connection (no heartbeat) and reconnects", async () => {
    const { svc, sockets } = makeService();
    await svc.start();
    sockets[0]!.open();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(sockets[0]!.closed).toBe(true);
    expect(svc.state().status).toBe("RECONNECTING");
    await svc.stop();
  });

  it("stops retrying when the session is rejected or expired", async () => {
    const rejected = makeService({ profile: () => 403 });
    await rejected.svc.start();
    expect(rejected.svc.state()).toMatchObject({ status: "AUTH_REQUIRED", lastError: "AUTH" });
    expect(rejected.sockets).toHaveLength(0);

    const expired = makeService({ file: sessionFile("2026-10-26 09:00:00") });
    await expired.svc.start();
    expect(expired.svc.state().status).toBe("AUTH_REQUIRED");
    expect(expired.fetchCalls).toHaveLength(0);

    let status = 200; // accepted at start, revoked later: the third failed reconnect re-checks the session
    const revoked = makeService({ profile: () => status });
    await revoked.svc.start();
    status = 403;
    for (let i = 0; i < 3; i++) {
      revoked.sockets.at(-1)!.drop();
      await vi.advanceTimersByTimeAsync(BACKOFF_MAX_MS);
    }
    expect(revoked.svc.state().status).toBe("AUTH_REQUIRED");
    const count = revoked.sockets.length;
    await vi.advanceTimersByTimeAsync(10 * BACKOFF_MAX_MS);
    expect(revoked.sockets.length).toBe(count);
  });

  it("shuts down cleanly: socket closed, no timers, no reconnect afterwards", async () => {
    const { svc, sockets } = makeService();
    await svc.start();
    sockets[0]!.open();
    sockets[0]!.drop(); // a retry is pending
    await svc.stop();
    expect(svc.state().status).toBe("STOPPED");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(10 * BACKOFF_MAX_MS);
    expect(sockets).toHaveLength(1);
  });
});

// ------------------------------------------------------------------ response building

function source(status: LiveState["status"], quotes: Record<string, StoredQuote>): { state(): LiveState; quote(s: string): StoredQuote | null } {
  return {
    state: () => ({
      status, reason: null, connectedSince: null, lastTickAt: null, lastError: null, reconnectAttempts: 0,
      watchlist: Object.keys(quotes), tokens: new Map([["RELIANCE", RELIANCE], ["TCS", TCS]]), unresolved: ["GONE"],
    }),
    quote: (s) => quotes[s] ?? null,
  };
}
const stored = (symbol: string, receivedAt: number, ltp = 250050): StoredQuote => ({
  symbol, receivedAt,
  tick: { token: RELIANCE, mode: "quote", ltpPaise: ltp, volume: 5, openPaise: 248000, highPaise: 251000,
    lowPaise: 247000, closePaise: 248500, exchangeTimeMs: null },
});

describe("quote view", () => {
  const now = NOW.getTime();
  const eod = [{ symbol: "RELIANCE", date: "2026-10-26", close: 2480 }, { symbol: "INFY", date: "2026-10-26", close: 1500 }];

  it("labels fresh, quiet and stale live quotes, converting paise to rupees", () => {
    const quotes = { RELIANCE: stored("RELIANCE", now - 10_000), TCS: stored("TCS", now - 600_000) };
    const v = buildLiveQuotes(source("CONNECTED", quotes), ["RELIANCE", "TCS"], eod, now, 60);
    expect(LiveQuotes.parse(v)).toBeTruthy();
    expect(v.quotes[0]).toMatchObject({ source: "LIVE", ltp: 2500.5, prev_close: 2485, freshness: "FRESH", age_seconds: 10 });
    expect(v.quotes[1]).toMatchObject({ source: "LIVE", freshness: "QUIET" });
    expect(v.fresh_quotes).toBe(1);
    const down = buildLiveQuotes(source("RECONNECTING", quotes), ["RELIANCE"], eod, now, 60);
    expect(down.quotes[0]).toMatchObject({ source: "LIVE", freshness: "STALE" });
    expect(down.quotes[0]!.note).toMatch(/not current/);
    expect(down.fresh_quotes).toBe(0);
  });

  it("falls back to the end-of-day close, labelled with its date, and never invents a price", () => {
    const v = buildLiveQuotes(source("CONNECTED", {}), ["RELIANCE", "GONE", "NOPE"], eod, now, 60);
    expect(v.quotes[0]).toMatchObject({ source: "EOD", ltp: 2480, eod_date: "2026-10-26", freshness: "UNAVAILABLE", received_at: null });
    expect(v.quotes[1]).toMatchObject({ source: "NONE", ltp: null, note: "Not found in Kite's NSE equity list." });
    expect(v.quotes[2]).toMatchObject({ source: "NONE", ltp: null });
    // A live quote from the previous day is older than that day's close: the close is shown.
    const old = { RELIANCE: stored("RELIANCE", new Date("2026-10-26T06:00:00Z").getTime()) };
    expect(buildLiveQuotes(source("CONNECTED", old), ["RELIANCE"], eod, now, 60).quotes[0]!.source).toBe("EOD");
    const noEod = buildLiveQuotes(source("CONNECTED", old), ["RELIANCE"], [], now, 60);
    expect(noEod.quotes[0]).toMatchObject({ source: "LIVE", freshness: "STALE" });
  });

  it("never calls a quote fresh while the market is closed (Kite still sends a snapshot on subscribe)", () => {
    const evening = new Date("2026-10-27T14:27:00Z").getTime(); // 19:57 IST
    const v = buildLiveQuotes(source("CONNECTED", { RELIANCE: stored("RELIANCE", evening - 5_000) }), ["RELIANCE"], eod, evening, 60);
    expect(v.session.status).toBe("CLOSED");
    expect(v.quotes[0]).toMatchObject({ source: "LIVE", freshness: "QUIET" });
    expect(v.fresh_quotes).toBe(0);
  });

  it("reports the session, closed markets and an unknown calendar honestly", () => {
    expect(sessionStatus(NOW)).toEqual({ status: "OPEN", calendar_known: true });
    expect(sessionStatus(new Date("2026-10-27T12:00:00Z")).status).toBe("CLOSED"); // 17:30 IST
    expect(sessionStatus(new Date("2026-10-25T05:00:00Z")).status).toBe("WEEKEND");
    expect(sessionStatus(new Date("2027-03-02T05:00:00Z"))).toEqual({ status: "UNKNOWN", calendar_known: false });
  });

  it("reports DISABLED with end-of-day prices when the live feed is off", () => {
    const v = buildLiveQuotes(null, ["RELIANCE"], eod, now, 60);
    expect(v.connection).toMatchObject({ status: "DISABLED", subscribed: 0 });
    expect(v.quotes[0]).toMatchObject({ source: "EOD" });
  });
});

describe("GET /v1/live/quotes", () => {
  const app = async (live = source("CONNECTED", { RELIANCE: stored("RELIANCE", NOW.getTime() - 5_000) }), repo = new FixtureRepo()) =>
    buildApp({ repo, now: () => new Date(Date.now()), live: { source: live, watchlist: ["RELIANCE", "TCS"], freshSeconds: 60 } });

  it("returns the watchlist with freshness, source and connection health, uncached and without secrets", async () => {
    const a = await app();
    const res = await a.inject({ method: "GET", url: "/v1/live/quotes" });
    expect(res.statusCode).toBe(200);
    expect(res.headers["cache-control"]).toBe("no-store");
    const body = res.json();
    expect(body.data.quotes.map((q: { symbol: string; source: string }) => [q.symbol, q.source])).toEqual([
      ["RELIANCE", "LIVE"], ["TCS", "EOD"],
    ]);
    expect(body.data.connection.status).toBe("CONNECTED");
    expect(res.body).not.toMatch(/access_token|api_key|secret/);
    const health = await a.inject({ method: "GET", url: "/health" });
    expect(health.json().live).toEqual({ status: "CONNECTED" });
    await a.close();
  });

  it("validates parameters and answers only for watchlist symbols", async () => {
    const a = await app();
    expect((await a.inject({ method: "GET", url: "/v1/live/quotes?symbols=tcs" })).json().data.quotes).toHaveLength(1);
    const outside = await a.inject({ method: "GET", url: "/v1/live/quotes?symbols=INFY" });
    expect(outside.statusCode).toBe(400);
    expect(outside.json().error.code).toBe("NOT_IN_WATCHLIST");
    expect((await a.inject({ method: "GET", url: "/v1/live/quotes?symbols=%3Cscript%3E" })).statusCode).toBe(400);
    await a.close();
  });

  it("still answers when the database (EOD fallback) or Redis is unavailable", async () => {
    const repo = new FixtureRepo();
    repo.latestCloses = async () => {
      throw new Error("db down");
    };
    const a = await app(source("RECONNECTING", {}), repo);
    const body = (await a.inject({ method: "GET", url: "/v1/live/quotes" })).json();
    expect(body.data.quotes.every((q: { source: string; ltp: null }) => q.source === "NONE" && q.ltp === null)).toBe(true);
    expect(body.data.connection.status).toBe("RECONNECTING");
    await a.close();

    const brokenRedis = { get: async () => { throw new Error("down"); }, set: async () => { throw new Error("down"); } };
    const b = await buildApp({
      repo: new FixtureRepo(), cache: new RedisCache(brokenRedis as never), now: () => new Date(Date.now()),
      live: { source: source("CONNECTED", {}), watchlist: ["RELIANCE"], freshSeconds: 60 },
    });
    const r = await b.inject({ method: "GET", url: "/v1/live/quotes" });
    expect(r.statusCode).toBe(200);
    expect(r.json().data.quotes[0].source).toBe("EOD");
    await b.close();
  });

  it("reports DISABLED with an empty watchlist when no live feed is configured", async () => {
    const a = await buildApp({ repo: new FixtureRepo() });
    const body = (await a.inject({ method: "GET", url: "/v1/live/quotes" })).json();
    expect(body.data).toMatchObject({ quotes: [], connection: { status: "DISABLED" } });
    await a.close();
  });
});
