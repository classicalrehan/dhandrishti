/**
 * Single catalogue of DhanDrishti research tools, shared by the MCP server and the
 * Claude research assistant. Tools only select fields from engine output; they never
 * compute, adjust or invent values.
 */
import { z } from "zod";
import type { PortResult, ResearchPort } from "./port";

export const DISCLAIMER =
  "Scores are outputs of DhanDrishti's deterministic quantitative model, for research and decision support only. They are not investment advice or recommendations to buy or sell.";

export function provenanceNotice(provenance: string): string {
  return provenance === "MOCK"
    ? "MOCK DATA: synthetic values for development. Not real market information; do not present as real prices or fundamentals."
    : `Data provenance: ${provenance}.`;
}

export interface ToolPayload {
  as_of: string;
  data_provenance: string;
  model_version: string;
  notice: string;
  data: unknown;
}

export type ToolOutcome = { ok: true; payload: ToolPayload } | { ok: false; message: string };

/** Only genuinely missing data is "Data unavailable"; anything else is reported as an error. */
export function toOutcome<T>(res: PortResult<T>, select: (data: T) => unknown): ToolOutcome {
  if (!res.ok) {
    const prefix = res.code === "NOT_FOUND" || res.code === "NO_DATA" ? "Data unavailable" : "Error";
    return { ok: false, message: `${prefix}: ${res.message}` };
  }
  return {
    ok: true,
    payload: {
      as_of: res.meta.as_of,
      data_provenance: res.meta.data_provenance,
      model_version: res.meta.config_version,
      notice: `${provenanceNotice(res.meta.data_provenance)} ${DISCLAIMER}`,
      data: select(res.data),
    },
  };
}

export const symbolArg = z
  .string()
  .regex(/^[A-Za-z0-9&-]{1,20}$/)
  .transform((s) => s.toUpperCase())
  .describe("NSE trading symbol, e.g. HDFCBANK, RELIANCE, M&M");

const RISK = z.enum(["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]);
const CONFIDENCE = z.enum(["LOW", "MEDIUM", "HIGH"]);

export interface ResearchTool<S extends z.ZodRawShape = z.ZodRawShape> {
  name: string;
  title: string;
  description: string;
  input: S;
  run(port: ResearchPort, args: z.output<z.ZodObject<S>>): Promise<ToolOutcome>;
}

const tool = <S extends z.ZodRawShape>(t: ResearchTool<S>) => t as unknown as ResearchTool;

export const RESEARCH_TOOLS: ResearchTool[] = [
  tool({
    name: "get_stock_score",
    title: "Stock score and explanation",
    description:
      "DhanDrishti score (0-100) for one NSE stock with its full explanation: rank, confidence, risk level, the top positive and negative factors, and per-component points (fundamental quality, earnings growth, momentum, technical trend, valuation, liquidity, sector strength, risk). Quote the values as given; they come from the scoring engine and must not be adjusted.",
    input: { symbol: symbolArg },
    run: async (port, { symbol }) =>
      toOutcome(await port.stock(symbol), (d) => {
        const { technicals: _omit, ...score } = d.score;
        return { security: d.security, score };
      }),
  }),
  tool({
    name: "get_stock_fundamentals",
    title: "Stock fundamentals",
    description:
      "Latest fundamentals for one NSE stock (growth, ROE/ROCE, margins, leverage, cash-flow quality, valuation multiples, shareholding, quarterly EPS) plus how the engine scored fundamental quality, earnings growth and valuation. Null values mean the data is unavailable.",
    input: { symbol: symbolArg },
    run: async (port, { symbol }) =>
      toOutcome(await port.stock(symbol), (d) => ({
        security: d.security,
        fundamentals: d.fundamentals,
        scored_components: {
          fundamentals: d.score.components.fundamentals,
          earningsGrowth: d.score.components.earningsGrowth,
          valuation: d.score.components.valuation,
        },
      })),
  }),
  tool({
    name: "get_stock_technicals",
    title: "Stock technicals",
    description:
      "Technical snapshot for one NSE stock as computed by the engine: moving averages (20/50/100/200), RSI, MACD, ADX, ATR, Bollinger bands, 52-week range, returns (1D to 1Y), relative strength vs NIFTY 50, volatility, drawdown and trend classification, plus the momentum and technical-trend component scores.",
    input: { symbol: symbolArg },
    run: async (port, { symbol }) =>
      toOutcome(await port.stock(symbol), (d) => ({
        symbol: d.security.symbol,
        technicals: d.score.technicals,
        scored_components: { momentum: d.score.components.momentum, technicalTrend: d.score.components.technicalTrend },
      })),
  }),
  tool({
    name: "get_stock_risks",
    title: "Stock risk flags",
    description:
      "Risk assessment for one NSE stock: risk level (LOW, MEDIUM, HIGH, VERY_HIGH), penalty points, and every triggered flag (volatility, drawdown, liquidity, valuation, debt, earnings deterioration, promoter pledge, unusual volume, gap moves, overextension, upcoming events).",
    input: { symbol: symbolArg },
    run: async (port, { symbol }) =>
      toOutcome(await port.stock(symbol), (d) => ({
        symbol: d.security.symbol,
        risk_level: d.score.risk_level,
        risk_points: d.score.risk_points,
        risk_flags: d.score.risk_flags,
        upcoming_events: d.upcoming_events,
      })),
  }),
  tool({
    name: "get_score_history",
    title: "Score history",
    description: "How one stock's total score, rank, confidence and risk level have changed across scoring dates (oldest first).",
    input: { symbol: symbolArg, limit: z.number().int().min(1).max(365).default(60).describe("Number of most recent scoring dates") },
    run: async (port, { symbol, limit }) => toOutcome(await port.scoreHistory(symbol, limit), (d) => d),
  }),
  tool({
    name: "get_ranking_history",
    title: "Ranking history",
    description: "The top-ranked stocks on each recent scoring date (oldest first). Useful for seeing which names have stayed near the top.",
    input: {
      days: z.number().int().min(1).max(365).default(30).describe("Number of most recent scoring dates"),
      top: z.number().int().min(1).max(50).default(10).describe("Ranks to include per date"),
    },
    run: async (port, { days, top }) => toOutcome(await port.rankingHistory(days, top), (d) => d),
  }),
  tool({
    name: "get_top_opportunities",
    title: "Top opportunities",
    description:
      "Stocks currently ranked highest by the engine, with score, confidence, risk and the key reason. Optional filters only hide rows; they never re-rank.",
    input: {
      limit: z.number().int().min(1).max(50).default(10),
      sector: z.string().max(40).optional().describe("Exact sector name, e.g. Banking, IT, Pharma"),
      max_risk: RISK.optional(),
      min_confidence: CONFIDENCE.optional(),
    },
    run: async (port, q) => toOutcome(await port.opportunities(q), (d) => d),
  }),
  tool({
    name: "get_sector_strength",
    title: "Sector strength",
    description:
      "All sectors ranked by strength (0-100), with momentum and breadth labels, relative strength vs NIFTY 50, share of members above their 50 DMA, median profit growth, and member symbols.",
    input: {},
    run: async (port) => toOutcome(await port.sectors(), (d) => d),
  }),
  tool({
    name: "get_market_regime",
    title: "Market regime",
    description:
      "Current market regime (BULLISH, NEUTRAL, CAUTIOUS, BEARISH) with composite score, bounded confidence (never 100%), the six factor scores and the reason, plus market breadth and NIFTY 50 / BANK NIFTY / INDIA VIX levels.",
    input: {},
    run: async (port) =>
      toOutcome(await port.overview(), (d) => ({
        regime: d.regime,
        breadth: d.breadth,
        indices: d.indices.map(({ sparkline: _omit, ...q }) => q),
      })),
  }),
  tool({
    name: "get_latest_news",
    title: "Latest news",
    description:
      "Latest stored news items, optionally for one stock. Returns an empty list when no news provider is connected; never infer or invent headlines.",
    input: { symbol: symbolArg.optional(), limit: z.number().int().min(1).max(50).default(10) },
    run: async (port, { symbol, limit }) => toOutcome(await port.news(symbol ?? null, limit), (d) => d),
  }),
  tool({
    name: "compare_stocks",
    title: "Compare stocks",
    description:
      "Side-by-side engine output for 2-5 NSE stocks: total score, rank, confidence, risk, per-component points and top factors. Symbols without a score are listed in not_found. Describe the differences; the comparison names no winner.",
    input: { symbols: z.array(symbolArg).min(2).max(5).describe("2 to 5 distinct NSE symbols") },
    run: async (port, { symbols }) => toOutcome(await port.compare(symbols), (d) => d),
  }),
  tool({
    name: "search_stocks",
    title: "Search stocks",
    description: "Find NSE symbols by company name or symbol prefix. Use this before other tools when the user gives a company name.",
    input: { query: z.string().trim().min(1).max(50) },
    run: async (port, { query }) => toOutcome(await port.search(query), (d) => d),
  }),
];

export const TOOL_BY_NAME = new Map(RESEARCH_TOOLS.map((t) => [t.name, t]));

/** Validate model- or client-supplied arguments, then run. Never throws. */
export async function runTool(port: ResearchPort, name: string, rawArgs: unknown): Promise<ToolOutcome> {
  const t = TOOL_BY_NAME.get(name);
  if (!t) return { ok: false, message: `Error: unknown tool ${name}` };
  const parsed = z.object(t.input).strict().safeParse(rawArgs ?? {});
  if (!parsed.success) return { ok: false, message: `Error: invalid arguments for ${name}: ${parsed.error.message}` };
  try {
    return await t.run(port, parsed.data);
  } catch (err) {
    return { ok: false, message: `Error: ${name} failed: ${(err as Error).message}` };
  }
}
