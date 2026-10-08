import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { buildApp } from "../../api/src/app";
import { FixtureRepo, GOLDEN } from "../../api/test/fixture-repo";
import { createServer, INSTRUCTIONS } from "../src/create-server";

let api: Awaited<ReturnType<typeof buildApp>>;
let client: Client;

beforeAll(async () => {
  api = await buildApp({ repo: new FixtureRepo() });
  const url = await api.listen({ port: 0, host: "127.0.0.1" });
  const server = createServer(url);
  const [clientT, serverT] = InMemoryTransport.createLinkedPair();
  await server.connect(serverT);
  client = new Client({ name: "test", version: "0" });
  await client.connect(clientT);
});

afterAll(async () => {
  await client?.close();
  await api?.close();
});

type Payload = { data_provenance: string; notice: string; as_of: string; data: any };
async function call(name: string, args: Record<string, unknown> = {}) {
  const res = await client.callTool({ name, arguments: args });
  const text = (res.content as { type: string; text: string }[])[0]!.text;
  return { isError: Boolean(res.isError), text, payload: res.isError ? null : (JSON.parse(text) as Payload) };
}

describe("tool catalogue", () => {
  it("exposes the planned read-only tools", async () => {
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual(
      [
        "compare_stocks",
        "get_latest_news",
        "get_market_regime",
        "get_ranking_history",
        "get_score_history",
        "get_sector_strength",
        "get_stock_fundamentals",
        "get_stock_risks",
        "get_stock_score",
        "get_stock_technicals",
        "get_top_opportunities",
        "search_stocks",
      ].sort(),
    );
    for (const t of tools) {
      expect(t.annotations?.readOnlyHint, t.name).toBe(true);
      expect(t.annotations?.destructiveHint, t.name).toBe(false);
      expect(t.description!.length, t.name).toBeGreaterThan(40);
    }
  });

  it("ships grounding instructions", () => {
    expect(client.getInstructions()).toBe(INSTRUCTIONS);
    expect(INSTRUCTIONS).toMatch(/Data unavailable/);
  });
});

describe("pass-through fidelity", () => {
  it("get_stock_score returns the engine's score unchanged, with MOCK provenance and disclaimer", async () => {
    const { payload } = await call("get_stock_score", { symbol: "hdfcbank" });
    const golden = GOLDEN.find((g) => g.symbol === "HDFCBANK")!;
    const { technicals: _t, ...expected } = golden;
    expect(payload!.data.score).toEqual(expected);
    expect(payload!.data_provenance).toBe("MOCK");
    expect(payload!.notice).toMatch(/MOCK DATA/);
    expect(payload!.notice).toMatch(/not investment advice/);
  });

  it("focused tools select fields without altering them", async () => {
    const golden = GOLDEN.find((g) => g.symbol === "RELIANCE")!;
    const tech = await call("get_stock_technicals", { symbol: "RELIANCE" });
    expect(tech.payload!.data.technicals).toEqual(golden.technicals);
    const risk = await call("get_stock_risks", { symbol: "RELIANCE" });
    expect(risk.payload!.data).toMatchObject({ risk_level: golden.risk_level, risk_flags: golden.risk_flags });
    const fund = await call("get_stock_fundamentals", { symbol: "RELIANCE" });
    expect(fund.payload!.data.fundamentals).toBeNull(); // fixture has none: stays null, never invented
    expect(fund.payload!.data.scored_components.valuation).toEqual(golden.components.valuation);
  });

  it("market, sector, ranking, opportunity, history, news and search tools return API data", async () => {
    const regime = await call("get_market_regime");
    expect(regime.payload!.data.regime.confidence).toBeLessThan(100);
    expect(regime.payload!.data.indices[0]).not.toHaveProperty("sparkline");
    expect((await call("get_sector_strength")).payload!.data.length).toBeGreaterThan(5);
    expect((await call("get_ranking_history", { top: 2 })).payload!.data[0].rows).toHaveLength(2);
    const opp = await call("get_top_opportunities", { limit: 2, max_risk: "LOW" });
    expect(opp.payload!.data.every((r: { risk_level: string }) => r.risk_level === "LOW")).toBe(true);
    expect((await call("get_score_history", { symbol: "ICICIBANK" })).payload!.data).toHaveLength(1);
    expect((await call("get_latest_news")).payload!.data).toEqual([]);
    expect((await call("search_stocks", { query: "hdfc" })).payload!.data[0].symbol).toBe("HDFCBANK");
  });

  it("compare_stocks reports unknown symbols instead of guessing", async () => {
    const { payload } = await call("compare_stocks", { symbols: ["HDFCBANK", "ICICIBANK", "NOPE"] });
    expect(payload!.data.stocks.map((s: { symbol: string }) => s.symbol)).toEqual(["HDFCBANK", "ICICIBANK"]);
    expect(payload!.data.not_found).toEqual(["NOPE"]);
  });
});

describe("errors", () => {
  it("unknown symbols yield 'Data unavailable', not fabricated data", async () => {
    const r = await call("get_stock_score", { symbol: "NOPE" });
    expect(r.isError).toBe(true);
    expect(r.text).toMatch(/^Data unavailable/);
  });

  it("rejects malformed input before calling the API", async () => {
    const r = await client.callTool({ name: "get_stock_score", arguments: { symbol: "DROP TABLE;" } });
    expect(r.isError).toBe(true);
  });

  it("reports an unreachable API clearly", async () => {
    const server = createServer("http://127.0.0.1:1");
    const [c, s] = InMemoryTransport.createLinkedPair();
    await server.connect(s);
    const other = new Client({ name: "t", version: "0" });
    await other.connect(c);
    const res = await other.callTool({ name: "get_market_regime", arguments: {} });
    expect(res.isError).toBe(true);
    expect((res.content as { text: string }[])[0]!.text).toMatch(/not reachable/);
    await other.close();
  });
});
