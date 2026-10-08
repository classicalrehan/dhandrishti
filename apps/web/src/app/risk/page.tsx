import type { RiskRadarRow } from "@dd/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/shell/page-header";
import { ProvenanceBanner } from "@/components/shell/provenance";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";
import { RISK_LABEL, RISK_TONE } from "@/lib/labels";

export const metadata: Metadata = { title: "Risk Radar" };

const CODE_LABEL: Record<string, string> = {
  EXTREME_VOLATILITY: "Volatility",
  LARGE_DRAWDOWN: "Drawdown",
  LOW_LIQUIDITY: "Liquidity",
  EXCESSIVE_VALUATION: "Valuation",
  DEBT_CONCERN: "Debt",
  EARNINGS_DETERIORATION: "Earnings",
  PROMOTER_PLEDGE: "Pledge",
  UNUSUAL_VOLUME: "Volume",
  LARGE_GAP_MOVES: "Gaps",
  OVEREXTENDED: "Overextended",
};

export default async function Risk() {
  const res = await apiGet<RiskRadarRow[]>("/v1/risk");
  return (
    <>
      <PageHeader
        title="Risk Radar"
        subtitle="Every stock with at least one penalised risk flag. Elevated flags cost 1 point, extreme flags 2. Levels: 0–1 Low, 2–3 Medium, 4–5 High, 6+ Very high."
      />
      {!res.ok ? (
        <ApiState result={res} />
      ) : (
        <>
          <ProvenanceBanner meta={res.meta} />
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
                  <th className="py-2 pl-5 font-medium">Stock</th>
                  <th className="px-2 font-medium">Risk</th>
                  <th className="px-2 text-right font-medium">Points</th>
                  <th className="px-2 text-right font-medium">Score</th>
                  <th className="px-2 pr-5 font-medium">Flags</th>
                </tr>
              </thead>
              <tbody>
                {res.data.map((r) => (
                  <tr key={r.symbol} className="border-b border-line/60 align-top last:border-0">
                    <td className="py-3 pl-5">
                      <Link href={`/stock/${encodeURIComponent(r.symbol)}`} className="font-medium hover:underline">
                        {r.name}
                      </Link>
                      <div className="font-mono text-[11px] text-faint">
                        {r.symbol} · {r.sector}
                      </div>
                    </td>
                    <td className="px-2 py-3">
                      <Badge tone={RISK_TONE[r.risk_level]}>{RISK_LABEL[r.risk_level]}</Badge>
                    </td>
                    <td className="num px-2 py-3 text-right">{r.risk_points}</td>
                    <td className="num px-2 py-3 text-right text-muted">{Math.round(r.total_score)}</td>
                    <td className="px-2 py-3 pr-5">
                      <ul className="space-y-1">
                        {r.flags
                          .filter((f) => f.points > 0)
                          .map((f) => (
                            <li key={f.code} className="flex items-start gap-2 text-xs">
                              <Badge tone={f.severity === "EXTREME" ? "down" : "warn"} className="shrink-0">
                                {CODE_LABEL[f.code] ?? f.code} · {f.severity === "EXTREME" ? "extreme" : "elevated"}
                              </Badge>
                              <span className="text-muted">{f.message}</span>
                            </li>
                          ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </>
  );
}
