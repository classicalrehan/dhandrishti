/**
 * Kite session and read-only REST calls for the live feed.
 *
 * Reuses the session file written by the worker's `pnpm kite:login` (apps/worker/.../providers/kite/session.py):
 * {api_key, access_token, user_id, login_time}. The access token expires at 6 AM IST the next day. Credentials stay
 * in this process: they are never logged, returned by the API or sent anywhere but api.kite.trade / ws.kite.trade.
 * No order, GTT or portfolio-changing endpoint is called; only /user/profile (session check) and /instruments/NSE.
 */
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { gunzipSync } from "node:zlib";

export const API_ROOT = "https://api.kite.trade";
export const TICKER_URL = "wss://ws.kite.trade";

export interface KiteCredentials {
  apiKey: string;
  accessToken: string;
  /** IST wall-clock login time as written by the worker ("YYYY-MM-DD HH:MM:SS"), if known. */
  loginTime: string | null;
}

export class KiteAuthError extends Error {}

export function sessionFilePath(env: NodeJS.ProcessEnv = process.env): string {
  return env.DD_KITE_SESSION_FILE ?? join(homedir(), ".config", "dhandrishti", "kite_session.json");
}

export async function loadCredentials(path: string): Promise<KiteCredentials> {
  let raw: string;
  try {
    raw = await readFile(path, "utf-8");
  } catch {
    throw new KiteAuthError("No Kite session found. Run `pnpm kite:login`.");
  }
  let data: { api_key?: unknown; access_token?: unknown; login_time?: unknown };
  try {
    data = JSON.parse(raw);
  } catch {
    throw new KiteAuthError("The Kite session file is unreadable. Run `pnpm kite:login`.");
  }
  if (typeof data.api_key !== "string" || typeof data.access_token !== "string" || !data.api_key || !data.access_token) {
    throw new KiteAuthError("The Kite session file is incomplete. Run `pnpm kite:login`.");
  }
  return {
    apiKey: data.api_key,
    accessToken: data.access_token,
    loginTime: typeof data.login_time === "string" ? data.login_time : null,
  };
}

/** True once 6:00 IST after the login has passed (Kite invalidates tokens then). Unknown login time: false. */
export function sessionExpired(loginTime: string | null, now: Date): boolean {
  const m = loginTime?.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return false;
  const [, y, mo, d, h] = m.map(Number) as [number, number, number, number, number];
  // 6:00 IST on the login day, or the next day when the login was at/after 6:00; IST = UTC+5:30.
  const sixIstUtc = Date.UTC(y, mo - 1, d + (h >= 6 ? 1 : 0), 0, 30);
  return now.getTime() >= sixIstUtc;
}

export type Fetch = typeof fetch;

function headers(c: KiteCredentials): Record<string, string> {
  return { "X-Kite-Version": "3", Authorization: `token ${c.apiKey}:${c.accessToken}` };
}

/** Confirms the token is accepted (GET /user/profile). Throws KiteAuthError on 403, Error otherwise. */
export async function checkSession(c: KiteCredentials, fetchFn: Fetch = fetch): Promise<void> {
  const res = await fetchFn(`${API_ROOT}/user/profile`, { headers: headers(c), signal: AbortSignal.timeout(10_000) });
  if (res.status === 403) throw new KiteAuthError("Kite rejected the session (expired or revoked). Run `pnpm kite:login`.");
  if (!res.ok) throw new Error(`Kite profile check failed: HTTP ${res.status}`);
}

/** NSE cash-market equities: tradingsymbol -> instrument_token, from Kite's instrument master (CSV). */
export async function fetchNseEquityTokens(c: KiteCredentials, fetchFn: Fetch = fetch): Promise<Map<string, number>> {
  const res = await fetchFn(`${API_ROOT}/instruments/NSE`, { headers: headers(c), signal: AbortSignal.timeout(30_000) });
  if (res.status === 403) throw new KiteAuthError("Kite rejected the session (expired or revoked). Run `pnpm kite:login`.");
  if (!res.ok) throw new Error(`Kite instrument list failed: HTTP ${res.status}`);
  let body = Buffer.from(await res.arrayBuffer());
  if (body[0] === 0x1f && body[1] === 0x8b) body = gunzipSync(body); // gzip without Content-Encoding
  return parseInstruments(body.toString("utf-8"));
}

export function parseInstruments(csv: string): Map<string, number> {
  const lines = csv.split(/\r?\n/).filter(Boolean);
  const head = splitCsv(lines[0] ?? "");
  const col = (name: string) => head.indexOf(name);
  const [iTok, iSym, iSeg, iType] = [col("instrument_token"), col("tradingsymbol"), col("segment"), col("instrument_type")];
  if ([iTok, iSym, iSeg, iType].some((i) => i < 0)) throw new Error("Kite instrument list: unexpected columns");
  const out = new Map<string, number>();
  for (const line of lines.slice(1)) {
    const f = splitCsv(line);
    if (f[iSeg] !== "NSE" || f[iType] !== "EQ") continue;
    const token = Number(f[iTok]);
    if (Number.isInteger(token) && token > 0 && f[iSym]) out.set(f[iSym]!, token);
  }
  return out;
}

/** Minimal RFC 4180 field splitter (company names may be quoted and contain commas). */
function splitCsv(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!;
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}
