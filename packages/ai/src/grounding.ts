/**
 * Grounding check: does every substantive number in the assistant's answer appear in
 * the tool results it fetched this turn?
 *
 * A number is "verified" when some numeric value in the tool data equals it after
 * rounding to the precision the answer shows (also as a percentage of a 0-1 ratio).
 * This is a heuristic safety net, not a proof: it flags invented or derived figures
 * (differences, averages, targets) for the reader; it cannot prove a correct number
 * was attached to the right label.
 */

export interface GroundingReport {
  /** Numbers in the answer that were checked. */
  checked: number;
  /** Numbers that could not be matched to any tool value. */
  unverified: string[];
  /** True when the answer contains numbers but no tool data was fetched. */
  noToolData: boolean;
}

const DATE_PATTERNS = [
  /\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?\b/g, // 2026-10-05, ISO timestamps
  /\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b/gi, // 05 Oct 2026
  /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b/gi, // Oct 5, 2026
  /\b(?:FY|Q[1-4])\s?'?\d{2,4}\b/gi, // FY26, Q2 2026
  /\b20\d{2}\.\d{1,2}-v\d+\b/g, // model version 2026.10-v1
];

// Indicator and period *names* contain numbers that are labels, not data values.
const LABEL_PATTERNS = [
  /\b\d{1,3}[\s-]?(?:DMA|EMA|SMA|MA|day|days|session|sessions)\b/gi, // 50 DMA, 200-day
  /\b(?:RSI|ADX|ATR|EMA|SMA|MACD)\s?\(?\d{1,3}(?:\s?,\s?\d{1,3}){0,2}\)?/gi, // RSI(14), MACD(12,26,9)
  /\b52[\s-]?(?:week|wk)\b/gi, // 52-week
  /\b\d{1,2}\s?[DWMY]\b/g, // 1D, 1W, 3M, 6M, 1Y, 5Y
  /\bNIFTY\s?\d{2,3}\b/gi, // NIFTY 50
];

// Indian (12,34,567.89) and international (1,234,567) grouping, optional sign/decimals.
const NUMBER = /(?<![\w.])[-+−]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?/g;

/** Small integers are counts/ordinals ("top 5", "3 stocks"), not market data. */
const IGNORE_BELOW = 10;

function collectNumbers(value: unknown, out: number[]): void {
  if (typeof value === "number" && Number.isFinite(value)) out.push(value);
  else if (Array.isArray(value)) for (const v of value) collectNumbers(v, out);
  else if (value && typeof value === "object") for (const v of Object.values(value)) collectNumbers(v, out);
}

function matches(shown: number, decimals: number, candidates: number[]): boolean {
  const tol = 0.5 * 10 ** -decimals + 1e-9;
  return candidates.some(
    (v) => Math.abs(v - shown) <= tol || Math.abs(Math.abs(v) - Math.abs(shown)) <= tol || Math.abs(v * 100 - shown) <= tol,
  );
}

export function checkGrounding(answer: string, toolData: unknown[]): GroundingReport {
  let text = answer;
  for (const p of [...DATE_PATTERNS, ...LABEL_PATTERNS]) text = text.replace(p, " ");

  const candidates: number[] = [];
  for (const d of toolData) collectNumbers(d, candidates);

  const unverified: string[] = [];
  let checked = 0;
  for (const m of text.matchAll(NUMBER)) {
    const raw = m[0];
    const normalized = raw.replace(/,/g, "").replace("−", "-");
    const value = Number(normalized);
    if (!Number.isFinite(value)) continue;
    const decimals = normalized.includes(".") ? normalized.split(".")[1]!.length : 0;
    if (decimals === 0 && Math.abs(value) <= IGNORE_BELOW) continue;
    checked++;
    if (!matches(value, decimals, candidates)) unverified.push(raw);
  }
  return { checked, unverified: [...new Set(unverified)], noToolData: checked > 0 && toolData.length === 0 };
}
