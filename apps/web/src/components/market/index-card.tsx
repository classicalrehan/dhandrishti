import type { IndexQuote } from "@dd/contracts";
import { fmtPrice } from "@dd/shared";
import { Card } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";

const LABEL: Record<string, string> = { "NIFTY 50": "NIFTY 50", "NIFTY BANK": "BANK NIFTY", "INDIA VIX": "INDIA VIX" };

function Sparkline({ points, label }: { points: { date: string; close: number }[]; label: string }) {
  if (points.length < 2) return null;
  const w = 104;
  const h = 36;
  const ys = points.map((p) => p.close);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * w).toFixed(1)},${(h - 2 - ((p.close - min) / span) * (h - 4)).toFixed(1)}`)
    .join("");
  const first = points[0]!;
  const last = points.at(-1)!;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="text-muted" role="img">
      <title>{`${label}: ${fmtPrice(first.close)} on ${first.date} to ${fmtPrice(last.close)} on ${last.date}`}</title>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function IndexCard({ q }: { q: IndexQuote }) {
  const label = LABEL[q.code] ?? q.code;
  return (
    <Card className="p-4">
      <div className="text-xs font-medium tracking-wide text-muted">{label}</div>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div>
          <div className="num text-2xl font-semibold tracking-tight">{fmtPrice(q.close)}</div>
          <div className="mt-1 text-sm">
            <Delta value={q.change_pct} />
          </div>
        </div>
        <Sparkline points={q.sparkline} label={`${label}, last ${q.sparkline.length} sessions`} />
      </div>
      <div className="num mt-2 text-[11px] text-faint">
        H {fmtPrice(q.high)} · L {fmtPrice(q.low)}
        {q.code === "INDIA VIX" && <span className="ml-2">· lower means calmer</span>}
      </div>
    </Card>
  );
}
