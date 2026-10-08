/**
 * Indian market calendar helpers (NSE equity segment).
 *
 * All exchange logic is evaluated in Asia/Kolkata regardless of server TZ.
 */
import holidays from "./nse-holidays.json";
import type { ISODate } from "./types";

export const MARKET_TZ = "Asia/Kolkata";
export const IST_OFFSET_MINUTES = 330;

export const SESSION = {
  preOpenStart: 9 * 60, // 09:00
  open: 9 * 60 + 15, // 09:15
  close: 15 * 60 + 30, // 15:30
} as const;

interface HolidayFile {
  verified: boolean;
  source: string;
  years: Record<string, { date: ISODate; name: string }[]>;
}

const holidayData = holidays as HolidayFile;
const holidaySet = new Set(
  Object.values(holidayData.years).flatMap((list) => list.map((h) => h.date)),
);

export function holidayCalendarVerified(): boolean {
  return holidayData.verified;
}

export function listHolidays(year: number): { date: ISODate; name: string }[] {
  return holidayData.years[String(year)] ?? [];
}

/** Wall-clock parts of a Date in IST. */
export function istParts(d: Date): { date: ISODate; minutes: number; weekday: number } {
  const shifted = new Date(d.getTime() + IST_OFFSET_MINUTES * 60_000);
  const date = shifted.toISOString().slice(0, 10);
  return {
    date,
    minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes(),
    weekday: shifted.getUTCDay(),
  };
}

export function isWeekend(date: ISODate): boolean {
  const wd = new Date(`${date}T00:00:00Z`).getUTCDay();
  return wd === 0 || wd === 6;
}

export function isTradingDay(date: ISODate): boolean {
  return !isWeekend(date) && !holidaySet.has(date);
}

export type MarketStatus = "PRE_OPEN" | "OPEN" | "CLOSED" | "HOLIDAY" | "WEEKEND";

export function marketStatus(now: Date = new Date()): MarketStatus {
  const { date, minutes } = istParts(now);
  if (isWeekend(date)) return "WEEKEND";
  if (holidaySet.has(date)) return "HOLIDAY";
  if (minutes >= SESSION.preOpenStart && minutes < SESSION.open) return "PRE_OPEN";
  if (minutes >= SESSION.open && minutes < SESSION.close) return "OPEN";
  return "CLOSED";
}

export function addDays(date: ISODate, n: number): ISODate {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Trading dates (ascending) ending on or before `end`, `count` long. */
export function tradingDaysBack(end: ISODate, count: number): ISODate[] {
  const out: ISODate[] = [];
  let d = end;
  while (out.length < count) {
    if (isTradingDay(d)) out.push(d);
    d = addDays(d, -1);
  }
  return out.reverse();
}
