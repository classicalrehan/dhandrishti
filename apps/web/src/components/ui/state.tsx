import { DatabaseZap, PlugZap, SearchX, TriangleAlert } from "lucide-react";
import type { ApiResult } from "@/lib/api";
import { Card } from "./card";

/** Rendered instead of data when the API cannot serve it. Never shows placeholder numbers. */
export function ApiState({ result }: { result: Extract<ApiResult<unknown>, { ok: false }> }) {
  const view = {
    unavailable: {
      Icon: PlugZap,
      title: "API unavailable",
      hint: "Start it with `pnpm --filter @dd/api dev` (needs PostgreSQL running).",
    },
    "no-data": { Icon: DatabaseZap, title: "No scored data yet", hint: "Run `pnpm pipeline:daily` to ingest and score." },
    "not-found": { Icon: SearchX, title: "Not found", hint: null },
    error: { Icon: TriangleAlert, title: "Something went wrong", hint: null },
  }[result.kind];
  return (
    <Card className="mx-auto mt-10 max-w-xl p-8 text-center">
      <view.Icon aria-hidden className="mx-auto size-8 text-muted" />
      <h2 className="mt-3 text-lg font-semibold">{view.title}</h2>
      <p className="mt-1 text-sm text-muted">{result.message}</p>
      {view.hint && <p className="mt-3 font-mono text-xs text-faint">{view.hint}</p>}
    </Card>
  );
}
