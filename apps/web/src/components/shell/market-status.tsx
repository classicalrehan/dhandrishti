import { holidayCalendarVerified, istParts, marketStatus, type MarketStatus } from "@dd/shared";
import { StatusDot } from "@/components/ui/badge";

const LABEL: Record<MarketStatus, string> = {
  PRE_OPEN: "Pre-open",
  OPEN: "Market open",
  CLOSED: "Market closed",
  HOLIDAY: "Market holiday",
  WEEKEND: "Weekend",
};

/** Real NSE session state from the clock (independent of the data's provenance). */
export function MarketStatusPill() {
  const now = new Date();
  const status = marketStatus(now);
  const { minutes } = istParts(now);
  const hh = String(Math.floor(minutes / 60)).padStart(2, "0");
  const mm = String(minutes % 60).padStart(2, "0");
  return (
    <div className="hidden items-center gap-2 text-xs md:flex" title={holidayCalendarVerified() ? undefined : "Holiday calendar not yet verified against NSE"}>
      <StatusDot tone={status === "OPEN" ? "up" : status === "PRE_OPEN" ? "warn" : "neutral"} />
      <span className="font-medium text-ink">{LABEL[status]}</span>
      <span className="num text-faint">NSE · {hh}:{mm} IST</span>
    </div>
  );
}
