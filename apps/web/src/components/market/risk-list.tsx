import type { RiskRadarRow } from "@dd/contracts";
import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { RISK_LABEL, RISK_TONE } from "@/lib/labels";

export function RiskList({ rows, limitFlags = 2 }: { rows: RiskRadarRow[]; limitFlags?: number }) {
  if (rows.length === 0) return <p className="text-sm text-muted">No stocks currently carry penalised risk flags.</p>;
  return (
    <ul className="divide-y divide-line/70">
      {rows.map((r) => {
        const flags = r.flags.filter((f) => f.points > 0);
        return (
          <li key={r.symbol} className="flex items-start gap-3 py-2.5">
            <ShieldAlert aria-hidden className={`mt-0.5 size-4 shrink-0 ${RISK_TONE[r.risk_level] === "down" ? "text-down" : "text-warn"}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <Link href={`/stock/${encodeURIComponent(r.symbol)}`} className="truncate text-sm font-medium hover:underline">
                  {r.name} <span className="font-mono text-[11px] text-faint">{r.symbol}</span>
                </Link>
                <Badge tone={RISK_TONE[r.risk_level]}>{RISK_LABEL[r.risk_level]}</Badge>
              </div>
              <ul className="mt-1 space-y-0.5 text-xs text-muted">
                {flags.slice(0, limitFlags).map((f) => (
                  <li key={f.code}>{f.message}</li>
                ))}
                {flags.length > limitFlags && <li className="text-faint">+{flags.length - limitFlags} more</li>}
              </ul>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
