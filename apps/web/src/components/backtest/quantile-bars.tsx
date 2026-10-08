/**
 * Average next-period return by score quintile (Q1 = lowest scores, Q5 = highest).
 * If the score carries information, bars should rise from left to right.
 */
export function QuantileBars({ values }: { values: (number | null)[] }) {
  const nums = values.map((v) => v ?? 0);
  const max = Math.max(...nums.map(Math.abs), 0.01);
  return (
    <div>
      <div className="grid h-44 grid-cols-5 items-end gap-[2px]" role="img"
        aria-label={`Average period return by score quintile: ${values.map((v, i) => `Q${i + 1} ${v == null ? "n/a" : v.toFixed(2) + "%"}`).join(", ")}`}>
        {values.map((v, i) => (
          <div key={i} className="flex h-full flex-col items-center justify-end">
            <span className={`num mb-1 text-xs ${v != null && v < 0 ? "text-down" : "text-ink"}`}>{v == null ? "—" : `${v.toFixed(2)}%`}</span>
            <div
              className={`w-full max-w-16 rounded-t ${v != null && v < 0 ? "bg-down/70" : "bg-brand-deep"}`}
              style={{ height: `${Math.max(2, (Math.abs(v ?? 0) / max) * 80)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-5 text-center text-[11px] text-muted">
        {values.map((_, i) => (
          <span key={i}>{i === 0 ? "Q1 lowest" : i === values.length - 1 ? `Q${i + 1} highest` : `Q${i + 1}`}</span>
        ))}
      </div>
    </div>
  );
}
