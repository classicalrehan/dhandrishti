import pg from "pg";
import type {
  BacktestDetail,
  BacktestRunSummary,
  Breadth,
  PaperDetail,
  PaperSummary,
  Regime,
  SectorStrength,
  StockScore,
} from "@dd/contracts";
import type {
  HoldingsSnapshot,
  FundamentalsRow,
  IndexBar,
  MarketRepository,
  PriceRow,
  RunContext,
} from "./market-repository";

// Keep DATE columns as 'YYYY-MM-DD' strings (no timezone shifting) and BIGINT as numbers
// (volumes are far below 2^53).
pg.types.setTypeParser(1082, (v) => v);
pg.types.setTypeParser(20, (v) => Number(v));

const FUNDAMENTAL_METRICS = [
  "market_cap_cr",
  "revenue_growth_yoy",
  "profit_growth_yoy",
  "eps_growth_yoy",
  "eps_cagr_3y",
  "roe",
  "roce",
  "operating_margin",
  "net_margin",
  "free_cash_flow_cr",
  "cfo_to_pat",
  "debt_to_equity",
  "interest_coverage",
  "pe",
  "pb",
  "peg",
  "dividend_yield",
  "promoter_holding",
  "promoter_pledge",
  "institutional_holding",
  "pe_median_5y",
  "positive_eps_quarters_8",
] as const;

export class PgMarketRepository implements MarketRepository {
  constructor(private readonly pool: pg.Pool) {}

  async ping(): Promise<void> {
    await this.pool.query("SELECT 1");
  }

  async latestRun(onOrBefore?: string): Promise<RunContext | null> {
    const { rows } = await this.pool.query(
      `SELECT id::int AS run_id, as_of, config_version, provenance FROM scoring_runs
       WHERE status = 'SUCCEEDED' AND ($1::date IS NULL OR as_of <= $1::date)
       ORDER BY as_of DESC, id DESC LIMIT 1`,
      [onOrBefore ?? null],
    );
    return rows[0] ?? null;
  }

  async scores(ctx: RunContext): Promise<StockScore[]> {
    const { rows } = await this.pool.query(
      `SELECT result FROM score_history WHERE as_of = $1 AND config_version = $2 ORDER BY rank`,
      [ctx.as_of, ctx.config_version],
    );
    return rows.map((r) => r.result);
  }

  async score(ctx: RunContext, symbol: string): Promise<StockScore | null> {
    const { rows } = await this.pool.query(
      `SELECT result FROM score_history WHERE as_of = $1 AND config_version = $2 AND symbol = $3`,
      [ctx.as_of, ctx.config_version, symbol],
    );
    return rows[0]?.result ?? null;
  }

  async scoreHistory(symbol: string, configVersion: string, limit: number) {
    const { rows } = await this.pool.query(
      `SELECT as_of, total_score, rank, confidence, risk_level FROM score_history
       WHERE symbol = $1 AND config_version = $2 ORDER BY as_of DESC LIMIT $3`,
      [symbol, configVersion, limit],
    );
    return rows.reverse();
  }

  async rankingHistory(configVersion: string, days: number, top: number) {
    const { rows } = await this.pool.query(
      `WITH dates AS (
         SELECT DISTINCT as_of FROM score_history WHERE config_version = $1 ORDER BY as_of DESC LIMIT $2)
       SELECT s.as_of, s.rank, s.symbol, s.total_score FROM score_history s JOIN dates d USING (as_of)
       WHERE s.config_version = $1 AND s.rank <= $3 ORDER BY s.as_of, s.rank`,
      [configVersion, days, top],
    );
    const byDate = new Map<string, { rank: number; symbol: string; total_score: number }[]>();
    for (const r of rows) {
      if (!byDate.has(r.as_of)) byDate.set(r.as_of, []);
      byDate.get(r.as_of)!.push({ rank: r.rank, symbol: r.symbol, total_score: r.total_score });
    }
    return [...byDate].map(([as_of, list]) => ({ as_of, rows: list }));
  }

  async news(symbol: string | null, limit: number) {
    const { rows } = await this.pool.query(
      `SELECT symbol, to_char(published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS published_at,
              headline, summary, url, source, provenance
       FROM news_items WHERE ($1::text IS NULL OR symbol = $1) ORDER BY published_at DESC LIMIT $2`,
      [symbol, limit],
    );
    return rows;
  }

  async sectors(ctx: RunContext): Promise<SectorStrength[]> {
    const { rows } = await this.pool.query(
      `SELECT detail FROM sector_strength_history WHERE as_of = $1 AND config_version = $2 ORDER BY rank`,
      [ctx.as_of, ctx.config_version],
    );
    return rows.map((r) => r.detail);
  }

  async regime(ctx: RunContext): Promise<{ regime: Regime; breadth: Breadth } | null> {
    const { rows } = await this.pool.query(
      `SELECT regime, composite, confidence, factors, reason, breadth FROM market_regime_history
       WHERE as_of = $1 AND config_version = $2`,
      [ctx.as_of, ctx.config_version],
    );
    const r = rows[0];
    if (!r) return null;
    return {
      regime: { regime: r.regime, composite: r.composite, confidence: r.confidence, factors: r.factors, reason: r.reason },
      breadth: r.breadth,
    };
  }

  async indexBars(codes: string[], asOf: string, perIndex: number): Promise<IndexBar[]> {
    const { rows } = await this.pool.query(
      `SELECT code, date, open, high, low, close FROM (
         SELECT index_code AS code, trade_date AS date, open, high, low, close,
                row_number() OVER (PARTITION BY index_code ORDER BY trade_date DESC) AS rn
         FROM index_prices WHERE index_code = ANY($1) AND trade_date <= $2) t
       WHERE rn <= $3 ORDER BY code, date`,
      [codes, asOf, perIndex],
    );
    return rows;
  }

  async security(symbol: string) {
    const { rows } = await this.pool.query(
      `SELECT symbol, name, exchange, sector, industry, is_financial FROM securities WHERE symbol = $1`,
      [symbol],
    );
    return rows[0] ?? null;
  }

  async search(q: string, limit: number) {
    const { rows } = await this.pool.query(
      `SELECT symbol, name, sector FROM securities
       WHERE active AND (symbol ILIKE $1 || '%' OR name ILIKE '%' || $1 || '%')
       ORDER BY (symbol ILIKE $1 || '%') DESC, symbol LIMIT $2`,
      [q.replace(/[%_\\]/g, "\\$&"), limit],
    );
    return rows;
  }

  async fundamentals(symbol: string, asOf: string): Promise<FundamentalsRow | null> {
    const { rows } = await this.pool.query(
      `SELECT as_of, provenance, quarterly_eps, ${FUNDAMENTAL_METRICS.join(", ")}
       FROM fundamentals WHERE symbol = $1 AND as_of <= $2 ORDER BY as_of DESC LIMIT 1`,
      [symbol, asOf],
    );
    const r = rows[0];
    if (!r) return null;
    return {
      as_of: r.as_of,
      provenance: r.provenance,
      quarterly_eps: r.quarterly_eps,
      metrics: Object.fromEntries(FUNDAMENTAL_METRICS.map((m) => [m, r[m]])),
    };
  }

  async events(symbol: string, after: string, until: string) {
    const { rows } = await this.pool.query(
      `SELECT event_date AS date, event_type AS type, title FROM corporate_events
       WHERE symbol = $1 AND event_date > $2 AND event_date <= $3 ORDER BY event_date, event_type`,
      [symbol, after, until],
    );
    return rows;
  }

  async prices(symbol: string, asOf: string, from: string | null): Promise<PriceRow[]> {
    const { rows } = await this.pool.query(
      `SELECT p.trade_date AS date, p.open, p.high, p.low, p.close, p.volume,
              i.sma20, i.sma50, i.sma200, i.rsi14, i.macd, i.macd_signal, i.macd_hist
       FROM daily_prices p
       LEFT JOIN indicator_series i ON i.symbol = p.symbol AND i.trade_date = p.trade_date
       WHERE p.symbol = $1 AND p.trade_date <= $2 AND ($3::date IS NULL OR p.trade_date >= $3::date)
       ORDER BY p.trade_date`,
      [symbol, asOf, from],
    );
    return rows;
  }

  async paperPortfolios(): Promise<PaperSummary[]> {
    const { rows } = await this.pool.query(`${PAPER_SUMMARY_SQL} ORDER BY (p.status = 'CLOSED'), p.id`);
    return rows.map(toPaperSummary);
  }

  async paperPortfolio(id: number): Promise<PaperDetail | null> {
    const summary = (await this.pool.query(`${PAPER_SUMMARY_SQL} WHERE p.id = $1`, [id])).rows[0];
    if (!summary) return null;
    const portfolio = toPaperSummary(summary);
    const [positions, orders, daily] = await Promise.all([
      this.pool.query(
        `SELECT pp.symbol, s.name, pp.qty, pp.avg_price, pp.last_close, pp.entry_date
         FROM paper_positions pp JOIN securities s USING (symbol) WHERE pp.portfolio_id = $1 ORDER BY pp.symbol`,
        [id],
      ),
      this.pool.query(
        `SELECT id::int AS id, created_on, side, symbol, qty, reason, status, fill_date, fill_price, charges, note
         FROM paper_orders WHERE portfolio_id = $1 ORDER BY created_on DESC, id DESC LIMIT 500`,
        [id],
      ),
      this.pool.query(
        `SELECT trade_date AS date, equity, cash, drawdown_pct, nifty_close, events
         FROM paper_daily WHERE portfolio_id = $1 ORDER BY trade_date`,
        [id],
      ),
    ]);
    return {
      portfolio,
      positions: positions.rows.map((p) => {
        const value = p.qty * p.last_close;
        const cost = p.qty * p.avg_price;
        return {
          ...p,
          value,
          pnl: value - cost,
          pnl_pct: cost ? (value / cost - 1) * 100 : 0,
          weight_pct: portfolio.equity ? (value / portfolio.equity) * 100 : 0,
        };
      }),
      orders: orders.rows,
      daily: daily.rows,
    };
  }

  async holdings(): Promise<HoldingsSnapshot | null> {
    const { rows: history } = await this.pool.query(
      `SELECT as_of AS date, value, invested, twr_index, nifty_close, fetched_at
       FROM holdings_snapshots ORDER BY as_of`,
    );
    const last = history.at(-1);
    if (!last) return null;
    const { rows: items } = await this.pool.query(
      `SELECT kind, tradingsymbol AS symbol, exchange, product, qty, t1_qty, avg_price, last_price, close_price, pnl
       FROM holding_items WHERE as_of = $1 ORDER BY kind, tradingsymbol`,
      [last.date],
    );
    return {
      as_of: last.date,
      fetched_at: new Date(last.fetched_at).toISOString(),
      items,
      history: history.map(({ fetched_at: _f, ...p }) => p),
    };
  }

  async backtestRuns(limit: number): Promise<BacktestRunSummary[]> {
    const { rows } = await this.pool.query(
      `SELECT ${RUN_COLUMNS} FROM backtest_runs ORDER BY started_at DESC, id DESC LIMIT $1`,
      [limit],
    );
    return rows.map(toRunSummary);
  }

  async backtest(id: number): Promise<BacktestDetail | null> {
    const run = (await this.pool.query(`SELECT ${RUN_COLUMNS}, periods FROM backtest_runs WHERE id = $1`, [id])).rows[0];
    if (!run) return null;
    const [equity, holdings] = await Promise.all([
      this.pool.query(
        `SELECT trade_date AS date, strategy, nifty, universe_ew, drawdown_pct FROM backtest_equity
         WHERE run_id = $1 ORDER BY trade_date`,
        [id],
      ),
      this.pool.query(
        `SELECT signal_date AS signal, execution_date AS execution, symbol, rank, total_score, risk_level,
                confidence, weight, entry_price
         FROM backtest_holdings
         WHERE run_id = $1 AND execution_date = (SELECT max(execution_date) FROM backtest_holdings WHERE run_id = $1)
         ORDER BY rank`,
        [id],
      ),
    ]);
    return {
      run: toRunSummary(run),
      metrics: run.metrics ?? null,
      periods: run.periods ?? [],
      equity: equity.rows,
      latest_holdings: holdings.rows,
    };
  }
}

const PAPER_SUMMARY_SQL = `
  WITH last AS (
    SELECT DISTINCT ON (portfolio_id) portfolio_id, equity, drawdown_pct, nifty_close
    FROM paper_daily ORDER BY portfolio_id, trade_date DESC),
  first AS (
    SELECT DISTINCT ON (portfolio_id) portfolio_id, nifty_close
    FROM paper_daily ORDER BY portfolio_id, trade_date),
  dd AS (SELECT portfolio_id, min(drawdown_pct) AS max_dd FROM paper_daily GROUP BY portfolio_id),
  ch AS (SELECT portfolio_id, coalesce(sum(charges), 0) AS charges FROM paper_orders
         WHERE status = 'FILLED' GROUP BY portfolio_id),
  pos AS (SELECT portfolio_id, count(*)::int AS n FROM paper_positions GROUP BY portfolio_id)
  SELECT p.id::int AS id, p.name, p.status, p.halt_reason, p.start_date, p.last_processed, p.provenance, p.params,
         p.cash, coalesce(l.equity, p.cash) AS equity, coalesce(l.drawdown_pct, 0) AS drawdown_pct,
         coalesce(dd.max_dd, 0) AS max_drawdown_pct, coalesce(pos.n, 0) AS positions,
         coalesce(ch.charges, 0) AS charges_paid,
         CASE WHEN f.nifty_close > 0 AND l.nifty_close IS NOT NULL THEN (l.nifty_close / f.nifty_close - 1) * 100 END
           AS nifty_return_pct
  FROM paper_portfolios p
  LEFT JOIN last l ON l.portfolio_id = p.id LEFT JOIN first f ON f.portfolio_id = p.id
  LEFT JOIN dd ON dd.portfolio_id = p.id LEFT JOIN ch ON ch.portfolio_id = p.id LEFT JOIN pos ON pos.portfolio_id = p.id`;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toPaperSummary(r: any): PaperSummary {
  return { ...r, return_pct: (r.equity / r.params.capital - 1) * 100 };
}

const RUN_COLUMNS = "id::int AS id, name, status, started_at, finished_at, config_version, provenance, params, error, metrics";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toRunSummary(r: any): BacktestRunSummary {
  const m = r.metrics;
  return {
    id: r.id,
    name: r.name,
    status: r.status,
    started_at: new Date(r.started_at).toISOString(),
    finished_at: r.finished_at ? new Date(r.finished_at).toISOString() : null,
    config_version: r.config_version,
    provenance: r.provenance,
    params: r.params,
    error: r.error,
    headline: m
      ? {
          cagr_pct: m.strategy.cagr_pct,
          nifty_cagr_pct: m.nifty.cagr_pct,
          universe_cagr_pct: m.universe_ew.cagr_pct,
          max_drawdown_pct: m.strategy.max_drawdown_pct,
          sharpe: m.strategy.sharpe,
          rebalances: m.period.rebalances,
        }
      : null,
  };
}
