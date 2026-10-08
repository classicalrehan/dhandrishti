import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const badge = cva("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap", {
  variants: {
    tone: {
      neutral: "border-line-strong bg-surface-2 text-muted",
      up: "border-up/25 bg-up/10 text-up",
      down: "border-down/25 bg-down/10 text-down",
      warn: "border-warn/25 bg-warn/10 text-warn",
      info: "border-info/25 bg-info/10 text-info",
      brand: "border-brand/25 bg-brand/10 text-brand",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({
  tone,
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

/** Colour is never the only signal: a dot plus the text label. */
export function StatusDot({ tone }: { tone: "up" | "down" | "warn" | "info" | "neutral" }) {
  const color = {
    up: "bg-up",
    down: "bg-down",
    warn: "bg-warn",
    info: "bg-info",
    neutral: "bg-faint",
  }[tone];
  return <span aria-hidden className={cn("inline-block size-1.5 rounded-full", color)} />;
}
