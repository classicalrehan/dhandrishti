import type { PriceSeries, StockDetail } from "@dd/contracts";
import { fmtCr, fmtNum, fmtPct, fmtPrice } from "@dd/shared";
import { Bot, CalendarClock, Newspaper } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ScoreRing } from "@/components/market/score-ring";
import { ProvenanceBanner } from "@/components/shell/provenance";
import { ComponentDetail } from "@/components/stock/component-detail";
import { EpsBars } from "@/components/stock/eps-bars";
import { MetricGrid } from "@/components/stock/metric-grid";
import { PriceChart } from "@/components/stock/price-chart";
import { ReasonList } from "@/components/stock/reasons";
import { ScoreBreakdown } from "@/components/stock/score-breakdown";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";
import { ApiState } from "@/components/ui/state";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/cn";
import { CONFIDENCE_LABEL, fmtDate, RISK_LABEL, RISK_TONE, TREND_LABEL } from "@/lib/labels";

const TABS = ["overview", "chart", "fundamentals", "technicals", "earnings", "valuation", "news", "risk"] as const;
type Tab = (typeof TABS)[number];

type Params = { params: Promise<{ symbol: string }>; searchParams: Promise<{ tab?: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { symbol } = await params;
  return { title: decodeURIComponent(symbol) };
}

const n = (v: unknown) => (typeof v === "number" ? v : null);

export default async function StockPage({ params, searchParams }: Params) {
  const symbol = decodeURIComponent((await params).symbol).toUpperCase();
  const tabParam = (await searchParams).tab;
  const tab: Tab = TABS.includes(tabParam as Tab) ? (tabParam as Tab) : "overview";

  const [res, prices] = await Promise.all([
    apiGet<StockDetail>(`/v1/stocks/${encodeURIComponent(symbol)}`),
    apiGet<PriceSeries>(`/v1/stocks/${encodeURIComponent(symbol)}/prices?range=1Y`),
  ]);
  if (!res.ok && res.kind === "not-found") notFound();
  if (!res.ok) return <ApiState result={res} />;

  const { security, score, fundamentals, upcoming_events } = res.data;
  const t = score.technicals;
  const f = fundamentals?.metrics ?? {};
  const fv = (k: string) => (f[k] ?? null) as number | null;

  return (
    <>
      <ProvenanceBanner meta={res.meta} />

      {/* Hero */}
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="font-mono">{security.exchange}: {security.symbol}</span>
            <span>·</span>
            <Link href="/sectors" className="hover:text-ink">{security.sector}</Link>
          </div>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">{security.name}</h1>
          <div className="mt-2 flex items-baseline gap-3">
            <span className="num text-2xl font-semibold">₹{fmtPrice(n(t.close))}</span>
            <Delta value={n(t.change_pct)} className="text-base" />
            <span className="text-xs text-faint">close · {fmtDate(score.as_of)}</span>
          </div>
          <Link
            href={`/research?q=${encodeURIComponent(`Why is ${security.name} (${security.symbol}) ranked #${score.rank}? What are its main risks?`)}`}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-brand/30 hover:text-ink"
          >
            <Bot aria-hidden className="size-3.5 text-brand" /> Ask AI about {security.symbol}
          </Link>
        </div>
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <ScoreRing score={score.total_score} size={72} stroke={6} />
            <div className="text-sm">
              <div className="text-muted">Score</div>
              <div className="num font-semibold">
                {score.total_score.toFixed(1)} <span className="font-normal text-faint">/ {score.max_score}</span>
              </div>
              <div className="text-xs text-faint">Rank #{score.rank}</div>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-5 gap-y-1 text-sm">
            <dt className="text-muted">Confidence</dt>
            <dd className="font-medium">{CONFIDENCE_LABEL[score.confidence]}</dd>
            <dt className="text-muted">Risk</dt>
            <dd>
              <Badge tone={RISK_TONE[score.risk_level]}>{RISK_LABEL[score.risk_level]}</Badge>
            </dd>
            <dt className="text-muted">Trend</dt>
            <dd className="font-medium">{TREND_LABEL[String(t.trend)] ?? "—"}</dd>
          </dl>
        </div>
      </div>

      {/* Tabs */}
      <nav aria-label="Sections" className="mt-6 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((k) => (
          <Link
            key={k}
            href={k === "overview" ? `/stock/${encodeURIComponent(symbol)}` : `/stock/${encodeURIComponent(symbol)}?tab=${k}`}
            aria-current={k === tab ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm capitalize whitespace-nowrap",
              k === tab ? "border-brand text-ink" : "border-transparent text-muted hover:text-ink",
            )}
            scroll={false}
          >
            {k}
          </Link>
        ))}
      </nav>

      <div className="mt-5">
        {tab === "overview" && (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader
                title={`Why is ${security.name} ranked #${score.rank}?`}
                subtitle={`Key strengths: ${score.key_reason}. Explanations are generated deterministically from the engine's metrics.`}
              />
              <CardBody className="grid gap-6 md:grid-cols-2">
                <div>
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-up">Supporting the score</h3>
                  <ReasonList items={score.top_positives} kind="positive" />
                </div>
                <div>
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-down">Holding it back</h3>
                  <ReasonList items={score.top_negatives} kind="negative" />
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Score breakdown" subtitle={`Model ${score.config_version} · data coverage ${Math.round(score.data_coverage * 100)}%`} />
              <CardBody>
                <ScoreBreakdown components={score.components} />
              </CardBody>
            </Card>
            <Card className="xl:col-span-2">
              <CardBody className="pt-5">
                {prices.ok ? (
                  <PriceChart symbol={symbol} initialBars={prices.data.bars} initialRange="1Y" />
                ) : (
                  <p className="text-sm text-muted">Price history unavailable: {prices.message}</p>
                )}
              </CardBody>
            </Card>
          </div>
        )}

        {tab === "chart" && (
          <Card>
            <CardBody className="pt-5">
              {prices.ok ? (
                <PriceChart symbol={symbol} initialBars={prices.data.bars} initialRange="1Y" />
              ) : (
                <p className="text-sm text-muted">Price history unavailable: {prices.message}</p>
              )}
            </CardBody>
          </Card>
        )}

        {tab === "fundamentals" && (
          <div className="grid gap-4">
            <Card>
              <CardHeader
                title="Fundamentals"
                subtitle={fundamentals ? `As of ${fmtDate(fundamentals.as_of)} · ${fundamentals.provenance}` : "Data unavailable"}
              />
              <CardBody>
                <MetricGrid
                  items={[
                    { label: "Market cap", value: fv("market_cap_cr") == null ? null : fmtCr(fv("market_cap_cr")) },
                    { label: "ROE", value: fv("roe") == null ? null : fmtPct(fv("roe"), 1, false) },
                    { label: "ROCE", value: fv("roce") == null ? null : fmtPct(fv("roce"), 1, false), hint: security.is_financial ? "Not applicable to financials" : undefined },
                    { label: "Operating margin", value: fv("operating_margin") == null ? null : fmtPct(fv("operating_margin"), 1, false) },
                    { label: "Net margin", value: fv("net_margin") == null ? null : fmtPct(fv("net_margin"), 1, false) },
                    { label: "Debt / Equity", value: fv("debt_to_equity") == null ? null : `${fmtNum(fv("debt_to_equity"))}x` },
                    { label: "Interest coverage", value: fv("interest_coverage") == null ? null : `${fmtNum(fv("interest_coverage"), 1)}x` },
                    { label: "Free cash flow", value: fv("free_cash_flow_cr") == null ? null : fmtCr(fv("free_cash_flow_cr")) },
                    { label: "CFO / PAT", value: fv("cfo_to_pat") == null ? null : `${fmtNum(fv("cfo_to_pat"))}x` },
                    { label: "Promoter holding", value: fv("promoter_holding") == null ? null : fmtPct(fv("promoter_holding"), 1, false) },
                    { label: "Promoter pledge", value: fv("promoter_pledge") == null ? null : fmtPct(fv("promoter_pledge"), 1, false) },
                    { label: "Institutional holding", value: fv("institutional_holding") == null ? null : fmtPct(fv("institutional_holding"), 1, false) },
                  ]}
                />
                {security.is_financial && (
                  <p className="mt-3 text-xs text-faint">Leverage and cash-flow metrics are not applicable to banks and NBFCs and are excluded from scoring.</p>
                )}
              </CardBody>
            </Card>
            <ComponentDetail c={score.components.fundamentals} />
          </div>
        )}

        {tab === "technicals" && (
          <div className="grid gap-4">
            <Card>
              <CardHeader title="Technicals" subtitle={`${TREND_LABEL[String(t.trend)] ?? "—"} · computed by the quant engine`} />
              <CardBody>
                <MetricGrid
                  items={[
                    { label: "20 DMA", value: n(t.sma20) == null ? null : fmtPrice(n(t.sma20)) },
                    { label: "50 DMA", value: n(t.sma50) == null ? null : fmtPrice(n(t.sma50)) },
                    { label: "200 DMA", value: n(t.sma200) == null ? null : fmtPrice(n(t.sma200)) },
                    { label: "Distance from 200 DMA", value: n(t.dist_from_sma200) == null ? null : fmtPct(n(t.dist_from_sma200), 1) },
                    { label: "RSI (14)", value: n(t.rsi14) == null ? null : fmtNum(n(t.rsi14), 1) },
                    { label: "MACD histogram", value: n(t.macd_hist) == null ? null : fmtNum(n(t.macd_hist), 2) },
                    { label: "ADX (14)", value: n(t.adx14) == null ? null : fmtNum(n(t.adx14), 1) },
                    { label: "ATR (14) % of price", value: n(t.atr_pct) == null ? null : fmtPct(n(t.atr_pct), 2, false) },
                    { label: "52-week high", value: n(t.high_52w) == null ? null : fmtPrice(n(t.high_52w)) },
                    { label: "52-week low", value: n(t.low_52w) == null ? null : fmtPrice(n(t.low_52w)) },
                    { label: "Volatility (60D, ann.)", value: n(t.volatility_60d) == null ? null : fmtPct(n(t.volatility_60d), 1, false) },
                    { label: "Relative volume", value: n(t.relative_volume) == null ? null : `${fmtNum(n(t.relative_volume))}x` },
                    { label: "Return 1W", value: n(t.ret_1w) == null ? null : fmtPct(n(t.ret_1w), 1) },
                    { label: "Return 1M", value: n(t.ret_1m) == null ? null : fmtPct(n(t.ret_1m), 1) },
                    { label: "Return 3M", value: n(t.ret_3m) == null ? null : fmtPct(n(t.ret_3m), 1) },
                    { label: "Return 6M", value: n(t.ret_6m) == null ? null : fmtPct(n(t.ret_6m), 1) },
                    { label: "Return 1Y", value: n(t.ret_1y) == null ? null : fmtPct(n(t.ret_1y), 1) },
                    { label: "RS vs NIFTY 50 (6M)", value: n(t.rs_nifty_6m) == null ? null : `${fmtPct(n(t.rs_nifty_6m), 1).replace("%", " pp")}` },
                  ]}
                />
              </CardBody>
            </Card>
            <div className="grid gap-4 xl:grid-cols-2">
              <ComponentDetail c={score.components.technicalTrend} />
              <ComponentDetail c={score.components.momentum} />
            </div>
          </div>
        )}

        {tab === "earnings" && (
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Quarterly EPS" subtitle="Last 12 quarters" />
              <CardBody>
                {fundamentals?.quarterly_eps?.length ? (
                  <EpsBars eps={fundamentals.quarterly_eps} />
                ) : (
                  <p className="text-sm text-muted">Data unavailable.</p>
                )}
              </CardBody>
            </Card>
            <ComponentDetail c={score.components.earningsGrowth} />
          </div>
        )}

        {tab === "valuation" && (
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Valuation multiples" subtitle="Interpreted against sector peers, own history and growth, never in isolation" />
              <CardBody>
                <MetricGrid
                  items={[
                    { label: "PE", value: fv("pe") == null ? null : `${fmtNum(fv("pe"), 1)}x` },
                    { label: "PE 5Y median", value: fv("pe_median_5y") == null ? null : `${fmtNum(fv("pe_median_5y"), 1)}x` },
                    { label: "PB", value: fv("pb") == null ? null : `${fmtNum(fv("pb"), 2)}x` },
                    { label: "PEG", value: fv("peg") == null ? null : fmtNum(fv("peg"), 2) },
                    { label: "Dividend yield", value: fv("dividend_yield") == null ? null : fmtPct(fv("dividend_yield"), 2, false) },
                  ]}
                />
              </CardBody>
            </Card>
            <ComponentDetail c={score.components.valuation} />
          </div>
        )}

        {tab === "news" && (
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Upcoming events" subtitle="Next 90 days" />
              <CardBody>
                {upcoming_events.length ? (
                  <ul className="space-y-2">
                    {upcoming_events.map((e) => (
                      <li key={`${e.date}-${e.type}`} className="flex items-center gap-3 text-sm">
                        <CalendarClock aria-hidden className="size-4 text-info" />
                        <span className="num w-28 text-muted">{fmtDate(e.date)}</span>
                        <span>{e.title}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">No scheduled events in the next 90 days.</p>
                )}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="News" />
              <CardBody className="flex items-start gap-3 text-sm text-muted">
                <Newspaper aria-hidden className="mt-0.5 size-4 shrink-0" />
                No news provider is connected. DhanDrishti does not generate or simulate headlines.
              </CardBody>
            </Card>
          </div>
        )}

        {tab === "risk" && (
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader
                title={`Risk: ${RISK_LABEL[score.risk_level]}`}
                subtitle={`${score.risk_points} penalty point${score.risk_points === 1 ? "" : "s"} · 0–1 Low, 2–3 Medium, 4–5 High, 6+ Very high`}
              />
              <CardBody>
                {score.risk_flags.length ? (
                  <ul className="space-y-2">
                    {score.risk_flags.map((fl) => (
                      <li key={fl.code} className="flex items-start gap-2 text-sm">
                        <Badge tone={fl.severity === "EXTREME" ? "down" : fl.severity === "ELEVATED" ? "warn" : "info"} className="shrink-0">
                          {fl.severity.toLowerCase()} · {fl.points} pt
                        </Badge>
                        <span>{fl.message}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">No risk flags triggered.</p>
                )}
              </CardBody>
            </Card>
            <ComponentDetail c={score.components.risk} />
          </div>
        )}
      </div>
    </>
  );
}
