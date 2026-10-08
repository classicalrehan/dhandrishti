const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export const UNAVAILABLE = "Data unavailable";

export function fmtPrice(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : inr2.format(v);
}

export function fmtInr(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : `₹${inr2.format(v)}`;
}

export function fmtPct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v.toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
}

/** Crore formatting, e.g. 12,34,567 Cr. */
export function fmtCr(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : `₹${inr0.format(v)} Cr`;
}
