"use client";

/**
 * Backtest equity curves (strategy vs NIFTY 50 vs equal-weight universe) with a drawdown pane.
 * Series colours are the validated 3-slot palette used by the price chart.
 */
import { AreaSeries, ColorType, CrosshairMode, LineSeries, createChart, type MouseEventParams, type Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

/** Validated 3-slot palette (series 1–3); series take colours in this fixed order. */
const PALETTE = ["#3987e5", "#d95926", "#199e70"];

export interface CurvePoint {
  date: string;
  drawdown_pct: number;
  [series: string]: number | string;
}

export interface CurveSeries {
  key: string;
  label: string;
}

const BACKTEST_SERIES: CurveSeries[] = [
  { key: "strategy", label: "DhanDrishti top picks" },
  { key: "nifty", label: "NIFTY 50" },
  { key: "universe_ew", label: "Equal-weight universe" },
];

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
/** Axis labels in lakh / crore, e.g. ₹18.4L, ₹1.2Cr. */
const lakhs = (v: number) => (Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toFixed(2)}Cr` : `₹${(v / 1e5).toFixed(1)}L`);
const RUPEES = { type: "custom" as const, formatter: lakhs, minMove: 1 };
const PERCENT = { type: "custom" as const, formatter: (v: number) => `${v.toFixed(0)}%`, minMove: 0.1 };

export function EquityChart({
  equity,
  series = BACKTEST_SERIES,
  caption = "Value of ₹10 lakh invested at the first rebalance. Lower pane: drawdown of the DhanDrishti portfolio from its previous peak. Scroll to zoom, drag to pan.",
}: {
  equity: CurvePoint[];
  series?: CurveSeries[];
  caption?: string;
}) {
  const SERIES = series.slice(0, PALETTE.length).map((s, i) => ({ ...s, color: PALETTE[i]! }));
  const el = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<CurvePoint | null>(null);
  const byDate = useMemo(() => new Map(equity.map((p) => [p.date, p])), [equity]);

  useEffect(() => {
    if (!el.current || equity.length === 0) return;
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a0b4",
        fontFamily: "var(--font-inter), system-ui, sans-serif",
        panes: { separatorColor: "rgba(255,255,255,0.08)", enableResize: false },
      },
      grid: { vertLines: { color: "rgba(255,255,255,0.05)" }, horzLines: { color: "rgba(255,255,255,0.05)" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: { borderColor: "rgba(255,255,255,0.1)" },
    });
    for (const s of SERIES) {
      const line = chart.addSeries(LineSeries, {
        color: s.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, priceFormat: RUPEES,
      });
      line.setData(equity.map((p) => ({ time: p.date as Time, value: Number(p[s.key]) })));
    }
    const dd = chart.addSeries(
      AreaSeries,
      { lineColor: "#f26b74", topColor: "rgba(242,107,116,0.05)", bottomColor: "rgba(242,107,116,0.35)", lineWidth: 1, priceLineVisible: false, invertFilledArea: true, priceFormat: PERCENT },
      1,
    );
    dd.setData(equity.map((p) => ({ time: p.date as Time, value: p.drawdown_pct })));
    chart.panes()[0]?.setStretchFactor(0.75);
    chart.panes()[1]?.setStretchFactor(0.25);
    chart.timeScale().fitContent();
    const onMove = (p: MouseEventParams<Time>) => setHover(p.time ? (byDate.get(String(p.time)) ?? null) : null);
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equity, byDate]);

  const shown = hover ?? equity.at(-1) ?? null;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs" aria-live="polite">
        {shown && <span className="num text-ink">{shown.date}</span>}
        {SERIES.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5 text-muted">
            <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} />
            {s.label} <span className="num text-ink">₹{shown ? inr.format(Number(shown[s.key])) : "—"}</span>
          </span>
        ))}
        <span className="text-muted">
          Drawdown <span className="num text-down">{shown ? `${shown.drawdown_pct.toFixed(1)}%` : "—"}</span>
        </span>
      </div>
      <div className="relative mt-3 h-[380px]">
        <div ref={el} className="absolute inset-0" />
      </div>
      <p className="mt-2 text-[11px] text-faint">{caption}</p>
    </div>
  );
}
