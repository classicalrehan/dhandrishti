"use client";

/**
 * Interactive price chart (TradingView Lightweight Charts, Apache-2.0; attribution logo kept).
 * Panes: candles + 20/50/200 DMA, volume, RSI(14). All indicator values come from the
 * worker-computed indicator_series via the API; nothing is calculated here.
 * Zoom (wheel/pinch), pan, crosshair and per-bar readout are built in.
 */
import type { PriceBar, PriceRange } from "@dd/contracts";
import { fmtPrice } from "@dd/shared";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { browserApiBase } from "@/lib/browser-api";

const RANGES: PriceRange[] = ["1M", "3M", "6M", "1Y", "MAX"];

// Validated with the dataviz palette validator on the chart surface (#0d1422): all checks pass.
const SERIES = [
  { key: "sma20", label: "20 DMA", color: "#3987e5" },
  { key: "sma50", label: "50 DMA", color: "#d95926" },
  { key: "sma200", label: "200 DMA", color: "#199e70" },
] as const;
const UP = "#3ccf8a";
const DOWN = "#f26b74";
const MUTED = "#94a0b4";
const GRID = "rgba(255,255,255,0.05)";

type Readout = PriceBar | null;

export function PriceChart({ symbol, initialBars, initialRange }: { symbol: string; initialBars: PriceBar[]; initialRange: PriceRange }) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [range, setRange] = useState<PriceRange>(initialRange);
  const [bars, setBars] = useState<PriceBar[]>(initialBars);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [hover, setHover] = useState<Readout>(null);
  const byDate = useMemo(() => new Map(bars.map((b) => [b.date, b])), [bars]);

  useEffect(() => {
    if (range === initialRange) {
      setBars(initialBars);
      return;
    }
    const ctrl = new AbortController();
    setState("loading");
    fetch(`${browserApiBase()}/v1/stocks/${encodeURIComponent(symbol)}/prices?range=${range}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((b) => {
        setBars(b.data.bars);
        setState("idle");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setState("error");
      });
    return () => ctrl.abort();
  }, [range, symbol, initialBars, initialRange]);

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: MUTED,
        fontFamily: "var(--font-inter), system-ui, sans-serif",
        panes: { separatorColor: "rgba(255,255,255,0.08)", enableResize: false },
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: { borderColor: "rgba(255,255,255,0.1)" },
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;
    // Rebuild series for the new range (simple and cheap at these sizes).
    for (const s of [...chart.panes()].flatMap((p) => p.getSeries())) chart.removeSeries(s);

    const t = (d: string) => d as Time;
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineVisible: false,
    });
    candles.setData(bars.map((b) => ({ time: t(b.date), open: b.open, high: b.high, low: b.low, close: b.close })));

    for (const s of SERIES) {
      const line = chart.addSeries(LineSeries, {
        color: s.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData(bars.flatMap((b) => (b[s.key] == null ? [] : [{ time: t(b.date), value: b[s.key]! }])));
    }

    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
    volume.setData(
      bars.map((b) => ({ time: t(b.date), value: b.volume, color: b.close >= b.open ? "rgba(60,207,138,0.45)" : "rgba(242,107,116,0.45)" })),
    );

    const rsi = chart.addSeries(LineSeries, { color: MUTED, lineWidth: 2, priceLineVisible: false, lastValueVisible: true }, 2);
    rsi.setData(bars.flatMap((b) => (b.rsi14 == null ? [] : [{ time: t(b.date), value: b.rsi14 }])));
    for (const level of [30, 70]) {
      rsi.createPriceLine({ price: level, color: "rgba(255,255,255,0.25)", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    }

    const panes = chart.panes();
    panes[0]?.setStretchFactor(0.64);
    panes[1]?.setStretchFactor(0.16);
    panes[2]?.setStretchFactor(0.2);
    chart.timeScale().fitContent();

    const onMove = (p: MouseEventParams<Time>) => setHover(p.time ? (byDate.get(String(p.time)) ?? null) : null);
    chart.subscribeCrosshairMove(onMove);
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, [bars, byDate]);

  const shown = hover ?? bars.at(-1) ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" aria-live="polite">
          {shown && (
            <span className="num text-muted">
              <span className="text-ink">{shown.date}</span> O {fmtPrice(shown.open)} H {fmtPrice(shown.high)} L {fmtPrice(shown.low)} C{" "}
              <span className="text-ink">{fmtPrice(shown.close)}</span>
            </span>
          )}
          {SERIES.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5 text-muted">
              <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} />
              {s.label} <span className="num text-ink">{shown ? fmtPrice(shown[s.key]) : "—"}</span>
            </span>
          ))}
          <span className="text-muted">
            RSI(14) <span className="num text-ink">{shown?.rsi14 == null ? "—" : shown.rsi14.toFixed(1)}</span>
          </span>
        </div>
        <div role="group" aria-label="Range" className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              aria-pressed={r === range}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs",
                r === range ? "bg-brand/15 text-ink ring-1 ring-brand/30" : "text-muted hover:bg-surface-2 hover:text-ink",
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div className="relative mt-3 h-[460px]">
        <div ref={el} className="absolute inset-0" />
        {state !== "idle" && (
          <div className="absolute inset-0 grid place-items-center bg-surface/60 text-sm text-muted">
            {state === "loading" ? "Loading…" : "Could not load prices for this range."}
          </div>
        )}
      </div>
      <p className="mt-2 text-[11px] text-faint">
        Panes: price with moving averages · volume · RSI(14) with 30/70 guides. Scroll to zoom, drag to pan. 1W/1D/3Y/5Y ranges need
        longer and intraday history (not in the mock dataset).
      </p>
    </div>
  );
}
