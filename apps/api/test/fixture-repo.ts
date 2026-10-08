/** In-memory MarketRepository backed by the quant-spec golden fixtures (MOCK data). */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { StockScore } from "@dd/contracts";
import type {
  HoldingsSnapshot,
  IndexBar,
  MarketRepository,
  PriceRow,
  RunContext,
} from "../src/repositories/market-repository";

const FIX = fileURLToPath(new URL("../../../packages/quant-spec/fixtures/", import.meta.url));
const read = (p: string) => JSON.parse(readFileSync(FIX + p, "utf8"));

export const GOLDEN = ["hdfcbank", "icicibank", "reliance"].map((s) => read(`expected/${s}.json`)) as StockScore[];
const market = read("expected/market.json");
const inputs = read("inputs/universe-2026-10-05.json");
/** A small paper portfolio in the API's response shape. */
export const PAPER = {
  portfolio: {
    id: 1, name: "Monthly top 5", status: "ACTIVE" as const, halt_reason: null, start_date: "2026-10-06",
    last_processed: "2026-10-08", provenance: "EOD" as const,
    params: { capital: 100000, top_n: 5, rebalance: "monthly" as const, max_risk: "MEDIUM" as const, min_confidence: null,
      stop_loss_pct: 10, rank_buffer: 10, kill_switch_pct: 18, lookback_bars: 300 },
    equity: 100850.5, cash: 1210.25, return_pct: 0.8505, nifty_return_pct: 0.42, drawdown_pct: -0.3,
    max_drawdown_pct: -0.6, positions: 1, charges_paid: 118.4,
  },
  positions: [{ symbol: "HDFCBANK", name: "HDFC Bank", qty: 50, avg_price: 1980, last_close: 1992.8, value: 99640,
    pnl: 640, pnl_pct: 0.6465, weight_pct: 98.8, entry_date: "2026-10-07" }],
  orders: [{ id: 1, created_on: "2026-10-06", side: "BUY" as const, symbol: "HDFCBANK", qty: 50,
    reason: "INITIAL" as const, status: "FILLED" as const, fill_date: "2026-10-07", fill_price: 1980, charges: 118.4,
    note: "rank 1" }],
  daily: [
    { date: "2026-10-06", equity: 100000, cash: 100000, drawdown_pct: 0, nifty_close: 24000, events: [] },
    { date: "2026-10-07", equity: 100300, cash: 1210.25, drawdown_pct: 0, nifty_close: 24050, events: [] },
    { date: "2026-10-08", equity: 100850.5, cash: 1210.25, drawdown_pct: -0.3, nifty_close: 24100.8, events: [] },
  ],
};

/** A real engine result (apps/worker backtest), so contract tests exercise the true shape. */
export const BACKTEST = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/backtest-sample.json", import.meta.url)), "utf8"),
);

type Cols = { open: number[]; high: number[]; low: number[]; close: number[]; volume: number[] };

export class FixtureRepo implements MarketRepository {
  run: RunContext | null = { run_id: 1, as_of: "2026-10-05", config_version: GOLDEN[0]!.config_version, provenance: "MOCK" };
  scoresOverride: StockScore[] | null = null;
  pingFails = false;
  holdingsSnapshot: HoldingsSnapshot | null = null;

  async holdings() {
    return this.holdingsSnapshot;
  }

  async ping() {
    if (this.pingFails) throw new Error("db down");
  }
  calls: Record<string, number> = {};
  private count(name: string) {
    this.calls[name] = (this.calls[name] ?? 0) + 1;
  }
  async latestRun() {
    this.count("latestRun");
    return this.run;
  }
  async scores() {
    this.count("scores");
    return this.scoresOverride ?? [...GOLDEN].sort((a, b) => a.rank - b.rank);
  }
  async score(_ctx: RunContext, symbol: string) {
    return (await this.scores()).find((s) => s.symbol === symbol) ?? null;
  }
  async scoreHistory(symbol: string) {
    const s = GOLDEN.find((g) => g.symbol === symbol);
    return s ? [{ as_of: s.as_of, total_score: s.total_score, rank: s.rank, confidence: s.confidence, risk_level: s.risk_level }] : [];
  }
  async rankingHistory(_cv: string, _days: number, top: number) {
    const rows = [...GOLDEN].sort((a, b) => a.rank - b.rank).slice(0, top);
    return [{ as_of: "2026-10-05", rows: rows.map((s) => ({ rank: s.rank, symbol: s.symbol, total_score: s.total_score })) }];
  }
  async news() {
    return [];
  }
  async paperPortfolios() {
    return [PAPER.portfolio];
  }
  async paperPortfolio(id: number) {
    return id === 1 ? PAPER : null;
  }
  async backtestRuns() {
    const b = BACKTEST;
    return [{
      id: 1, name: "fixture", status: "SUCCEEDED" as const, started_at: "2026-10-06T10:00:00.000Z",
      finished_at: "2026-10-06T10:00:20.000Z", config_version: b.config_version, provenance: "MOCK" as const,
      params: b.params, error: null,
      headline: {
        cagr_pct: b.metrics.strategy.cagr_pct, nifty_cagr_pct: b.metrics.nifty.cagr_pct,
        universe_cagr_pct: b.metrics.universe_ew.cagr_pct, max_drawdown_pct: b.metrics.strategy.max_drawdown_pct,
        sharpe: b.metrics.strategy.sharpe, rebalances: b.metrics.period.rebalances,
      },
    }];
  }
  async backtest(id: number) {
    if (id !== 1) return null;
    const last = BACKTEST.holdings.at(-1)!.execution;
    return {
      run: (await this.backtestRuns())[0]!,
      metrics: BACKTEST.metrics,
      periods: BACKTEST.periods,
      equity: BACKTEST.equity,
      latest_holdings: BACKTEST.holdings.filter((h: { execution: string }) => h.execution === last),
    };
  }
  async sectors() {
    return market.sectors;
  }
  async regime() {
    return { regime: market.regime, breadth: market.breadth };
  }
  async indexBars(codes: string[], _asOf: string, perIndex: number): Promise<IndexBar[]> {
    const dates: string[] = inputs.dates;
    return codes.flatMap((code) => {
      const c: Cols = inputs.indices[code];
      return dates.slice(-perIndex).map((date, j) => {
        const i = dates.length - perIndex + j;
        return { code, date, open: c.open[i]!, high: c.high[i]!, low: c.low[i]!, close: c.close[i]! };
      });
    });
  }
  async security(symbol: string) {
    const s = inputs.stocks.find((x: { security: { symbol: string } }) => x.security.symbol === symbol);
    if (!s) return null;
    const { name, exchange, sector, industry, is_financial } = s.security;
    return { symbol, name, exchange, sector, industry, is_financial };
  }
  async search(q: string) {
    return inputs.stocks
      .map((s: { security: { symbol: string; name: string; sector: string } }) => s.security)
      .filter((s: { symbol: string }) => s.symbol.startsWith(q.toUpperCase()))
      .map(({ symbol, name, sector }: { symbol: string; name: string; sector: string }) => ({ symbol, name, sector }));
  }
  async fundamentals() {
    return null;
  }
  async events() {
    return [];
  }
  async prices(symbol: string, _asOf: string, from: string | null): Promise<PriceRow[]> {
    const s = inputs.stocks.find((x: { security: { symbol: string } }) => x.security.symbol === symbol);
    if (!s) return [];
    const b: Cols = s.bars;
    return (inputs.dates as string[])
      .map((date, i) => ({
        date,
        open: b.open[i]!,
        high: b.high[i]!,
        low: b.low[i]!,
        close: b.close[i]!,
        volume: b.volume[i]!,
        sma20: null,
        sma50: null,
        sma200: null,
        rsi14: null,
        macd: null,
        macd_signal: null,
        macd_hist: null,
      }))
      .filter((r) => from == null || r.date >= from);
  }
}
