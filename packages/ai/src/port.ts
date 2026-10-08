/**
 * The application-tool port: the only way an AI client (Claude via the research
 * assistant, or any MCP client) reaches DhanDrishti data. Implementations:
 *   - apps/api: in-process, backed by MarketService (application services)
 *   - apps/mcp: over the read-only HTTP API
 * Neither exposes SQL, credentials, writes or trading.
 */
import type {
  Comparison,
  MarketOverview,
  Meta,
  NewsItem,
  OpportunitiesQuery,
  OpportunityRow,
  RankingSnapshot,
  ScoreHistoryPoint,
  SearchResult,
  SectorStrength,
  StockDetail,
} from "@dd/contracts";

export type PortResult<T> = { ok: true; data: T; meta: Meta } | { ok: false; code: string; message: string };

export interface ResearchPort {
  stock(symbol: string): Promise<PortResult<StockDetail>>;
  scoreHistory(symbol: string, limit: number): Promise<PortResult<ScoreHistoryPoint[]>>;
  rankingHistory(days: number, top: number): Promise<PortResult<RankingSnapshot[]>>;
  opportunities(q: OpportunitiesQuery): Promise<PortResult<OpportunityRow[]>>;
  sectors(): Promise<PortResult<SectorStrength[]>>;
  overview(): Promise<PortResult<MarketOverview>>;
  news(symbol: string | null, limit: number): Promise<PortResult<NewsItem[]>>;
  compare(symbols: string[]): Promise<PortResult<Comparison>>;
  search(q: string): Promise<PortResult<SearchResult[]>>;
}
