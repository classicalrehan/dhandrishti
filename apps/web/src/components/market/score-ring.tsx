/** Score out of 100 as a ring (single brand hue: magnitude, not a traffic light). */
export function ScoreRing({ score, size = 44, stroke = 4 }: { score: number; size?: number; stroke?: number }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  return (
    <span className="relative inline-grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" role="img" aria-label={`Score ${Math.round(score)} out of 100`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-surface-3" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`}
          className="text-brand"
        />
      </svg>
      <span className="num absolute text-[13px] font-semibold text-ink" style={{ fontSize: size * 0.3 }}>
        {Math.round(score)}
      </span>
    </span>
  );
}
