import type { HoldingRow, HoldingsView, PaperSummary } from "@dd/contracts";
import { fmtPct } from "@dd/shared";
import { Briefcase, Lock } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { EquityChart } from "@/components/backtest/equity-chart";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/cn";
import { RISK_LABEL, RISK_TONE, TREND_LABEL, fmtDate } from "@/lib/labels";

export const metadata: Metadata = { title: "My Portfolio" };

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rupees = (v: number) => `₹${inr.format(v)}`;
const signed = (v: number) => `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(v))}`;
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "text-muted" : v > 0 ? "text-up" : "text-down");

function Stat({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cn("num mt-1 text-2xl font-semibold", className)}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-faint">{sub}</div>}
    </Card>
  );
}

export default async function PortfolioPage() {
  const header = (
    <PageHeader
      title="My Portfolio"
      subtitle="Your real Zerodha holdings, read-only, next to how DhanDrishti scores each stock today."
    />
  );
  const [res, paper] = await Promise.all([apiGet<HoldingsView>("/v1/holdings"), apiGet<PaperSummary[]>("/v1/paper")]);
  if (!res.ok && res.kind === "not-found") {
    return (
      <>
        {header}
        <Card className="p-6 text-sm text-muted">
          <Briefcase aria-hidden className="mb-2 size-6 text-brand" />
          No holdings fetched yet. With the real-price app running (<code className="font-mono">pnpm dev:kite</code>), fetch them:
          <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink">
            {"pnpm kite:login\npnpm holdings          # also part of pnpm daily:kite"}
          </pre>
        </Card>
      </>
    );
  }
  if (!res.ok) return (<>{header}<ApiState result={res} /></>);
  return (
    <>
      {header}
      <PortfolioView d={res.data} paper={paper.ok ? paper.data : []} />
    </>
  );
}

function PortfolioView({ d, paper }: { d: HoldingsView; paper: PaperSummary[] }) {
  const base = d.history[0]?.value ?? d.value;
  const nifty0 = d.history.find((p) => p.nifty_close != null)?.nifty_close ?? null;
  let peak = 0;
  const curve = d.history.map((p) => {
    const mine = (base * p.twr_index) / 100;
    peak = Math.max(peak, mine);
    return {
      date: p.date,
      mine,
      nifty: nifty0 && p.nifty_close ? (base * p.nifty_close) / nifty0 : mine,
      drawdown_pct: peak ? (mine / peak - 1) * 100 : 0,
    };
  });
  const flagged = d.holdings.filter((h) => h.watch.length > 0).length;
  const unscored = d.holdings.filter((h) => !h.score).length;
  const days = d.history.length;

  return (
    <>
      <div role="note" className="mb-4 flex items-start gap-2 rounded-lg border border-info/30 bg-info/[0.07] px-4 py-3 text-sm">
        <Lock aria-hidden className="mt-0.5 size-4 shrink-0 text-info" />
        <span>
          <span className="font-semibold text-info">Read-only and private.</span> Fetched from Zerodha at{" "}
          {new Date(d.fetched_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" })} IST.
          Nothing is ever bought or sold, the data stays in your local database, and the AI assistant cannot see it.
          The &ldquo;worth a look&rdquo; notes are fixed rules, not advice.
        </span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Current value" value={rupees(d.value)} sub={`${d.holdings.length} stock${d.holdings.length === 1 ? "" : "s"} · invested ${rupees(d.invested)}`} />
        <Stat label="Total P&L" value={signed(d.pnl)} className={tone(d.pnl)} sub={d.pnl_pct == null ? undefined : `${fmtPct(d.pnl_pct, 2)} on your buy prices`} />
        <Stat label="Today" value={d.day_change == null ? "—" : signed(d.day_change)} className={tone(d.day_change)} sub="vs the previous close" />
        <Stat
          label={`Since tracking began (${fmtDate(d.since)})`}
          value={days >= 2 ? fmtPct(d.return_pct, 2) : "—"}
          className={days >= 2 ? tone(d.return_pct) : undefined}
          sub={days < 2 ? "Needs a second day of snapshots" : d.nifty_return_pct == null ? "NIFTY: n/a" : `NIFTY: ${fmtPct(d.nifty_return_pct, 2)}`}
        />
      </div>

      <Card className="mt-4 overflow-x-auto">
        <CardHeader
          title="Holdings and their DhanDrishti scores"
          subtitle={`Prices at fetch time · scores from ${d.scores_as_of ? fmtDate(d.scores_as_of) : "no scoring run yet"}${flagged ? ` · ${flagged} worth a look` : ""}${unscored ? ` · ${unscored} outside the 44 scored stocks` : ""}`}
        />
        <table className="mt-2 w-full min-w-[980px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
              <th className="py-2 pl-5 font-medium">Stock</th>
              <th className="px-2 text-right font-medium">Qty</th>
              <th className="px-2 text-right font-medium">Avg buy</th>
              <th className="px-2 text-right font-medium">Price</th>
              <th className="px-2 text-right font-medium">Value</th>
              <th className="px-2 text-right font-medium">P&amp;L</th>
              <th className="px-2 text-right font-medium">Rank</th>
              <th className="px-2 text-right font-medium">Score</th>
              <th className="px-2 font-medium">Risk · trend</th>
              <th className="px-2 pr-5 font-medium">Worth a look</th>
            </tr>
          </thead>
          <tbody>
            {d.holdings.map((h) => <Row key={`${h.exchange}:${h.symbol}`} h={h} />)}
          </tbody>
        </table>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardBody className="pt-5">
            {curve.length >= 2 ? (
              <EquityChart
                equity={curve}
                series={[{ key: "mine", label: "My holdings" }, { key: "nifty", label: "NIFTY 50 (same start)" }]}
                caption={`Time-weighted: buying more or adding money is not counted as profit. Both lines start at your value on ${fmtDate(d.since)}. Lower pane: drawdown from the peak.`}
              />
            ) : (
              <p className="py-10 text-center text-sm text-muted">
                The comparison chart appears after a second day of snapshots. <code className="font-mono">pnpm daily:kite</code> saves one each evening.
              </p>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="You vs the paper portfolios" subtitle="Each since its own start date" />
          <CardBody>
            <ul className="space-y-2 text-sm">
              <li className="flex justify-between gap-3">
                <span>My holdings <span className="text-xs text-faint">since {fmtDate(d.since)}</span></span>
                <span className={cn("num", days >= 2 ? tone(d.return_pct) : "text-muted")}>{days >= 2 ? fmtPct(d.return_pct, 2) : "—"}</span>
              </li>
              {paper.filter((p) => p.status !== "CLOSED").map((p) => (
                <li key={p.id} className="flex justify-between gap-3">
                  <Link href={`/paper?id=${p.id}`} className="hover:underline">
                    #{p.id} {p.name} <span className="text-xs text-faint">since {fmtDate(p.start_date)}</span>
                  </Link>
                  <span className={cn("num", tone(p.return_pct))}>{fmtPct(p.return_pct, 2)}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 border-t border-line pt-3 text-[11px] text-faint">
              Different start dates are not a fair race. Compare over the same months once both have a few months of history.
            </p>
          </CardBody>
        </Card>
      </div>

      {d.positions.length > 0 && (
        <Card className="mt-4 overflow-x-auto">
          <CardHeader title="Open positions" subtitle="Intraday, F&O or today's delivery buys (not scored)" />
          <table className="mt-2 w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="py-2 pl-5 font-medium">Instrument</th>
                <th className="px-2 font-medium">Product</th>
                <th className="px-2 text-right font-medium">Qty</th>
                <th className="px-2 text-right font-medium">Avg</th>
                <th className="px-2 text-right font-medium">Last</th>
                <th className="px-2 pr-5 text-right font-medium">P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {d.positions.map((p) => (
                <tr key={`${p.exchange}:${p.symbol}:${p.product}`} className="border-b border-line/60 last:border-0">
                  <td className="py-2 pl-5 font-mono text-xs">{p.symbol} <span className="text-faint">{p.exchange}</span></td>
                  <td className="px-2 text-xs text-muted">{p.product}</td>
                  <td className="num px-2 text-right">{p.qty}</td>
                  <td className="num px-2 text-right text-muted">{inr2.format(p.avg_price)}</td>
                  <td className="num px-2 text-right">{inr2.format(p.last_price)}</td>
                  <td className={cn("num px-2 pr-5 text-right", tone(p.pnl))}>{signed(p.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}

function Row({ h }: { h: HoldingRow }) {
  const s = h.score;
  return (
    <tr className="border-b border-line/60 align-top last:border-0">
      <td className="py-2 pl-5">
        {s ? (
          <Link href={`/stock/${encodeURIComponent(h.symbol)}`} className="font-medium hover:underline">{h.name ?? h.symbol}</Link>
        ) : (
          <span className="font-medium">{h.symbol}</span>
        )}
        <div className="font-mono text-[11px] text-faint">
          {h.symbol} · {h.exchange}{h.sector ? ` · ${h.sector}` : ""}{h.t1_qty ? ` · ${h.t1_qty} in T1` : ""}
        </div>
      </td>
      <td className="num px-2 text-right">{h.qty}</td>
      <td className="num px-2 text-right text-muted">{inr2.format(h.avg_price)}</td>
      <td className="num px-2 text-right">
        {inr2.format(h.last_price)}
        {h.day_change_pct != null && <div className={cn("text-[11px]", tone(h.day_change_pct))}>{fmtPct(h.day_change_pct, 2)}</div>}
      </td>
      <td className="num px-2 text-right">
        {rupees(h.value)}
        <div className="text-[11px] text-faint">{h.weight_pct.toFixed(1)}%</div>
      </td>
      <td className={cn("num px-2 text-right", tone(h.pnl))}>
        {signed(h.pnl)}
        {h.pnl_pct != null && <div className="text-[11px]">{fmtPct(h.pnl_pct, 1)}</div>}
      </td>
      <td className="num px-2 text-right">{s ? <>{s.rank}<span className="text-faint">/{s.of}</span></> : <span className="text-faint">—</span>}</td>
      <td className="num px-2 text-right font-semibold">{s ? s.total_score.toFixed(1) : <span className="font-normal text-faint">—</span>}</td>
      <td className="px-2">
        {s ? (
          <div className="flex flex-wrap gap-1">
            <Badge tone={RISK_TONE[s.risk_level]}>{RISK_LABEL[s.risk_level]}</Badge>
            <Badge>{TREND_LABEL[s.trend] ?? s.trend}</Badge>
          </div>
        ) : (
          <span className="text-xs text-faint">Not scored</span>
        )}
      </td>
      <td className="max-w-[280px] px-2 pr-5 text-xs">
        {h.watch.length ? (
          <ul className="space-y-0.5 text-warn">{h.watch.map((w) => <li key={w}>{w}</li>)}</ul>
        ) : s ? (
          <span className="text-faint">Nothing flagged</span>
        ) : (
          <span className="text-faint">Outside the scored universe</span>
        )}
      </td>
    </tr>
  );
}
