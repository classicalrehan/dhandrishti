/** Key/value grid. `null` renders as "Data unavailable" — never a guess. */
export function MetricGrid({ items }: { items: { label: string; value: string | null; hint?: string }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((i) => (
        <div key={i.label} className="flex items-baseline justify-between gap-3 border-b border-line/60 py-2 text-sm" title={i.hint}>
          <dt className="text-muted">{i.label}</dt>
          <dd className={i.value == null ? "text-xs text-faint" : "num text-ink"}>{i.value ?? "Data unavailable"}</dd>
        </div>
      ))}
    </dl>
  );
}
