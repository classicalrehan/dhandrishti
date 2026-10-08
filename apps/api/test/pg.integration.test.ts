/**
 * End-to-end: Python pipeline (migrate → ingest MOCK → score) into a throwaway database,
 * then the API reads it through PgMarketRepository.
 *
 *   DD_TEST_DATABASE_URL=postgresql://dhandrishti:dhandrishti_dev@localhost:5432/postgres pnpm test
 */
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildApp } from "../src/app";
import { PgMarketRepository } from "../src/repositories/pg-market-repository";

const ADMIN_URL = process.env.DD_TEST_DATABASE_URL;
const WORKER_DIR = fileURLToPath(new URL("../../worker/", import.meta.url));
const EXPECTED = fileURLToPath(new URL("../../../packages/quant-spec/fixtures/expected/", import.meta.url));

/** Swap the database name; works for TCP URLs and socket URLs like postgresql://u:@/db?host=/run/... */
function withDb(url: string, db: string): string {
  return url.replace(/^(postgres(?:ql)?:\/\/[^/]*\/)([^?]*)/, `$1${db}`);
}

describe.skipIf(!ADMIN_URL)("API on a real pipeline-populated database", () => {
  const db = `dd_api_test_${randomBytes(5).toString("hex")}`;
  let pool: pg.Pool;
  let app: FastifyInstance;

  beforeAll(async () => {
    const admin = new pg.Client({ connectionString: ADMIN_URL });
    await admin.connect();
    await admin.query(`CREATE DATABASE "${db}"`);
    await admin.end();
    const url = withDb(ADMIN_URL!, db);
    const env = { ...process.env, DD_DATABASE_URL: url };
    execFileSync("uv", ["run", "python", "-m", "dhandrishti.jobs.daily", "--as-of", "2026-10-05"], {
      cwd: WORKER_DIR, env, stdio: "pipe",
    });
    execFileSync("uv", ["run", "python", "-m", "dhandrishti.jobs.backtest", "--start", "2025-09-01",
      "--end", "2026-03-31", "--rebalance", "quarterly", "--top-n", "5", "--name", "integration"], {
      cwd: WORKER_DIR, env, stdio: "pipe",
    });
    execFileSync("uv", ["run", "python", "-m", "dhandrishti.jobs.paper", "create", "--name", "integration",
      "--top-n", "3"], { cwd: WORKER_DIR, env, stdio: "pipe" });
    pool = new pg.Pool({ connectionString: url });
    app = await buildApp({ repo: new PgMarketRepository(pool) });
  }, 180_000);

  afterAll(async () => {
    await app?.close();
    await pool?.end();
    const admin = new pg.Client({ connectionString: ADMIN_URL });
    await admin.connect();
    await admin.query(`DROP DATABASE IF EXISTS "${db}" WITH (FORCE)`);
    await admin.end();
  });

  const get = async (url: string) => {
    const res = await app.inject({ method: "GET", url });
    return { status: res.statusCode, body: res.json() };
  };

  it("serves the engine's golden output unchanged", async () => {
    const expected = JSON.parse(readFileSync(EXPECTED + "hdfcbank.json", "utf8"));
    const { status, body } = await get("/v1/stocks/HDFCBANK");
    expect(status).toBe(200);
    expect(body.meta.data_provenance).toBe("MOCK");
    expect(body.data.score).toEqual(expected);
    expect(body.data.fundamentals.provenance).toBe("MOCK");
  });

  it("overview, opportunities, sectors and risk all satisfy the contract", async () => {
    for (const url of ["/v1/market/overview", "/v1/opportunities?limit=200", "/v1/sectors", "/v1/risk",
                       "/v1/search?q=HDF", "/v1/scoring/config", "/v1/compare?symbols=HDFCBANK,ICICIBANK",
                       "/v1/stocks/HDFCBANK/score-history", "/v1/rankings/history", "/v1/news"]) {
      const { status } = await get(url);
      expect(status, url).toBe(200);
    }
    const opp = await get("/v1/opportunities?limit=200");
    expect(opp.body.data).toHaveLength(44);
    expect(opp.body.data.map((r: { rank: number }) => r.rank)).toEqual(Array.from({ length: 44 }, (_, i) => i + 1));
  });

  it("returns prices joined with worker-computed indicator series", async () => {
    const { body } = await get("/v1/stocks/HDFCBANK/prices?range=1Y");
    const last = body.data.bars.at(-1);
    expect(last.date).toBe("2026-10-05");
    expect(last.sma200).not.toBeNull();
    expect(last.rsi14).not.toBeNull();
  });

  it("serves a backtest the worker stored, within the contract", async () => {
    const list = await get("/v1/backtests");
    expect(list.status).toBe(200);
    const run = list.body.data.find((r: { name: string }) => r.name === "integration");
    expect(run).toMatchObject({ status: "SUCCEEDED", provenance: "MOCK" });
    const detail = await get(`/v1/backtests/${run.id}`);
    expect(detail.status).toBe(200);
    expect(detail.body.data.metrics.period.rebalances).toBe(2);
    expect(detail.body.data.latest_holdings).toHaveLength(5);
  });

  it("serves a paper portfolio created by the worker, within the contract", async () => {
    const list = await get("/v1/paper");
    expect(list.status).toBe(200);
    const p = list.body.data.find((x: { name: string }) => x.name === "integration");
    expect(p).toMatchObject({ status: "ACTIVE", provenance: "MOCK", equity: 100000 });
    const detail = await get(`/v1/paper/${p.id}`);
    expect(detail.status).toBe(200);
    expect(detail.body.data.orders).toHaveLength(3);
    expect(detail.body.data.orders.every((o: { status: string }) => o.status === "PENDING")).toBe(true);
  });
});
