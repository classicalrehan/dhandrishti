/**
 * In-process ResearchPort for the AI assistant: Claude → application tools →
 * application services (MarketService) → repositories → database. No SQL or
 * credentials are ever exposed to the model.
 */
import type { PortResult, ResearchPort } from "@dd/ai";
import { AppError } from "../errors";
import type { MarketService, Result } from "./market-service";

async function wrap<T>(call: () => Promise<Result<T>>): Promise<PortResult<T>> {
  try {
    const { data, meta } = await call();
    return { ok: true, data, meta };
  } catch (err) {
    if (err instanceof AppError) return { ok: false, code: err.code, message: err.message };
    throw err;
  }
}

export function servicePort(service: MarketService): ResearchPort {
  return {
    stock: (s) => wrap(() => service.stock(s)),
    scoreHistory: (s, limit) => wrap(() => service.scoreHistory(s, limit)),
    rankingHistory: (days, top) => wrap(() => service.rankingHistory(days, top)),
    opportunities: (q) => wrap(() => service.opportunities(q)),
    sectors: () => wrap(() => service.sectors()),
    overview: () => wrap(() => service.overview()),
    news: (symbol, limit) => wrap(() => service.news(symbol, limit)),
    compare: (symbols) => wrap(() => service.compare(symbols)),
    search: (q) => wrap(() => service.search(q)),
  };
}
