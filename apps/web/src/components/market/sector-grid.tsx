import type { SectorStrength } from "@dd/contracts";
import { Delta } from "@/components/ui/delta";

/** Sector tiles: tint encodes strength score (one hue, magnitude); the number is always printed. */
export function SectorGrid({ sectors }: { sectors: SectorStrength[] }) {
  return (
    <ul className="grid grid-cols-2 gap-[2px] overflow-hidden rounded-lg sm:grid-cols-3 xl:grid-cols-4">
      {sectors.map((s) => (
        <li
          key={s.sector}
          className="p-3"
          style={{ background: `color-mix(in oklab, var(--color-brand-deep) ${Math.round(8 + s.score * 0.32)}%, var(--color-surface-2))` }}
          title={`${s.sector}: strength ${s.score}/100, rank ${s.rank}; momentum ${s.momentum}; breadth ${s.breadth}`}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-sm font-medium text-ink">{s.sector}</span>
            <span className="num text-sm font-semibold text-ink">{s.score}</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-xs">
            <span className="text-ink/70">1D median</span>
            <Delta value={s.median_ret_1d} className="text-xs" />
          </div>
        </li>
      ))}
    </ul>
  );
}
