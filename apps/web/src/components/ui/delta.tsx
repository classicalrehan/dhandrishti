import { fmtPct } from "@dd/shared";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/cn";
import { toneOf } from "@/lib/labels";

/** Signed percentage with an arrow icon so direction is not conveyed by colour alone. */
export function Delta({ value, className, digits = 2 }: { value: number | null; className?: string; digits?: number }) {
  const tone = toneOf(value);
  const Icon = tone === "up" ? ArrowUpRight : tone === "down" ? ArrowDownRight : Minus;
  return (
    <span
      className={cn(
        "num inline-flex items-center gap-0.5",
        tone === "up" && "text-up",
        tone === "down" && "text-down",
        tone === "flat" && "text-muted",
        className,
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {fmtPct(value, digits)}
    </span>
  );
}
