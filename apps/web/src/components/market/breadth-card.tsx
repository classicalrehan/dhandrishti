import type { Breadth } from "@dd/contracts";
import { Card } from "@/components/ui/card";

export function BreadthCard({ b }: { b: Breadth }) {
  const total = b.advances + b.declines + b.unchanged || 1;
  const seg = [
    { label: "Advances", n: b.advances, cls: "bg-up", text: "text-up" },
    { label: "Declines", n: b.declines, cls: "bg-down", text: "text-down" },
    { label: "Unchanged", n: b.unchanged, cls: "bg-faint", text: "text-muted" },
  ];
  const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  return (
    <Card className="p-4">
      <div className="text-xs font-medium tracking-wide text-muted">MARKET BREADTH · scored universe</div>
      <div className="mt-3 flex h-2 gap-[2px] overflow-hidden rounded-full" role="img" aria-label={seg.map((s) => `${s.label} ${s.n}`).join(", ")}>
        {seg.filter((s) => s.n > 0).map((s) => (
          <span key={s.label} className={s.cls} style={{ width: `${(s.n / total) * 100}%` }} />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        {seg.map((s) => (
          <div key={s.label}>
            <dt className="text-[11px] text-muted">{s.label}</dt>
            <dd className={`num font-semibold ${s.text}`}>
              {s.n} <span className="text-xs font-normal text-faint">({Math.round((s.n / total) * 100)}%)</span>
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-2 text-[11px] text-faint">
        Above 50 DMA {pct(b.pct_above_sma50)} · above 200 DMA {pct(b.pct_above_sma200)}
      </div>
    </Card>
  );
}
