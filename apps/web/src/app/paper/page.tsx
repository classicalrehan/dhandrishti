import type { PaperDetail, PaperSummary } from "@dd/contracts";
import { fmtPct } from "@dd/shared";
import { NotebookPen, OctagonAlert } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { EquityChart } from "@/components/backtest/equity-chart";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtDate } from "@/lib/labels";

export const metadata: Metadata = { title: "Paper Trading" };

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rupees = (v: number) => `₹${inr.format(v)}`;
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "text-muted" : v > 0 ? "text-up" : "text-down");

const CREATE_CMD = 'pnpm paper create --name "Monthly top 5" --capital 100000 --top-n 5';
const REASON: Record<string, string> = {
  INITIAL: "Initial",
  REBALANCE: "Rebalance",
  STOP_LOSS: "Stop-loss",
  KILL_SWITCH: "Kill switch",
};

function Stat({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cn("num mt-1 text-2xl font-semibold", className)}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-faint">{sub}</div>}
    </Card>
  );
}

export default async function PaperPage({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const header = (
    <PageHeader
      title="Paper Trading"
      subtitle="Simulated portfolios that follow real trading rules: whole shares, Zerodha charges, next-day fills, stop-losses and a drawdown kill switch. No real orders are ever placed."
    />
  );
  const list = await apiGet<PaperSummary[]>("/v1/paper");
  if (!list.ok) return (<>{header}<ApiState result={list} /></>);
  if (list.data.length === 0) {
    return (
      <>
        {header}
        <Card className="p-6 text-sm text-muted">
          <NotebookPen aria-hidden className="mb-2 size-6 text-brand" />
          No paper portfolios yet. Create one on the real-price database, then process it daily:
          <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink">
            {`${CREATE_CMD}\n\n# every evening after 16:30 IST\npnpm kite:login\npnpm daily:kite`}
          </pre>
        </Card>
      </>
    );
  }

  const wanted = Number((await searchParams).id);
  const selected = list.data.find((p) => p.id === wanted) ?? list.data[0]!;
  const res = await apiGet<PaperDetail>(`/v1/paper/${selected.id}`);

  return (
    <>
      {header}
      <div role="note" className="mb-4 flex items-start gap-2 rounded-lg border border-info/30 bg-info/[0.07] px-4 py-3 text-sm">
        <NotebookPen aria-hidden className="mt-0.5 size-4 shrink-0 text-info" />
        <span>
          <span className="font-semibold text-info">Simulation.</span> Paper results show how these rules would have
          traded with real prices since the start date. Real fills can differ (liquidity, timing). Judge a strategy
          only after several months, against NIFTY.
          {selected.provenance === "MOCK" && <span className="ml-1 font-semibold text-warn">This portfolio uses MOCK prices.</span>}
        </span>
      </div>

      <nav aria-label="Paper portfolios" className="mb-5 flex flex-wrap gap-1.5">
        {list.data.map((p) => (
          <Link
            key={p.id}
            href={`/paper?id=${p.id}`}
            aria-current={p.id === selected.id ? "true" : undefined}
            className={cn("rounded-md border px-2.5 py-1.5 text-xs",
              p.id === selected.id ? "border-brand/40 bg-brand/10 text-ink" : "border-line text-muted hover:text-ink")}
          >
            #{p.id} {p.name} <span className={cn("num ml-1", tone(p.return_pct))}>{fmtPct(p.return_pct, 1)}</span>
            {p.status !== "ACTIVE" && <span className="ml-1 text-warn">({p.status.toLowerCase()})</span>}
          </Link>
        ))}
      </nav>

      {!res.ok ? <ApiState result={res} /> : <PaperView d={res.data} />}
    </>
  );
}

function PaperView({ d }: { d: PaperDetail }) {
  const p = d.portfolio;
  const capital = p.params.capital;
  const nifty0 = d.daily.find((x) => x.nifty_close != null)?.nifty_close ?? null;
  const curve = d.daily.map((x) => ({
    date: x.date,
    drawdown_pct: x.drawdown_pct,
    equity: x.equity,
    nifty: nifty0 && x.nifty_close ? (capital * x.nifty_close) / nifty0 : x.equity,
  }));
  const pending = d.orders.filter((o) => o.status === "PENDING");

  return (
    <>
      {p.status === "HALTED" && (
        <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-down/40 bg-down/10 px-4 py-3 text-sm">
          <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-down" />
          <span>
            <span className="font-semibold text-down">Kill switch triggered.</span> {p.halt_reason}. Holdings are sold and
            no new buying happens until you resume with <code className="font-mono">pnpm paper resume {p.id}</code>.
          </span>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Stat label="Portfolio value" value={rupees(p.equity)} sub={`Started with ${rupees(capital)} on ${fmtDate(p.start_date)}`} />
        <Stat label="Return" value={fmtPct(p.return_pct, 2)} className={tone(p.return_pct)}
          sub={p.nifty_return_pct == null ? "NIFTY: n/a" : `NIFTY over the same days: ${fmtPct(p.nifty_return_pct, 2)}`} />
        <Stat label="Drawdown now / worst" value={`${p.drawdown_pct.toFixed(1)}%`} className={p.drawdown_pct < 0 ? "text-down" : undefined}
          sub={`Worst ${p.max_drawdown_pct.toFixed(1)}% · kill switch at −${p.params.kill_switch_pct}%`} />
        <Stat label="Cash" value={rupees(p.cash)} sub={`${p.positions} holding${p.positions === 1 ? "" : "s"} · ${pending.length} pending order${pending.length === 1 ? "" : "s"}`} />
        <Stat label="Charges paid" value={`₹${inr2.format(p.charges_paid)}`} sub="STT, stamp duty, fees, GST, DP" />
      </div>

      <Card className="mt-4">
        <CardBody className="pt-5">
          {curve.length >= 2 ? (
            <EquityChart
              equity={curve}
              series={[{ key: "equity", label: "Paper portfolio" }, { key: "nifty", label: "NIFTY 50 (same start)" }]}
              caption={`Portfolio value vs NIFTY 50 scaled to the same ${rupees(capital)} start. Lower pane: drawdown from the portfolio's peak.`}
            />
          ) : (
            <p className="py-10 text-center text-sm text-muted">
              The chart appears after the first trading days are processed (<code className="font-mono">pnpm daily:kite</code> each evening).
            </p>
          )}
        </CardBody>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="overflow-x-auto">
          <CardHeader title="Holdings" subtitle={`As of ${fmtDate(p.last_processed)} close`} />
          <table className="mt-2 w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="py-2 pl-5 font-medium">Stock</th>
                <th className="px-2 text-right font-medium">Qty</th>
                <th className="px-2 text-right font-medium">Avg buy</th>
                <th className="px-2 text-right font-medium">Last close</th>
                <th className="px-2 text-right font-medium">Value</th>
                <th className="px-2 text-right font-medium">P&amp;L</th>
                <th className="px-2 pr-5 text-right font-medium">Weight</th>
              </tr>
            </thead>
            <tbody>
              {d.positions.map((x) => (
                <tr key={x.symbol} className="border-b border-line/60">
                  <td className="py-2 pl-5">
                    <Link href={`/stock/${encodeURIComponent(x.symbol)}`} className="font-medium hover:underline">{x.name}</Link>
                    <div className="font-mono text-[11px] text-faint">{x.symbol} · since {fmtDate(x.entry_date)}</div>
                  </td>
                  <td className="num px-2 text-right">{x.qty}</td>
                  <td className="num px-2 text-right text-muted">{inr2.format(x.avg_price)}</td>
                  <td className="num px-2 text-right">{inr2.format(x.last_close)}</td>
                  <td className="num px-2 text-right">{rupees(x.value)}</td>
                  <td className={cn("num px-2 text-right", tone(x.pnl))}>
                    {x.pnl >= 0 ? "+" : "−"}₹{inr.format(Math.abs(x.pnl))} <span className="text-xs">({fmtPct(x.pnl_pct, 1)})</span>
                  </td>
                  <td className="num px-2 pr-5 text-right text-muted">{x.weight_pct.toFixed(1)}%</td>
                </tr>
              ))}
              <tr>
                <td className="py-2 pl-5 text-muted">Cash</td>
                <td colSpan={3} />
                <td className="num px-2 text-right">{rupees(p.cash)}</td>
                <td />
                <td className="num px-2 pr-5 text-right text-muted">{p.equity ? ((p.cash / p.equity) * 100).toFixed(1) : "0"}%</td>
              </tr>
            </tbody>
          </table>
          {d.positions.length === 0 && (
            <p className="px-5 pb-4 text-sm text-muted">
              {pending.length ? "Orders are pending: they fill at the next session's open." : "No holdings."}
            </p>
          )}
        </Card>

        <Card>
          <CardHeader title="Rules" />
          <CardBody>
            <ul className="list-disc space-y-1 pl-4 text-xs text-muted">
              <li>Top {p.params.top_n} by score, {p.params.rebalance} rebalance{p.params.max_risk ? `, risk up to ${p.params.max_risk}` : ""}{p.params.min_confidence ? `, confidence ≥ ${p.params.min_confidence}` : ""}</li>
              <li>Keep a holding while it stays in the top {p.params.rank_buffer ?? p.params.top_n} (fewer trades, lower charges)</li>
              <li>{p.params.stop_loss_pct ? `Stop-loss: sell if a close is ${p.params.stop_loss_pct}% below the buy price` : "No stop-loss"}</li>
              {p.params.trailing_stop_pct ? <li>Trailing stop: sell if a close is {p.params.trailing_stop_pct}% below the highest close since buying</li> : null}
              {p.params.min_history_bars ? <li>Only stocks with at least {p.params.min_history_bars} sessions (~{Math.round(p.params.min_history_bars / 252)} year) of price history</li> : null}
              {p.params.regime_slots && Object.keys(p.params.regime_slots).length ? (
                <li>Market regime limits: {Object.entries(p.params.regime_slots).map(([r, n]) => `${n} holding${n === 1 ? "" : "s"} when ${r.toLowerCase()}`).join(", ")}</li>
              ) : null}
              <li>Kill switch: sell everything and stop buying at a {p.params.kill_switch_pct}% drawdown</li>
              <li>Signals on the close; fills at the next session&apos;s open; whole shares; Zerodha delivery charges</li>
            </ul>
            <div className="mt-3 border-t border-line pt-3 text-[11px] text-faint">
              Each evening after 16:30 IST: <code className="font-mono text-muted">pnpm kite:login</code> then{" "}
              <code className="font-mono text-muted">pnpm daily:kite</code>. Missed days are caught up automatically.
            </div>
          </CardBody>
        </Card>
      </div>

      <Card className="mt-4 overflow-x-auto">
        <CardHeader title="Orders" subtitle="Every simulated order with its reason, fill and charges" />
        <table className="mt-2 w-full min-w-[860px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
              <th className="py-2 pl-5 font-medium">Decided</th>
              <th className="px-2 font-medium">Order</th>
              <th className="px-2 font-medium">Reason</th>
              <th className="px-2 font-medium">Status</th>
              <th className="px-2 text-right font-medium">Fill</th>
              <th className="px-2 text-right font-medium">Charges</th>
              <th className="px-2 pr-5 font-medium">Note</th>
            </tr>
          </thead>
          <tbody>
            {d.orders.map((o) => (
              <tr key={o.id} className="border-b border-line/60 last:border-0">
                <td className="num whitespace-nowrap py-2 pl-5 text-muted">{o.created_on}</td>
                <td className="whitespace-nowrap px-2">
                  <span className={o.side === "BUY" ? "text-up" : "text-down"}>{o.side}</span>{" "}
                  <span className="num">{o.qty}</span> <span className="font-mono text-xs">{o.symbol}</span>
                </td>
                <td className="px-2"><Badge tone={o.reason === "KILL_SWITCH" || o.reason === "STOP_LOSS" ? "down" : "neutral"}>{REASON[o.reason]}</Badge></td>
                <td className="px-2 text-xs text-muted">{o.status.toLowerCase()}</td>
                <td className="num whitespace-nowrap px-2 text-right text-muted">
                  {o.fill_price != null ? `₹${inr2.format(o.fill_price)} · ${o.fill_date}` : "—"}
                </td>
                <td className="num px-2 text-right text-muted">{o.charges ? `₹${inr2.format(o.charges)}` : "—"}</td>
                <td className="px-2 pr-5 text-xs text-faint">{o.note ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
