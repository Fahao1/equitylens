export type Bag = Record<string, any>;
export type Price = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adj_close?: number;
  volume: number;
};
export type CategoryResult = {
  score: number | null;
  confidence: number;
  signals: string[];
  limitations: string[];
  [key: string]: any;
};
export type CategoryContribution = {
  key: string;
  label: string;
  score: number | null;
  weight: number;
  contribution: number | null;
  confidence: number;
};
export type StockScore = {
  overall: number | null;
  company_quality: number | null;
  confidence: number;
  coverage: number;
  categories: CategoryContribution[];
  limitations: string[];
  [key: string]: any;
};
export type TradePlan = {
  recommendation: string;
  status: string;
  entry_zone: [number, number] | null;
  targets: number[];
  stop: number | null;
  breakout_entry: number | null;
  risk_reward: number | null;
  upside_percent: number | null;
  downside_percent: number | null;
  position_size: number;
  risk_budget: number;
  holding_horizon: string;
  calculation: string[];
  invalidation: string[];
  event_warnings: string[];
  [key: string]: any;
};
export type Research = {
  ticker: string;
  as_of: string;
  overview: Bag;
  history: {
    prices: Price[];
    source?: string;
    interval?: string;
    period?: string;
  };
  technical: CategoryResult;
  fundamentals: CategoryResult;
  valuation: CategoryResult;
  news: CategoryResult;
  macro: CategoryResult;
  score: StockScore;
  trade_plan: TradePlan;
  report: { markdown: string };
  data_quality: Bag;
  quant_core?: QuantCore;
};
export type CalendarEvent = {
  id: string;
  title: string;
  country?: string;
  currency?: string;
  scheduled_at?: string | null;
  impact?: string;
  forecast?: string | number | null;
  previous?: string | number | null;
  actual?: string | number | null;
  revised_previous?: string | number | null;
  status?: string;
  source_url?: string;
  surprise?: number | null;
  [key: string]: any;
};
export type CalendarData = {
  events: CalendarEvent[];
  source?: string;
  status?: string;
  coverage?: any;
  limitations?: string[];
};
export const DEFAULT_WEIGHTS: Record<string, number> = {
  financial: 0.25,
  valuation: 0.2,
  technical: 0.2,
  news: 0.1,
  macro: 0.1,
  risk: 0.15,
};
export const CATEGORY_LABELS: Record<string, string> = {
  financial: "Financial health & growth",
  valuation: "Valuation",
  technical: "Technical analysis",
  news: "News & earnings",
  macro: "Macroeconomic outlook",
  risk: "Risk & resilience",
};
export type StockSearchResult = {
  symbol: string;
  name: string | null;
  exchange: string | null;
  asset_type: string | null;
};
export type StockSearchResponse = {
  query: string;
  results: StockSearchResult[];
  source: string;
  fetched_at: string;
  cache_stale: boolean;
  cache_age_seconds?: number;
};
export type DataSectionStatus = {
  status:
    | "available"
    | "unavailable"
    | "error"
    | "cached"
    | "partial"
    | "not_applicable";
  fetched_at?: string | null;
  cache_stale?: boolean;
  error?: { code: string; message: string; retryable: boolean } | null;
};
export type HistoryResponse = Research["history"] & {
  fetched_at?: string;
  cache_stale?: boolean;
  cache_age_seconds?: number;
  from_cache?: boolean;
};

export type QuantScoreKey =
  | "company_quality"
  | "valuation_attractiveness"
  | "technical_strength"
  | "trade_setup_quality"
  | "macroeconomic_environment"
  | "overall_investment_attractiveness";
export type QuantScores = Partial<Record<QuantScoreKey, number | null>> & {
  weights?: Record<string, number>;
  contributions?: Record<string, number | null> | Bag[];
  weight_mapping?: Bag;
  [key: string]: any;
};
export type QuantEvidence = {
  confidence?: number | null;
  data_freshness?: Bag | number | string | null;
  model_uncertainty?:
    | {
        kind?: string;
        calibrated?: boolean;
        limitations?: string[];
        [key: string]: unknown;
      }
    | string
    | null;
  sample_reliability?:
    | {
        status?: string;
        sample_size?: number | null;
        min_samples?: number | null;
        [key: string]: unknown;
      }
    | string
    | null;
  limitations?: string[];
};
export type QuantRegime = {
  regime?: string;
  trend_strength?: number | string | Bag | null;
  volatility_regime?: string | Bag | null;
  confidence?: number | null;
  evidence?: string[];
  features?: Bag;
  limitations?: string[];
};
export type QuantTimeframe = {
  timeframe: string;
  status: string;
  trend?: string | Bag | null;
  momentum?: string | number | Bag | null;
  volatility?: string | number | Bag | null;
  support?: number | number[] | null;
  resistance?: number | number[] | null;
  bars?: number | null;
  last_bar_at?: string | null;
  last_bar_end?: string | null;
  source?: string | Bag;
  limitations?: string[];
};
export type QuantStrategy = {
  id: string;
  name?: string;
  status?: string;
  eligible?: boolean;
  entry_condition?: string;
  entry_zone?: [number, number] | null;
  entry_reference?: number | null;
  stop?: number | null;
  targets?: number[];
  net_reward_risk?: Array<number | null>;
  risk_reward?: number | null;
  position_size?: number | null;
  holding_horizon?: string;
  max_holding_bars?: number;
  evidence?: string[];
  avoid_reasons?: string[];
  invalidation?: { price?: number | null; kind?: string; condition?: string };
  target_methodology?: string[];
  calculation?: string[];
  regime?: string;
};
export type ProbabilityEstimate =
  | number
  | null
  | {
      value?: number | null;
      estimate?: number | null;
      probability?: number | null;
      sample_size?: number | null;
      status?: string;
      [key: string]: unknown;
    };
export type ProbabilityInterval =
  | [number, number]
  | {
      lower?: number | null;
      upper?: number | null;
      level?: number | null;
      sample_size?: number | null;
      status?: string;
    }
  | null;
export type QuantProbability = {
  status?: string;
  sample_size?: number | null;
  min_samples?: number | null;
  validation_period?:
    | { start?: string | null; end?: string | null }
    | string
    | null;
  estimates?: Partial<
    Record<
      | "target_1_before_stop"
      | "target_2_before_stop"
      | "stop_before_target"
      | "expected_return"
      | "expected_holding_bars",
      ProbabilityEstimate
    >
  >;
  confidence_intervals?: Record<string, ProbabilityInterval>;
  sample_sizes?: Record<string, number | null>;
  estimate_details?: Record<string, Bag>;
  limitations?: string[];
  [key: string]: any;
};
export type QuantRecommendation = {
  recommendation?: string;
  best_strategy?: string | null;
  entry_zone?: [number, number] | null;
  stop?: number | null;
  targets?: number[];
  risk_reward?: number | null;
  net_reward_risk?: Array<number | null>;
  position_size?: number | null;
  entry_condition?: string;
  calculation?: string[];
  invalidation?: string[] | Bag;
  event_warnings?: string[];
  limitations?: string[];
  [key: string]: any;
};
export type QuantCore = {
  ticker?: string;
  as_of?: string;
  methodology_version?: string;
  regime?: QuantRegime;
  strategies?: QuantStrategy[];
  recommendation?: QuantRecommendation;
  scores?: QuantScores;
  evidence?: QuantEvidence;
  valuation?: Bag;
  event_risk?: Bag;
  [key: string]: any;
};
export type QuantResearchResponse = QuantCore & {
  ticker: string;
  as_of: string;
  methodology_version: string;
  timeframes?: {
    timeframes?: QuantTimeframe[];
    alignment?: string | Bag;
    confidence?: number | null;
    limitations?: string[];
  };
  probabilities?: QuantProbability;
  validation?: {
    strategies?: Record<string, Bag>;
    benchmark?: Bag;
    methodology?: string | Bag | string[];
    limitations?: string[];
  };
  source?: string | Bag;
};
