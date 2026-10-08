import type { ComponentScore } from "@dd/contracts";
import { COMPONENT_ORDER } from "@dd/config";

/** One bar per component: earned points of its weight. Values always printed. */
export function ScoreBreakdown({ components }: { components: Record<string, ComponentScore> }) {
  return (
    <ul className="space-y-3">
      {COMPONENT_ORDER.map((k) => {
        const c = components[k];
        if (!c) return null;
        const missing = c.coverage === 0;
        return (
          <li key={k}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-ink">
                {c.label}
                {missing && <span className="ml-2 text-[11px] text-warn">Data unavailable · neutral applied</span>}
                {!missing && c.coverage < 1 && (
                  <span className="ml-2 text-[11px] text-faint">{Math.round(c.coverage * 100)}% data coverage</span>
                )}
              </span>
              <span className="num text-muted">
                <span className="font-semibold text-ink">{c.score.toFixed(1)}</span> / {c.max}
              </span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-3" role="img" aria-label={`${c.label}: ${c.score.toFixed(1)} of ${c.max}`}>
              <div
                className={missing ? "h-full rounded-full bg-faint" : "h-full rounded-full bg-brand-deep"}
                style={{ width: `${Math.max(1.5, c.normalized_score * 100)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
