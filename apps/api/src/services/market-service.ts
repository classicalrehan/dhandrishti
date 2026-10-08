/**
 * Application service: orchestrates repository reads into API views.
 *
 * It shapes and filters engine output; it never computes scores, indicators or
 * risk. Those come precomputed from the Python worker (score_history etc.).
 */
import {
  type HoldingRow,
  type HoldingsView,
  type PaperDetail,
  type PaperSummary,
  type BacktestDetail,
  type BacktestRunSummary,
  type Comparison,
  CONFIDENCE_ORDER,
  RISK_ORDER,
  type MarketOverview,
  type Meta,
  type OpportunitiesQuery,
  type OpportunityRow,
  type PriceRange,
  type PriceSeries,
  type RiskRadarRow,
  type ScoringConfigSummary,
  type StockDetail,
  type StockScore,
} from "@dd/contracts";
import { COMPONENT_ORDER, SCORING_CONFIG } from "@dd/config";
import { NoDataError, NotFoundError } from "../errors";
import type { HoldingItem, MarketRepository, RunContext } from "../repositories/market-repository";

export const OVERVIEW_INDICES = ["NIFTY 50", "NIFTY BANK", "INDIA VIX"];
const RANGE_DAYS: Record<PriceRange, number | null> = { "1M": 31, "3M": 92, "6M": 183, "1Y": 366, MAX: null };
const EVENT_HORIZON_DAYS = 90;

export interface Result<T> {
  data: T;
  meta: Meta;
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Display label for the momentum component, using the spec's reason thresholds. */
export function momentumLabel(normalized: number): OpportunityRow["momentum"] {
  const t = SCORING_CONFIG.reason_thresholds as { positive: number; negative: number };
  if (normalized >= t.positive) return "Strong";
  if (normalized <= t.negative) return "Weak";
  return "Moderate";
}

export function toOpportunity(s: StockScore): OpportunityRow {
  const t = s.technicals;
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  return {
    rank: s.rank,
    symbol: s.symbol,
    name: s.name,
    sector: s.sector,
    price: num(t.close) ?? 0,
    change: num(t.change),
    change_pct: num(t.change_pct),
    total_score: s.total_score,
    confidence: s.confidence,
    risk_level: s.risk_level,
    momentum: momentumLabel(s.components.momentum.normalized_score),
    trend: typeof t.trend === "string" ? t.trend : "SIDEWAYS",
    key_reason: s.key_reason,
  };
}

function toRiskRow(s: StockScore): RiskRadarRow {
  return {
    symbol: s.symbol,
    name: s.name,
    sector: s.sector,
    total_score: s.total_score,
    risk_level: s.risk_level,
    risk_points: s.risk_points,
    flags: s.risk_flags,
  };
}

export class MarketService {
  constructor(
    private readonly repo: MarketRepository,
    private readonly now: () => Date = () => new Date(),
  ) {}

  private async context(): Promise<{ ctx: RunContext; meta: Meta }> {
    const ctx = await this.repo.latestRun();
    if (!ctx) throw new NoDataError();
    return {
      ctx,
      meta: {
        as_of: ctx.as_of,
        data_provenance: ctx.provenance,
        config_version: ctx.config_version,
        generated_at: this.now().toISOString(),
      },
    };
  }

  async overview(): Promise<Result<MarketOverview>> {
    const { ctx, meta } = await this.context();
    const [scores, sectors, regime, bars] = await Promise.all([
      this.repo.scores(ctx),
      this.repo.sectors(ctx),
      this.repo.regime(ctx),
      this.repo.indexBars(OVERVIEW_INDICES, ctx.as_of, 30),
    ]);
    if (!regime) throw new NoDataError("Market regime not available for the latest run");

    const indices = OVERVIEW_INDICES.flatMap((code) => {
      const series = bars.filter((b) => b.code === code);
      const last = series.at(-1);
      if (!last) return [];
      const prev = series.at(-2);
      return [
        {
          code,
          close: last.close,
          change: prev ? last.close - prev.close : null,
          change_pct: prev ? (last.close / prev.close - 1) * 100 : null,
          high: last.high,
          low: last.low,
          sparkline: series.map((b) => ({ date: b.date, close: b.close })),
        },
      ];
    });

    return {
      meta,
      data: {
        indices,
        breadth: regime.breadth,
        regime: regime.regime,
        sectors,
        top_opportunities: scores.slice(0, 5).map(toOpportunity),
        risk_radar: this.riskRows(scores).slice(0, 6),
      },
    };
  }

  async opportunities(q: OpportunitiesQuery): Promise<Result<OpportunityRow[]>> {
    const { ctx, meta } = await this.context();
    const minConf = q.min_confidence ? CONFIDENCE_ORDER.indexOf(q.min_confidence) : 0;
    const maxRisk = q.max_risk ? RISK_ORDER.indexOf(q.max_risk) : RISK_ORDER.length - 1;
    const rows = (await this.repo.scores(ctx))
      .filter((s) => !q.sector || s.sector === q.sector)
      .filter((s) => CONFIDENCE_ORDER.indexOf(s.confidence) >= minConf)
      .filter((s) => RISK_ORDER.indexOf(s.risk_level) <= maxRisk)
      .slice(0, q.limit)
      .map(toOpportunity);
    return { meta, data: rows };
  }

  async stock(symbol: string): Promise<Result<StockDetail>> {
    const { ctx, meta } = await this.context();
    const [security, score, fundamentals, events, history] = await Promise.all([
      this.repo.security(symbol),
      this.repo.score(ctx, symbol),
      this.repo.fundamentals(symbol, ctx.as_of),
      this.repo.events(symbol, ctx.as_of, addDays(ctx.as_of, EVENT_HORIZON_DAYS)),
      this.repo.scoreHistory(symbol, ctx.config_version, 60),
    ]);
    if (!security || !score) throw new NotFoundError(`No score for ${symbol} as of ${ctx.as_of}`);
    return { meta, data: { security, score, fundamentals, upcoming_events: events, score_history: history } };
  }

  async prices(symbol: string, range: PriceRange): Promise<Result<PriceSeries>> {
    const { ctx, meta } = await this.context();
    const days = RANGE_DAYS[range];
    const bars = await this.repo.prices(symbol, ctx.as_of, days == null ? null : addDays(ctx.as_of, -days));
    if (bars.length === 0) throw new NotFoundError(`No price history for ${symbol}`);
    return { meta, data: { symbol, range, bars } };
  }

  async sectors() {
    const { ctx, meta } = await this.context();
    return { meta, data: await this.repo.sectors(ctx) };
  }

  async riskRadar(): Promise<Result<RiskRadarRow[]>> {
    const { ctx, meta } = await this.context();
    return { meta, data: this.riskRows(await this.repo.scores(ctx)) };
  }

  async search(q: string) {
    const { meta } = await this.context();
    return { meta, data: await this.repo.search(q, 10) };
  }

  async scoringConfig(): Promise<Result<ScoringConfigSummary>> {
    const { meta } = await this.context();
    return {
      meta,
      data: {
        version: SCORING_CONFIG.version,
        components: COMPONENT_ORDER.map((key) => ({
          key,
          label: SCORING_CONFIG.components[key].label,
          weight: SCORING_CONFIG.components[key].weight,
        })),
      },
    };
  }

  async scoreHistory(symbol: string, limit: number) {
    const { ctx, meta } = await this.context();
    if (!(await this.repo.security(symbol))) throw new NotFoundError(`Unknown symbol ${symbol}`);
    return { meta, data: await this.repo.scoreHistory(symbol, ctx.config_version, limit) };
  }

  async rankingHistory(days: number, top: number) {
    const { ctx, meta } = await this.context();
    return { meta, data: await this.repo.rankingHistory(ctx.config_version, days, top) };
  }

  /** Side-by-side engine output. Deliberately names no "winner": the scores speak for themselves. */
  async compare(symbols: string[]): Promise<Result<Comparison>> {
    const { ctx, meta } = await this.context();
    const scores = await Promise.all(symbols.map((s) => this.repo.score(ctx, s)));
    const stocks = scores.flatMap((s) =>
      s
        ? [
            {
              symbol: s.symbol,
              name: s.name,
              sector: s.sector,
              rank: s.rank,
              total_score: s.total_score,
              confidence: s.confidence,
              risk_level: s.risk_level,
              risk_points: s.risk_points,
              key_reason: s.key_reason,
              components: Object.fromEntries(
                COMPONENT_ORDER.map((k) => {
                  const c = s.components[k];
                  return [k, { label: c.label, score: c.score, max: c.max, coverage: c.coverage }];
                }),
              ) as Comparison["stocks"][number]["components"],
              top_positives: s.top_positives,
              top_negatives: s.top_negatives,
            },
          ]
        : [],
    );
    const not_found = symbols.filter((_, i) => !scores[i]);
    return { meta, data: { stocks, not_found } };
  }

  async news(symbol: string | null, limit: number) {
    const { meta } = await this.context();
    return { meta, data: await this.repo.news(symbol, limit) };
  }

  async backtests(limit = 50): Promise<Result<BacktestRunSummary[]>> {
    const { meta } = await this.context();
    return { meta, data: await this.repo.backtestRuns(limit) };
  }

  /** Meta describes the backtest itself: its end date, data provenance and scoring model. */
  async backtest(id: number): Promise<Result<BacktestDetail>> {
    const detail = await this.repo.backtest(id);
    if (!detail) throw new NotFoundError(`No backtest ${id}`);
    const { run, metrics } = detail;
    return {
      meta: {
        as_of: metrics?.period.end ?? run.params.end,
        data_provenance: run.provenance,
        config_version: run.config_version,
        generated_at: this.now().toISOString(),
      },
      data: detail,
    };
  }

  async paperPortfolios(): Promise<Result<PaperSummary[]>> {
    const { meta } = await this.context();
    return { meta, data: await this.repo.paperPortfolios() };
  }

  /** Meta describes the portfolio: last processed session and the provenance of its prices. */
  async paperPortfolio(id: number): Promise<Result<PaperDetail>> {
    const detail = await this.repo.paperPortfolio(id);
    if (!detail) throw new NotFoundError(`No paper portfolio ${id}`);
    const p = detail.portfolio;
    return {
      meta: {
        as_of: p.last_processed,
        data_provenance: p.provenance,
        config_version: (await this.repo.latestRun())?.config_version ?? "unknown",
        generated_at: this.now().toISOString(),
      },
      data: detail,
    };
  }

  /**
   * Your real Zerodha holdings (latest snapshot) joined with the latest scores. The watch notes
   * are fixed rules over engine output, not advice. Deliberately not exposed to the AI assistant.
   */
  async holdings(): Promise<Result<HoldingsView>> {
    const snap = await this.repo.holdings();
    if (!snap) throw new NotFoundError("No holdings fetched yet. Run `pnpm holdings` (or `pnpm daily:kite`).");
    const ctx = await this.repo.latestRun();
    const scores = ctx ? await this.repo.scores(ctx) : [];
    const bySymbol = new Map(scores.map((s) => [s.symbol, s]));
    const universe = scores.reduce((n, s) => Math.max(n, s.rank), 0);

    const held = snap.items.filter((i) => i.kind === "HOLDING" && i.qty > 0);
    const value = held.reduce((a, i) => a + i.qty * i.last_price, 0);
    const invested = held.reduce((a, i) => a + i.qty * i.avg_price, 0);
    const priced = held.filter((i) => i.close_price != null && i.close_price > 0);
    const dayChange = priced.length ? priced.reduce((a, i) => a + i.qty * (i.last_price - i.close_price!), 0) : null;

    const holdings = held
      .map((i) => toHoldingRow(i, value, bySymbol.get(i.symbol), universe))
      .sort((a, b) => b.value - a.value);
    const first = snap.history[0]!;
    const last = snap.history.at(-1)!;
    return {
      meta: {
        as_of: snap.as_of,
        data_provenance: ctx?.provenance ?? "EOD",
        config_version: ctx?.config_version ?? "unknown",
        generated_at: this.now().toISOString(),
      },
      data: {
        as_of: snap.as_of,
        fetched_at: snap.fetched_at,
        scores_as_of: ctx?.as_of ?? null,
        value,
        invested,
        pnl: value - invested,
        pnl_pct: invested ? (value / invested - 1) * 100 : null,
        day_change: dayChange,
        since: first.date,
        return_pct: (last.twr_index / 100 - 1) * 100,
        nifty_return_pct:
          first.nifty_close && last.nifty_close ? (last.nifty_close / first.nifty_close - 1) * 100 : null,
        holdings,
        positions: snap.items
          .filter((i) => i.kind === "POSITION")
          .map(({ symbol, exchange, product, qty, avg_price, last_price, pnl }) => ({
            symbol, exchange, product, qty, avg_price, last_price, pnl,
          })),
        history: snap.history,
      },
    };
  }

  /** Stocks with at least one penalised risk flag, most risky first. */
  private riskRows(scores: StockScore[]): RiskRadarRow[] {
    return scores
      .filter((s) => s.risk_flags.some((f) => f.points > 0))
      .sort((a, b) => b.risk_points - a.risk_points || a.symbol.localeCompare(b.symbol))
      .map(toRiskRow);
  }
}

/** Thresholds for the holdings watch notes (display rules only; scores come from the worker). */
export const WATCH = { bottomFraction: 2 / 3, lossPct: -10, concentrationPct: 25 } as const;

function toHoldingRow(i: HoldingItem, total: number, s: StockScore | undefined, universe: number): HoldingRow {
  const value = i.qty * i.last_price;
  const invested = i.qty * i.avg_price;
  const pnlPct = invested ? (value / invested - 1) * 100 : null;
  const weight = total ? (value / total) * 100 : 0;
  const trend = s && typeof s.technicals.trend === "string" ? s.technicals.trend : "SIDEWAYS";
  const watch: string[] = [];
  if (s && s.rank > Math.ceil(universe * WATCH.bottomFraction)) {
    watch.push(`Ranked ${s.rank} of ${universe}: bottom third of the scored stocks`);
  }
  if (s && (s.risk_level === "HIGH" || s.risk_level === "VERY_HIGH")) {
    const flags = s.risk_flags.filter((f) => f.points > 0).map((f) => f.message).slice(0, 2);
    watch.push(`${s.risk_level === "HIGH" ? "High" : "Very high"} risk${flags.length ? `: ${flags.join("; ")}` : ""}`);
  }
  if (trend.includes("DOWNTREND")) watch.push("Price is in a downtrend (below its moving averages)");
  if (pnlPct != null && pnlPct <= WATCH.lossPct) {
    watch.push(`Down ${Math.abs(pnlPct).toFixed(1)}% from your average buy price (paper portfolios sell at −10%)`);
  }
  if (weight > WATCH.concentrationPct) watch.push(`${weight.toFixed(0)}% of your portfolio is in this one stock`);
  return {
    symbol: i.symbol,
    exchange: i.exchange,
    name: s?.name ?? null,
    sector: s?.sector ?? null,
    qty: i.qty,
    t1_qty: i.t1_qty,
    avg_price: i.avg_price,
    last_price: i.last_price,
    value,
    invested,
    pnl: value - invested,
    pnl_pct: pnlPct,
    day_change_pct: i.close_price ? (i.last_price / i.close_price - 1) * 100 : null,
    weight_pct: weight,
    score: s
      ? {
          rank: s.rank,
          of: universe,
          total_score: s.total_score,
          confidence: s.confidence,
          risk_level: s.risk_level,
          trend,
          key_reason: s.key_reason,
        }
      : null,
    watch,
  };
}
