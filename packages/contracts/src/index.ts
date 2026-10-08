/**
 * HTTP contracts between apps/api and its clients (web, MCP).
 *
 * Score objects mirror packages/quant-spec/SPEC.md §11 exactly — the API passes
 * engine output through and never recomputes it. `null` means "Data unavailable".
 */
import { z } from "zod";

export const Provenance = z.enum(["MOCK", "EOD", "DELAYED", "LIVE"]);
export const Confidence = z.enum(["HIGH", "MEDIUM", "LOW"]);
export const RiskLevel = z.enum(["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]);
export const RegimeName = z.enum(["BULLISH", "NEUTRAL", "CAUTIOUS", "BEARISH"]);
export const ComponentKey = z.enum([
  "fundamentals",
  "earningsGrowth",
  "momentum",
  "technicalTrend",
  "valuation",
  "liquidity",
  "sectorStrength",
  "risk",
]);
export const MomentumLabel = z.enum(["Strong", "Moderate", "Weak"]);

const num = z.number().nullable();
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

export const Meta = z.object({
  as_of: isoDate,
  data_provenance: Provenance,
  config_version: z.string(),
  generated_at: z.string(),
});

export const envelope = <T extends z.ZodTypeAny>(data: T) => z.object({ data, meta: Meta });

// ------------------------------------------------------------------ engine output (SPEC §11)

export const Reason = z.object({
  text: z.string(),
  impact: z.enum(["positive", "negative", "neutral"]),
  metric: z.string().nullable(),
  points: z.number(),
});

export const ComponentScore = z.object({
  key: ComponentKey,
  label: z.string(),
  score: z.number(),
  max: z.number(),
  weight: z.number(),
  normalized_score: z.number(),
  coverage: z.number(),
  raw_metrics: z.record(z.string(), z.union([z.number(), z.boolean()]).nullable()),
  metric_scores: z.record(z.string(), z.number()),
  reasons: z.array(Reason),
  data_timestamp: z.string(),
});

export const RiskFlag = z.object({
  code: z.string(),
  severity: z.enum(["ELEVATED", "EXTREME", "INFO"]),
  points: z.number(),
  message: z.string(),
});

export const Highlight = z.object({
  component: z.string(),
  metric: z.string().nullable(),
  text: z.string(),
  impact: z.number(),
});

export const Technicals = z.record(z.string(), z.union([z.number(), z.string()]).nullable());

export const StockScore = z.object({
  symbol: z.string(),
  name: z.string(),
  sector: z.string(),
  as_of: isoDate,
  data_provenance: Provenance,
  config_version: z.string(),
  total_score: z.number(),
  max_score: z.number(),
  rank: z.number().int(),
  confidence: Confidence,
  data_coverage: z.number(),
  risk_level: RiskLevel,
  risk_points: z.number(),
  risk_flags: z.array(RiskFlag),
  key_reason: z.string(),
  top_positives: z.array(Highlight),
  top_negatives: z.array(Highlight),
  components: z.record(ComponentKey, ComponentScore),
  technicals: Technicals,
});

// ------------------------------------------------------------------ API views

export const OpportunityRow = z.object({
  rank: z.number().int(),
  symbol: z.string(),
  name: z.string(),
  sector: z.string(),
  price: z.number(),
  change: num,
  change_pct: num,
  total_score: z.number(),
  confidence: Confidence,
  risk_level: RiskLevel,
  momentum: MomentumLabel,
  trend: z.string(),
  key_reason: z.string(),
});

export const SectorStrength = z.object({
  sector: z.string(),
  score: z.number().int(),
  rank: z.number().int(),
  momentum: z.string(),
  breadth: z.string(),
  median_rs_nifty_3m: num,
  median_rs_nifty_1m: num,
  pct_above_sma50: num,
  median_profit_growth: num,
  median_ret_1d: num,
  median_ret_1m: num,
  members: z.array(z.string()),
});

export const Breadth = z.object({
  advances: z.number().int(),
  declines: z.number().int(),
  unchanged: z.number().int(),
  advance_ratio: num,
  pct_above_sma50: num,
  pct_above_sma200: num,
});

export const RegimeFactor = z.object({
  key: z.string(),
  label: z.string(),
  weight: z.number(),
  score: z.number(),
});

export const Regime = z.object({
  regime: RegimeName,
  composite: z.number(),
  confidence: z.number().int(),
  factors: z.array(RegimeFactor),
  reason: z.string(),
});

export const IndexQuote = z.object({
  code: z.string(),
  close: z.number(),
  change: num,
  change_pct: num,
  high: z.number(),
  low: z.number(),
  sparkline: z.array(z.object({ date: isoDate, close: z.number() })),
});

export const RiskRadarRow = z.object({
  symbol: z.string(),
  name: z.string(),
  sector: z.string(),
  total_score: z.number(),
  risk_level: RiskLevel,
  risk_points: z.number(),
  flags: z.array(RiskFlag),
});

export const MarketOverview = z.object({
  indices: z.array(IndexQuote),
  breadth: Breadth,
  regime: Regime,
  sectors: z.array(SectorStrength),
  top_opportunities: z.array(OpportunityRow),
  risk_radar: z.array(RiskRadarRow),
});

export const Security = z.object({
  symbol: z.string(),
  name: z.string(),
  exchange: z.string(),
  sector: z.string(),
  industry: z.string().nullable(),
  is_financial: z.boolean(),
});

export const Fundamentals = z.object({
  as_of: isoDate,
  provenance: Provenance,
  metrics: z.record(z.string(), num),
  quarterly_eps: z.array(z.number()).nullable(),
});

export const CorporateEvent = z.object({
  date: isoDate,
  type: z.string(),
  title: z.string(),
});

export const ScoreHistoryPoint = z.object({
  as_of: isoDate,
  total_score: z.number(),
  rank: z.number().int(),
  confidence: Confidence,
  risk_level: RiskLevel,
});

export const StockDetail = z.object({
  security: Security,
  score: StockScore,
  fundamentals: Fundamentals.nullable(),
  upcoming_events: z.array(CorporateEvent),
  score_history: z.array(ScoreHistoryPoint),
});

export const PriceRange = z.enum(["1M", "3M", "6M", "1Y", "MAX"]);

export const PriceBar = z.object({
  date: isoDate,
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number(),
  sma20: num,
  sma50: num,
  sma200: num,
  rsi14: num,
  macd: num,
  macd_signal: num,
  macd_hist: num,
});

export const PriceSeries = z.object({
  symbol: z.string(),
  range: PriceRange,
  bars: z.array(PriceBar),
});

export const RankingSnapshot = z.object({
  as_of: isoDate,
  rows: z.array(z.object({ rank: z.number().int(), symbol: z.string(), total_score: z.number() })),
});

export const ComparedStock = z.object({
  symbol: z.string(),
  name: z.string(),
  sector: z.string(),
  rank: z.number().int(),
  total_score: z.number(),
  confidence: Confidence,
  risk_level: RiskLevel,
  risk_points: z.number(),
  key_reason: z.string(),
  components: z.record(ComponentKey, z.object({ label: z.string(), score: z.number(), max: z.number(), coverage: z.number() })),
  top_positives: z.array(Highlight),
  top_negatives: z.array(Highlight),
});

export const Comparison = z.object({
  stocks: z.array(ComparedStock),
  /** Requested symbols with no score in the latest run. */
  not_found: z.array(z.string()),
});

export const NewsItem = z.object({
  symbol: z.string().nullable(),
  published_at: z.string(),
  headline: z.string(),
  summary: z.string().nullable(),
  url: z.string(),
  source: z.string(),
  provenance: Provenance,
});

// ------------------------------------------------------------------ backtests (hypothetical results)

const PerfStats = z.object({
  total_return_pct: z.number(),
  cagr_pct: num,
  volatility_pct: num,
  sharpe: num,
  sortino: num,
  max_drawdown_pct: z.number(),
  max_drawdown_peak: z.string(),
  max_drawdown_trough: z.string(),
  calmar: num,
});

const Relative = z.object({
  excess_cagr_pct: num,
  beta: num,
  tracking_error_pct: num,
  information_ratio: num,
  periods_beaten_pct: num,
});

export const BacktestMetrics = z.object({
  period: z.object({ start: isoDate, end: isoDate, rebalances: z.number().int() }),
  strategy: PerfStats,
  nifty: PerfStats,
  universe_ew: PerfStats,
  vs_nifty: Relative,
  vs_universe: Relative,
  trading: z.object({
    avg_holdings: z.number(),
    avg_turnover_pct: z.number(),
    total_costs: z.number(),
    costs_pct_of_capital: z.number(),
  }),
  signal: z.object({
    mean_ic: num,
    ic_t_stat: num,
    positive_ic_pct: num,
    top_minus_bottom_pct: num,
    quantile_mean_returns_pct: z.array(num),
  }),
});

export const BacktestParams = z.object({
  start: isoDate,
  end: isoDate,
  rebalance: z.enum(["weekly", "monthly", "quarterly"]),
  top_n: z.number().int(),
  max_risk: RiskLevel.nullable(),
  min_confidence: Confidence.nullable(),
  buy_cost_bps: z.number(),
  sell_cost_bps: z.number(),
  initial_capital: z.number(),
  risk_free_rate: z.number(),
  lookback_bars: z.number().int(),
  quantiles: z.number().int(),
});

export const BacktestRunSummary = z.object({
  id: z.number().int(),
  name: z.string().nullable(),
  status: z.enum(["RUNNING", "SUCCEEDED", "FAILED"]),
  started_at: z.string(),
  finished_at: z.string().nullable(),
  config_version: z.string(),
  provenance: Provenance,
  params: BacktestParams,
  error: z.string().nullable(),
  headline: z
    .object({
      cagr_pct: num,
      nifty_cagr_pct: num,
      universe_cagr_pct: num,
      max_drawdown_pct: z.number(),
      sharpe: num,
      rebalances: z.number().int(),
    })
    .nullable(),
});

export const BacktestPeriod = z.object({
  signal: isoDate,
  execution: isoDate,
  end: isoDate,
  regime: z.string(),
  picks: z.array(z.string()),
  turnover_pct: z.number(),
  strategy_return_pct: z.number(),
  universe_return_pct: z.number(),
  nifty_return_pct: z.number(),
  ic: num,
  quantile_returns_pct: z.array(num),
});

export const BacktestEquityPoint = z.object({
  date: isoDate,
  strategy: z.number(),
  nifty: z.number(),
  universe_ew: z.number(),
  drawdown_pct: z.number(),
});

export const BacktestHolding = z.object({
  signal: isoDate,
  execution: isoDate,
  symbol: z.string(),
  rank: z.number().int(),
  total_score: z.number(),
  risk_level: RiskLevel,
  confidence: Confidence,
  weight: z.number(),
  entry_price: z.number(),
});

export const BacktestDetail = z.object({
  run: BacktestRunSummary,
  metrics: BacktestMetrics.nullable(),
  periods: z.array(BacktestPeriod),
  equity: z.array(BacktestEquityPoint),
  /** Holdings chosen at the most recent rebalance. */
  latest_holdings: z.array(BacktestHolding),
});

// ------------------------------------------------------------------ paper trading (simulated, no real orders)

export const PaperParams = z.object({
  capital: z.number(),
  top_n: z.number().int(),
  rebalance: z.enum(["weekly", "monthly", "quarterly"]),
  max_risk: RiskLevel.nullable(),
  min_confidence: Confidence.nullable(),
  stop_loss_pct: num,
  rank_buffer: z.number().int().nullable(),
  kill_switch_pct: z.number(),
  lookback_bars: z.number().int(),
  // Optional rules (2026-10 rule study); absent on portfolios created before them.
  regime_slots: z.record(z.string(), z.number().int()).nullable().optional(),
  min_history_bars: z.number().int().nullable().optional(),
  trailing_stop_pct: num.optional(),
});

export const PaperSummary = z.object({
  id: z.number().int(),
  name: z.string(),
  status: z.enum(["ACTIVE", "HALTED", "CLOSED"]),
  halt_reason: z.string().nullable(),
  start_date: isoDate,
  last_processed: isoDate,
  provenance: Provenance,
  params: PaperParams,
  equity: z.number(),
  cash: z.number(),
  return_pct: z.number(),
  nifty_return_pct: num,
  drawdown_pct: z.number(),
  max_drawdown_pct: z.number(),
  positions: z.number().int(),
  charges_paid: z.number(),
});

export const PaperPosition = z.object({
  symbol: z.string(),
  name: z.string(),
  qty: z.number().int(),
  avg_price: z.number(),
  last_close: z.number(),
  value: z.number(),
  pnl: z.number(),
  pnl_pct: z.number(),
  weight_pct: z.number(),
  entry_date: isoDate,
});

export const PaperOrder = z.object({
  id: z.number().int(),
  created_on: isoDate,
  side: z.enum(["BUY", "SELL"]),
  symbol: z.string(),
  qty: z.number().int(),
  reason: z.enum(["INITIAL", "REBALANCE", "STOP_LOSS", "KILL_SWITCH"]),
  status: z.enum(["PENDING", "FILLED", "CANCELLED"]),
  fill_date: isoDate.nullable(),
  fill_price: num,
  charges: z.number(),
  note: z.string().nullable(),
});

export const PaperDay = z.object({
  date: isoDate,
  equity: z.number(),
  cash: z.number(),
  drawdown_pct: z.number(),
  nifty_close: num,
  events: z.array(z.string()),
});

export const PaperDetail = z.object({
  portfolio: PaperSummary,
  positions: z.array(PaperPosition),
  orders: z.array(PaperOrder),
  daily: z.array(PaperDay),
});

// ------------------------------------------------------------------ real holdings (read-only from Zerodha; personal)

export const HoldingScore = z.object({
  rank: z.number().int(),
  of: z.number().int(),
  total_score: z.number(),
  confidence: Confidence,
  risk_level: RiskLevel,
  trend: z.string(),
  key_reason: z.string(),
});

export const HoldingRow = z.object({
  symbol: z.string(),
  exchange: z.string(),
  name: z.string().nullable(),
  sector: z.string().nullable(),
  qty: z.number().int(),
  t1_qty: z.number().int(),
  avg_price: z.number(),
  last_price: z.number(),
  value: z.number(),
  invested: z.number(),
  pnl: z.number(),
  pnl_pct: num,
  day_change_pct: num,
  weight_pct: z.number(),
  /** Latest DhanDrishti score; null when the stock is outside the scored universe. */
  score: HoldingScore.nullable(),
  /** Deterministic points worth a look (not advice). */
  watch: z.array(z.string()),
});

export const PositionRow = z.object({
  symbol: z.string(),
  exchange: z.string(),
  product: z.string(),
  qty: z.number().int(),
  avg_price: z.number(),
  last_price: z.number(),
  pnl: z.number(),
});

export const HoldingsPoint = z.object({
  date: isoDate,
  value: z.number(),
  invested: z.number(),
  twr_index: z.number(),
  nifty_close: num,
});

export const HoldingsView = z.object({
  as_of: isoDate,
  fetched_at: z.string(),
  scores_as_of: isoDate.nullable(),
  value: z.number(),
  invested: z.number(),
  pnl: z.number(),
  pnl_pct: num,
  day_change: num,
  /** Time-weighted return and NIFTY change since the first snapshot (`since`). */
  since: isoDate,
  return_pct: z.number(),
  nifty_return_pct: num,
  holdings: z.array(HoldingRow),
  positions: z.array(PositionRow),
  history: z.array(HoldingsPoint),
});

export const BacktestIdParams = z.object({ id: z.coerce.number().int().positive() });

export const SearchResult = z.object({ symbol: z.string(), name: z.string(), sector: z.string() });

export const ScoringConfigSummary = z.object({
  version: z.string(),
  components: z.array(z.object({ key: ComponentKey, label: z.string(), weight: z.number() })),
});

export const ApiError = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});

// ------------------------------------------------------------------ query params

export const OpportunitiesQuery = z.object({
  limit: z.coerce.number().int().min(1).max(200).default(50),
  sector: z.string().optional(),
  min_confidence: Confidence.optional(),
  max_risk: RiskLevel.optional(),
});

export const SymbolParams = z.object({ symbol: z.string().min(1).max(20).regex(/^[A-Z0-9&-]+$/) });
export const PricesQuery = z.object({ range: PriceRange.default("1Y") });
export const HistoryQuery = z.object({ limit: z.coerce.number().int().min(1).max(365).default(60) });
export const RankingHistoryQuery = z.object({
  days: z.coerce.number().int().min(1).max(365).default(30),
  top: z.coerce.number().int().min(1).max(50).default(10),
});
export const CompareQuery = z.object({
  symbols: z
    .string()
    .transform((s) => [...new Set(s.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean))])
    .pipe(z.array(z.string().regex(/^[A-Z0-9&-]{1,20}$/)).min(2).max(5)),
});
export const NewsQuery = z.object({
  symbol: z.string().regex(/^[A-Z0-9&-]{1,20}$/).optional(),
  limit: z.coerce.number().int().min(1).max(50).default(20),
});
export const SearchQuery = z.object({ q: z.string().trim().min(1).max(50) });

// ------------------------------------------------------------------ inferred types

export type Provenance = z.infer<typeof Provenance>;
export type Confidence = z.infer<typeof Confidence>;
export type RiskLevel = z.infer<typeof RiskLevel>;
export type ComponentKey = z.infer<typeof ComponentKey>;
export type Meta = z.infer<typeof Meta>;
export type Reason = z.infer<typeof Reason>;
export type ComponentScore = z.infer<typeof ComponentScore>;
export type RiskFlag = z.infer<typeof RiskFlag>;
export type Highlight = z.infer<typeof Highlight>;
export type StockScore = z.infer<typeof StockScore>;
export type OpportunityRow = z.infer<typeof OpportunityRow>;
export type SectorStrength = z.infer<typeof SectorStrength>;
export type Breadth = z.infer<typeof Breadth>;
export type Regime = z.infer<typeof Regime>;
export type IndexQuote = z.infer<typeof IndexQuote>;
export type RiskRadarRow = z.infer<typeof RiskRadarRow>;
export type MarketOverview = z.infer<typeof MarketOverview>;
export type Security = z.infer<typeof Security>;
export type Fundamentals = z.infer<typeof Fundamentals>;
export type CorporateEvent = z.infer<typeof CorporateEvent>;
export type StockDetail = z.infer<typeof StockDetail>;
export type PriceRange = z.infer<typeof PriceRange>;
export type PriceBar = z.infer<typeof PriceBar>;
export type PriceSeries = z.infer<typeof PriceSeries>;
export type SearchResult = z.infer<typeof SearchResult>;
export type ScoreHistoryPoint = z.infer<typeof ScoreHistoryPoint>;
export type RankingSnapshot = z.infer<typeof RankingSnapshot>;
export type ComparedStock = z.infer<typeof ComparedStock>;
export type Comparison = z.infer<typeof Comparison>;
export type NewsItem = z.infer<typeof NewsItem>;
export type BacktestMetrics = z.infer<typeof BacktestMetrics>;
export type BacktestRunSummary = z.infer<typeof BacktestRunSummary>;
export type BacktestPeriod = z.infer<typeof BacktestPeriod>;
export type BacktestEquityPoint = z.infer<typeof BacktestEquityPoint>;
export type BacktestHolding = z.infer<typeof BacktestHolding>;
export type BacktestDetail = z.infer<typeof BacktestDetail>;
export type PaperSummary = z.infer<typeof PaperSummary>;
export type PaperPosition = z.infer<typeof PaperPosition>;
export type PaperOrder = z.infer<typeof PaperOrder>;
export type PaperDay = z.infer<typeof PaperDay>;
export type PaperDetail = z.infer<typeof PaperDetail>;
export type HoldingRow = z.infer<typeof HoldingRow>;
export type PositionRow = z.infer<typeof PositionRow>;
export type HoldingsPoint = z.infer<typeof HoldingsPoint>;
export type HoldingsView = z.infer<typeof HoldingsView>;
export type ScoringConfigSummary = z.infer<typeof ScoringConfigSummary>;
export type OpportunitiesQuery = z.infer<typeof OpportunitiesQuery>;
export type Envelope<T> = { data: T; meta: Meta };

export const RISK_ORDER: RiskLevel[] = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"];
export const CONFIDENCE_ORDER: Confidence[] = ["LOW", "MEDIUM", "HIGH"];
