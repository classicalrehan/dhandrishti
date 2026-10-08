import type { MarketOverview } from "@dd/contracts";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { BreadthCard } from "@/components/market/breadth-card";
import { IndexCard } from "@/components/market/index-card";
import { OpportunitiesTable } from "@/components/market/opportunities-table";
import { RegimeCard } from "@/components/market/regime-card";
import { RiskList } from "@/components/market/risk-list";
import { SectorGrid } from "@/components/market/sector-grid";
import { ProvenanceBanner } from "@/components/shell/provenance";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";

export default async function Dashboard() {
  const res = await apiGet<MarketOverview>("/v1/market/overview");
  if (!res.ok) return <ApiState result={res} />;
  const d = res.data;

  return (
    <>
      <ProvenanceBanner meta={res.meta} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {d.indices.map((q) => (
          <IndexCard key={q.code} q={q} />
        ))}
        <BreadthCard b={d.breadth} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader
            title="Top Opportunities"
            subtitle="Strongest combination of quality, growth, momentum, trend and risk, ranked by the quantitative engine"
            action={
              <Link href="/picks" className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-ink">
                View all <ArrowRight aria-hidden className="size-3.5" />
              </Link>
            }
          />
          <div className="pt-2">
            <OpportunitiesTable rows={d.top_opportunities} compact />
          </div>
        </Card>
        <RegimeCard r={d.regime} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader
            title="Sector Strength"
            subtitle="Score 0–100 from relative strength, breadth and earnings trend; tint deepens with strength"
            action={
              <Link href="/sectors" className="text-xs text-muted hover:text-ink">
                Details →
              </Link>
            }
          />
          <CardBody>
            <SectorGrid sectors={d.sectors} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader
            title="Risk Radar"
            subtitle="Stocks with penalised risk flags"
            action={
              <Link href="/risk" className="text-xs text-muted hover:text-ink">
                All →
              </Link>
            }
          />
          <CardBody>
            <RiskList rows={d.risk_radar} />
          </CardBody>
        </Card>
      </div>
    </>
  );
}
