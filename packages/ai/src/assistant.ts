/**
 * Research assistant turn: Claude + DhanDrishti application tools, streamed.
 *
 * Claude never touches the database: tools go through a ResearchPort (application
 * services). The browser sends only plain user/assistant text; tool results are
 * produced server-side within the turn, so the client cannot forge "DhanDrishti data".
 * History is rebuilt from text each turn and carries no thinking blocks, which is
 * the valid stripped form for preserved thinking.
 */
import Anthropic from "@anthropic-ai/sdk";
import type {
  BetaContentBlock,
  BetaMessageParam,
  BetaToolResultBlockParam,
  BetaToolUseBlock,
} from "@anthropic-ai/sdk/resources/beta/messages/messages";
import { z } from "zod";
import { RESEARCH_TOOLS, runTool, type ToolPayload } from "./catalogue";
import { checkGrounding, type GroundingReport } from "./grounding";
import type { ResearchPort } from "./port";
import { RESEARCH_SYSTEM_PROMPT } from "./prompt";

export const RESEARCH_MODEL = "claude-opus-5-5";

export const ChatTurn = z.object({ role: z.enum(["user", "assistant"]), content: z.string().min(1).max(8_000) });
export const ChatRequest = z
  .object({ messages: z.array(ChatTurn).min(1).max(30) })
  // Refinements can run even when the array check failed (zod 4), so stay null-safe.
  .refine((r) => r.messages.at(-1)?.role === "user", "the last message must be from the user")
  .refine((r) => r.messages[0]?.role === "user", "the conversation must start with a user message")
  .refine((r) => r.messages.every((m, i) => i === 0 || m.role !== r.messages[i - 1]!.role), "roles must alternate")
  .refine((r) => r.messages.reduce((n, m) => n + m.content.length, 0) <= 60_000, "conversation too long");
export type ChatTurn = z.infer<typeof ChatTurn>;

export type ResearchEvent =
  | { type: "text"; delta: string }
  | { type: "tool_call"; id: string; name: string; input: unknown }
  | { type: "tool_result"; id: string; name: string; ok: boolean; message?: string }
  | {
      type: "done";
      stop_reason: string | null;
      grounding: GroundingReport;
      data_provenance: string | null;
      as_of: string | null;
      model: string;
      fallback_used: boolean;
      usage: { input_tokens: number; output_tokens: number; cache_read_input_tokens: number };
    }
  | { type: "error"; code: string; message: string };

export interface ResearchOptions {
  client: Pick<Anthropic, "beta">;
  port: ResearchPort;
  messages: ChatTurn[];
  onEvent: (e: ResearchEvent) => void;
  signal?: AbortSignal;
  maxToolRounds?: number;
  effort?: "low" | "medium" | "high" | "xhigh" | "max";
}

/** Tool definitions for the Messages API, generated from the shared catalogue. */
export const RESEARCH_API_TOOLS = RESEARCH_TOOLS.map((t) => ({
  name: t.name,
  description: t.description,
  input_schema: z.toJSONSchema(z.object(t.input), { io: "input" }) as Anthropic.Beta.BetaTool.InputSchema,
}));

export async function runResearchTurn(opts: ResearchOptions): Promise<void> {
  const { client, port, onEvent, signal } = opts;
  const maxRounds = opts.maxToolRounds ?? 6;
  const messages: BetaMessageParam[] = opts.messages.map((m) => ({ role: m.role, content: m.content }));
  const toolData: unknown[] = [];
  const provenances = new Set<string>();
  let asOf: string | null = null;
  let answer = "";
  let fallbackUsed = false;
  const usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0 };

  for (let round = 0; ; round++) {
    const stream = client.beta.messages.stream(
      {
        model: RESEARCH_MODEL,
        max_tokens: 16_000,
        system: [{ type: "text", text: RESEARCH_SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
        tools: RESEARCH_API_TOOLS,
        messages,
        output_config: { effort: opts.effort ?? "medium" },
        // Opus 5.5 safety classifiers can decline; re-run a declined request on Anthropic's
        // recommended fallback model instead of failing the turn.
        betas: ["server-side-fallback-2026-07-01"],
        fallbacks: "default",
      },
      { signal },
    );
    let roundHasText = false;
    stream.on("text", (delta) => {
      // Separate text written before a tool round from text written after it.
      if (!roundHasText && answer && !answer.endsWith("\n")) {
        answer += "\n\n";
        onEvent({ type: "text", delta: "\n\n" });
      }
      roundHasText = true;
      answer += delta;
      onEvent({ type: "text", delta });
    });

    let message: Anthropic.Beta.BetaMessage;
    try {
      message = await stream.finalMessage();
    } catch (err) {
      if (signal?.aborted) return;
      onEvent({ type: "error", ...describeError(err) });
      return;
    }

    usage.input_tokens += message.usage.input_tokens;
    usage.output_tokens += message.usage.output_tokens;
    usage.cache_read_input_tokens += message.usage.cache_read_input_tokens ?? 0;
    if (message.content.some((b) => b.type === "fallback")) fallbackUsed = true;

    if (message.stop_reason === "refusal") {
      onEvent({ type: "error", code: "DECLINED", message: "The model declined this request. Try rephrasing the question." });
      return;
    }
    if (message.stop_reason === "pause_turn") {
      messages.push({ role: "assistant", content: message.content as BetaContentBlock[] });
      continue;
    }

    const toolUses = message.content.filter((b): b is BetaToolUseBlock => b.type === "tool_use");
    if (toolUses.length === 0) {
      onEvent({
        type: "done",
        stop_reason: message.stop_reason,
        grounding: checkGrounding(answer, toolData),
        data_provenance: provenances.size ? [...provenances].sort().join(",") : null,
        as_of: asOf,
        model: message.model,
        fallback_used: fallbackUsed,
        usage,
      });
      return;
    }
    if (message.stop_reason === "max_tokens") {
      onEvent({ type: "error", code: "TRUNCATED", message: "The answer was cut off before a tool call completed." });
      return;
    }
    if (round >= maxRounds) {
      onEvent({ type: "error", code: "TOOL_BUDGET", message: `Stopped after ${maxRounds} rounds of tool calls.` });
      return;
    }

    // Append-only: the assistant turn goes back exactly as received (thinking, fallback and
    // tool_use blocks included), followed by one user message with every tool result.
    messages.push({ role: "assistant", content: message.content as BetaContentBlock[] });
    const results: BetaToolResultBlockParam[] = await Promise.all(
      toolUses.map(async (tu) => {
        onEvent({ type: "tool_call", id: tu.id, name: tu.name, input: tu.input });
        const outcome = await runTool(port, tu.name, tu.input);
        if (outcome.ok) {
          recordPayload(outcome.payload);
          onEvent({ type: "tool_result", id: tu.id, name: tu.name, ok: true });
          return { type: "tool_result", tool_use_id: tu.id, content: JSON.stringify(outcome.payload) };
        }
        onEvent({ type: "tool_result", id: tu.id, name: tu.name, ok: false, message: outcome.message });
        return { type: "tool_result", tool_use_id: tu.id, content: outcome.message, is_error: true };
      }),
    );
    messages.push({ role: "user", content: results });
  }

  function recordPayload(p: ToolPayload) {
    toolData.push(p.data);
    provenances.add(p.data_provenance);
    asOf = p.as_of;
  }
}

function describeError(err: unknown): { code: string; message: string } {
  if (err instanceof Anthropic.AuthenticationError)
    return { code: "AI_AUTH", message: "The AI service rejected the API credentials." };
  if (err instanceof Anthropic.RateLimitError)
    return { code: "AI_RATE_LIMITED", message: "The AI service is rate limited. Please retry shortly." };
  if (err instanceof Anthropic.APIConnectionError)
    return { code: "AI_UNREACHABLE", message: "Could not reach the AI service." };
  if (err instanceof Anthropic.APIError) return { code: "AI_ERROR", message: `AI service error (${err.status ?? "unknown"}).` };
  return { code: "AI_ERROR", message: "Unexpected error while generating the answer." };
}
