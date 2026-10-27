/**
 * Kite Connect WebSocket (ticker) binary message parser. Docs: https://kite.trade/docs/connect/v3/websocket/
 *
 * A binary message is: int16 packet count, then per packet an int16 length and the packet. All integers are
 * big-endian. Prices are integers in paise for NSE/BSE equities (segment 1/2, read from the token's low byte);
 * other segments use different divisors and are rejected rather than mis-scaled. A 1-byte message is a
 * heartbeat. Packet length selects the mode: 8 = ltp, 44 = quote, 184 = full (quote + timestamps + depth);
 * 28/32 are index packets, which the watchlist never subscribes and are skipped.
 */

export type TickMode = "ltp" | "quote" | "full";

export interface Tick {
  token: number;
  mode: TickMode;
  /** Prices in paise (integers): exact, converted to rupees only for display. */
  ltpPaise: number;
  volume: number | null;
  openPaise: number | null;
  highPaise: number | null;
  lowPaise: number | null;
  /** Previous session's close (Kite's ohlc.close). */
  closePaise: number | null;
  /** Exchange time of the last trade (full mode only), epoch milliseconds. */
  exchangeTimeMs: number | null;
}

export interface ParseResult {
  ticks: Tick[];
  heartbeat: boolean;
  /** Packets that were malformed or of an unsupported segment/length. */
  skipped: number;
}

const EQUITY_SEGMENTS = new Set([1, 2]); // NSE, BSE cash market: prices in paise

export function parseBinary(buf: ArrayBuffer): ParseResult {
  if (buf.byteLength < 2) return { ticks: [], heartbeat: buf.byteLength === 1, skipped: 0 };
  const view = new DataView(buf);
  const count = view.getInt16(0);
  const ticks: Tick[] = [];
  let skipped = 0;
  let off = 2;
  for (let i = 0; i < count; i++) {
    if (off + 2 > buf.byteLength) return { ticks, heartbeat: false, skipped: skipped + (count - i) };
    const len = view.getInt16(off);
    off += 2;
    if (len <= 0 || off + len > buf.byteLength) return { ticks, heartbeat: false, skipped: skipped + (count - i) };
    const tick = parsePacket(new DataView(buf, off, len));
    if (tick) ticks.push(tick);
    else skipped++;
    off += len;
  }
  return { ticks, heartbeat: false, skipped };
}

function parsePacket(p: DataView): Tick | null {
  const len = p.byteLength;
  if (len !== 8 && len !== 44 && len !== 184) return null;
  const token = p.getUint32(0);
  if (!EQUITY_SEGMENTS.has(token & 0xff)) return null;
  const ltpPaise = p.getInt32(4);
  if (!(ltpPaise > 0)) return null; // no trade yet / invalid: never shown as a price
  if (len === 8) {
    return { token, mode: "ltp", ltpPaise, volume: null, openPaise: null, highPaise: null, lowPaise: null,
      closePaise: null, exchangeTimeMs: null };
  }
  const positive = (v: number) => (v > 0 ? v : null);
  const lastTrade = len === 184 ? p.getInt32(44) : 0;
  return {
    token,
    mode: len === 44 ? "quote" : "full",
    ltpPaise,
    volume: p.getInt32(16) >= 0 ? p.getInt32(16) : null,
    openPaise: positive(p.getInt32(28)),
    highPaise: positive(p.getInt32(32)),
    lowPaise: positive(p.getInt32(36)),
    closePaise: positive(p.getInt32(40)),
    exchangeTimeMs: lastTrade > 0 ? lastTrade * 1000 : null,
  };
}

/** Text frames: {"type": "error" | "message" | "order", "data": ...}. Order updates are ignored (read-only). */
export function parseText(text: string): { type: string; message: string | null } | null {
  try {
    const msg = JSON.parse(text) as { type?: unknown; data?: unknown };
    if (typeof msg.type !== "string") return null;
    return { type: msg.type, message: typeof msg.data === "string" ? msg.data.slice(0, 200) : null };
  } catch {
    return null;
  }
}
