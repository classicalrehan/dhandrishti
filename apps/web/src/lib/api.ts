/**
 * Server-side API client. Pages render exactly what the API returns; when the API
 * is unreachable or has no data, pages show that state — they never fall back to
 * bundled or invented numbers.
 */
import "server-only";
import type { Envelope } from "@dd/contracts";

const BASE = process.env.DD_API_URL ?? "http://127.0.0.1:4000";

export type ApiResult<T> =
  | { ok: true; data: T; meta: Envelope<T>["meta"] }
  | { ok: false; kind: "unavailable" | "no-data" | "not-found" | "error"; message: string };

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  } catch {
    return { ok: false, kind: "unavailable", message: `The DhanDrishti API is not reachable at ${BASE}.` };
  }
  const body = await res.json().catch(() => null);
  if (res.ok && body) return { ok: true, data: body.data as T, meta: body.meta };
  const message: string = body?.error?.message ?? `Request failed (${res.status})`;
  if (res.status === 503 && body?.error?.code === "NO_DATA") return { ok: false, kind: "no-data", message };
  if (res.status === 404) return { ok: false, kind: "not-found", message };
  return { ok: false, kind: "error", message };
}
