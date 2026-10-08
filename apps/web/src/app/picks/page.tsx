import type { OpportunityRow } from "@dd/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { OpportunitiesTable } from "@/components/market/opportunities-table";
import { PageHeader } from "@/components/shell/page-header";
import { ProvenanceBanner } from "@/components/shell/provenance";
import { Card } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/cn";

export const metadata: Metadata = { title: "Top Opportunities" };

const FILTERS = [
  { label: "All", qs: "" },
  { label: "Low risk only", qs: "max_risk=LOW" },
  { label: "High confidence", qs: "min_confidence=HIGH" },
  { label: "Low risk · high confidence", qs: "max_risk=LOW&min_confidence=HIGH" },
];

export default async function Picks({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  qs.set("limit", "100");
  for (const k of ["max_risk", "min_confidence", "sector"]) if (sp[k]) qs.set(k, sp[k]!);
  const res = await apiGet<OpportunityRow[]>(`/v1/opportunities?${qs}`);
  const current = FILTERS.find((f) => f.qs === [sp.max_risk && `max_risk=${sp.max_risk}`, sp.min_confidence && `min_confidence=${sp.min_confidence}`].filter(Boolean).join("&"));

  return (
    <>
      <PageHeader
        title="Top Opportunities"
        subtitle="Stocks currently showing the strongest combination of quality, momentum, earnings and risk characteristics. Ranks come from the engine; filters only hide rows."
      >
        <nav aria-label="Filters" className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <Link
              key={f.label}
              href={f.qs ? `/picks?${f.qs}` : "/picks"}
              aria-current={current?.label === f.label ? "true" : undefined}
              className={cn(
                "rounded-md border px-2.5 py-1.5 text-xs",
                current?.label === f.label ? "border-brand/40 bg-brand/10 text-ink" : "border-line text-muted hover:text-ink",
              )}
            >
              {f.label}
            </Link>
          ))}
        </nav>
      </PageHeader>
      {!res.ok ? (
        <ApiState result={res} />
      ) : (
        <>
          <ProvenanceBanner meta={res.meta} />
          <Card className="pt-1">
            {res.data.length ? (
              <OpportunitiesTable rows={res.data} />
            ) : (
              <p className="p-6 text-sm text-muted">No stocks match these filters.</p>
            )}
          </Card>
        </>
      )}
    </>
  );
}
