/**
 * Builds the read-only quote response from the live feed's state and the latest end-of-day closes.
 *
 * Rules (never present an old price as live):
 *  - A live quote received today (IST) while connected, within `freshSeconds` and during the open or pre-open
 *    session is FRESH; otherwise, while still connected, it is QUIET (no recent trade: thin trading, or the
 *    market is closed and Kite sent its last snapshot; not necessarily a fault).
 *  - A live quote held while the feed is not connected, or received on an earlier IST day, is STALE.
 *  - With no live quote, or when the end-of-day close is at least as recent, the EOD close is shown as source EOD
 *    with its trading date (freshness UNAVAILABLE: it is not a live price). Neither: source NONE, nulls.
 * Prices are converted from integer paise to rupees here, for display only.
 */
import type { LiveQuote, LiveQuotes, SessionStatus } from "@dd/contracts";
import { istParts, listHolidays, marketStatus } from "@dd/shared";
import type { LiveQuoteSource } from "./live-quote-service";

export interface EodClose {
  symbol: string;
  date: string;
  close: number;
}

const rupees = (paise: number | null) => (paise == null ? null : paise / 100);
const iso = (ms: number | null) => (ms == null ? null : new Date(ms).toISOString());

/** Session state; UNKNOWN when the holiday calendar does not cover the year (never guess a trading day). */
export function sessionStatus(now: Date): { status: SessionStatus; calendar_known: boolean } {
  const year = Number(istParts(now).date.slice(0, 4));
  const known = listHolidays(year).length > 0;
  return { status: known ? marketStatus(now) : "UNKNOWN", calendar_known: known };
}

export function buildLiveQuotes(
  live: LiveQuoteSource | null,
  watchlist: string[],
  eod: EodClose[],
  nowMs: number,
  freshSeconds: number,
): LiveQuotes {
  const now = new Date(nowMs);
  const today = istParts(now).date;
  const state = live?.state() ?? null;
  const connected = state?.status === "CONNECTED";
  const session = sessionStatus(now);
  const trading = session.status === "OPEN" || session.status === "PRE_OPEN" || session.status === "UNKNOWN";
  const eodBy = new Map(eod.map((e) => [e.symbol, e]));
  let fresh = 0;

  const quotes: LiveQuote[] = watchlist.map((symbol) => {
    const q = live?.quote(symbol) ?? null;
    const close = eodBy.get(symbol) ?? null;
    const token = state?.tokens.get(symbol) ?? null;
    const receivedDay = q ? istParts(new Date(q.receivedAt)).date : null;
    const useLive = q != null && (close == null || receivedDay! > close.date);
    if (useLive) {
      const age = Math.max(0, (nowMs - q.receivedAt) / 1000);
      const freshness = !connected || receivedDay !== today ? "STALE" : age <= freshSeconds && trading ? "FRESH" : "QUIET";
      if (freshness === "FRESH") fresh++;
      return {
        symbol, exchange: "NSE", instrument_token: token, source: "LIVE",
        ltp: rupees(q.tick.ltpPaise), prev_close: rupees(q.tick.closePaise), day_open: rupees(q.tick.openPaise),
        day_high: rupees(q.tick.highPaise), day_low: rupees(q.tick.lowPaise), volume: q.tick.volume,
        exchange_time: iso(q.tick.exchangeTimeMs), received_at: iso(q.receivedAt), eod_date: null,
        freshness, age_seconds: Math.round(age),
        note: freshness === "STALE" ? "Last live price from an earlier connection; not current." : null,
      };
    }
    const unresolved = state?.unresolved.includes(symbol) ?? false;
    const base = {
      symbol, exchange: "NSE" as const, instrument_token: token, prev_close: null, day_open: null, day_high: null,
      day_low: null, volume: null, exchange_time: null, received_at: null, freshness: "UNAVAILABLE" as const,
      age_seconds: null,
    };
    if (close) {
      return { ...base, source: "EOD", ltp: close.close, eod_date: close.date,
        note: unresolved ? "Not found in Kite's NSE equity list; end-of-day close shown." : "End-of-day close, not a live price." };
    }
    return { ...base, source: "NONE", ltp: null, eod_date: null,
      note: unresolved ? "Not found in Kite's NSE equity list." : "No price available." };
  });

  return {
    generated_at: now.toISOString(),
    mode: "quote",
    freshness_seconds: freshSeconds,
    session,
    connection: {
      status: state?.status ?? "DISABLED",
      reason: state ? state.reason : "Live market data is turned off (DD_LIVE).",
      connected_since: iso(state?.connectedSince ?? null),
      last_tick_at: iso(state?.lastTickAt ?? null),
      last_error: state?.lastError ?? null,
      reconnect_attempts: state?.reconnectAttempts ?? 0,
      subscribed: state?.tokens.size ?? 0,
      unresolved: state?.unresolved ?? [],
    },
    fresh_quotes: fresh,
    quotes,
  };
}
