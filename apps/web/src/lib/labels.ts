import type { Confidence, RiskLevel } from "@dd/contracts";

export const RISK_LABEL: Record<RiskLevel, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  VERY_HIGH: "Very high",
};

export const RISK_TONE: Record<RiskLevel, "up" | "warn" | "down"> = {
  LOW: "up",
  MEDIUM: "warn",
  HIGH: "down",
  VERY_HIGH: "down",
};

export const CONFIDENCE_LABEL: Record<Confidence, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };
export const CONFIDENCE_BARS: Record<Confidence, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };

export const TREND_LABEL: Record<string, string> = {
  STRONG_UPTREND: "Strong uptrend",
  UPTREND: "Uptrend",
  SIDEWAYS: "Sideways",
  DOWNTREND: "Downtrend",
  STRONG_DOWNTREND: "Strong downtrend",
};

export const REGIME_LABEL: Record<string, string> = {
  BULLISH: "Bullish",
  NEUTRAL: "Neutral",
  CAUTIOUS: "Cautious",
  BEARISH: "Bearish",
};

export function toneOf(v: number | null | undefined): "up" | "down" | "flat" {
  if (v == null || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

export function fmtDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
