/**
 * Display rules for live quotes (pure; tested in live-view.test.ts). An EOD close is never labelled live, a
 * stale live price never looks current, and price movement is shown in neutral colours: it is not a buy/sell call.
 */
import type { LiveConnection, LiveQuote, LiveQuotes, SessionStatus } from "@dd/contracts";

type Tone = "up" | "down" | "warn" | "info" | "neutral";

const istTime = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});
const istDate = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" });
const price = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export interface RowView {
  symbol: string;
  price: string;
  change: string | null;
  updated: string;
  source: { label: string; tone: Tone };
  freshness: { label: string; tone: Tone };
  note: string | null;
}

export function rowView(q: LiveQuote, generatedAt: string): RowView {
  const sameDay = (iso: string) => istDate.format(new Date(iso)) === istDate.format(new Date(generatedAt));
  const updated =
    q.source === "LIVE" && q.received_at
      ? `${istTime.format(new Date(q.received_at))} IST${sameDay(q.received_at) ? "" : `, ${istDate.format(new Date(q.received_at))}`}`
      : q.source === "EOD" && q.eod_date
        ? `Close of ${istDate.format(new Date(`${q.eod_date}T12:00:00+05:30`))}`
        : "—";
  const change =
    q.ltp != null && q.prev_close != null && q.prev_close > 0
      ? `${q.ltp >= q.prev_close ? "+" : "−"}${(Math.abs(q.ltp / q.prev_close - 1) * 100).toFixed(2)}%`
      : null;
  return {
    symbol: q.symbol,
    price: q.ltp == null ? "Unavailable" : `₹${price.format(q.ltp)}`,
    change,
    updated,
    source:
      q.source === "LIVE" ? { label: "Live", tone: "info" }
      : q.source === "EOD" ? { label: "End of day", tone: "neutral" }
      : { label: "No data", tone: "neutral" },
    freshness: {
      FRESH: { label: "Fresh", tone: "info" as Tone },
      QUIET: { label: "No recent trade", tone: "neutral" as Tone },
      STALE: { label: "Stale", tone: "warn" as Tone },
      UNAVAILABLE: { label: q.source === "EOD" ? "Not live" : "Unavailable", tone: "neutral" as Tone },
    }[q.freshness],
    note: q.note,
  };
}

const SESSION_LABEL: Record<SessionStatus, string> = {
  OPEN: "Market open",
  PRE_OPEN: "Pre-open session",
  CLOSED: "Market closed",
  HOLIDAY: "Market holiday",
  WEEKEND: "Weekend: market closed",
  UNKNOWN: "Session unknown (holiday calendar does not cover this year)",
};

export interface Banner {
  connection: { label: string; tone: Tone };
  session: string;
  message: string | null;
}

export function banner(d: LiveQuotes): Banner {
  const c: LiveConnection = d.connection;
  const label: Record<LiveConnection["status"], [string, Tone]> = {
    CONNECTED: ["Connected", "info"],
    CONNECTING: ["Connecting", "neutral"],
    RECONNECTING: ["Reconnecting", "warn"],
    AUTH_REQUIRED: ["Login required", "warn"],
    NOT_CONFIGURED: ["Not configured", "neutral"],
    DISABLED: ["Live data off", "neutral"],
    STOPPED: ["Stopped", "neutral"],
  };
  const [text, tone] = label[c.status];
  let message = c.reason;
  if (c.status === "CONNECTED" && d.fresh_quotes === 0 && d.quotes.length > 0) {
    message = d.session.status === "OPEN"
      ? "Connected, but no recent trades for these stocks."
      : "Connected; no ticks while the market is closed. Prices shown are the last known.";
  }
  if (c.unresolved.length) {
    message = [message, `Not found on Kite: ${c.unresolved.join(", ")}.`].filter(Boolean).join(" ");
  }
  return { connection: { label: text, tone }, session: SESSION_LABEL[d.session.status], message };
}
