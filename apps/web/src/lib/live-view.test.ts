import type { LiveQuote, LiveQuotes } from "@dd/contracts";
import { describe, expect, it } from "vitest";
import { banner, rowView } from "./live-view";

const GEN = "2026-10-27T05:00:30.000Z"; // 10:30:30 IST

const quote = (over: Partial<LiveQuote>): LiveQuote => ({
  symbol: "RELIANCE", exchange: "NSE", instrument_token: 738561, source: "LIVE", ltp: 2500.5, prev_close: 2485,
  day_open: null, day_high: null, day_low: null, volume: null, exchange_time: null,
  received_at: "2026-10-27T05:00:20.000Z", eod_date: null, freshness: "FRESH", age_seconds: 10, note: null, ...over,
});

const quotes = (over: Partial<LiveQuotes>, conn: Partial<LiveQuotes["connection"]> = {}): LiveQuotes => ({
  generated_at: GEN, mode: "quote", freshness_seconds: 60, session: { status: "OPEN", calendar_known: true },
  connection: { status: "CONNECTED", reason: null, connected_since: null, last_tick_at: null, last_error: null,
    reconnect_attempts: 0, subscribed: 1, unresolved: [], ...conn },
  fresh_quotes: 1, quotes: [quote({})], ...over,
});

describe("rowView", () => {
  it("shows a fresh live price with IST time and a neutral change", () => {
    const r = rowView(quote({}), GEN);
    expect(r).toMatchObject({ price: "₹2,500.50", change: "+0.62%", updated: "10:30:20 IST" });
    expect(r.source).toEqual({ label: "Live", tone: "info" });
    expect(r.freshness).toEqual({ label: "Fresh", tone: "info" });
    expect([r.source.tone, r.freshness.tone]).not.toContain("up"); // never a green "buy" colour
  });

  it("marks stale and quiet live prices, including the day when not today", () => {
    const stale = rowView(quote({ freshness: "STALE", received_at: "2026-10-26T09:55:00.000Z" }), GEN);
    expect(stale.freshness).toEqual({ label: "Stale", tone: "warn" });
    expect(stale.updated).toBe("15:25:00 IST, 26 Oct");
    expect(rowView(quote({ freshness: "QUIET" }), GEN).freshness.label).toBe("No recent trade");
  });

  it("never labels an end-of-day close as live, and shows unavailable prices as such", () => {
    const eod = rowView(quote({ source: "EOD", ltp: 2480, prev_close: null, received_at: null, eod_date: "2026-10-26",
      freshness: "UNAVAILABLE" }), GEN);
    expect(eod).toMatchObject({ price: "₹2,480.00", change: null, updated: "Close of 26 Oct" });
    expect(eod.source.label).toBe("End of day");
    expect(eod.freshness.label).toBe("Not live");
    const none = rowView(quote({ source: "NONE", ltp: null, prev_close: null, received_at: null, freshness: "UNAVAILABLE",
      note: "No price available." }), GEN);
    expect(none).toMatchObject({ price: "Unavailable", updated: "—", note: "No price available." });
  });
});

describe("banner", () => {
  it("describes connection and session states", () => {
    expect(banner(quotes({}))).toEqual({ connection: { label: "Connected", tone: "info" }, session: "Market open", message: null });
    const down = banner(quotes({}, { status: "RECONNECTING", reason: "Connection lost; reconnecting." }));
    expect(down).toMatchObject({ connection: { label: "Reconnecting", tone: "warn" }, message: "Connection lost; reconnecting." });
    expect(banner(quotes({}, { status: "AUTH_REQUIRED", reason: "Run `pnpm kite:login`." })).connection.label).toBe("Login required");
    expect(banner(quotes({}, { status: "DISABLED" })).connection.label).toBe("Live data off");
  });

  it("explains quiet connections, a closed market, unknown calendars and unresolved symbols", () => {
    const closed = banner(quotes({ fresh_quotes: 0, session: { status: "CLOSED", calendar_known: true } }));
    expect(closed.session).toBe("Market closed");
    expect(closed.message).toMatch(/market is closed/);
    expect(banner(quotes({ fresh_quotes: 0 })).message).toMatch(/no recent trades/);
    expect(banner(quotes({ session: { status: "UNKNOWN", calendar_known: false } })).session).toMatch(/unknown/);
    expect(banner(quotes({}, { unresolved: ["GONE"] })).message).toBe("Not found on Kite: GONE.");
    expect(banner(quotes({ quotes: [], fresh_quotes: 0 })).message).toBeNull(); // empty watchlist: table explains
  });
});
