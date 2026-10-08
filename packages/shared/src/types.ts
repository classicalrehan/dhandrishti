/**
 * Core domain types shared across DhanDrishti.
 *
 * Convention: any metric that may be missing is `number | null`.
 * `null` always means "Data unavailable" — never substitute a guess.
 */

export type ISODate = string; // YYYY-MM-DD (IST trading date)
export type ISODateTime = string; // full ISO-8601 timestamp

export interface Bar {
  date: ISODate;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type Sector =
  | "Banking"
  | "Financial Services"
  | "IT"
  | "Energy"
  | "Auto"
  | "FMCG"
  | "Pharma" // MOCK universe only; the real universe uses "Healthcare"
  | "Healthcare"
  | "Metal"
  | "Telecom"
  | "Infra"
  | "Realty"
  | "Cement"
  | "Consumer Durables"
  | "Power"
  | "Media"
  | "Capital Goods"
  | "Chemicals"
  | "Services"
  | "Consumer Services"
  | "Textiles"
  | "Materials"
  | "Diversified";

export type IndexMembership =
  | "NIFTY 50"
  | "NIFTY NEXT 50"
  | "NIFTY MIDCAP 150"
  | "NIFTY SMALLCAP 250";

export interface Security {
  symbol: string; // NSE symbol, e.g. HDFCBANK
  name: string;
  exchange: "NSE" | "BSE";
  sector: Sector;
  industry: string | null;
  indices: IndexMembership[];
  /** True for banks / NBFCs where debt-equity is not a meaningful leverage metric. */
  isFinancial: boolean;
}

export interface Fundamentals {
  asOf: ISODate | null;
  marketCapCr: number | null;
  revenueGrowthYoY: number | null; // %, latest FY
  profitGrowthYoY: number | null; // %
  epsGrowthYoY: number | null; // %
  epsCagr3y: number | null; // %
  roe: number | null; // %
  roce: number | null; // %
  operatingMargin: number | null; // %
  netMargin: number | null; // %
  freeCashFlowCr: number | null;
  cfoToPat: number | null; // ratio, cash-flow quality
  debtToEquity: number | null;
  interestCoverage: number | null;
  pe: number | null;
  pb: number | null;
  peg: number | null;
  dividendYield: number | null; // %
  promoterHolding: number | null; // %
  promoterPledge: number | null; // % of promoter holding pledged
  institutionalHolding: number | null; // % FII + DII
  peMedian5y: number | null; // own historical median PE
  /** Most recent quarters last. */
  quarterlyEps: number[] | null;
  /** Count of the last 8 quarters with positive YoY EPS growth. */
  positiveEpsQuarters8: number | null;
}

export interface MarketEvent {
  symbol: string | null; // null = market-wide
  date: ISODate;
  type: "EARNINGS" | "DIVIDEND" | "SPLIT" | "BONUS" | "AGM" | "REGULATORY" | "OTHER";
  title: string;
  source: string;
}

export interface StockSnapshot {
  security: Security;
  bars: Bar[]; // ascending by date
  fundamentals: Fundamentals | null;
  events: MarketEvent[];
  priceAsOf: ISODateTime;
}

export interface IndexSeries {
  symbol: "NIFTY 50" | "NIFTY BANK" | "INDIA VIX" | string;
  bars: Bar[];
}

export type DataProvenance = "DEMO" | "LIVE" | "DELAYED" | "EOD";

export interface DataSourceInfo {
  provider: string;
  provenance: DataProvenance;
  asOf: ISODateTime;
  notice: string | null;
}
