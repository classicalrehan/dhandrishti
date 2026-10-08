import type { Highlight } from "@dd/contracts";
import { CircleMinus, CirclePlus } from "lucide-react";

export function ReasonList({ items, kind }: { items: Highlight[]; kind: "positive" | "negative" }) {
  const Icon = kind === "positive" ? CirclePlus : CircleMinus;
  if (items.length === 0) {
    return <p className="text-sm text-muted">{kind === "positive" ? "No standout strengths." : "No notable weaknesses."}</p>;
  }
  return (
    <ul className="space-y-2">
      {items.map((h, i) => (
        <li key={`${h.metric}-${i}`} className="flex items-start gap-2.5 text-sm">
          <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${kind === "positive" ? "text-up" : "text-down"}`} />
          <span className="flex-1 text-ink">{h.text}</span>
          <span className={`num text-xs ${kind === "positive" ? "text-up" : "text-down"}`} title="Score points relative to neutral">
            {h.impact > 0 ? "+" : ""}
            {h.impact.toFixed(1)}
          </span>
        </li>
      ))}
    </ul>
  );
}
