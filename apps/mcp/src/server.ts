#!/usr/bin/env -S npx tsx
/**
 * DhanDrishti MCP server (stdio).
 *
 *   DD_API_URL=http://127.0.0.1:4000 pnpm --filter @dd/mcp start
 *
 * stdout carries the MCP protocol; diagnostics go to stderr only.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createServer } from "./create-server";

const server: McpServer = createServer(process.env.DD_API_URL ?? "http://127.0.0.1:4000");
await server.connect(new StdioServerTransport());
console.error("dhandrishti-mcp: ready on stdio");
