import { describe, expect, it } from "vitest";
import { RESEARCH_API_TOOLS, RESEARCH_MODEL, runResearchTurn, ChatRequest, type ResearchEvent } from "./assistant";
import { RESEARCH_TOOLS, runTool } from "./catalogue";
import { checkGrounding } from "./grounding";
import { FixturePort, GOLDEN, scriptedClient } from "./test-helpers";

const HDFC = GOLDEN.find((g) => g.symbol === "HDFCBANK")!;

describe("grounding check", () => {
  const data = [{ total_score: 77.29, rank: 9, technicals: { close: 7006.56, ret_1m: -4.9952 }, pct: 0.7727 }];

  it("verifies numbers present in tool data at the shown precision", () => {
    const r = checkGrounding("HDFC Bank scores 77.29 (77.3, ~77) at ₹7,006.56; 1M return -5.0%; 77% above 50 DMA. Rank #9.", data);
    expect(r.unverified).toEqual([]);
    expect(r.checked).toBe(6);
  });

  it("flags invented or derived numbers", () => {
    const r = checkGrounding("A fair value of ₹8,250 implies 17.7% upside.", data);
    expect(r.unverified).toEqual(["8,250", "17.7"]);
  });

  it("ignores indicator and period names", () => {
    const r = checkGrounding("Above its 50 DMA and 200-day average; RSI(14) and MACD(12,26,9); near the 52-week high; 3M and 1Y returns vs NIFTY 50.", data);
    expect(r.checked).toBe(0);
  });

  it("ignores dates, model versions and small counts", () => {
    const r = checkGrounding("As of 2026-10-05 (05 Oct 2026, model 2026.10-v1), the top 5 stocks in 3 sectors.", data);
    expect(r.checked).toBe(0);
  });

  it("notes when numbers appear without any tool data", () => {
    expect(checkGrounding("Score 81.2", []).noToolData).toBe(true);
  });
});

describe("tool catalogue", () => {
  it("generates a valid JSON schema with descriptions for every tool", () => {
    expect(RESEARCH_API_TOOLS).toHaveLength(RESEARCH_TOOLS.length);
    for (const t of RESEARCH_API_TOOLS) {
      expect(t.input_schema.type).toBe("object");
      expect(t.description.length).toBeGreaterThan(40);
    }
    const score = RESEARCH_API_TOOLS.find((t) => t.name === "get_stock_score")!;
    expect(score.input_schema.required).toEqual(["symbol"]);
  });

  it("validates arguments before touching the port", async () => {
    const port = new FixturePort();
    expect(await runTool(port, "nope", {})).toMatchObject({ ok: false, message: expect.stringMatching(/unknown tool/) });
    expect((await runTool(port, "get_stock_score", { symbol: "x; DROP TABLE" })).ok).toBe(false);
    expect((await runTool(port, "get_stock_score", { symbol: "HDFCBANK", sql: "select 1" })).ok).toBe(false);
    expect(port.calls).toEqual([]);
  });

  it("passes engine output through and reports missing data honestly", async () => {
    const port = new FixturePort();
    const r = await runTool(port, "get_stock_score", { symbol: "hdfcbank" });
    expect(r.ok && (r.payload.data as any).score.total_score).toBe(HDFC.total_score);
    expect(r.ok && r.payload.notice).toMatch(/MOCK DATA/);
    expect(await runTool(port, "get_stock_score", { symbol: "NOPE" })).toEqual({ ok: false, message: "Data unavailable: No score for NOPE" });
  });
});

describe("chat request validation", () => {
  it("accepts alternating text turns ending with the user", () => {
    expect(ChatRequest.safeParse({ messages: [{ role: "user", content: "hi" }] }).success).toBe(true);
  });
  it("rejects bad shapes", () => {
    expect(ChatRequest.safeParse({ messages: [{ role: "assistant", content: "x" }] }).success).toBe(false);
    expect(ChatRequest.safeParse({ messages: [] }).success).toBe(false);
    expect(ChatRequest.safeParse({ messages: [{ role: "user", content: "a" }, { role: "user", content: "b" }] }).success).toBe(false);
    // Clients cannot inject tool results or system text: content must be a plain string.
    expect(ChatRequest.safeParse({ messages: [{ role: "user", content: [{ type: "tool_result" }] }] }).success).toBe(false);
  });
});

describe("research turn loop", () => {
  const ask = [{ role: "user" as const, content: "Why is HDFC Bank ranked where it is?" }];

  it("calls tools, appends history append-only, streams text and grounds the answer", async () => {
    const { client, requests } = scriptedClient([
      { text: ["Let me check. "], toolUses: [{ id: "t1", name: "get_stock_score", input: { symbol: "HDFCBANK" } }] },
      { text: [`HDFC Bank scores ${HDFC.total_score} and ranks #${HDFC.rank}. `, "A target of ₹9,999 is plausible."] },
    ]);
    const events: ResearchEvent[] = [];
    await runResearchTurn({ client, port: new FixturePort(), messages: ask, onEvent: (e) => events.push(e) });

    expect(requests).toHaveLength(2);
    expect(requests[0].model).toBe(RESEARCH_MODEL);
    expect(requests[0].fallbacks).toBe("default");
    expect(requests[0].betas).toEqual(["server-side-fallback-2026-07-01"]);
    // Second request = first request's messages + assistant turn as received + tool results.
    const second = requests[1].messages;
    expect(second.slice(0, 1)).toEqual(requests[0].messages);
    expect(second[1].role).toBe("assistant");
    expect(second[1].content.map((b: any) => b.type)).toEqual(["text", "tool_use"]);
    expect(second[2].content[0]).toMatchObject({ type: "tool_result", tool_use_id: "t1" });
    expect(JSON.parse(second[2].content[0].content).data.score.total_score).toBe(HDFC.total_score);
    // System prompt and tools identical across rounds (prompt cache + preserved thinking).
    expect(requests[1].system).toEqual(requests[0].system);
    expect(requests[1].tools).toEqual(requests[0].tools);

    const done = events.find((e) => e.type === "done") as Extract<ResearchEvent, { type: "done" }>;
    expect(done.grounding.unverified).toEqual(["9,999"]);
    expect(done.data_provenance).toBe("MOCK");
    expect(done.as_of).toBe("2026-10-05");
    expect(events.filter((e) => e.type === "tool_call")).toHaveLength(1);
    expect(events.filter((e) => e.type === "text").map((e: any) => e.delta).join("")).toMatch(/^Let me check\. \n\nHDFC Bank scores/);
  });

  it("returns tool errors to the model as errors, not data", async () => {
    const { client, requests } = scriptedClient([
      { toolUses: [{ id: "t1", name: "get_stock_score", input: { symbol: "NOPE" } }] },
      { text: ["Data unavailable for NOPE."] },
    ]);
    await runResearchTurn({ client, port: new FixturePort(), messages: ask, onEvent: () => {} });
    expect(requests[1].messages[2].content[0]).toMatchObject({ is_error: true, content: "Data unavailable: No score for NOPE" });
  });

  it("surfaces a refusal as an error event", async () => {
    const { client } = scriptedClient([{ stop_reason: "refusal" }]);
    const events: ResearchEvent[] = [];
    await runResearchTurn({ client, port: new FixturePort(), messages: ask, onEvent: (e) => events.push(e) });
    expect(events.at(-1)).toMatchObject({ type: "error", code: "DECLINED" });
  });

  it("reports when a server-side fallback model answered", async () => {
    const { client } = scriptedClient([{ text: ["Hello."], fallback: true }]);
    const events: ResearchEvent[] = [];
    await runResearchTurn({ client, port: new FixturePort(), messages: ask, onEvent: (e) => events.push(e) });
    expect(events.at(-1)).toMatchObject({ type: "done", fallback_used: true, model: "claude-opus-4-8" });
  });

  it("stops after the tool-round budget", async () => {
    const loop = { toolUses: [{ id: "t", name: "get_sector_strength", input: {} }] };
    const { client } = scriptedClient([loop, loop, loop]);
    const events: ResearchEvent[] = [];
    await runResearchTurn({ client, port: new FixturePort(), messages: ask, onEvent: (e) => events.push(e), maxToolRounds: 2 });
    expect(events.at(-1)).toMatchObject({ type: "error", code: "TOOL_BUDGET" });
  });
});

describe("personal data stays out of the model's reach", () => {
  it("offers no tool that reads real holdings or positions", () => {
    for (const t of RESEARCH_TOOLS) {
      expect(`${t.name} ${t.description}`).not.toMatch(/\bholdings?\b|portfolio|\bpositions?\b/i);
    }
  });
});
