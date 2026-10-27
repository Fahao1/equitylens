import type {
  Bag,
  DataSectionStatus,
  QuantRecommendation,
  QuantResearchResponse,
} from "./types";

export type ScreenerHorizon = "short_term" | "long_term";
export type ScreenerFilters = {
  industries?: string[];
  exchanges?: string[];
  countries?: string[];
  include_international?: boolean;
  market_cap_min?: number;
  market_cap_max?: number;
  average_volume_min?: number;
  profitable_only?: boolean;
  min_revenue_growth?: number;
  max_forward_pe?: number;
  min_valuation?: number;
  min_technical?: number;
  min_overall?: number;
};
export type ScreenerJob = {
  id?: string;
  status?: string;
  stage?: string;
  total?: number;
  processed?: number;
  deep_total?: number;
  deep_processed?: number;
  message?: string;
};
export type ScreenerCoverage = {
  total_eligible?: number;
  total_discovered?: number;
  successfully_analyzed?: number;
  incomplete?: number;
  excluded?: number;
  ranked?: number;
  deep_analyzed?: number;
  source?: string;
  comprehensive?: boolean;
};
export type ScreenerStock = {
  rank?: number;
  ticker: string;
  name?: string;
  price?: number | null;
  currency?: string;
  industry?: string;
  exchange?: string;
  country?: string;
  market_cap?: number | null;
  average_volume?: number | null;
  overall_score?: number | null;
  company_quality?: number | null;
  valuation_attractiveness?: number | null;
  technical_strength?: number | null;
  trade_setup_quality?: number | null;
  historical_evidence?: number | null;
  historical_performance?: QuantResearchResponse["validation"];
  risk_score?: number | null;
  confidence?: number | null;
  data_completeness?: number | null;
  metrics_evaluated?: number | null;
  missing_information?: string[];
  fetched_at?: string | null;
  quote_at?: string | null;
  cache_stale?: boolean;
  analysis_stage?: "broad" | "deep";
  recommendation?: string;
  holding_horizon?: string;
  eligible_buy?: boolean;
  ranking_explanation?: string[];
  risks?: string[];
  buy_triggers?: string[];
  thesis_invalidation?: string[];
  plan?: QuantRecommendation;
  scenarios?: Bag[];
  fair_value?: {
    bear?: number | null;
    base?: number | null;
    bull?: number | null;
  } | null;
  margin_of_safety?: number | null;
  scores?: Record<string, number | null>;
  source_freshness?: Record<string, DataSectionStatus>;
  valuation_assumptions?: Bag;
  model_uncertainty?: Bag;
  [key: string]: unknown;
};
export type ScreenerProviderError =
  | string
  | {
      ticker?: string;
      code?: string;
      message?: string;
      retryable?: boolean;
    };
export type ScreenerSnapshot = {
  horizon: ScreenerHorizon;
  run_id?: string | null;
  as_of?: string | null;
  methodology_version?: string;
  weights?: Record<string, number>;
  filters?: ScreenerFilters;
  configuration?: Bag;
  rankings?: ScreenerStock[];
  top_ranked?: ScreenerStock | null;
  best_eligible?: ScreenerStock | null;
  buy_candidates?: ScreenerStock[];
  watchlist_candidates?: ScreenerStock[];
  coverage?: ScreenerCoverage;
  job?: ScreenerJob;
  provider_errors?: ScreenerProviderError[];
  limitations?: string[];
};
export type ScreenerStatus = Pick<
  ScreenerSnapshot,
  "horizon" | "run_id" | "as_of" | "coverage" | "job" | "provider_errors"
>;
export type ScreenerUniverse = {
  source?: string;
  as_of?: string | null;
  members?: Array<Partial<ScreenerStock> & { ticker: string }>;
  coverage?: ScreenerCoverage;
  industries?: string[];
  exchanges?: string[];
  countries?: string[];
  limitations?: string[];
};
export type ScreenerRequest = {
  horizon: ScreenerHorizon;
  filters: ScreenerFilters;
  weights: Record<string, number>;
  risk_tolerance: string;
  capital: number;
  capital_currency: string;
  risk_per_trade: number;
  min_reward_risk: number;
  commission_bps: number;
  slippage_bps: number;
  existing_shares: number;
  position_ticker: string | null;
  cost_basis: number | null;
  max_deep_analysis: number;
  valuation_assumptions?: {
    enable_dcf: boolean;
    growth?: number;
    discount_rate?: number;
    terminal_growth?: number;
    years?: number;
  };
};
export type ScreenerRefresh = {
  horizon: ScreenerHorizon;
  job: ScreenerJob;
  run_id?: string;
  accepted: boolean;
};
