"use client";

import {
  Activity,
  BarChart3,
  Bell,
  Bot,
  Briefcase,
  Eye,
  FlaskConical,
  Gauge,
  HeartPulse,
  LayoutDashboard,
  Newspaper,
  Radar,
  Settings,
  SlidersHorizontal,
  Trophy,
  Wallet,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/picks", label: "Top Opportunities", Icon: Trophy },
  { href: "/market", label: "Market Pulse", Icon: Activity },
  { href: "/sectors", label: "Sector Analysis", Icon: BarChart3 },
  { href: "/risk", label: "Risk Radar", Icon: Radar },
  { href: "/screener", label: "Stock Screener", Icon: SlidersHorizontal, soon: true },
  { href: "/signals", label: "Smart Signals", Icon: Zap, soon: true },
  { href: "/watchlist", label: "Watchlist", Icon: Eye, soon: true },
  { href: "/research", label: "AI Research", Icon: Bot },
  { href: "/backtest", label: "Backtesting", Icon: FlaskConical },
  { href: "/paper", label: "Paper Trading", Icon: Wallet },
  { href: "/portfolio", label: "My Portfolio", Icon: Briefcase },
  { href: "/news", label: "News & Events", Icon: Newspaper, soon: true },
  { href: "/alerts", label: "Alerts", Icon: Bell, soon: true },
];

const ADMIN = [
  { href: "/admin/data-health", label: "Data Health", Icon: HeartPulse, soon: true },
  { href: "/settings", label: "Settings", Icon: Settings, soon: true },
];

function Item({ href, label, Icon, soon }: (typeof NAV)[number]) {
  const path = usePathname();
  const active = href === "/" ? path === "/" : path.startsWith(href);
  if (soon) {
    return (
      <span
        aria-disabled
        className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-faint"
        title="Planned for a later increment"
      >
        <Icon aria-hidden className="size-4" />
        <span className="flex-1">{label}</span>
        <span className="rounded border border-line px-1.5 text-[10px] uppercase tracking-wide">Soon</span>
      </span>
    );
  }
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active ? "bg-brand/10 font-medium text-ink ring-1 ring-brand/20" : "text-muted hover:bg-surface-2 hover:text-ink",
      )}
    >
      <Icon aria-hidden className={cn("size-4", active && "text-brand")} />
      {label}
    </Link>
  );
}

export function SideNav() {
  return (
    <nav aria-label="Primary" className="flex flex-col gap-0.5">
      {NAV.map((i) => (
        <Item key={i.href} {...i} />
      ))}
      <div className="mt-4 mb-1 px-3 text-[11px] font-medium uppercase tracking-wider text-faint">Admin</div>
      {ADMIN.map((i) => (
        <Item key={i.href} {...i} />
      ))}
      <div className="mt-4 flex items-center gap-2 px-3 text-[11px] text-faint">
        <Gauge aria-hidden className="size-3.5" /> Research software, not advice
      </div>
    </nav>
  );
}
