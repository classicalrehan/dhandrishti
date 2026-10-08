/** Test doubles: a ResearchPort over golden fixtures and a scripted Claude client. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Meta, StockScore } from "@dd/contracts";
import type { PortResult, ResearchPort } from "./port";

const FIX = fileURLToPath(new URL("../../quant-spec/fixtures/expected/", import.meta.url));
export const GOLDEN: StockScore[] = ["hdfcbank", "icicibank", "reliance"].map((s) =>
  JSON.parse(readFileSync(`${FIX}${s}.json`, "utf8")),
);
export const META: Meta = { as_of: "2026-10-05", data_provenance: "MOCK", config_version: "2026.10-v1", generated_at: "x" };

const ok = <T>(data: T): PortResult<T> => ({ ok: true, data, meta: META });
const missing = (m: string) => ({ ok: false as const, code: "NOT_FOUND", message: m });

export class FixturePort implements ResearchPort {
  calls: string[] = [];
  async stock(symbol: string) {
    this.calls.push(`stock:${symbol}`);
    const s = GOLDEN.find((g) => g.symbol === symbol);
    if (!s) return missing(`No score for ${symbol}`);
    return ok({
      security: { symbol, name: s.name, exchange: "NSE", sector: s.sector, industry: null, is_financial: s.sector === "Banking" },
      score: s,
      fundamentals: null,
      upcoming_events: [],
      score_history: [],
    });
  }
  async scoreHistory() { return ok([]); }
  async rankingHistory() { return ok([]); }
  async opportunities() { return ok([]); }
  async sectors() { return ok([]); }
  async overview() { return missing("not in fixture"); }
  async news() { return ok([]); }
  async compare(symbols: string[]) {
    return ok({ stocks: [], not_found: symbols });
  }
  async search() { return ok([]); }
}

export interface ScriptedTurn {
  text?: string[];
  toolUses?: { id: string; name: string; input: unknown }[];
  stop_reason?: string;
  fallback?: boolean;
}

/** Minimal stand-in for client.beta.messages.stream(): replays scripted turns. */
export function scriptedClient(turns: ScriptedTurn[]) {
  const requests: any[] = [];
  let i = 0;
  const client = {
    beta: {
      messages: {
        stream(params: any) {
          requests.push(structuredClone(params));
          const turn = turns[i++];
          if (!turn) throw new Error("script exhausted");
          const handlers: ((d: string) => void)[] = [];
          return {
            on(event: string, cb: (d: string) => void) {
              if (event === "text") handlers.push(cb);
              return this;
            },
            async finalMessage() {
              for (const d of turn.text ?? []) handlers.forEach((h) => h(d));
              const content: any[] = [];
              if (turn.fallback) content.push({ type: "fallback", from: { model: "claude-opus-5-5" }, to: { model: "claude-opus-4-8" } });
              if (turn.text?.length) content.push({ type: "text", text: turn.text.join("") });
              for (const t of turn.toolUses ?? []) content.push({ type: "tool_use", ...t });
              return {
                model: turn.fallback ? "claude-opus-4-8" : "claude-opus-5-5",
                content,
                stop_reason: turn.stop_reason ?? (turn.toolUses?.length ? "tool_use" : "end_turn"),
                usage: { input_tokens: 100, output_tokens: 20, cache_read_input_tokens: 80 },
              };
            },
          };
        },
      },
    },
  };
  return { client: client as any, requests };
}
