/**
 * Registers the shared DhanDrishti research tools (@dd/ai) on an MCP server.
 * Tool definitions live in one catalogue used by both MCP and the in-app assistant.
 */
import { RESEARCH_TOOLS, type ResearchPort, runTool } from "@dd/ai";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } as const;

export function registerTools(server: McpServer, port: ResearchPort): void {
  for (const tool of RESEARCH_TOOLS) {
    server.registerTool(
      tool.name,
      { title: tool.title, description: tool.description, inputSchema: tool.input, annotations: READ_ONLY },
      async (args: unknown): Promise<CallToolResult> => {
        const outcome = await runTool(port, tool.name, args);
        if (!outcome.ok) return { isError: true, content: [{ type: "text", text: outcome.message }] };
        return {
          content: [{ type: "text", text: JSON.stringify(outcome.payload, null, 2) }],
          structuredContent: outcome.payload as unknown as Record<string, unknown>,
        };
      },
    );
  }
}
