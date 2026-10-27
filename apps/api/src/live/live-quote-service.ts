/**
 * Read-only live quotes from the Kite ticker for a small configured watchlist.
 *
 * One process-wide connection (start() is idempotent). Lifecycle:
 *   start: session file -> expiry check -> /user/profile -> instrument master -> resolve watchlist -> connect
 *   open: subscribe the resolved tokens in "quote" mode (LTP, OHLC, volume; no depth)
 *   Kite sends a heartbeat every second, so 15 s of silence on an open socket means a dead connection: it is
 *   closed and re-opened. Reconnects use exponential backoff with jitter (1 s .. 60 s); the attempt counter is
 *   reset after 30 s of stable connection. Every third failed attempt re-checks the session; a rejected or
 *   expired session stops retrying (AUTH_REQUIRED) instead of looping on invalid credentials.
 *
 * Latest quotes are kept in memory (bounded: one entry per subscribed token) by this process, which owns the
 * socket; nothing is persisted and no tick is logged. The service never places, modifies or cancels orders.
 */
import type { LiveConnectionStatus } from "@dd/contracts";
import {
  checkSession,
  type Fetch,
  fetchNseEquityTokens,
  KiteAuthError,
  type KiteCredentials,
  loadCredentials,
  sessionExpired,
  TICKER_URL,
} from "./kite-session";
import { parseBinary, parseText, type Tick } from "./ticker-packets";

export interface TickerSocket {
  binaryType: string;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  send(data: string): void;
  close(): void;
}
export type SocketFactory = (url: string) => TickerSocket;

export interface LiveOptions {
  watchlist: string[];
  sessionFile: string;
  maxSymbols?: number;
  socketFactory?: SocketFactory;
  fetchFn?: Fetch;
  now?: () => number;
  random?: () => number;
  log?: { info(obj: object, msg: string): void; warn(obj: object, msg: string): void };
}

export interface StoredQuote {
  symbol: string;
  tick: Tick;
  receivedAt: number;
}

export interface LiveState {
  status: LiveConnectionStatus;
  reason: string | null;
  connectedSince: number | null;
  lastTickAt: number | null;
  lastError: "NETWORK" | "AUTH" | "PROTOCOL" | "CONFIG" | null;
  reconnectAttempts: number;
  watchlist: string[];
  tokens: Map<string, number>;
  unresolved: string[];
}

/** What the quote API needs from the live feed (lets routes be tested without a socket). */
export interface LiveQuoteSource {
  state(): LiveState;
  quote(symbol: string): StoredQuote | null;
}

export const BACKOFF_MIN_MS = 1_000;
export const BACKOFF_MAX_MS = 60_000;
export const STABLE_MS = 30_000;
export const SILENCE_MS = 15_000;
const WATCHDOG_MS = 5_000;
const AUTH_RECHECK_EVERY = 3;

export class LiveQuoteService implements LiveQuoteSource {
  private readonly watchlist: string[];
  private readonly now: () => number;
  private readonly random: () => number;
  private readonly socketFactory: SocketFactory;
  private readonly fetchFn: Fetch;
  private status: LiveConnectionStatus = "STOPPED";
  private reason: string | null = null;
  private lastError: LiveState["lastError"] = null;
  private connectedSince: number | null = null;
  private lastTickAt: number | null = null;
  private lastMessageAt = 0;
  private attempts = 0;
  private creds: KiteCredentials | null = null;
  private tokens = new Map<string, number>();
  private symbolOf = new Map<number, string>();
  private unresolved: string[] = [];
  private readonly quotes = new Map<number, StoredQuote>();
  private socket: TickerSocket | null = null;
  private retryTimer: NodeJS.Timeout | null = null;
  private stableTimer: NodeJS.Timeout | null = null;
  private watchdog: NodeJS.Timeout | null = null;
  private starting: Promise<void> | null = null;
  private stopped = false;
  /** Counters for tests and diagnostics. */
  readonly counters = { connects: 0, outOfOrder: 0, skippedPackets: 0 };

  constructor(private readonly opts: LiveOptions) {
    const max = opts.maxSymbols ?? 50;
    const unique = [...new Set(opts.watchlist.map((s) => s.trim().toUpperCase()).filter(Boolean))];
    this.watchlist = unique.slice(0, max);
    if (unique.length > max) this.reason = `Watchlist truncated to ${max} symbols (DD_LIVE_MAX_SYMBOLS).`;
    this.now = opts.now ?? Date.now;
    this.random = opts.random ?? Math.random;
    this.socketFactory = opts.socketFactory ?? ((url) => new WebSocket(url) as unknown as TickerSocket);
    this.fetchFn = opts.fetchFn ?? fetch;
  }

  /** Idempotent: repeated calls share one start and never open a second connection. */
  start(): Promise<void> {
    this.starting ??= this.init();
    return this.starting;
  }

  private async init(): Promise<void> {
    this.stopped = false;
    if (!this.watchlist.length) return this.halt("NOT_CONFIGURED", "No watchlist configured (DD_LIVE_WATCHLIST).", "CONFIG");
    this.set("CONNECTING", null);
    try {
      this.creds = await loadCredentials(this.opts.sessionFile);
      if (sessionExpired(this.creds.loginTime, new Date(this.now()))) {
        throw new KiteAuthError("The Kite session expired at 6 AM IST. Run `pnpm kite:login`.");
      }
      await checkSession(this.creds, this.fetchFn);
      const all = await fetchNseEquityTokens(this.creds, this.fetchFn);
      this.tokens = new Map(this.watchlist.filter((s) => all.has(s)).map((s) => [s, all.get(s)!]));
      this.symbolOf = new Map([...this.tokens].map(([s, t]) => [t, s]));
      this.unresolved = this.watchlist.filter((s) => !all.has(s));
    } catch (err) {
      if (err instanceof KiteAuthError) return this.halt("AUTH_REQUIRED", err.message, "AUTH");
      this.lastError = "NETWORK";
      this.reason = "Could not reach Kite to start the live feed; retrying.";
      this.opts.log?.warn({ err: String(err) }, "live feed start failed");
      this.starting = null;
      return this.scheduleRetry(() => void this.start());
    }
    if (this.unresolved.length) {
      this.opts.log?.warn({ unresolved: this.unresolved }, "watchlist symbols not in Kite's NSE equity list");
    }
    if (!this.tokens.size) return this.halt("NOT_CONFIGURED", "No watchlist symbol is an NSE equity on Kite.", "CONFIG");
    if (this.stopped) return;
    this.connect();
  }

  private connect(): void {
    if (this.stopped || this.socket || !this.creds) return;
    this.set(this.attempts ? "RECONNECTING" : "CONNECTING", this.reason);
    const url = `${TICKER_URL}?api_key=${encodeURIComponent(this.creds.apiKey)}&access_token=${encodeURIComponent(this.creds.accessToken)}`;
    let ws: TickerSocket;
    try {
      ws = this.socketFactory(url);
    } catch (err) {
      this.lastError = "NETWORK";
      this.opts.log?.warn({ err: String(err).replace(url, "<ticker url>") }, "live feed socket failed");
      return this.scheduleRetry(() => this.connect());
    }
    this.counters.connects++;
    ws.binaryType = "arraybuffer";
    this.socket = ws;
    ws.onopen = () => this.onOpen(ws);
    ws.onmessage = (ev) => this.onMessage(ws, ev.data);
    ws.onerror = () => {
      if (this.socket === ws) this.lastError = "NETWORK";
    };
    ws.onclose = () => this.onClose(ws);
  }

  private onOpen(ws: TickerSocket): void {
    if (this.socket !== ws) return;
    this.connectedSince = this.now();
    this.lastMessageAt = this.now();
    this.set("CONNECTED", null);
    const tokens = [...new Set(this.tokens.values())];
    ws.send(JSON.stringify({ a: "subscribe", v: tokens }));
    ws.send(JSON.stringify({ a: "mode", v: ["quote", tokens] }));
    this.opts.log?.info({ subscribed: tokens.length }, "live feed connected");
    this.clear("stableTimer");
    this.stableTimer = setTimeout(() => {
      if (this.socket === ws && this.status === "CONNECTED") this.attempts = 0;
    }, STABLE_MS);
    this.clear("watchdog");
    this.watchdog = setInterval(() => {
      if (this.socket === ws && this.now() - this.lastMessageAt > SILENCE_MS) {
        this.opts.log?.warn({ silent_ms: this.now() - this.lastMessageAt }, "live feed silent; reconnecting");
        this.lastError = "NETWORK";
        ws.close();
        this.onClose(ws); // do not wait for a close event a dead socket may never deliver
      }
    }, WATCHDOG_MS);
    this.stableTimer.unref?.();
    this.watchdog.unref?.();
  }

  private onMessage(ws: TickerSocket, data: unknown): void {
    if (this.socket !== ws) return;
    this.lastMessageAt = this.now();
    if (typeof data === "string") {
      const msg = parseText(data);
      if (msg?.type === "error") {
        this.lastError = "PROTOCOL";
        this.reason = msg.message ? `Kite: ${msg.message}` : "Kite reported an error.";
        this.opts.log?.warn({ reason: this.reason }, "live feed error message");
      }
      return;
    }
    if (!(data instanceof ArrayBuffer)) return;
    const { ticks, skipped } = parseBinary(data);
    this.counters.skippedPackets += skipped;
    for (const tick of ticks) this.store(tick);
  }

  private store(tick: Tick): void {
    const symbol = this.symbolOf.get(tick.token);
    if (!symbol) return; // not subscribed by us: ignored, keeps the map bounded
    const prev = this.quotes.get(tick.token);
    if (prev?.tick.exchangeTimeMs != null && tick.exchangeTimeMs != null && tick.exchangeTimeMs < prev.tick.exchangeTimeMs) {
      this.counters.outOfOrder++;
      return; // older than what we hold: never overwrite newer data
    }
    const at = this.now();
    this.quotes.set(tick.token, { symbol, tick, receivedAt: at });
    this.lastTickAt = at;
  }

  private onClose(ws: TickerSocket): void {
    if (this.socket !== ws) return;
    this.socket = null;
    this.connectedSince = null;
    this.clear("watchdog");
    this.clear("stableTimer");
    if (this.stopped) return;
    this.scheduleRetry(() => this.connect());
  }

  private scheduleRetry(run: () => void): void {
    if (this.stopped || this.retryTimer) return;
    this.attempts++;
    if (this.creds && sessionExpired(this.creds.loginTime, new Date(this.now()))) {
      return this.halt("AUTH_REQUIRED", "The Kite session expired at 6 AM IST. Run `pnpm kite:login`.", "AUTH");
    }
    const base = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** (this.attempts - 1));
    const delay = Math.round(base / 2 + (this.random() * base) / 2);
    this.set("RECONNECTING", this.reason ?? "Connection lost; reconnecting.");
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.attempts % AUTH_RECHECK_EVERY === 0 && this.creds) {
        checkSession(this.creds, this.fetchFn).then(run, (err) => {
          if (err instanceof KiteAuthError) this.halt("AUTH_REQUIRED", err.message, "AUTH");
          else run();
        });
      } else run();
    }, delay);
    this.retryTimer.unref?.();
  }

  /** Close the socket and stop all timers; resolves immediately (never waits on the network). */
  async stop(): Promise<void> {
    this.stopped = true;
    this.clear("retryTimer");
    this.clear("stableTimer");
    this.clear("watchdog");
    const ws = this.socket;
    this.socket = null;
    if (ws) {
      try {
        ws.close();
      } catch {
        // already closed
      }
    }
    this.connectedSince = null;
    if (this.status !== "AUTH_REQUIRED" && this.status !== "NOT_CONFIGURED") this.set("STOPPED", null);
    this.starting = null;
  }

  state(): LiveState {
    return {
      status: this.status,
      reason: this.reason,
      connectedSince: this.connectedSince,
      lastTickAt: this.lastTickAt,
      lastError: this.lastError,
      reconnectAttempts: this.attempts,
      watchlist: [...this.watchlist],
      tokens: new Map(this.tokens),
      unresolved: [...this.unresolved],
    };
  }

  quote(symbol: string): StoredQuote | null {
    const token = this.tokens.get(symbol);
    return token == null ? null : (this.quotes.get(token) ?? null);
  }

  private halt(status: LiveConnectionStatus, reason: string, error: LiveState["lastError"]): void {
    this.clear("retryTimer");
    this.lastError = error;
    this.set(status, reason);
    if (status === "AUTH_REQUIRED") this.opts.log?.warn({ reason }, "live feed stopped: authentication required");
  }

  private set(status: LiveConnectionStatus, reason: string | null): void {
    this.status = status;
    this.reason = reason;
  }

  private clear(name: "retryTimer" | "stableTimer" | "watchdog"): void {
    const t = this[name];
    if (t) {
      clearTimeout(t);
      clearInterval(t);
    }
    this[name] = null;
  }
}
