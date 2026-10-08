"use client";

/**
 * AI Research Assistant chat. Streams Server-Sent Events from POST /v1/research/chat.
 * Only plain text turns are sent back as history; every figure in an answer comes from
 * DhanDrishti tools called on the server during that turn, and the grounding badge
 * reports any number that could not be matched to that data.
 */
import { ArrowUp, Bot, CircleAlert, CircleCheck, FlaskConical, Loader2, Square, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/cn";
import { browserApiBase } from "@/lib/browser-api";


const TOOL_LABEL: Record<string, string> = {
  get_stock_score: "Score",
  get_stock_fundamentals: "Fundamentals",
  get_stock_technicals: "Technicals",
  get_stock_risks: "Risks",
  get_score_history: "Score history",
  get_ranking_history: "Ranking history",
  get_top_opportunities: "Top opportunities",
  get_sector_strength: "Sector strength",
  get_market_regime: "Market regime",
  get_latest_news: "News",
  compare_stocks: "Compare",
  search_stocks: "Search",
};

const SUGGESTIONS = [
  "Why is the top-ranked stock ranked #1? What are its risks?",
  "Compare HDFCBANK and ICICIBANK. Where does each score better?",
  "What is the current market regime, and which factor is weakest?",
  "Which sectors are strongest right now, and why?",
];

interface ToolChip {
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: "running" | "ok" | "error";
  message?: string;
}

interface Done {
  grounding: { checked: number; unverified: string[]; noToolData: boolean };
  data_provenance: string | null;
  as_of: string | null;
  model: string;
  fallback_used: boolean;
}

interface Turn {
  role: "user" | "assistant";
  content: string;
  tools?: ToolChip[];
  done?: Done;
  error?: { code: string; message: string };
  streaming?: boolean;
}

function chipLabel(t: ToolChip) {
  const arg = (t.input.symbol as string) ?? (Array.isArray(t.input.symbols) ? (t.input.symbols as string[]).join(" · ") : (t.input.query as string));
  return `${TOOL_LABEL[t.name] ?? t.name}${arg ? ` · ${String(arg).toUpperCase()}` : ""}`;
}

function Grounding({ d }: { d: Done }) {
  const { checked, unverified, noToolData } = d.grounding;
  if (noToolData) {
    return (
      <span className="inline-flex items-center gap-1.5 text-warn">
        <CircleAlert aria-hidden className="size-3.5" /> Numbers in this answer were not backed by any DhanDrishti lookup.
      </span>
    );
  }
  if (unverified.length) {
    return (
      <span className="inline-flex items-center gap-1.5 text-warn" title="These figures could not be matched to the data the assistant fetched. Treat them with caution.">
        <CircleAlert aria-hidden className="size-3.5" />
        {unverified.length} of {checked} figures not found in DhanDrishti data: {unverified.join(", ")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-up">
      <CircleCheck aria-hidden className="size-3.5" />
      {checked ? `All ${checked} figures match DhanDrishti data` : "No figures to verify"}
    </span>
  );
}

export function ResearchChat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [disabled, setDisabled] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Block body on purpose: newer browsers return a Promise from scrollIntoView(), and an
  // effect must return nothing or a cleanup function.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  // Deep link: /research?q=... asks once on load (used by "Ask AI" links on stock pages).
  const askedFromUrl = useRef(false);
  useEffect(() => {
    if (askedFromUrl.current) return;
    askedFromUrl.current = true;
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      window.history.replaceState(null, "", window.location.pathname);
      void send(q.slice(0, 4000));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patchLast = (fn: (t: Turn) => Turn) =>
    setTurns((ts) => [...ts.slice(0, -1), fn(ts[ts.length - 1]!)]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    // History = completed text turns only (failed assistant turns are dropped with their question).
    const history = turns
      .filter((t, i) => !(t.role === "assistant" && (t.error || !t.content)) && !(t.role === "user" && turns[i + 1]?.error))
      .map((t) => ({ role: t.role, content: t.content }));
    const messages = [...history, { role: "user" as const, content: q }];
    setTurns((ts) => [...ts, { role: "user", content: q }, { role: "assistant", content: "", tools: [], streaming: true }]);
    setInput("");
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch(`${browserApiBase()}/v1/research/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null);
        const err = body?.error ?? { code: "HTTP", message: `Request failed (${res.status})` };
        if (err.code === "AI_DISABLED") setDisabled(err.message);
        patchLast((t) => ({ ...t, streaming: false, error: err }));
        return;
      }
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value;
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          const e = JSON.parse(line.slice(6));
          if (e.type === "text") patchLast((t) => ({ ...t, content: t.content + e.delta }));
          else if (e.type === "tool_call")
            patchLast((t) => ({ ...t, tools: [...(t.tools ?? []), { id: e.id, name: e.name, input: e.input ?? {}, status: "running" }] }));
          else if (e.type === "tool_result")
            patchLast((t) => ({
              ...t,
              tools: t.tools?.map((c) => (c.id === e.id ? { ...c, status: e.ok ? "ok" : "error", message: e.message } : c)),
            }));
          else if (e.type === "done") patchLast((t) => ({ ...t, done: e, streaming: false }));
          else if (e.type === "error") patchLast((t) => ({ ...t, error: e, streaming: false }));
        }
      }
    } catch (err) {
      const aborted = (err as Error).name === "AbortError";
      patchLast((t) => ({
        ...t,
        streaming: false,
        error: aborted ? { code: "STOPPED", message: "Stopped." } : { code: "NETWORK", message: "Could not reach the DhanDrishti API." },
      }));
    } finally {
      patchLast((t) => ({ ...t, streaming: false }));
      setBusy(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="flex min-h-[calc(100dvh-14rem)] flex-col">
      {disabled && (
        <div role="note" className="mb-4 rounded-lg border border-line-strong bg-surface-2 px-4 py-3 text-sm text-muted">
          <span className="font-medium text-ink">Assistant not configured.</span> {disabled} Start the API with{" "}
          <code className="font-mono text-xs text-ink">ANTHROPIC_API_KEY</code> set.
        </div>
      )}

      <div className="flex-1 space-y-6">
        {turns.length === 0 && (
          <div className="mx-auto max-w-2xl pt-6 text-center">
            <Bot aria-hidden className="mx-auto size-8 text-brand" />
            <h2 className="mt-3 text-lg font-semibold">Ask about any stock, sector or the market</h2>
            <p className="mt-1 text-sm text-muted">
              Answers are built only from DhanDrishti's engine data. Every figure is checked against what the assistant looked up.
            </p>
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left text-sm text-muted hover:border-brand/30 hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-surface-3 px-4 py-2.5 text-sm text-ink">{t.content}</div>
            </div>
          ) : (
            <div key={i} className="flex gap-3">
              <div className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-brand/10 ring-1 ring-brand/30">
                <Bot aria-hidden className="size-4 text-brand" />
              </div>
              <div className="min-w-0 flex-1">
                {!!t.tools?.length && (
                  <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Data looked up">
                    {t.tools.map((c) => (
                      <li
                        key={c.id}
                        title={c.message}
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px]",
                          c.status === "error" ? "border-warn/30 text-warn" : "border-line text-muted",
                        )}
                      >
                        {c.status === "running" ? <Loader2 aria-hidden className="size-3 animate-spin" /> : <Wrench aria-hidden className="size-3" />}
                        {chipLabel(c)}
                      </li>
                    ))}
                  </ul>
                )}
                {t.content ? (
                  <div className="prose-dd text-sm leading-relaxed text-ink">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.content}</ReactMarkdown>
                  </div>
                ) : t.streaming ? (
                  <p className="text-sm text-muted">Thinking…</p>
                ) : null}
                {t.error && (
                  <p className="mt-2 inline-flex items-center gap-1.5 text-sm text-warn">
                    <CircleAlert aria-hidden className="size-4" /> {t.error.message}
                  </p>
                )}
                {t.done && (
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-2 text-[11px] text-faint">
                    <Grounding d={t.done} />
                    {t.done.data_provenance?.includes("MOCK") && (
                      <span className="inline-flex items-center gap-1 text-warn">
                        <FlaskConical aria-hidden className="size-3" /> MOCK data
                      </span>
                    )}
                    {t.done.as_of && <span>Data as of {t.done.as_of}</span>}
                    <span>
                      {t.done.model}
                      {t.done.fallback_used && " (fallback model)"}
                    </span>
                  </div>
                )}
              </div>
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>

      <form
        className="sticky bottom-0 mt-6 bg-gradient-to-t from-bg via-bg pb-2 pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <div className="flex items-end gap-2 rounded-xl border border-line-strong bg-surface p-2 focus-within:border-brand/40">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
            rows={1}
            maxLength={4000}
            placeholder="Ask why a stock ranks where it does, compare stocks, or check the market regime…"
            aria-label="Question"
            className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-ink placeholder:text-faint focus:outline-none"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="grid size-9 place-items-center rounded-lg bg-surface-3 text-ink hover:bg-surface-2"
              aria-label="Stop"
            >
              <Square className="size-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="grid size-9 place-items-center rounded-lg bg-brand-deep text-bg disabled:opacity-40"
              aria-label="Send"
            >
              <ArrowUp className="size-4" />
            </button>
          )}
        </div>
        <p className="mt-2 text-center text-[11px] text-faint">
          Research assistance, not investment advice. The assistant explains engine output; it cannot change scores or place trades.
        </p>
      </form>
    </div>
  );
}
