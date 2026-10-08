import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { DhanDrishtiApi } from "./api-client";
import { httpPort } from "./http-port";
import { registerTools } from "./tools";

export const INSTRUCTIONS = `DhanDrishti is research and decision-support software for Indian (NSE) equities.
Every number these tools return comes from DhanDrishti's deterministic engine. When you use them:
- Quote scores, ranks, metrics, prices and risk levels exactly as returned. Do not compute, adjust or estimate your own.
- If a value is null or a tool returns "Data unavailable", say "Data unavailable". Never fill the gap.
- Explain why a stock ranks where it does using the returned factors; do not say "buy" or "sell".
- Check data_provenance: MOCK data is synthetic and must be described as such.
- These tools are read-only. They cannot place trades or change scores.`;

export function createServer(apiUrl: string, fetchImpl?: typeof fetch): McpServer {
  const server = new McpServer({ name: "dhandrishti", version: "0.1.0" }, { instructions: INSTRUCTIONS });
  registerTools(server, httpPort(new DhanDrishtiApi(apiUrl, fetchImpl)));
  return server;
}
