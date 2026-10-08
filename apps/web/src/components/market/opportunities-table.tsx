import type { OpportunityRow } from "@dd/contracts";
import { fmtPrice } from "@dd/shared";
import Link from "next/link";
import { StatusDot } from "@/components/ui/badge";
import { Delta } from "@/components/ui/delta";
import { CONFIDENCE_BARS, CONFIDENCE_LABEL, RISK_LABEL, RISK_TONE } from "@/lib/labels";
import { ScoreRing } from "./score-ring";

function ConfidenceMeter({ c }: { c: OpportunityRow["confidence"] }) {
  const n = CONFIDENCE_BARS[c];
  return (
    <span className="inline-flex items-center gap-2">
      <span>{CONFIDENCE_LABEL[c]}</span>
      <span className="flex items-end gap-[2px]" aria-hidden>
        {[1, 2, 3].map((i) => (
          <span key={i} className={`w-1 rounded-sm ${i <= n ? "bg-brand" : "bg-surface-3"}`} style={{ height: 4 + i * 3 }} />
        ))}
      </span>
    </span>
  );
}

export function OpportunitiesTable({ rows, compact = false }: { rows: OpportunityRow[]; compact?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
            <th className="py-2 pl-5 pr-2 font-medium">#</th>
            <th className="px-2 font-medium">Stock</th>
            <th className="px-2 text-right font-medium">LTP (₹)</th>
            <th className="px-2 text-right font-medium">Day</th>
            <th className="px-2 text-center font-medium">Score</th>
            <th className="px-2 font-medium">Confidence</th>
            <th className="px-2 font-medium">Risk</th>
            {!compact && <th className="px-2 font-medium">Momentum</th>}
            <th className="px-2 font-medium">Sector</th>
            <th className="px-2 pr-5 font-medium">Why it ranks</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="group border-b border-line/60 last:border-0 hover:bg-surface-2/60">
              <td className="num py-2.5 pl-5 pr-2 font-semibold text-brand">{r.rank}</td>
              <td className="px-2">
                <Link href={`/stock/${encodeURIComponent(r.symbol)}`} className="block focus:outline-none">
                  <span className="whitespace-nowrap font-medium text-ink group-hover:underline">{r.name}</span>
                  <span className="block font-mono text-[11px] text-faint">{r.symbol}</span>
                </Link>
              </td>
              <td className="num px-2 text-right">{fmtPrice(r.price)}</td>
              <td className="px-2 text-right">
                <Delta value={r.change_pct} />
              </td>
              <td className="px-2 text-center">
                <ScoreRing score={r.total_score} size={38} />
              </td>
              <td className="px-2 text-muted">
                <ConfidenceMeter c={r.confidence} />
              </td>
              <td className="px-2">
                <span className="inline-flex items-center gap-1.5 text-muted">
                  <StatusDot tone={RISK_TONE[r.risk_level]} />
                  {RISK_LABEL[r.risk_level]}
                </span>
              </td>
              {!compact && <td className="px-2 text-muted">{r.momentum}</td>}
              <td className="whitespace-nowrap px-2 text-muted">{r.sector}</td>
              <td className="min-w-[260px] px-2 pr-5 text-xs text-muted">{r.key_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
