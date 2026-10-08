/**
 * Read-only data access for the API. Repositories return rows as stored; they hold
 * no business rules. All scores come from the Python worker via score_history.
 */
import type {
  HoldingsPoint,
  BacktestDetail,
  BacktestRunSummary,
  PaperDetail,
  PaperSummary,
  Breadth,
  CorporateEvent,
  NewsItem,
  RankingSnapshot,
  ScoreHistoryPoint,
  Provenance,
  Regime,
  SectorStrength,
  SearchResult,
  Security,
  StockScore,
} from "@dd/contracts";

export interface RunContext {
  run_id: number;
  as_of: string;
  config_version: string;
  provenance: Provenance;
}

export interface IndexBar {
  code: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface PriceRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  sma20: number | null;
  sma50: number | null;
  sma200: number | null;
  rsi14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
}

export interface FundamentalsRow {
  as_of: string;
  provenance: Provenance;
  metrics: Record<string, number | null>;
  quarterly_eps: number[] | null;
}

export interface MarketRepository {
  /** Latest successful scoring run (optionally on or before a date). */
  latestRun(onOrBefore?: string): Promise<RunContext | null>;
  scores(ctx: RunContext): Promise<StockScore[]>;
  score(ctx: RunContext, symbol: string): Promise<StockScore | null>;
  /** Oldest first. */
  scoreHistory(symbol: string, configVersion: string, limit: number): Promise<ScoreHistoryPoint[]>;
  /** Top `top` ranks for each of the latest `days` scored dates, oldest first. */
  rankingHistory(configVersion: string, days: number, top: number): Promise<RankingSnapshot[]>;
  news(symbol: string | null, limit: number): Promise<NewsItem[]>;
  sectors(ctx: RunContext): Promise<SectorStrength[]>;
  regime(ctx: RunContext): Promise<{ regime: Regime; breadth: Breadth } | null>;
  indexBars(codes: string[], asOf: string, perIndex: number): Promise<IndexBar[]>;
  security(symbol: string): Promise<Security | null>;
  search(q: string, limit: number): Promise<SearchResult[]>;
  fundamentals(symbol: string, asOf: string): Promise<FundamentalsRow | null>;
  events(symbol: string, after: string, until: string): Promise<CorporateEvent[]>;
  prices(symbol: string, asOf: string, from: string | null): Promise<PriceRow[]>;
  /** Most recent backtest runs first. */
  backtestRuns(limit: number): Promise<BacktestRunSummary[]>;
  backtest(id: number): Promise<BacktestDetail | null>;
  paperPortfolios(): Promise<PaperSummary[]>;
  paperPortfolio(id: number): Promise<PaperDetail | null>;
  /** Latest real-holdings snapshot with its items and the snapshot history; null when none exist. */
  holdings(): Promise<HoldingsSnapshot | null>;
  ping(): Promise<void>;
}

export interface HoldingItem {
  kind: "HOLDING" | "POSITION";
  symbol: string;
  exchange: string;
  product: string;
  qty: number;
  t1_qty: number;
  avg_price: number;
  last_price: number;
  close_price: number | null;
  pnl: number;
}

export interface HoldingsSnapshot {
  as_of: string;
  fetched_at: string;
  items: HoldingItem[];
  history: HoldingsPoint[];
}
