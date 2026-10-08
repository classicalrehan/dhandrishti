/**
 * Minimal client for the DhanDrishti HTTP API. The MCP server holds no database or
 * cache credentials: everything it knows comes through this read-only API.
 */
import type { PortResult } from "@dd/ai";
import type { Meta } from "@dd/contracts";

export type ApiResponse<T> = PortResult<T>;

export class DhanDrishtiApi {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly timeoutMs = 10_000,
  ) {}

  async get<T>(path: string, query: Record<string, string | number | undefined> = {}): Promise<ApiResponse<T>> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined) qs.set(k, String(v));
    const url = `${this.baseUrl}${path}${qs.size ? `?${qs}` : ""}`;
    let res: Response;
    try {
      res = await this.fetchImpl(url, { signal: AbortSignal.timeout(this.timeoutMs) });
    } catch {
      return { ok: false, code: "API_UNREACHABLE", message: `DhanDrishti API is not reachable at ${this.baseUrl}` };
    }
    const body = (await res.json().catch(() => null)) as
      | { data?: T; meta?: Meta; error?: { code: string; message: string } }
      | null;
    if (res.ok && body?.data !== undefined && body.meta) return { ok: true, data: body.data, meta: body.meta };
    return {
      ok: false,
      code: body?.error?.code ?? "API_ERROR",
      message: body?.error?.message ?? `API request failed with status ${res.status}`,
    };
  }
}
