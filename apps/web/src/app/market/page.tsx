import type { MarketOverview } from "@dd/contracts";
import type { Metadata } from "next";
import { BreadthCard } from "@/components/market/breadth-card";
import { IndexCard } from "@/components/market/index-card";
import { RegimeCard } from "@/components/market/regime-card";
import { SectorGrid } from "@/components/market/sector-grid";
import { PageHeader } from "@/components/shell/page-header";
import { ProvenanceBanner } from "@/components/shell/provenance";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";

export const metadata: Metadata = { title: "Market Pulse" };

export default async function MarketPulse() {
  const res = await apiGet<MarketOverview>("/v1/market/overview");
  return (
    <>
      <PageHeader title="Market Pulse" subtitle="What is happening in the market today, and how confident the model is about it." />
      {!res.ok ? (
        <ApiState result={res} />
      ) : (
        <>
          <ProvenanceBanner meta={res.meta} />
          <div className="grid gap-4 lg:grid-cols-3">
            {res.data.indices.map((q) => (
              <IndexCard key={q.code} q={q} />
            ))}
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <RegimeCard r={res.data.regime} />
            <div className="flex flex-col gap-4">
              <BreadthCard b={res.data.breadth} />
              <Card>
                <CardHeader title="Sector participation" subtitle="Strength score per sector" />
                <CardBody>
                  <SectorGrid sectors={res.data.sectors} />
                </CardBody>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
