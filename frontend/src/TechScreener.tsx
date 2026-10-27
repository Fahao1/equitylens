import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUp,
  ArrowRight,
  Check,
  Filter,
  FlaskConical,
  Layers3,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Star,
  Target,
} from "lucide-react";
import { api, post, retryTransient } from "./api";
import DataStatus from "./DataStatus";
import { useRequestScope, type RequestScope } from "./useRequestScope";
import { normalizeTicker } from "./tickerState";
import type { Bag } from "./types";
import type {
  ScreenerFilters,
  ScreenerHorizon,
  ScreenerJob,
  ScreenerProviderError,
  ScreenerRefresh,
  ScreenerRequest,
  ScreenerSnapshot,
  ScreenerStatus,
  ScreenerStock,
  ScreenerUniverse,
} from "./techScreenerTypes";
import {
  Badge,
  DataTable,
  Empty,
  ErrorBox,
  Evidence,
  Limitations,
  PageIntro,
  SectionHeading,
  compact,
  currencySymbol,
  dateTime,
  label,
  num,
  pct,
  scoreColor,
} from "./ui";

const WEIGHTS: Record<ScreenerHorizon, Record<string, number>> = {
  short_term: {
    technical_strength: 0.3,
    trade_setup_quality: 0.25,
    momentum_volume: 0.15,
    news_catalysts: 0.15,
    fundamentals_risk: 0.15,
  },
  long_term: {
    financial_quality_growth: 0.3,
    valuation_attractiveness: 0.25,
    growth_outlook: 0.2,
    financial_resilience: 0.15,
    technical_entry_timing: 0.1,
  },
};
const SORT_FIELDS = [
  ["overall_score", "Overall rating"],
  ["company_quality", "Company quality"],
  ["valuation_attractiveness", "Valuation"],
  ["technical_strength", "Technical strength"],
  ["trade_setup_quality", "Trade setup quality"],
  ["historical_evidence", "Historical evidence (sample N)"],
  ["risk_score", "Financial resilience / risk"],
  ["market_cap", "Market capitalization"],
] as const;
const running = (job?: ScreenerJob) =>
  /^(queued|running|pending|in_progress)$/i.test(job?.status || "");
const eligible = (stock?: ScreenerStock | null) =>
  Boolean(
    stock?.eligible_buy &&
      stock.analysis_stage === "deep" &&
      !stock.cache_stale,
  );
const amount = (value: unknown, currency?: string) =>
  value == null ? "—" : `${currencySymbol(currency)}${num(value)}`;
const zone = (value: unknown, currency?: string) =>
  Array.isArray(value) && value.length === 2
    ? `${amount(value[0], currency)} – ${amount(value[1], currency)}`
    : "Not established";
const priceRatio = (value: unknown) =>
  value == null ? "—" : `${num(value)} : 1`;
const errorText = (error: ScreenerProviderError) =>
  typeof error === "string"
    ? error
    : [error.ticker, error.code, error.message].filter(Boolean).join(" · ");
const recommendation = (stock: ScreenerStock) =>
  eligible(stock)
    ? "Buy Candidate"
    : /buy/i.test(stock.recommendation || "")
      ? "Wait"
      : stock.recommendation || "Insufficient Evidence";
export function sortScreenerStocks(
  rows: ScreenerStock[],
  field: string,
  descending = true,
) {
  return [...rows].sort((a, b) => {
    const left =
      typeof a[field] === "number" && Number.isFinite(a[field])
        ? Number(a[field])
        : null;
    const right =
      typeof b[field] === "number" && Number.isFinite(b[field])
        ? Number(b[field])
        : null;
    if (left == null || right == null)
      return left == null && right == null
        ? a.ticker.localeCompare(b.ticker)
        : left == null
          ? 1
          : -1;
    return (
      (descending ? right - left : left - right) ||
      a.ticker.localeCompare(b.ticker)
    );
  });
}
function StockLink({
  stock,
  openStock,
}: {
  stock: ScreenerStock;
  openStock: (ticker: string) => void;
}) {
  return (
    <button
      className="text-button green screener-stock-link"
      onClick={(event) => {
        event.stopPropagation();
        openStock(stock.ticker);
      }}
      aria-label={`Open ${stock.ticker} research`}
    >
      <strong>{stock.ticker}</strong>
      <span>{stock.name || "Company name unavailable"}</span>
      <ArrowRight size={12} />
    </button>
  );
}
function Candidate({
  stock,
  openStock,
  title,
  eligibleOnly = false,
}: {
  stock?: ScreenerStock | null;
  openStock: (ticker: string) => void;
  title: string;
  eligibleOnly?: boolean;
}) {
  const candidate = eligibleOnly && !eligible(stock) ? null : stock;
  const plan = candidate?.plan || {};
  return (
    <section className="panel screener-candidate">
      <SectionHeading
        eyebrow={
          eligibleOnly
            ? "A CONFIRMED SETUP IS A SEPARATE REQUIREMENT"
            : "RANKING DOES NOT ESTABLISH A BUY"
        }
        title={title}
      >
        <Target size={18} />
      </SectionHeading>
      {!candidate ? (
        <Empty
          title={
            eligibleOnly
              ? "No qualified buy candidate"
              : "No ranked company yet"
          }
        >
          <p>
            {eligibleOnly
              ? "No stock in the analyzed coverage meets all current buy requirements. Waiting is a valid outcome."
              : "Start a screening run to evaluate the available technology-company universe."}
          </p>
        </Empty>
      ) : (
        <>
          <div className="screener-candidate-header">
            <StockLink stock={candidate} openStock={openStock} />
            <Badge tone={eligible(candidate) ? "green" : "amber"}>
              {recommendation(candidate)}
            </Badge>
          </div>
          <div className="metric-grid screener-candidate-metrics">
            {[
              [
                "Current quoted price",
                amount(candidate.price, candidate.currency),
              ],
              [
                "Investment attractiveness",
                candidate.overall_score == null
                  ? "Unavailable"
                  : `${num(candidate.overall_score, 1)} /10`,
              ],
              [
                "Company quality",
                candidate.company_quality == null
                  ? "Unavailable"
                  : `${num(candidate.company_quality, 1)} /10`,
              ],
              [
                "Technical strength",
                candidate.technical_strength == null
                  ? "Unavailable"
                  : `${num(candidate.technical_strength, 1)} /10`,
              ],
              [
                "Valuation attractiveness",
                candidate.valuation_attractiveness == null
                  ? "Unavailable"
                  : `${num(candidate.valuation_attractiveness, 1)} /10`,
              ],
              ["Evidence confidence", pct(candidate.confidence)],
            ].map(([name, value]) => (
              <div className="metric-cell" key={name}>
                <span>{name}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <p className="panel-footnote">
            {candidate.analysis_stage === "deep"
              ? "Bounded deep review completed"
              : "Broad screening only; a trade recommendation has not been established"}{" "}
            · Quote {dateTime(candidate.quote_at)} ·{" "}
            {candidate.currency || "Currency unavailable"}
            {candidate.cache_stale ? " · Stale source snapshot" : ""}
          </p>
          <div className="screener-levels">
            {[
              [
                "Potential entry / accumulation zone",
                zone(plan.entry_zone, candidate.currency),
              ],
              [
                "Breakout alternative",
                amount(plan.breakout_entry, candidate.currency),
              ],
              [
                "Profit target 1",
                amount(plan.targets?.[0], candidate.currency),
              ],
              [
                "Profit target 2",
                amount(plan.targets?.[1], candidate.currency),
              ],
              [
                "Stop / capital-risk invalidation",
                amount(plan.stop, candidate.currency),
              ],
              ["Net reward / risk", priceRatio(plan.risk_reward)],
              ["Additional whole shares", num(plan.position_size, 0)],
              [
                "Maximum planned loss",
                amount(plan.maximum_planned_loss, candidate.currency),
              ],
              [
                "Potential net upside",
                plan.upside_percent == null
                  ? "—"
                  : `${num(plan.upside_percent, 1)}%`,
              ],
              [
                "Modeled net downside",
                plan.downside_percent == null
                  ? "—"
                  : `${num(plan.downside_percent, 1)}%`,
              ],
              [
                "Expected holding period",
                candidate.holding_horizon ||
                  plan.holding_horizon ||
                  "Not established",
              ],
            ].map(([name, value]) => (
              <div key={name}>
                <span>{name}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          {candidate.fair_value && (
            <p className="panel-footnote">
              Bear / base / bull valuation sensitivities:{" "}
              {["bear", "base", "bull"]
                .map((key) =>
                  amount(
                    candidate.fair_value?.[key as "bear" | "base" | "bull"],
                    candidate.currency,
                  ),
                )
                .join(" / ")}{" "}
              · margin of safety {pct(candidate.margin_of_safety)}. Valuation
              scenarios are assumption-driven long-term estimates, not predicted
              prices.
            </p>
          )}
          <details className="limitations">
            <summary>Why this stock ranks here</summary>
            <Evidence items={candidate.ranking_explanation} />
            {candidate.scores && (
              <DataTable
                rows={Object.entries(candidate.scores).map(([key, value]) => ({
                  category: label(key),
                  score_out_of_10: num(value, 1),
                }))}
              />
            )}
            <h3 className="subsection-title">What could go wrong</h3>
            <Evidence items={candidate.risks} />
            <h3 className="subsection-title">What would trigger a buy</h3>
            <Evidence
              items={
                candidate.buy_triggers || [plan.entry_condition].filter(Boolean)
              }
            />
            <h3 className="subsection-title">
              What would invalidate the thesis
            </h3>
            <Evidence items={candidate.thesis_invalidation} />
            <Evidence items={plan.event_warnings} />
          </details>
          {candidate.source_freshness && (
            <details className="limitations">
              <summary>Source freshness and financial availability</summary>
              {Object.entries(candidate.source_freshness).map(
                ([key, status]) => (
                  <DataStatus key={key} label={label(key)} status={status} />
                ),
              )}
            </details>
          )}
          {candidate.valuation_assumptions && (
            <details className="limitations">
              <summary>Valuation assumptions and model uncertainty</summary>
              <DataTable rows={[candidate.valuation_assumptions]} />
              <p className="panel-footnote">
                Growth, discount and terminal rates are fractions. These
                valuation scenarios share cash-flow assumptions and are not
                independent price forecasts.
              </p>
              <Limitations items={candidate.model_uncertainty?.limitations} />
            </details>
          )}
          {candidate.historical_performance && (
            <details className="limitations">
              <summary>Historical strategy evidence</summary>
              <p className="panel-footnote">
                Comparable historical observations:{" "}
                {num(candidate.historical_evidence, 0)}. Strategy results below
                are descriptive after modeled costs; a small or unsuitable
                cohort cannot establish a reliable future edge.
              </p>
              <DataTable
                rows={Object.entries(
                  candidate.historical_performance.strategies || {},
                ).map(([id, result]) => ({
                  strategy: label(id),
                  status: result.status,
                  sample_size: result.sample_size,
                  net_total_return: pct(result.metrics?.total_return),
                  maximum_drawdown: pct(result.metrics?.maximum_drawdown),
                  sharpe: result.metrics?.sharpe_ratio,
                }))}
              />
              <Limitations
                items={candidate.historical_performance.limitations}
              />
            </details>
          )}
          {candidate.scenarios?.length ? (
            <details className="limitations">
              <summary>Conditional future scenarios</summary>
              {candidate.scenarios.map((scenario, index) => (
                <div className="screener-scenario" key={scenario.id || index}>
                  <h3>
                    {scenario.name || label(scenario.id || "Scenario")}{" "}
                    <Badge>{scenario.status || "Insufficient evidence"}</Badge>
                  </h3>
                  <p>
                    {scenario.required_confirmation ||
                      scenario.entry_condition ||
                      scenario.confirmation}
                  </p>
                  <DataTable
                    rows={[
                      {
                        entry: zone(
                          scenario.entry_zone || scenario.entry,
                          candidate.currency,
                        ),
                        target_1: amount(
                          scenario.targets?.[0] ?? scenario.target_1,
                          candidate.currency,
                        ),
                        target_2: amount(
                          scenario.targets?.[1] ?? scenario.target_2,
                          candidate.currency,
                        ),
                        stop: amount(scenario.stop, candidate.currency),
                        reward_risk: priceRatio(scenario.risk_reward),
                        horizon: scenario.holding_horizon || scenario.horizon,
                      },
                    ]}
                  />
                  <Evidence
                    items={scenario.evidence || scenario.supporting_indicators}
                  />
                  {scenario.invalidation && (
                    <Evidence
                      items={
                        typeof scenario.invalidation === "string"
                          ? [scenario.invalidation]
                          : scenario.invalidation.condition
                            ? [scenario.invalidation.condition]
                            : scenario.invalidation
                      }
                    />
                  )}
                  <Evidence
                    items={scenario.calculation}
                    empty="No numerical calculation was returned for this conditional scenario."
                  />
                  <Limitations items={scenario.limitations} />
                </div>
              ))}
              <p className="panel-footnote">
                Waiting and untriggered scenarios are conditional possibilities,
                not immediate buy recommendations. A technical capital-risk stop
                is separate from a long-term business thesis.
              </p>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}
function RankingTable({
  rows,
  selected,
  toggle,
  openStock,
  sortField,
  descending,
  changeSort,
}: {
  rows: ScreenerStock[];
  selected: string[];
  toggle: (ticker: string) => void;
  openStock: (ticker: string) => void;
  sortField: string;
  descending: boolean;
  changeSort: (field: string) => void;
}) {
  return (
    <div className="table-scroll">
      <table className="screener-ranking-table">
        <thead>
          <tr>
            <th>Compare</th>
            <th>Rank</th>
            <th>Company</th>
            {[
              ["overall_score", "Rating"],
              ["company_quality", "Quality"],
              ["technical_strength", "Technical"],
              ["valuation_attractiveness", "Valuation"],
            ].map(([field, name]) => (
              <th
                key={field}
                aria-sort={
                  sortField === field
                    ? descending
                      ? "descending"
                      : "ascending"
                    : "none"
                }
              >
                <button
                  className="text-button"
                  onClick={() => changeSort(field)}
                >
                  {name}
                  <ArrowDownUp size={10} />
                </button>
              </th>
            ))}
            <th>Recommendation</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((stock) => (
            <tr
              key={stock.ticker}
              className="clickable-row"
              onClick={() => openStock(stock.ticker)}
            >
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={selected.includes(stock.ticker)}
                  onChange={() => toggle(stock.ticker)}
                  aria-label={`Compare ${stock.ticker}`}
                />
              </td>
              <td>{num(stock.rank, 0)}</td>
              <td>
                <StockLink stock={stock} openStock={openStock} />
                <span className="scope-note">
                  {stock.industry || "Industry unavailable"}
                </span>
              </td>
              {[
                "overall_score",
                "company_quality",
                "technical_strength",
                "valuation_attractiveness",
              ].map((field) => (
                <td
                  key={field}
                  className={scoreColor(stock[field] as number | null)}
                >
                  {num(stock[field], 1)}
                </td>
              ))}
              <td>
                <Badge tone={eligible(stock) ? "green" : "neutral"}>
                  {recommendation(stock)}
                </Badge>
                <span className="scope-note">
                  {stock.analysis_stage === "deep"
                    ? "Deep review"
                    : "Broad screen"}
                </span>
              </td>
              <td>
                <span>{pct(stock.confidence)} confidence</span>
                <span className="scope-note">
                  {pct(stock.data_completeness)} complete ·{" "}
                  {num(stock.metrics_evaluated, 0)} metrics
                </span>
                <details>
                  <summary>Coverage</summary>
                  <p>
                    Updated {dateTime(stock.fetched_at)}
                    {stock.cache_stale ? " · stale" : ""}
                  </p>
                  <Evidence
                    items={stock.missing_information}
                    empty="No missing fields were reported."
                  />
                  <Evidence items={stock.ranking_explanation} />
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Comparison({
  rows,
  openStock,
}: {
  rows: ScreenerStock[];
  openStock: (ticker: string) => void;
}) {
  const fields = [
    ["overall_score", "Investment attractiveness"],
    ["company_quality", "Company quality"],
    ["valuation_attractiveness", "Valuation"],
    ["technical_strength", "Technical strength"],
    ["trade_setup_quality", "Trade setup quality"],
    ["historical_evidence", "Comparable historical observations"],
    ["risk_score", "Financial resilience / risk"],
    ["confidence", "Evidence confidence"],
    ["data_completeness", "Data completeness"],
    ["market_cap", "Market capitalization"],
  ];
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="SAME HORIZON, SAME SCREENING SNAPSHOT"
        title="Detailed stock comparison"
      >
        <Layers3 size={18} />
      </SectionHeading>
      {rows.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Assessment</th>
                {rows.map((stock) => (
                  <th key={stock.ticker}>
                    <StockLink stock={stock} openStock={openStock} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fields.map(([field, name]) => (
                <tr key={field}>
                  <td>{name}</td>
                  {rows.map((stock) => (
                    <td key={stock.ticker}>
                      {["confidence", "data_completeness"].includes(field)
                        ? pct(stock[field])
                        : field === "market_cap"
                          ? `${currencySymbol(stock.currency)}${compact(stock[field])}`
                          : num(
                              stock[field],
                              field === "historical_evidence" ? 0 : 1,
                            )}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td>Recommendation</td>
                {rows.map((stock) => (
                  <td key={stock.ticker}>{recommendation(stock)}</td>
                ))}
              </tr>
              <tr>
                <td>Important missing evidence</td>
                {rows.map((stock) => (
                  <td key={stock.ticker}>
                    <Evidence
                      items={stock.missing_information}
                      empty="None reported"
                    />
                  </td>
                ))}
              </tr>
              <tr>
                <td>Ranking explanation</td>
                {rows.map((stock) => (
                  <td key={stock.ticker}>
                    <Evidence items={stock.ranking_explanation} />
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted small-text">
          Select up to three stocks in the rankings to compare their evidence
          side by side.
        </p>
      )}
    </section>
  );
}

export default function TechScreener({
  openStock,
  onToast,
}: {
  openStock: (ticker: string) => void;
  onToast: (message: string) => void;
}) {
  const [horizon, setHorizon] = useState<ScreenerHorizon>("short_term"),
    [weights, setWeights] = useState({ ...WEIGHTS.short_term }),
    [filters, setFilters] = useState<Record<string, string>>({
      market_cap_min: "1000000000",
      average_volume_min: "100000",
    }),
    [international, setInternational] = useState(false),
    [profitable, setProfitable] = useState(false),
    [risk, setRisk] = useState("medium"),
    [capital, setCapital] = useState(10000),
    [capitalCurrency, setCapitalCurrency] = useState("USD"),
    [riskPercent, setRiskPercent] = useState(1),
    [minRR, setMinRR] = useState(2),
    [commission, setCommission] = useState(5),
    [slippage, setSlippage] = useState(5),
    [maxDeep, setMaxDeep] = useState(15),
    [existingShares, setExistingShares] = useState(0),
    [positionTicker, setPositionTicker] = useState(""),
    [costBasis, setCostBasis] = useState(""),
    [enableDcf, setEnableDcf] = useState(true),
    [dcfGrowth, setDcfGrowth] = useState(5),
    [dcfDiscount, setDcfDiscount] = useState(10),
    [dcfTerminal, setDcfTerminal] = useState(2),
    [dcfYears, setDcfYears] = useState(5),
    [selected, setSelected] = useState<string[]>([]),
    [sortField, setSortField] = useState("overall_score"),
    [descending, setDescending] = useState(true),
    [message, setMessage] = useState(""),
    [activeJob, setActiveJob] = useState<{
      horizon: ScreenerHorizon;
      id?: string;
    } | null>(null),
    [backtestTop, setBacktestTop] = useState(5),
    [backtestCommission, setBacktestCommission] = useState(5),
    [backtestSlippage, setBacktestSlippage] = useState(5);
  const client = useQueryClient(),
    scope = useRequestScope(horizon),
    completedJob = useRef<string | null>(null);
  const universe = useQuery({
    queryKey: ["tech-universe"],
    queryFn: ({ signal }) =>
      api<ScreenerUniverse>("/screener/tech/universe", { signal }),
    retry: retryTransient,
  });
  const rankings = useQuery({
    queryKey: ["tech-rankings", horizon],
    queryFn: ({ signal }) =>
      api<ScreenerSnapshot>(`/screener/tech/rankings?horizon=${horizon}`, {
        signal,
      }),
    retry: retryTransient,
  });
  const status = useQuery({
    queryKey: ["tech-status", horizon],
    queryFn: ({ signal }) =>
      api<ScreenerStatus>(`/screener/tech/status?horizon=${horizon}`, {
        signal,
      }),
    retry: retryTransient,
    refetchInterval: (query) =>
      activeJob?.horizon === horizon || running(query.state.data?.job)
        ? 3000
        : false,
  });
  const snapshot =
    rankings.data?.horizon === horizon ? rankings.data : undefined;
  const currentStatus =
    status.data?.horizon === horizon ? status.data : undefined;
  const job = currentStatus?.job || snapshot?.job;
  useEffect(() => {
    if (
      !job?.id ||
      running(job) ||
      completedJob.current === `${horizon}:${job.id}:${job.status}`
    )
      return;
    completedJob.current = `${horizon}:${job.id}:${job.status}`;
    if (
      activeJob?.horizon === horizon &&
      (!activeJob.id || activeJob.id === job.id)
    )
      setActiveJob(null);
    client.invalidateQueries({ queryKey: ["tech-rankings", horizon] });
    client.invalidateQueries({ queryKey: ["tech-universe"] });
  }, [job?.id, job?.status, horizon, activeJob, client]);
  const refresh = useMutation({
    mutationFn: ({
      request,
    }: {
      request: ScreenerRequest;
      scope: RequestScope;
    }) => post<ScreenerRefresh>("/screener/tech/refresh", request),
    onSuccess: (result, request) => {
      client.invalidateQueries({ queryKey: ["tech-status", result.horizon] });
      if (!scope.isCurrent(request.scope) || result.horizon !== horizon) return;
      setActiveJob({ horizon, id: result.job?.id });
      setMessage(
        "Screening started. Rankings update after the background run finishes.",
      );
      if (!running(result.job))
        client.invalidateQueries({ queryKey: ["tech-rankings", horizon] });
    },
    onError: (error, request) => {
      if (scope.isCurrent(request.scope)) setMessage(error.message);
    },
  });
  const addWatch = useMutation({
    mutationFn: (ticker: string) => post("/watchlist", { ticker }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["watchlist"] });
      onToast("Added to your watchlist.");
    },
    onError: (error) => onToast(error.message),
  });
  const backtest = useMutation({
    mutationFn: ({
      horizon: requested,
      top_n,
    }: {
      horizon: ScreenerHorizon;
      top_n: number;
      scope: RequestScope;
    }) =>
      post<Bag>("/screener/tech/backtest", {
        horizon: requested,
        top_n,
        starting_capital: capital,
        commission_bps: backtestCommission,
        slippage_bps: backtestSlippage,
      }),
    onSuccess: (result, request) => {
      if (scope.isCurrent(request.scope))
        setBacktestResult({ horizon: request.horizon, result });
    },
  });
  const [backtestResult, setBacktestResult] = useState<{
    horizon: ScreenerHorizon;
    result: Bag;
  } | null>(null);
  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0);
  const start = (event: FormEvent) => {
    event.preventDefault();
    if (Math.abs(totalWeight - 1) > 0.0001) {
      setMessage("Weights must total 100% before screening.");
      return;
    }
    const existingTicker = normalizeTicker(positionTicker);
    if (existingShares > 0 && !existingTicker) {
      setMessage(
        "Enter the ticker of your existing position so holdings are only applied to that company.",
      );
      return;
    }
    if (!/^[A-Z]{3}$/.test(capitalCurrency)) {
      setMessage("Enter a three-letter capital currency such as USD.");
      return;
    }
    if (enableDcf && dcfDiscount - 1 <= dcfTerminal) {
      setMessage(
        "The optimistic DCF discount rate (base minus 1%) must exceed terminal growth.",
      );
      return;
    }
    const parsed: ScreenerFilters = {
      include_international: international,
      profitable_only: profitable,
    };
    for (const key of ["industries", "exchanges", "countries"] as const)
      if (filters[key])
        parsed[key] = filters[key]
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean);
    for (const key of [
      "market_cap_min",
      "market_cap_max",
      "average_volume_min",
      "min_revenue_growth",
      "max_forward_pe",
      "min_valuation",
      "min_technical",
      "min_overall",
    ] as const)
      if (filters[key] !== undefined && filters[key] !== "")
        parsed[key] =
          Number(filters[key]) / (key === "min_revenue_growth" ? 100 : 1);
    if (
      parsed.market_cap_min != null &&
      parsed.market_cap_max != null &&
      parsed.market_cap_min > parsed.market_cap_max
    ) {
      setMessage("Minimum market capitalization must not exceed the maximum.");
      return;
    }
    setMessage("");
    refresh.mutate({
      scope: scope.capture(),
      request: {
        horizon,
        filters: parsed,
        weights,
        risk_tolerance: risk,
        capital,
        capital_currency: capitalCurrency,
        risk_per_trade: riskPercent / 100,
        min_reward_risk: minRR,
        commission_bps: commission,
        slippage_bps: slippage,
        existing_shares: existingShares,
        position_ticker: existingShares > 0 ? existingTicker : null,
        cost_basis: costBasis ? Number(costBasis) : null,
        max_deep_analysis: maxDeep,
        valuation_assumptions: enableDcf
          ? {
              enable_dcf: true,
              growth: dcfGrowth / 100,
              discount_rate: dcfDiscount / 100,
              terminal_growth: dcfTerminal / 100,
              years: dcfYears,
            }
          : { enable_dcf: false },
      },
    });
  };
  const changeHorizon = (value: ScreenerHorizon) => {
    setHorizon(value);
    setWeights({ ...WEIGHTS[value] });
    setSelected([]);
    setMessage("");
  };
  const toggle = (ticker: string) =>
    setSelected((previous) => {
      if (previous.includes(ticker))
        return previous.filter((value) => value !== ticker);
      if (previous.length >= 3) {
        setMessage("Choose up to three stocks for comparison.");
        return previous;
      }
      return [...previous, ticker];
    });
  const allRows = [
    ...new Map(
      [
        ...(snapshot?.rankings || []),
        ...(snapshot?.watchlist_candidates || []),
        ...(snapshot?.buy_candidates || []),
        ...(snapshot?.top_ranked ? [snapshot.top_ranked] : []),
      ].map((stock) => [stock.ticker, stock]),
    ).values(),
  ];
  const topRows = sortScreenerStocks(
    snapshot?.rankings || [],
    sortField,
    descending,
  ).slice(0, 10);
  const coverage =
    snapshot?.coverage ||
    currentStatus?.coverage ||
    universe.data?.coverage ||
    {};
  const errors = [
    ...(snapshot?.provider_errors || []),
    ...(currentStatus?.provider_errors || []),
  ].map(errorText);
  const progress =
    job?.total && job.processed != null
      ? Math.min(100, Math.max(0, (job.processed / job.total) * 100))
      : null;
  const busy =
    (refresh.isPending && refresh.variables?.request.horizon === horizon) ||
    running(job) ||
    activeJob?.horizon === horizon;
  const historyResult =
    backtestResult?.horizon === horizon ? backtestResult.result : undefined;
  return (
    <>
      <PageIntro
        eyebrow="FIND OPPORTUNITIES, THEN TEST THE EVIDENCE"
        title="Tech Stock Screener"
        subtitle="Two investment horizons. A dynamic company universe. Explicit limits on what has been analyzed."
      />
      <section className="panel screener-horizon">
        <div>
          <p className="eyebrow">INVESTMENT HORIZON</p>
          <div
            className="period-switch"
            role="group"
            aria-label="Screening investment horizon"
          >
            <button
              aria-pressed={horizon === "short_term"}
              className={horizon === "short_term" ? "active" : ""}
              onClick={() => changeHorizon("short_term")}
            >
              Short-Term Trading
            </button>
            <button
              aria-pressed={horizon === "long_term"}
              className={horizon === "long_term" ? "active" : ""}
              onClick={() => changeHorizon("long_term")}
            >
              Long-Term Investing
            </button>
          </div>
          <p className="scope-note">
            {horizon === "short_term"
              ? "1 trading day to 3 months · technical setups, catalysts and execution risk"
              : "1–5+ years · business quality, growth, valuation and financial resilience"}
          </p>
        </div>
        <Badge>Separate ranking methodologies</Badge>
      </section>
      {rankings.isPending && (
        <div className="loading-strip">
          <LoaderCircle size={14} className="spin" />
          Loading the last persisted screening snapshot. No live rankings are
          invented.
        </div>
      )}
      <div className="screener-candidate-grid">
        <Candidate
          stock={snapshot?.best_eligible}
          eligibleOnly
          title="Top Technology Stock Candidate"
          openStock={openStock}
        />
        <Candidate
          stock={snapshot?.top_ranked}
          title="Highest-ranked stock"
          openStock={openStock}
        />
      </div>
      <form onSubmit={start} className="panel screener-settings">
        <SectionHeading title="Industry filters & screening assumptions">
          <Filter size={17} />
        </SectionHeading>
        <p className="panel-footnote">
          Changes apply to the next background screening run. Existing results
          retain their original timestamp and methodology. Broad screening is
          followed by a bounded deep review; this does not establish
          comprehensive sector coverage.
        </p>
        <p className="panel-footnote">
          {enableDcf
            ? `Optional DCF reference assumptions: ${dcfGrowth}% annual growth, ${dcfDiscount}% discount rate, ${dcfTerminal}% terminal growth, ${dcfYears} projection years. These are disclosed sensitivities, not company forecasts or guaranteed fair values.`
            : "Corporate DCF is disabled for the next screening run; no DCF value will be inferred."}{" "}
          Industry, exchange and listing-region filters accept comma-separated
          values.
        </p>
        <div className="form-grid screener-filter-grid">
          {[
            ["industries", "Industries", "All available industries"],
            ["exchanges", "Exchanges", "All supported exchanges"],
            [
              "countries",
              "Listing country / region",
              "All available listing regions",
            ],
          ].map(([key, title, placeholder]) => (
            <label key={key}>
              {title}
              <input
                list={`screener-${key}`}
                value={filters[key] || ""}
                onChange={(event) =>
                  setFilters({ ...filters, [key]: event.target.value })
                }
                placeholder={placeholder}
              />
              <datalist id={`screener-${key}`}>
                {(
                  (universe.data?.[
                    key as "industries" | "exchanges" | "countries"
                  ] || []) as string[]
                ).map((value) => (
                  <option value={value} key={value} />
                ))}
              </datalist>
            </label>
          ))}
          <label>
            Risk tolerance
            <select
              value={risk}
              onChange={(event) => setRisk(event.target.value)}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          {[
            ["market_cap_min", "Minimum market cap (quote currency)", "0", ""],
            [
              "market_cap_max",
              "Maximum market cap (quote currency)",
              "0.01",
              "",
            ],
            ["average_volume_min", "Minimum average daily volume", "0", ""],
            ["min_revenue_growth", "Minimum revenue growth (%)", "-100", ""],
            ["max_forward_pe", "Maximum forward P/E", "0.01", ""],
            ["min_valuation", "Minimum valuation score /10", "0", "10"],
            ["min_technical", "Minimum technical score /10", "0", "10"],
            ["min_overall", "Minimum overall rating /10", "0", "10"],
          ].map(([key, title, min, max]) => (
            <label key={key}>
              {title}
              <input
                type="number"
                min={min}
                max={max || undefined}
                step="any"
                value={filters[key] || ""}
                onChange={(event) =>
                  setFilters({ ...filters, [key]: event.target.value })
                }
                placeholder="No additional filter"
              />
            </label>
          ))}
        </div>
        <div className="screener-checks">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={profitable}
              onChange={(event) => setProfitable(event.target.checked)}
            />
            Profitable companies only
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={international}
              onChange={(event) => setInternational(event.target.checked)}
            />
            Include available international listings
          </label>
        </div>
        <details className="limitations">
          <summary>Scoring weights & position sizing</summary>
          <p className="panel-footnote">
            Configurable initial reference assumptions, not empirically proven
            optimal weights. Missing categories remain unavailable. Related
            technical measurements are grouped rather than counted as
            independent votes.
          </p>
          <div className="weights-header">
            <h3>
              {horizon === "short_term" ? "Short-term" : "Long-term"} evidence
              weights
            </h3>
            <span
              className={Math.abs(totalWeight - 1) < 0.0001 ? "green" : "amber"}
            >
              {num(totalWeight * 100, 0)}% of 100%
            </span>
          </div>
          <div className="weight-controls">
            {Object.entries(weights).map(([key, value]) => (
              <label key={key}>
                <span>{label(key)}</span>
                <input
                  aria-label={`${label(key)} weight`}
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={Math.round(value * 100)}
                  onChange={(event) =>
                    setWeights({
                      ...weights,
                      [key]: Number(event.target.value) / 100,
                    })
                  }
                />
                <strong>{num(value * 100, 0)}%</strong>
              </label>
            ))}
          </div>
          <button
            type="button"
            className="text-button"
            onClick={() => setWeights({ ...WEIGHTS[horizon] })}
          >
            Restore horizon defaults
          </button>
          <div className="form-grid screener-filter-grid">
            <label>
              Available capital
              <input
                type="number"
                min="1"
                max="1000000000"
                value={capital}
                onChange={(event) => setCapital(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Capital currency
              <input
                value={capitalCurrency}
                onChange={(event) =>
                  setCapitalCurrency(event.target.value.toUpperCase())
                }
                maxLength={3}
                pattern="[A-Z]{3}"
                required
              />
            </label>
            <label>
              Maximum risk per trade (%)
              <input
                type="number"
                min="0.01"
                max="5"
                step="0.01"
                value={riskPercent}
                onChange={(event) => setRiskPercent(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Minimum reward / risk
              <input
                type="number"
                min="1"
                max="10"
                step="0.1"
                value={minRR}
                onChange={(event) => setMinRR(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Maximum companies for deep review
              <input
                type="number"
                min="1"
                max="50"
                value={maxDeep}
                onChange={(event) => setMaxDeep(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Planned commission (bps)
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={commission}
                onChange={(event) => setCommission(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Planned slippage (bps)
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={slippage}
                onChange={(event) => setSlippage(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Existing shares in an analyzed company
              <input
                type="number"
                min="0"
                step="any"
                value={existingShares}
                onChange={(event) =>
                  setExistingShares(Number(event.target.value))
                }
              />
            </label>
            {existingShares > 0 && (
              <label>
                Existing position ticker
                <input
                  value={positionTicker}
                  onChange={(event) => setPositionTicker(event.target.value)}
                  maxLength={32}
                  required
                  placeholder="Ticker of the shares already held"
                />
              </label>
            )}
            <label>
              Cost basis per share (optional)
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={costBasis}
                onChange={(event) => setCostBasis(event.target.value)}
              />
            </label>
          </div>
          <p className="panel-footnote">
            Existing holdings apply only to the specified company. Suggested
            sizes are separate conditional plans, not a combined portfolio
            allocation. A quote in another currency requires verified conversion
            before sizing. Long-term thesis invalidation is separate from an ATR
            or support-based capital-risk stop.
          </p>
        </details>
        <details className="limitations">
          <summary>Optional DCF reference assumptions</summary>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={enableDcf}
              onChange={(event) => setEnableDcf(event.target.checked)}
            />
            Enable DCF sensitivities when reported cash flow and share data are
            suitable
          </label>
          {enableDcf && (
            <div className="form-grid screener-filter-grid">
              {[
                [
                  "Annual cash-flow growth (%)",
                  dcfGrowth,
                  setDcfGrowth,
                  -30,
                  30,
                  0.1,
                ],
                [
                  "Discount rate (%)",
                  dcfDiscount,
                  setDcfDiscount,
                  1.01,
                  40,
                  0.01,
                ],
                [
                  "Terminal growth (%)",
                  dcfTerminal,
                  setDcfTerminal,
                  -5,
                  5,
                  0.1,
                ],
                ["Projection years", dcfYears, setDcfYears, 1, 20, 1],
              ].map(([name, value, setter, min, max, step]) => (
                <label key={String(name)}>
                  {String(name)}
                  <input
                    type="number"
                    value={value as number}
                    min={min as number}
                    max={max as number}
                    step={step as number}
                    required
                    onChange={(event) =>
                      (setter as (value: number) => void)(
                        Number(event.target.value),
                      )
                    }
                  />
                </label>
              ))}
            </div>
          )}
          <p className="panel-footnote">
            The backend varies these assumptions for bear, base and bull
            scenarios. Financial firms, negative cash flow, incompatible
            currencies and missing statements can make a DCF unsuitable. Each
            company’s full research page supports more specific valuation
            assumptions and peer review.
          </p>
        </details>
        <div className="quant-actions">
          <button
            className="button primary"
            disabled={busy || Math.abs(totalWeight - 1) > 0.0001}
          >
            {busy ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            Apply & screen
          </button>
          <span>Snapshot: {dateTime(snapshot?.as_of)}</span>
        </div>
        {message && (
          <p role="status" className="partial-summary">
            {message}
          </p>
        )}
        {refresh.isError && refresh.variables?.request.horizon === horizon && (
          <ErrorBox error={refresh.error} />
        )}
      </form>
      {(rankings.isError || universe.isError || status.isError) && (
        <ErrorBox
          error={rankings.error || universe.error || status.error}
          onRetry={() => {
            rankings.refetch();
            universe.refetch();
            status.refetch();
          }}
        />
      )}
      <section className="panel screener-status">
        <SectionHeading
          eyebrow="WHAT WAS ACTUALLY EVALUATED"
          title="Screening status & coverage"
        >
          <Badge>
            {job?.status ? label(job.status) : "No completed screening run"}
          </Badge>
        </SectionHeading>
        <div className="metric-grid">
          {[
            ["Eligible universe", coverage.total_eligible],
            ["Successfully analyzed", coverage.successfully_analyzed],
            ["Incomplete data", coverage.incomplete],
            ["Excluded from ranking", coverage.excluded],
            ["Ranked", coverage.ranked],
            ["Deep reviews", coverage.deep_analyzed],
          ].map(([title, value]) => (
            <div className="metric-cell" key={String(title)}>
              <span>{title}</span>
              <strong>{num(value, 0)}</strong>
            </div>
          ))}
        </div>
        <p className="panel-footnote">
          Universe source:{" "}
          {coverage.source || universe.data?.source || "Not available"} · Last
          screen {dateTime(snapshot?.as_of)} ·{" "}
          {coverage.comprehensive === true
            ? "Provider reports comprehensive universe membership; analysis coverage remains limited to the counts above."
            : "Coverage is partial or unverified; this is not a claim that the entire technology sector was analyzed."}
        </p>
        {job && (
          <div className="screener-job">
            <span>
              {label(job.stage || job.status || "Pending")} · broad{" "}
              {num(job.processed, 0)} / {num(job.total, 0)} · deep{" "}
              {num(job.deep_processed, 0)} / {num(job.deep_total, 0)}
            </span>
            {progress != null && (
              <progress
                aria-label="Screening progress"
                value={progress}
                max={100}
              />
            )}
            <p>{job.message}</p>
          </div>
        )}
        {errors.length > 0 && (
          <details className="limitations" open>
            <summary>Provider errors ({new Set(errors).size})</summary>
            <Evidence items={[...new Set(errors)]} />
          </details>
        )}
        <Limitations
          items={[
            ...(universe.data?.limitations || []),
            ...(snapshot?.limitations || []),
          ]}
        />
      </section>
      <section className="panel">
        <SectionHeading
          eyebrow="RANKED WITHIN THE ANALYZED COVERAGE"
          title="Top 10 Technology Stocks"
        >
          <label className="screener-sort">
            Sort by
            <select
              value={sortField}
              onChange={(event) => {
                setSortField(event.target.value);
                setDescending(true);
              }}
            >
              {SORT_FIELDS.map(([field, title]) => (
                <option key={field} value={field}>
                  {title}
                </option>
              ))}
            </select>
          </label>
        </SectionHeading>
        {topRows.length ? (
          <RankingTable
            rows={topRows}
            selected={selected}
            toggle={toggle}
            openStock={openStock}
            sortField={sortField}
            descending={descending}
            changeSort={(field) => {
              if (sortField === field) setDescending(!descending);
              else {
                setSortField(field);
                setDescending(true);
              }
            }}
          />
        ) : (
          <Empty title="No companies qualified for ranking">
            <p>
              Insufficient or missing evidence remains unranked. Start a screen,
              broaden filters, or inspect provider errors.
            </p>
          </Empty>
        )}
        <p className="panel-footnote">
          Rows open the complete stock research dashboard. Compare up to three
          companies. Broad screening ratings cannot establish an immediate
          eligible buy. Snapshot methodology:{" "}
          {snapshot?.methodology_version || "Not available"}.
        </p>
        {snapshot?.weights && (
          <details className="limitations">
            <summary>Weights used for this ranking snapshot</summary>
            <DataTable
              rows={Object.entries(snapshot.weights).map(([key, value]) => ({
                category: label(key),
                weight: pct(value),
              }))}
            />
          </details>
        )}
        {snapshot?.configuration?.valuation_assumptions && (
          <details className="limitations">
            <summary>
              Valuation assumptions used in this ranking snapshot
            </summary>
            <DataTable rows={[snapshot.configuration.valuation_assumptions]} />
            <p className="panel-footnote">
              Capital currency:{" "}
              {snapshot.configuration.capital_currency || "Unavailable"} ·
              deep-review budget:{" "}
              {num(snapshot.configuration.max_deep_analysis, 0)} companies.
              These are the saved run settings.
            </p>
          </details>
        )}
      </section>
      <section className="panel">
        <SectionHeading title="Buy Candidates">
          <Check size={17} />
        </SectionHeading>
        {snapshot?.buy_candidates?.some(eligible) ? (
          <div className="screener-watch-grid">
            {snapshot.buy_candidates.filter(eligible).map((stock) => (
              <div key={stock.ticker}>
                <StockLink stock={stock} openStock={openStock} />
                <Badge tone="green">Buy Candidate</Badge>
                <p>
                  {num(stock.overall_score, 1)} /10 · {pct(stock.confidence)}{" "}
                  evidence confidence
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted small-text">
            No qualified buy candidate in the current analyzed coverage.
            Conditional scenarios may still be available for future
            confirmation.
          </p>
        )}
      </section>
      <section className="panel">
        <SectionHeading title="Stocks Worth Watching">
          <Star size={17} />
        </SectionHeading>
        {snapshot?.watchlist_candidates?.length ? (
          <div className="screener-watch-grid">
            {snapshot.watchlist_candidates.map((stock) => (
              <div key={stock.ticker}>
                <StockLink stock={stock} openStock={openStock} />
                <Badge>{recommendation(stock)}</Badge>
                <p>
                  {num(stock.overall_score, 1)} /10 ·{" "}
                  {stock.analysis_stage === "deep"
                    ? "Deep review"
                    : "Broad screen"}
                </p>
                <Evidence
                  items={
                    stock.buy_triggers?.slice(0, 2) ||
                    stock.ranking_explanation?.slice(0, 2)
                  }
                />
                <button
                  className="text-button"
                  onClick={() => addWatch.mutate(stock.ticker)}
                  disabled={addWatch.isPending}
                >
                  <Star size={12} />
                  Add to my watchlist
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted small-text">
            No watchlist candidates were returned for this horizon and snapshot.
          </p>
        )}
      </section>
      <Comparison
        rows={selected
          .map((ticker) => allRows.find((stock) => stock.ticker === ticker))
          .filter((stock): stock is ScreenerStock => Boolean(stock))}
        openStock={openStock}
      />
      <section className="panel">
        <SectionHeading
          eyebrow="HISTORICAL RANKINGS REQUIRE HISTORICAL VINTAGES"
          title="Screener portfolio validation"
        >
          <FlaskConical size={17} />
        </SectionHeading>
        <p className="panel-footnote">
          Today's universe members and current financial statements cannot
          reconstruct past technology-stock rankings. A top-5 or top-10
          portfolio result is withheld unless historical membership,
          publication-time fundamentals and tradable prices are verified. QQQ
          and XLK are comparison benchmarks, not substitute ranking history.
        </p>
        <div className="quant-actions">
          <label className="screener-sort">
            Equal-weight portfolio
            <select
              value={backtestTop}
              onChange={(event) => setBacktestTop(Number(event.target.value))}
            >
              <option value={5}>Top 5</option>
              <option value={10}>Top 10</option>
            </select>
          </label>
          <label className="screener-sort">
            Commission (bps)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={backtestCommission}
              onChange={(event) =>
                setBacktestCommission(Number(event.target.value))
              }
            />
          </label>
          <label className="screener-sort">
            Slippage (bps)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={backtestSlippage}
              onChange={(event) =>
                setBacktestSlippage(Number(event.target.value))
              }
            />
          </label>
          <button
            className="button secondary small"
            onClick={() =>
              backtest.mutate({
                horizon,
                top_n: backtestTop,
                scope: scope.capture(),
              })
            }
            disabled={backtest.isPending}
          >
            Check historical evidence
          </button>
        </div>
        {backtest.isError && backtest.variables?.horizon === horizon && (
          <ErrorBox error={backtest.error} />
        )}
        <div className="notice">
          <ShieldCheck size={16} />
          <p>
            {historyResult?.status || "Insufficient point-in-time evidence"}
            {historyResult?.reason
              ? `: ${historyResult.reason}`
              : ". No historical portfolio performance is inferred from today's stock rankings."}
          </p>
        </div>
        {historyResult?.required_data && (
          <Evidence items={historyResult.required_data} />
        )}
        <Limitations items={historyResult?.limitations} />
      </section>
    </>
  );
}
