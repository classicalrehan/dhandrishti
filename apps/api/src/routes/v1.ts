import {
  ApiError,
  BacktestDetail,
  BacktestIdParams,
  BacktestRunSummary,
  HoldingsView,
  PaperDetail,
  PaperSummary,
  CompareQuery,
  Comparison,
  HistoryQuery,
  NewsItem,
  NewsQuery,
  RankingHistoryQuery,
  RankingSnapshot,
  ScoreHistoryPoint,
  envelope,
  MarketOverview,
  OpportunitiesQuery,
  OpportunityRow,
  PricesQuery,
  PriceSeries,
  RiskRadarRow,
  ScoringConfigSummary,
  SearchQuery,
  SearchResult,
  SectorStrength,
  StockDetail,
  SymbolParams,
} from "@dd/contracts";
import { z } from "zod";
import type { FastifyPluginAsyncZod } from "fastify-type-provider-zod";
import type { MarketService } from "../services/market-service";

const errors = { 400: ApiError, 404: ApiError, 503: ApiError };

/** Read-only v1 endpoints. Every response is validated against @dd/contracts. */
export const v1Routes =
  (service: MarketService): FastifyPluginAsyncZod =>
  async (app) => {
    app.get(
      "/market/overview",
      { schema: { response: { 200: envelope(MarketOverview), ...errors } } },
      () => service.overview(),
    );

    app.get(
      "/opportunities",
      { schema: { querystring: OpportunitiesQuery, response: { 200: envelope(z.array(OpportunityRow)), ...errors } } },
      (req) => service.opportunities(req.query),
    );

    app.get(
      "/stocks/:symbol",
      { schema: { params: SymbolParams, response: { 200: envelope(StockDetail), ...errors } } },
      (req) => service.stock(req.params.symbol),
    );

    app.get(
      "/stocks/:symbol/prices",
      {
        schema: {
          params: SymbolParams,
          querystring: PricesQuery,
          response: { 200: envelope(PriceSeries), ...errors },
        },
      },
      (req) => service.prices(req.params.symbol, req.query.range),
    );

    app.get(
      "/stocks/:symbol/score-history",
      {
        schema: {
          params: SymbolParams,
          querystring: HistoryQuery,
          response: { 200: envelope(z.array(ScoreHistoryPoint)), ...errors },
        },
      },
      (req) => service.scoreHistory(req.params.symbol, req.query.limit),
    );

    app.get(
      "/rankings/history",
      { schema: { querystring: RankingHistoryQuery, response: { 200: envelope(z.array(RankingSnapshot)), ...errors } } },
      (req) => service.rankingHistory(req.query.days, req.query.top),
    );

    app.get(
      "/compare",
      { schema: { querystring: CompareQuery, response: { 200: envelope(Comparison), ...errors } } },
      (req) => service.compare(req.query.symbols),
    );

    app.get(
      "/news",
      { schema: { querystring: NewsQuery, response: { 200: envelope(z.array(NewsItem)), ...errors } } },
      (req) => service.news(req.query.symbol ?? null, req.query.limit),
    );

    app.get(
      "/backtests",
      { schema: { response: { 200: envelope(z.array(BacktestRunSummary)), ...errors } } },
      () => service.backtests(),
    );

    app.get(
      "/backtests/:id",
      { schema: { params: BacktestIdParams, response: { 200: envelope(BacktestDetail), ...errors } } },
      (req) => service.backtest(req.params.id),
    );

    app.get(
      "/paper",
      { schema: { response: { 200: envelope(z.array(PaperSummary)), ...errors } } },
      () => service.paperPortfolios(),
    );

    app.get(
      "/paper/:id",
      { schema: { params: BacktestIdParams, response: { 200: envelope(PaperDetail), ...errors } } },
      (req) => service.paperPortfolio(req.params.id),
    );

    app.get(
      "/holdings",
      { schema: { response: { 200: envelope(HoldingsView), ...errors } } },
      () => service.holdings(),
    );

    app.get(
      "/sectors",
      { schema: { response: { 200: envelope(z.array(SectorStrength)), ...errors } } },
      () => service.sectors(),
    );

    app.get(
      "/risk",
      { schema: { response: { 200: envelope(z.array(RiskRadarRow)), ...errors } } },
      () => service.riskRadar(),
    );

    app.get(
      "/search",
      { schema: { querystring: SearchQuery, response: { 200: envelope(z.array(SearchResult)), ...errors } } },
      (req) => service.search(req.query.q),
    );

    app.get(
      "/scoring/config",
      { schema: { response: { 200: envelope(ScoringConfigSummary), ...errors } } },
      () => service.scoringConfig(),
    );
  };
