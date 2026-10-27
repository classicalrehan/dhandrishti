"use client";

/**
 * Watchlist prices from GET /v1/live/quotes, polled every 5 s while the tab is visible (one request for the
 * whole list). The previous answer stays on screen during a refresh; rows are keyed by symbol so only changed
 * cells re-render. Read-only: there are no trade actions here.
 */
import type { LiveQuotes } from "@dd/contracts";
import { useEffect, useState } from "react";
import { Badge, StatusDot } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { browserApiBase } from "@/lib/browser-api";
import { banner, rowView } from "@/lib/live-view";

const POLL_MS = 5_000;

type Load = { state: "loading" } | { state: "ok"; data: LiveQuotes; failed: boolean } | { state: "error"; message: string };

export function LiveQuotesTable() {
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (document.visibilityState === "visible") {
        try {
          const res = await fetch(`${browserApiBase()}/v1/live/quotes`, { cache: "no-store" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const body = (await res.json()) as { data: LiveQuotes };
          if (!cancelled) setLoad({ state: "ok", data: body.data, failed: false });
        } catch {
          if (!cancelled) {
            setLoad((prev) =>
              prev.state === "ok" ? { ...prev, failed: true } : { state: "error", message: "Could not reach the DhanDrishti API." },
            );
          }
        }
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (load.state === "loading") return <Card className="p-6 text-sm text-muted">Loading prices…</Card>;
  if (load.state === "error") return <Card className="p-6 text-sm text-down">{load.message} Retrying every 5 seconds.</Card>;

  const d = load.data;
  const b = banner(d);
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <Badge tone={b.connection.tone}>
          <StatusDot tone={b.connection.tone} />
          {b.connection.label}
        </Badge>
        <Badge>{b.session}</Badge>
        <span className="text-xs text-faint">
          {d.connection.subscribed} subscribed · fresh = updated within {d.freshness_seconds}s
        </span>
        {load.failed && <Badge tone="warn">Refresh failed; showing the last answer</Badge>}
      </div>
      {b.message && <div className="border-b border-line px-4 py-2 text-xs text-muted">{b.message}</div>}
      <div className="overflow-x-auto">
        {d.quotes.length === 0 ? (
          <div className="p-6 text-sm text-muted">
            The watchlist is empty. Set <code className="font-mono">DD_LIVE_WATCHLIST</code> (for example{" "}
            <code className="font-mono">RELIANCE,TCS,HDFCBANK</code>) for the API and restart it.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">Symbol</th>
                <th className="px-4 py-2 text-right font-medium">Price</th>
                <th className="px-4 py-2 text-right font-medium">vs prev. close</th>
                <th className="px-4 py-2 font-medium">Updated</th>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Freshness</th>
              </tr>
            </thead>
            <tbody>
              {d.quotes.map((q) => {
                const r = rowView(q, d.generated_at);
                return (
                  <tr key={r.symbol} className="border-b border-line last:border-0" title={r.note ?? undefined}>
                    <td className="px-4 py-2 font-medium">{r.symbol}</td>
                    <td className="num px-4 py-2 text-right">{r.price}</td>
                    <td className="num px-4 py-2 text-right text-muted">{r.change ?? "—"}</td>
                    <td className="num px-4 py-2 text-muted">{r.updated}</td>
                    <td className="px-4 py-2"><Badge tone={r.source.tone}>{r.source.label}</Badge></td>
                    <td className="px-4 py-2">
                      <Badge tone={r.freshness.tone}>
                        <StatusDot tone={r.freshness.tone} />
                        {r.freshness.label}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}
