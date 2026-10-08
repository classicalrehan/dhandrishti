import type { SectorStrength } from "@dd/contracts";
import { fmtPct } from "@dd/shared";
import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/shell/page-header";
import { ProvenanceBanner } from "@/components/shell/provenance";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";

export const metadata: Metadata = { title: "Sector Analysis" };

const tone = (label: string) => (label === "Strong" || label === "Positive" ? "up" : label === "Weak" || label === "Negative" ? "down" : "neutral");

export default async function Sectors() {
  const res = await apiGet<SectorStrength[]>("/v1/sectors");
  return (
    <>
      <PageHeader
        title="Sector Analysis"
        subtitle="Sector strength blends median relative strength vs NIFTY 50 (3M and 1M), breadth above the 50 DMA and median profit growth."
      />
      {!res.ok ? (
        <ApiState result={res} />
      ) : (
        <>
          <ProvenanceBanner meta={res.meta} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {res.data.map((s) => (
              <Card key={s.sector} className="p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-xs text-faint">Rank #{s.rank}</div>
                    <h2 className="text-lg font-semibold">{s.sector}</h2>
                  </div>
                  <div className="text-right">
                    <div className="num text-2xl font-semibold">{s.score}</div>
                    <div className="text-[11px] text-faint">strength /100</div>
                  </div>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
                  <div className="h-full rounded-full bg-brand-deep" style={{ width: `${Math.max(2, s.score)}%` }} />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge tone={tone(s.momentum)}>Momentum: {s.momentum}</Badge>
                  <Badge tone={tone(s.breadth)}>Breadth: {s.breadth}</Badge>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                  <dt className="text-muted">RS vs NIFTY (3M)</dt>
                  <dd className="num text-right">{fmtPct(s.median_rs_nifty_3m, 1)}</dd>
                  <dt className="text-muted">RS vs NIFTY (1M)</dt>
                  <dd className="num text-right">{fmtPct(s.median_rs_nifty_1m, 1)}</dd>
                  <dt className="text-muted">Above 50 DMA</dt>
                  <dd className="num text-right">{s.pct_above_sma50 == null ? "—" : `${Math.round(s.pct_above_sma50 * 100)}%`}</dd>
                  <dt className="text-muted">Median profit growth</dt>
                  <dd className="num text-right">{fmtPct(s.median_profit_growth, 1)}</dd>
                  <dt className="text-muted">Median 1D move</dt>
                  <dd className="text-right">
                    <Delta value={s.median_ret_1d} className="text-xs" />
                  </dd>
                </dl>
                <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-3">
                  {s.members.map((m) => (
                    <Link key={m} href={`/stock/${encodeURIComponent(m)}`} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted hover:text-ink">
                      {m}
                    </Link>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
