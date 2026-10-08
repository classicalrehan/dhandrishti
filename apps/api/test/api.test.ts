import { afterAll, beforeEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildApp } from "../src/app";
import { FixtureRepo, GOLDEN } from "./fixture-repo";

let repo: FixtureRepo;
let app: FastifyInstance;
const NOW = () => new Date("2026-10-06T04:00:00Z");

beforeEach(async () => {
  repo = new FixtureRepo();
  app = await buildApp({ repo, now: NOW });
});
afterAll(async () => app?.close());

const get = async (url: string) => {
  const res = await app.inject({ method: "GET", url });
  return { status: res.statusCode, body: res.json() };
};

describe("meta & provenance", () => {
  it("labels every response with the run's provenance, as-of date and config version", async () => {
    const { status, body } = await get("/v1/opportunities");
    expect(status).toBe(200);
    expect(body.meta).toEqual({
      as_of: "2026-10-05",
      data_provenance: "MOCK",
      config_version: GOLDEN[0]!.config_version,
      generated_at: "2026-10-06T04:00:00.000Z",
    });
  });

  it("returns 503 NO_DATA before the first scoring run", async () => {
    repo.run = null;
    const { status, body } = await get("/v1/market/overview");
    expect(status).toBe(503);
    expect(body.error.code).toBe("NO_DATA");
  });
});

describe("GET /v1/market/overview", () => {
  it("passes engine output through and builds index quotes", async () => {
    const { status, body } = await get("/v1/market/overview");
    expect(status).toBe(200);
    const d = body.data;
    expect(d.indices.map((i: { code: string }) => i.code)).toEqual(["NIFTY 50", "NIFTY BANK", "INDIA VIX"]);
    expect(d.indices[0].sparkline).toHaveLength(30);
    expect(d.top_opportunities.map((o: { rank: number }) => o.rank)).toEqual(
      [...GOLDEN].map((g) => g.rank).sort((a, b) => a - b),
    );
    const hdfc = GOLDEN.find((g) => g.symbol === "HDFCBANK")!;
    const row = d.top_opportunities.find((o: { symbol: string }) => o.symbol === "HDFCBANK");
    expect(row.total_score).toBe(hdfc.total_score); // never recomputed
    expect(row.key_reason).toBe(hdfc.key_reason);
    expect(d.regime.confidence).toBeLessThan(100);
  });
});

describe("GET /v1/opportunities", () => {
  it("filters by risk and sector without re-ranking", async () => {
    const low = await get("/v1/opportunities?max_risk=LOW");
    expect(low.body.data.every((r: { risk_level: string }) => r.risk_level === "LOW")).toBe(true);
    const banks = await get("/v1/opportunities?sector=Banking");
    expect(banks.body.data.map((r: { symbol: string }) => r.symbol).sort()).toEqual(["HDFCBANK", "ICICIBANK"]);
  });

  it("rejects invalid query parameters", async () => {
    expect((await get("/v1/opportunities?limit=0")).status).toBe(400);
    expect((await get("/v1/opportunities?max_risk=TINY")).status).toBe(400);
  });
});

describe("GET /v1/stocks/:symbol", () => {
  it("returns the full engine explanation", async () => {
    const { status, body } = await get("/v1/stocks/RELIANCE");
    expect(status).toBe(200);
    expect(body.data.score).toEqual(GOLDEN.find((g) => g.symbol === "RELIANCE"));
    expect(body.data.fundamentals).toBeNull(); // missing stays null — never invented
  });

  it("404s for unknown symbols and 400s for malformed ones", async () => {
    expect((await get("/v1/stocks/NOPE")).status).toBe(404);
    expect((await get("/v1/stocks/hdfcbank")).status).toBe(400);
  });
});

describe("GET /v1/stocks/:symbol/prices", () => {
  it("slices history by range", async () => {
    const m1 = await get("/v1/stocks/HDFCBANK/prices?range=1M");
    const y1 = await get("/v1/stocks/HDFCBANK/prices?range=1Y");
    expect(m1.status).toBe(200);
    expect(m1.body.data.bars.length).toBeGreaterThan(15);
    expect(m1.body.data.bars.length).toBeLessThan(25);
    expect(y1.body.data.bars.length).toBeGreaterThan(240);
    expect(m1.body.data.bars.at(-1).date).toBe("2026-10-05");
  });
});

describe("contract enforcement", () => {
  it("refuses to serve engine output that violates the contract", async () => {
    repo.scoresOverride = [{ ...GOLDEN[0]!, confidence: "CERTAIN" as never }];
    const { status, body } = await get(`/v1/stocks/${GOLDEN[0]!.symbol}`);
    expect(status).toBe(500);
    expect(body.error.code).toBe("CONTRACT_VIOLATION");
  });
});

describe("GET /health", () => {
  it("reports database reachability", async () => {
    expect((await get("/health")).body).toMatchObject({ status: "ok", database: "ok", cache: { status: "disabled" } });
    repo.pingFails = true;
    expect((await get("/health")).status).toBe(503);
  });
});

describe("GET /v1/compare", () => {
  it("returns engine output side by side and reports unknown symbols", async () => {
    const { status, body } = await get("/v1/compare?symbols=hdfcbank,RELIANCE,NOPE");
    expect(status).toBe(200);
    expect(body.data.stocks.map((s: { symbol: string }) => s.symbol)).toEqual(["HDFCBANK", "RELIANCE"]);
    expect(body.data.not_found).toEqual(["NOPE"]);
    const hdfc = GOLDEN.find((g) => g.symbol === "HDFCBANK")!;
    expect(body.data.stocks[0].components.valuation.score).toBe(hdfc.components.valuation.score);
  });

  it("needs 2 to 5 distinct symbols", async () => {
    expect((await get("/v1/compare?symbols=HDFCBANK")).status).toBe(400);
    expect((await get("/v1/compare?symbols=HDFCBANK,hdfcbank")).status).toBe(400);
    expect((await get("/v1/compare?symbols=A,B,C,D,E,F")).status).toBe(400);
  });
});

describe("history and news endpoints", () => {
  it("serves score history, ranking history and (empty) news", async () => {
    const h = await get("/v1/stocks/HDFCBANK/score-history?limit=10");
    expect(h.status).toBe(200);
    expect(h.body.data[0]).toMatchObject({ as_of: "2026-10-05", confidence: expect.any(String) });
    expect((await get("/v1/stocks/NOPE/score-history")).status).toBe(404);
    const r = await get("/v1/rankings/history?days=5&top=2");
    expect(r.body.data[0].rows).toHaveLength(2);
    const n = await get("/v1/news?symbol=HDFCBANK");
    expect(n.status).toBe(200);
    expect(n.body.data).toEqual([]);
  });
});

describe("unknown routes", () => {
  it("return a distinct ROUTE_NOT_FOUND error", async () => {
    const { status, body } = await get("/v1/nope");
    expect(status).toBe(404);
    expect(body.error.code).toBe("ROUTE_NOT_FOUND");
  });
});

describe("backtests", () => {
  it("lists runs and serves a run's full detail within the contract", async () => {
    const list = await get("/v1/backtests");
    expect(list.status).toBe(200);
    expect(list.body.data[0]).toMatchObject({ id: 1, status: "SUCCEEDED", provenance: "MOCK" });
    const one = await get("/v1/backtests/1");
    expect(one.status).toBe(200);
    expect(one.body.meta.data_provenance).toBe("MOCK");
    expect(one.body.meta.as_of).toBe(one.body.data.metrics.period.end);
    expect(one.body.data.equity.length).toBeGreaterThan(50);
    expect(one.body.data.latest_holdings.every((h: { execution: string }) => h.execution === one.body.data.latest_holdings[0].execution)).toBe(true);
  });

  it("404s unknown runs and 400s bad ids", async () => {
    expect((await get("/v1/backtests/99")).status).toBe(404);
    expect((await get("/v1/backtests/abc")).status).toBe(400);
  });
});

describe("paper trading", () => {
  it("lists portfolios and serves one within the contract", async () => {
    const list = await get("/v1/paper");
    expect(list.status).toBe(200);
    expect(list.body.data[0]).toMatchObject({ id: 1, status: "ACTIVE", provenance: "EOD" });
    const one = await get("/v1/paper/1");
    expect(one.status).toBe(200);
    expect(one.body.meta).toMatchObject({ as_of: "2026-10-08", data_provenance: "EOD" });
    expect(one.body.data.positions[0].symbol).toBe("HDFCBANK");
    expect((await get("/v1/paper/2")).status).toBe(404);
  });
});

describe("real holdings", () => {
  const item = (symbol: string, qty: number, avg: number, last: number, close: number | null = null) => ({
    kind: "HOLDING" as const, symbol, exchange: "NSE", product: "CNC", qty, t1_qty: 0,
    avg_price: avg, last_price: last, close_price: close, pnl: qty * (last - avg),
  });

  it("returns 404 with instructions before the first fetch", async () => {
    const { status, body } = await get("/v1/holdings");
    expect(status).toBe(404);
    expect(body.error.message).toMatch(/pnpm holdings/);
  });

  it("joins holdings with scores and flags what deserves a look", async () => {
    const ranked = [...GOLDEN].sort((a, b) => a.rank - b.rank);
    const top = ranked[0]!;
    const bottom = ranked.at(-1)!;
    repo.holdingsSnapshot = {
      as_of: "2026-10-07",
      fetched_at: "2026-10-07T11:30:00.000Z",
      items: [
        item(top.symbol, 10, 100, 120, 118),
        item(bottom.symbol, 100, 100, 85, 86),
        item("GOLDBEES", 10, 60, 62),
        { ...item("NIFTY26OCT25000PE", 75, 80, 95), kind: "POSITION" as const, exchange: "NFO", product: "NRML" },
      ],
      history: [
        { date: "2026-10-01", value: 9000, invested: 9000, twr_index: 100, nifty_close: 25000 },
        { date: "2026-10-07", value: 10320, invested: 11600, twr_index: 103, nifty_close: 25250 },
      ],
    };
    const { status, body } = await get("/v1/holdings");
    expect(status).toBe(200);
    const d = body.data;
    expect(d.value).toBe(1200 + 8500 + 620);
    expect(d.invested).toBe(1000 + 10000 + 600);
    expect(d.return_pct).toBeCloseTo(3);
    expect(d.nifty_return_pct).toBeCloseTo(1);
    expect(d.day_change).toBeCloseTo(10 * 2 + 100 * -1);
    expect(d.positions).toHaveLength(1);
    const bySym = Object.fromEntries(d.holdings.map((h: { symbol: string }) => [h.symbol, h]));
    expect(bySym[top.symbol].score).toMatchObject({ rank: top.rank, of: bottom.rank });
    expect(bySym.GOLDBEES.score).toBeNull();
    expect(bySym[bottom.symbol].watch.join(" ")).toMatch(/bottom third/);
    expect(bySym[bottom.symbol].watch.join(" ")).toMatch(/Down 15\.0%/);
    expect(bySym[bottom.symbol].watch.join(" ")).toMatch(/82% of your portfolio/);
    expect(body.meta.as_of).toBe("2026-10-07");
  });
});

describe("outdated database schema", () => {
  it("explains how to migrate instead of a bare 500", async () => {
    const repo = new FixtureRepo();
    repo.paperPortfolios = async () => {
      throw Object.assign(new Error('relation "paper_portfolios" does not exist'), { code: "42P01" });
    };
    const app2 = await buildApp({ repo });
    const res = await app2.inject({ method: "GET", url: "/v1/paper" });
    expect(res.statusCode).toBe(503);
    expect(res.json().error).toMatchObject({ code: "SCHEMA_OUTDATED", message: expect.stringMatching(/db:migrate/) });
    await app2.close();
  });
});
