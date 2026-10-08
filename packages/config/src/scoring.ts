/**
 * TypeScript view of the quant scoring config.
 *
 * The numbers live ONLY in packages/quant-spec/scoring-config.json (SPEC.md).
 * This module re-exports them with types for API/UI consumers (labels, weights,
 * display order). It never computes scores; the Python worker does.
 */
import raw from "../../quant-spec/scoring-config.json";

export type ComponentKey =
  | "fundamentals"
  | "earningsGrowth"
  | "momentum"
  | "technicalTrend"
  | "valuation"
  | "liquidity"
  | "sectorStrength"
  | "risk";

export const COMPONENT_ORDER: ComponentKey[] = [
  "fundamentals",
  "earningsGrowth",
  "momentum",
  "technicalTrend",
  "valuation",
  "liquidity",
  "sectorStrength",
  "risk",
];

export interface ComponentConfig {
  label: string;
  weight: number;
  metrics: Record<string, { weight: number; fn: string; label: string; unit?: string }>;
}

export interface ScoringConfig {
  version: string;
  missing_data_neutral: number;
  components: Record<ComponentKey, ComponentConfig>;
  regime: { thresholds: { bullish: number; neutral: number; cautious: number } };
  [key: string]: unknown;
}

export const SCORING_CONFIG = raw as unknown as ScoringConfig;

export function componentWeights(cfg: ScoringConfig = SCORING_CONFIG): Record<ComponentKey, number> {
  return Object.fromEntries(COMPONENT_ORDER.map((k) => [k, cfg.components[k].weight])) as Record<
    ComponentKey,
    number
  >;
}

export function componentLabel(key: ComponentKey, cfg: ScoringConfig = SCORING_CONFIG): string {
  return cfg.components[key].label;
}

export function validateScoringConfig(cfg: ScoringConfig): string[] {
  const errors: string[] = [];
  const missing = COMPONENT_ORDER.filter((k) => !cfg.components[k]);
  if (missing.length) return [`missing components: ${missing.join(", ")}`];
  const total = COMPONENT_ORDER.reduce((s, k) => s + cfg.components[k].weight, 0);
  if (Math.abs(total - 100) > 1e-9) errors.push(`component weights must sum to 100 (got ${total})`);
  return errors;
}
