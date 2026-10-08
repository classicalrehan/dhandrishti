import type { BacktestDetail, BacktestRunSummary } from "@dd/contracts";
import { fmtPct } from "@dd/shared";
import { FlaskConical, TriangleAlert } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { EquityChart } from "@/components/backtest/equity-chart";
import { QuantileBars } from "@/components/backtest/quantile-bars";
import { PageHeader } from "@/components/shell/page-header";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtDate } from "@/lib/labels";

export const metadata: Metadata = { title: "Backtesting" };

const RUN_CMD = "cd apps/worker && uv run python -m dhandrishti.jobs.backtest --start 2023-10-01 --end 2026-10-05";
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const f2 = (v: number | null | undefined) => (v == null ? "—" : (Math.abs(v) < 0.005 ? 0 : v).toFixed(2));
const pct = (v: number | null | undefined, d = 1) => fmtPct(v ?? null, d);

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cn("num mt-1 text-2xl font-semibold", tone === "up" && "text-up", tone === "down" && "text-down")}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-faint">{sub}</div>}
    </Card>
  );
}

const toneOf = (v: number | null | undefined) => (v == null || v === 0 ? undefined : v > 0 ? "up" : "down");

export default async function BacktestPage({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const list = await apiGet<BacktestRunSummary[]>("/v1/backtests");
  const header = (
    <PageHeader
      title="Backtesting"
      subtitle="Would the DhanDrishti score have picked better stocks in the past? Each rebalance re-scores the universe using only data known on that date, then trades at the next session's open with Indian delivery costs."
    />
  );
  if (!list.ok) return (<>{header}<ApiState result={list} /></>);

  const runs = list.data;
  if (runs.length === 0) {
    return (
      <>
        {header}
        <Card className="p-6 text-sm text-muted">
          No backtests yet. Run one from the worker:
          <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink">{RUN_CMD}</pre>
        </Card>
      </>
    );
  }

  const wanted = Number((await searchParams).run);
  const selected = runs.find((r) => r.id === wanted) ?? runs.find((r) => r.status === "SUCCEEDED") ?? runs[0]!;
  const detailRes = await apiGet<BacktestDetail>(`/v1/backtests/${selected.id}`);

  return (
    <>
      {header}

      {/* Honesty first: these numbers are hypothetical, and on MOCK data the edge is built in. */}
      <div role="note" className="mb-4 space-y-2 rounded-lg border border-warn/30 bg-warn/[0.07] px-4 py-3 text-sm">
        <p className="flex items-start gap-2">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warn" />
          <span>
            <span className="font-semibold text-warn">Hypothetical results.</span> A backtest shows what a fixed rule would
            have done on past data. It is not a forecast and not a promise of future returns.
          </span>
        </p>
        {selected.provenance === "MOCK" && (
          <p className="flex items-start gap-2">
            <FlaskConical aria-hidden className="mt-0.5 size-4 shrink-0 text-warn" />
            <span>
              <span className="font-semibold text-warn">MOCK data: the edge below is built in.</span> The mock generator
              uses one hidden &quot;quality&quot; factor to drive both the fundamentals and future returns, so the score is
              guaranteed to look predictive here. These results test the backtest machinery, not the model. Only a run on
              real, point-in-time market data can tell whether the score works.
            </span>
          </p>
        )}
      </div>

      <nav aria-label="Backtest runs" className="mb-5 flex flex-wrap gap-1.5">
        {runs.map((r) => (
          <Link
            key={r.id}
            href={`/backtest?run=${r.id}`}
            aria-current={r.id === selected.id ? "true" : undefined}
            className={cn(
              "rounded-md border px-2.5 py-1.5 text-xs",
              r.id === selected.id ? "border-brand/40 bg-brand/10 text-ink" : "border-line text-muted hover:text-ink",
            )}
          >
            #{r.id} {r.name ?? `${r.params.rebalance} top ${r.params.top_n}`}
            {r.status !== "SUCCEEDED" && <span className="ml-1 text-warn">({r.status.toLowerCase()})</span>}
          </Link>
        ))}
      </nav>

      {!detailRes.ok ? (
        <ApiState result={detailRes} />
      ) : !detailRes.data.metrics ? (
        <Card className="p-6 text-sm text-muted">
          Run #{selected.id} {selected.status === "FAILED" ? `failed: ${selected.error}` : "is still running."}
        </Card>
      ) : (
        <BacktestView d={detailRes.data} />
      )}

      <p className="mt-6 text-[11px] text-faint">
        Run a new backtest: <code className="font-mono text-muted">{RUN_CMD}</code> (options: --rebalance weekly|monthly|quarterly,
        --top-n, --max-risk, --min-confidence, --buy-cost-bps, --sell-cost-bps).
      </p>
    </>
  );
}

function BacktestView({ d }: { d: BacktestDetail }) {
  const m = d.metrics!;
  const p = d.run.params;
  const rows: [string, (s: typeof m.strategy) => string][] = [
    ["Total return", (s) => pct(s.total_return_pct)],
    ["CAGR", (s) => pct(s.cagr_pct)],
    ["Volatility (annual)", (s) => pct(s.volatility_pct, 1).replace("+", "")],
    ["Sharpe", (s) => f2(s.sharpe)],
    ["Sortino", (s) => f2(s.sortino)],
    ["Max drawdown", (s) => pct(s.max_drawdown_pct)],
    ["Calmar", (s) => f2(s.calmar)],
  ];
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="DhanDrishti CAGR" value={pct(m.strategy.cagr_pct)} tone={toneOf(m.strategy.cagr_pct)}
          sub={`${fmtDate(m.period.start)} → ${fmtDate(m.period.end)} · ${m.period.rebalances} rebalances`} />
        <Stat label="vs equal-weight universe" value={pct(m.vs_universe.excess_cagr_pct)} tone={toneOf(m.vs_universe.excess_cagr_pct)}
          sub={`Beat it in ${pct(m.vs_universe.periods_beaten_pct, 0).replace("+", "")} of periods`} />
        <Stat label="vs NIFTY 50" value={pct(m.vs_nifty.excess_cagr_pct)} tone={toneOf(m.vs_nifty.excess_cagr_pct)}
          sub={`Beat it in ${pct(m.vs_nifty.periods_beaten_pct, 0).replace("+", "")} of periods`} />
        <Stat label="Max drawdown" value={pct(m.strategy.max_drawdown_pct)} tone="down"
          sub={`${fmtDate(m.strategy.max_drawdown_peak)} → ${fmtDate(m.strategy.max_drawdown_trough)}`} />
      </div>

      <Card className="mt-4">
        <CardBody className="pt-5">
          <EquityChart equity={d.equity} />
        </CardBody>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Performance" subtitle="Same schedule and costs for all three; NIFTY is the price index (no dividends)" />
          <CardBody>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-faint">
                  <th className="pb-2 font-medium">Metric</th>
                  <th className="pb-2 text-right font-medium">DhanDrishti</th>
                  <th className="pb-2 text-right font-medium">NIFTY 50</th>
                  <th className="pb-2 text-right font-medium">Equal-weight</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, fn]) => (
                  <tr key={label} className="border-t border-line/60">
                    <td className="py-2 text-muted">{label}</td>
                    <td className="num py-2 text-right text-ink">{fn(m.strategy)}</td>
                    <td className="num py-2 text-right text-muted">{fn(m.nifty)}</td>
                    <td className="num py-2 text-right text-muted">{fn(m.universe_ew)}</td>
                  </tr>
                ))}
                <tr className="border-t border-line/60">
                  <td className="py-2 text-muted">Beta / tracking error vs NIFTY</td>
                  <td className="num py-2 text-right text-ink" colSpan={3}>
                    {f2(m.vs_nifty.beta)} · {pct(m.vs_nifty.tracking_error_pct).replace("+", "")} · IR {f2(m.vs_nifty.information_ratio)}
                  </td>
                </tr>
                <tr className="border-t border-line/60">
                  <td className="py-2 text-muted">Avg turnover / costs paid</td>
                  <td className="num py-2 text-right text-ink" colSpan={3}>
                    {m.trading.avg_turnover_pct.toFixed(1)}% per rebalance · ₹{inr.format(m.trading.total_costs)} (
                    {m.trading.costs_pct_of_capital.toFixed(2)}% of capital)
                  </td>
                </tr>
              </tbody>
            </table>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Does a higher score mean a higher return?"
            subtitle="Average next-period return of every scored stock, grouped by score quintile"
          />
          <CardBody>
            <QuantileBars values={m.signal.quantile_mean_returns_pct} />
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
              <dt className="text-muted" title="Rank correlation between score and next-period return, averaged over rebalances">Mean IC</dt>
              <dd className="num text-right text-ink">{f2(m.signal.mean_ic)}</dd>
              <dt className="text-muted">IC t-stat</dt>
              <dd className="num text-right text-ink">{f2(m.signal.ic_t_stat)}</dd>
              <dt className="text-muted">Periods with positive IC</dt>
              <dd className="num text-right text-ink">{pct(m.signal.positive_ic_pct, 0).replace("+", "")}</dd>
              <dt className="text-muted">Top minus bottom quintile</dt>
              <dd className="num text-right text-ink">{pct(m.signal.top_minus_bottom_pct, 2)}</dd>
            </dl>
            <p className="mt-3 text-[11px] text-faint">
              IC near 0 means the score has no relationship with what happened next. On real data, a mean IC of 0.03–0.05
              that holds up across years is considered meaningful.
            </p>
          </CardBody>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="overflow-x-auto">
          <CardHeader title="Rebalances" subtitle="Signal at the close, trades at the next open" />
          <table className="mt-2 w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="py-2 pl-5 font-medium">Signal</th>
                <th className="px-2 font-medium">Regime</th>
                <th className="px-2 text-right font-medium">DhanDrishti</th>
                <th className="px-2 text-right font-medium">NIFTY</th>
                <th className="px-2 text-right font-medium">Equal-wt</th>
                <th className="px-2 text-right font-medium">IC</th>
                <th className="px-2 pr-5 font-medium">Picks</th>
              </tr>
            </thead>
            <tbody>
              {[...d.periods].reverse().map((r) => (
                <tr key={r.execution} className="border-b border-line/60 last:border-0">
                  <td className="num whitespace-nowrap py-2 pl-5 text-muted">{r.signal}</td>
                  <td className="whitespace-nowrap px-2 text-xs text-muted">{r.regime}</td>
                  <td className={cn("num px-2 text-right", r.strategy_return_pct >= 0 ? "text-up" : "text-down")}>{pct(r.strategy_return_pct)}</td>
                  <td className="num px-2 text-right text-muted">{pct(r.nifty_return_pct)}</td>
                  <td className="num px-2 text-right text-muted">{pct(r.universe_return_pct)}</td>
                  <td className="num px-2 text-right text-muted">{f2(r.ic)}</td>
                  <td className="px-2 pr-5 font-mono text-[11px] text-faint">{r.picks.join(" ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader title="Latest holdings" subtitle={d.latest_holdings[0] ? `Bought ${fmtDate(d.latest_holdings[0].execution)}` : undefined} />
            <CardBody>
              <ul className="divide-y divide-line/60 text-sm">
                {d.latest_holdings.map((h) => (
                  <li key={h.symbol} className="flex items-center justify-between py-1.5">
                    <Link href={`/stock/${encodeURIComponent(h.symbol)}`} className="font-mono text-xs hover:underline">{h.symbol}</Link>
                    <span className="num text-xs text-muted">#{h.rank} · {h.total_score.toFixed(1)} · {(h.weight * 100).toFixed(0)}%</span>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Assumptions" />
            <CardBody>
              <ul className="list-disc space-y-1 pl-4 text-xs text-muted">
                <li>{p.rebalance} rebalance, top {p.top_n} equal-weighted{p.max_risk ? `, risk up to ${p.max_risk}` : ""}{p.min_confidence ? `, confidence ≥ ${p.min_confidence}` : ""}</li>
                <li>Costs per side: buy {p.buy_cost_bps} bps, sell {p.sell_cost_bps} bps (STT, stamp duty, charges, slippage)</li>
                <li>Fundamentals used only after their publication date</li>
                <li>Fractional shares; price returns (dividends ignored)</li>
                <li>Universe fixed to today&apos;s 44 symbols (survivorship bias on real data)</li>
                <li>Scoring model {d.run.config_version}</li>
              </ul>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
