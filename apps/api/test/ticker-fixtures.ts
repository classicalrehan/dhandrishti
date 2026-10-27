/** Encodes Kite ticker packets (layout in src/live/ticker-packets.ts) for deterministic tests. */
import type { TickMode } from "../src/live/ticker-packets";

export interface PacketFields {
  token: number;
  ltp: number; // paise
  volume?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  lastTradeSec?: number;
}

export function encodePacket(f: PacketFields, mode: TickMode): Uint8Array {
  const len = mode === "ltp" ? 8 : mode === "quote" ? 44 : 184;
  const p = new DataView(new ArrayBuffer(len));
  p.setUint32(0, f.token);
  p.setInt32(4, f.ltp);
  if (len >= 44) {
    p.setInt32(16, f.volume ?? 0);
    p.setInt32(28, f.open ?? 0);
    p.setInt32(32, f.high ?? 0);
    p.setInt32(36, f.low ?? 0);
    p.setInt32(40, f.close ?? 0);
  }
  if (len === 184) p.setInt32(44, f.lastTradeSec ?? 0);
  return new Uint8Array(p.buffer);
}

export function encodeMessage(packets: Uint8Array[]): ArrayBuffer {
  const size = 2 + packets.reduce((n, p) => n + 2 + p.byteLength, 0);
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  view.setInt16(0, packets.length);
  let off = 2;
  for (const p of packets) {
    view.setInt16(off, p.byteLength);
    out.set(p, off + 2);
    off += 2 + p.byteLength;
  }
  return out.buffer;
}
