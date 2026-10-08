/** ResearchPort over the read-only DhanDrishti HTTP API (the MCP server holds no credentials). */
import type { ResearchPort } from "@dd/ai";
import type { DhanDrishtiApi } from "./api-client";

const enc = encodeURIComponent;

export function httpPort(api: DhanDrishtiApi): ResearchPort {
  return {
    stock: (s) => api.get(`/v1/stocks/${enc(s)}`),
    scoreHistory: (s, limit) => api.get(`/v1/stocks/${enc(s)}/score-history`, { limit }),
    rankingHistory: (days, top) => api.get("/v1/rankings/history", { days, top }),
    opportunities: (q) => api.get("/v1/opportunities", q),
    sectors: () => api.get("/v1/sectors"),
    overview: () => api.get("/v1/market/overview"),
    news: (symbol, limit) => api.get("/v1/news", { symbol: symbol ?? undefined, limit }),
    compare: (symbols) => api.get("/v1/compare", { symbols: symbols.join(",") }),
    search: (q) => api.get("/v1/search", { q }),
  };
}
