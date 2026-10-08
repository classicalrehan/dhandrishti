/** Quarterly EPS, oldest → newest. Same-quarter-last-year comparison is what the risk engine uses. */
export function EpsBars({ eps }: { eps: number[] }) {
  const max = Math.max(...eps.map(Math.abs), 1e-9);
  return (
    <div>
      <div className="flex h-40 items-end gap-[2px]" role="img" aria-label={`Quarterly EPS: ${eps.map((e) => e.toFixed(2)).join(", ")}`}>
        {eps.map((e, i) => {
          const yoy = i >= 4 ? e - eps[i - 4]! : null;
          return (
            <div key={i} className="group relative flex flex-1 flex-col items-center justify-end">
              <span className="num mb-1 hidden text-[10px] text-ink group-hover:block">{e.toFixed(2)}</span>
              <div
                className={`w-full max-w-8 rounded-t ${yoy == null ? "bg-faint/60" : yoy >= 0 ? "bg-brand-deep" : "bg-down/70"}`}
                style={{ height: `${Math.max(3, (Math.abs(e) / max) * 100)}%` }}
                title={`Q${i + 1}: EPS ${e.toFixed(2)}${yoy == null ? "" : ` · ${yoy >= 0 ? "up" : "down"} vs same quarter last year`}`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-faint">
        <span>Oldest</span>
        <span>Latest quarter</span>
      </div>
      <p className="mt-2 text-xs text-muted">
        <span className="mr-1 inline-block size-2 rounded-sm bg-brand-deep" /> higher than same quarter last year
        <span className="mx-1 ml-3 inline-block size-2 rounded-sm bg-down/70" /> lower
        <span className="mx-1 ml-3 inline-block size-2 rounded-sm bg-faint/60" /> no comparison
      </p>
    </div>
  );
}
