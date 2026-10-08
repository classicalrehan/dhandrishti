import type { Regime } from "@dd/contracts";
import { Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { REGIME_LABEL } from "@/lib/labels";

const TONE = { BULLISH: "up", NEUTRAL: "info", CAUTIOUS: "warn", BEARISH: "down" } as const;

export function RegimeCard({ r }: { r: Regime }) {
  return (
    <Card>
      <CardHeader
        title="Market Regime"
        subtitle="Six-factor model · never a certainty"
        action={
          <span title="Composite of index trend, Bank NIFTY trend, breadth, volatility, sector participation and momentum. See the quant spec §9.">
            <Info aria-hidden className="size-4 text-faint" />
          </span>
        }
      />
      <CardBody>
        <div className="flex items-center justify-between gap-4">
          <div>
            <Badge tone={TONE[r.regime]} className="px-2.5 py-1 text-sm font-semibold">
              {REGIME_LABEL[r.regime]}
            </Badge>
            <p className="mt-2 max-w-sm text-sm text-muted">{r.reason}</p>
          </div>
          <div className="text-right">
            <div className="num text-3xl font-semibold">
              {Math.round(r.composite)}
              <span className="text-base font-normal text-faint">/100</span>
            </div>
            <div className="text-xs text-muted">Confidence {r.confidence}%</div>
          </div>
        </div>
        <ul className="mt-4 space-y-2.5">
          {r.factors.map((f) => (
            <li key={f.key} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 text-sm">
              <span className="text-muted">
                {f.label} <span className="text-[11px] text-faint">· weight {f.weight}</span>
              </span>
              <span className="num text-right font-medium">{Math.round(f.score)}</span>
              <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
                <span className="block h-full rounded-full bg-brand-deep" style={{ width: `${Math.max(2, f.score)}%` }} />
              </span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
