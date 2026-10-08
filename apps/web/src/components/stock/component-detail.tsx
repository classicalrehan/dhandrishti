import type { ComponentScore } from "@dd/contracts";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";

/** Full audit trail for one component: every metric's raw value, normalized score and reason. */
export function ComponentDetail({ c }: { c: ComponentScore }) {
  return (
    <Card>
      <CardHeader
        title={c.label}
        subtitle={`${c.score.toFixed(2)} of ${c.max} points · normalized ${c.normalized_score.toFixed(3)} · coverage ${Math.round(c.coverage * 100)}%`}
      />
      <CardBody>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-faint">
              <th className="pb-2 font-medium">Metric</th>
              <th className="pb-2 text-right font-medium">Score 0–1</th>
              <th className="pb-2 text-right font-medium">Points vs neutral</th>
            </tr>
          </thead>
          <tbody>
            {c.reasons.map((r, i) => (
              <tr key={`${r.metric}-${i}`} className="border-t border-line/60">
                <td className="py-2 pr-2">
                  <span className="text-ink">{r.text}</span>
                  {r.impact !== "neutral" && (
                    <Badge tone={r.impact === "positive" ? "up" : "down"} className="ml-2">
                      {r.impact}
                    </Badge>
                  )}
                </td>
                <td className="num py-2 text-right text-muted">
                  {r.metric && c.metric_scores[r.metric] != null ? c.metric_scores[r.metric]!.toFixed(3) : "—"}
                </td>
                <td className="num py-2 text-right text-muted">{r.points > 0 ? `+${r.points.toFixed(2)}` : r.points.toFixed(2)}</td>
              </tr>
            ))}
            {Object.entries(c.raw_metrics)
              .filter(([, v]) => v == null)
              .map(([m]) => (
                <tr key={m} className="border-t border-line/60">
                  <td className="py-2 text-faint">{m.replaceAll("_", " ")}: Data unavailable</td>
                  <td className="py-2 text-right text-faint">—</td>
                  <td className="py-2 text-right text-faint">excluded</td>
                </tr>
              ))}
          </tbody>
        </table>
        <p className="mt-3 text-[11px] text-faint">Data as of {c.data_timestamp}</p>
      </CardBody>
    </Card>
  );
}
