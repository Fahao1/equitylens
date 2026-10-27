import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Clock3,
  FlaskConical,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { api, post, retryTransient } from "./api";
import { normalizeTicker } from "./tickerState";
import DataStatus from "./DataStatus";
import type {
  Bag,
  DataSectionStatus,
  ProbabilityInterval,
  QuantCore,
  QuantEvidence,
  QuantProbability,
  QuantRecommendation,
  QuantRegime,
  QuantResearchResponse,
  QuantScores,
  QuantStrategy,
  QuantTimeframe,
} from "./types";
import {
  Badge,
  DataTable,
  ErrorBox,
  Evidence,
  Limitations,
  SectionHeading,
  currencySymbol,
  dateOnly,
  dateTime,
  label,
  num,
  pct,
  strings,
} from "./ui";

const SCORE_LABELS = {
  company_quality: "Company quality",
  valuation_attractiveness: "Valuation attractiveness",
  technical_strength: "Technical strength",
  trade_setup_quality: "Trade setup quality",
  macroeconomic_environment: "Macroeconomic environment",
  overall_investment_attractiveness: "Overall investment attractiveness",
} as const;
const STRATEGIES = [
  ["trend_following", "Trend following"],
  ["breakout", "Breakout"],
  ["mean_reversion", "Mean reversion"],
  ["fundamental_value", "Fundamental value"],
] as const;
const FRAMES = ["weekly", "daily", "4h", "1h", "15m"];
const finite = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const available = (value: unknown) =>
  value == null
    ? "Not available"
    : typeof value === "number"
      ? num(value)
      : typeof value === "string"
        ? value
        : typeof value === "object"
          ? (value as Bag).label ||
            (value as Bag).status ||
            (value as Bag).level ||
            (value as Bag).description ||
            ((value as Bag).value != null
              ? String((value as Bag).value)
              : "Not available")
          : "Not available";
const amount = (value: unknown, symbol: string) =>
  finite(value) == null ? "—" : `${symbol}${num(value)}`;
const zone = (value: unknown, symbol: string) =>
  Array.isArray(value) &&
  value.length === 2 &&
  value.every((v) => finite(v) != null)
    ? `${amount(value[0], symbol)} – ${amount(value[1], symbol)}`
    : "—";
const ratio = (value: unknown) =>
  finite(value) == null ? "—" : `${num(value)} : 1`;
const interval = (value: ProbabilityInterval | undefined) =>
  Array.isArray(value)
    ? value
    : value && typeof value === "object"
      ? [value.lower, value.upper]
      : null;
export function pendingQuantPlan(
  plan: QuantRecommendation | undefined,
  authoritative = false,
): QuantRecommendation {
  if (!plan) return {};
  if (authoritative || !/buy|eligible/i.test(plan.recommendation || ""))
    return plan;
  return {
    ...plan,
    recommendation: "Wait",
    position_size: 0,
    status: "Full benchmark, timeframe and historical review is pending.",
    limitations: [
      ...(plan.limitations || []),
      "A preliminary daily-rule result is not an authoritative full-context trade recommendation.",
    ],
  };
}
function StrategyTable({
  strategies,
  symbol,
}: {
  strategies: QuantStrategy[];
  symbol: string;
}) {
  const rows = STRATEGIES.map(
    ([id, name]) =>
      strategies.find((strategy) => strategy.id === id) || {
        id,
        name,
        status: "insufficient_data",
        eligible: false,
        avoid_reasons: ["No result was returned for this strategy."],
      },
  );
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="DISTINCT RULES, EXPLICIT ELIGIBILITY"
        title="Strategy comparison"
      >
        <FlaskConical size={18} />
      </SectionHeading>
      <p className="panel-footnote">
        Each strategy has its own entry conditions and invalidation rules.
        Targets come from the supplied evidence; they are never moved to
        manufacture an attractive reward/risk ratio.
      </p>
      <div className="table-scroll">
        <table className="quant-strategy-table">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Eligibility</th>
              <th>Entry zone</th>
              <th>Stop / invalidation</th>
              <th>Target 1</th>
              <th>Target 2</th>
              <th>Target 3</th>
              <th>Net R/R T1 / T2 / T3</th>
              <th>Shares</th>
              <th>Horizon</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((strategy) => (
              <tr key={strategy.id}>
                <td>
                  <strong>{strategy.name || label(strategy.id)}</strong>
                </td>
                <td>
                  <Badge
                    tone={
                      strategy.eligible
                        ? "green"
                        : strategy.status === "avoid"
                          ? "red"
                          : "neutral"
                    }
                  >
                    {label(strategy.status || "insufficient_data")}
                  </Badge>
                </td>
                <td>{zone(strategy.entry_zone, symbol)}</td>
                <td>
                  {amount(strategy.stop, symbol)}
                  {strategy.invalidation?.kind && (
                    <small className="scope-note">
                      {label(strategy.invalidation.kind)}
                    </small>
                  )}
                </td>
                {[0, 1, 2].map((index) => (
                  <td key={index}>
                    {amount(strategy.targets?.[index], symbol)}
                  </td>
                ))}
                <td>
                  {[0, 1, 2]
                    .map((index) =>
                      ratio(
                        strategy.net_reward_risk?.[index] ??
                          (index === 0 ? strategy.risk_reward : null),
                      ),
                    )
                    .join(" / ")}
                </td>
                <td>{num(strategy.position_size, 0)}</td>
                <td>{strategy.holding_horizon || "Not specified"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="panel-footnote">
        Net reward/risk includes the configured commissions and slippage.
        Eligibility is a rule result, not a probability of success. Historical
        validation exits fully at the first target.
      </p>
      {rows.map((strategy) => (
        <details className="limitations" key={strategy.id}>
          <summary>
            {strategy.name || label(strategy.id)} — why this result
          </summary>
          {strategy.entry_condition && <p>{strategy.entry_condition}</p>}
          <Evidence
            items={strategy.evidence}
            empty="No supporting evidence was returned."
          />
          {Boolean(strategy.avoid_reasons?.length) && (
            <>
              <h3 className="subsection-title">Reasons to wait or avoid</h3>
              <Evidence items={strategy.avoid_reasons} />
            </>
          )}
          {strategy.invalidation?.condition && (
            <p>
              {label(strategy.invalidation.kind || "invalidation")}:{" "}
              {strategy.invalidation.condition}
            </p>
          )}
          {Boolean(strategy.target_methodology?.length) && (
            <>
              <h3 className="subsection-title">Target evidence</h3>
              <Evidence items={strategy.target_methodology} />
            </>
          )}
          {Boolean(strategy.calculation?.length) && (
            <>
              <h3 className="subsection-title">
                Level and sizing calculations
              </h3>
              <Evidence items={strategy.calculation} />
            </>
          )}
        </details>
      ))}
    </section>
  );
}
function RegimeContext({ regime }: { regime?: QuantRegime }) {
  const features = regime?.features || {};
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="MARKET CONTEXT BEFORE A SETUP"
        title="Regime & benchmark context"
      >
        <Badge>{regime?.regime || "Insufficient Data"}</Badge>
      </SectionHeading>
      <div className="metric-grid">
        <div className="metric-cell">
          <span>Trend strength</span>
          <strong className="metric-text">
            {available(regime?.trend_strength)}
          </strong>
        </div>
        <div className="metric-cell">
          <span>Volatility regime</span>
          <strong className="metric-text">
            {available(regime?.volatility_regime)}
          </strong>
        </div>
        <div className="metric-cell">
          <span>Benchmark trend</span>
          <strong className="metric-text">
            {available(features.benchmark_trend)}
          </strong>
        </div>
        <div className="metric-cell">
          <span>Regime evidence confidence</span>
          <strong>{pct(regime?.confidence)}</strong>
        </div>
      </div>
      <Evidence
        items={regime?.evidence}
        empty="Regime evidence is not available yet."
      />
      <p className="panel-footnote">
        ATR percentile: {num(features.atr_percentile, 0)} /100 ·
        historical-volatility percentile: {num(features.hv_percentile, 0)} /100
        · benchmark relative strength (63 bars):{" "}
        {pct(features.relative_strength_63)}.
      </p>
      <Limitations items={regime?.limitations} />
      <p className="panel-footnote">
        The classifier distinguishes strong and weak bullish/bearish trends,
        consolidation and high volatility. This context is descriptive; its
        confidence is not a chance of profit.
      </p>
    </section>
  );
}
function evidenceMetric(
  evidence: QuantEvidence,
  key: "data_freshness" | "model_uncertainty" | "sample_reliability",
) {
  const value = evidence[key];
  if (value == null) return "Not assessed";
  if (typeof value === "string") return value;
  if (typeof value === "number") return pct(value);
  if (key === "model_uncertainty")
    return value.calibrated === false
      ? "Not calibrated"
      : available(value.kind || value.status || value);
  if (key === "sample_reliability") return available(value.status || value);
  const freshnessSources =
    value.sections && typeof value.sections === "object"
      ? value.sections
      : value;
  if (value.quote_stale) return "Stale source present";
  const sources = Object.values(freshnessSources).filter(
    (item) => item && typeof item === "object",
  ) as Bag[];
  if (sources.some((item) => item.cache_stale || item.stale))
    return "Stale source present";
  return sources.length ? "Source timestamps below" : available(value);
}
function ScoreEvidence({
  scores = {},
  evidence = {},
  adapter = {},
}: {
  scores?: QuantScores;
  evidence?: QuantEvidence;
  adapter?: Bag;
}) {
  const freshness =
    evidence.data_freshness && typeof evidence.data_freshness === "object"
      ? evidence.data_freshness
      : {};
  const sourceRows = Object.entries(freshness.sections || freshness).filter(
    ([, value]) =>
      value &&
      typeof value === "object" &&
      ("status" in value || "fetched_at" in value),
  );
  const reliability =
    evidence.sample_reliability &&
    typeof evidence.sample_reliability === "object"
      ? evidence.sample_reliability
      : null;
  const uncertainty =
    evidence.model_uncertainty && typeof evidence.model_uncertainty === "object"
      ? evidence.model_uncertainty
      : null;
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="SIX ASSESSMENTS, SEPARATE MEANINGS"
        title="Scores & evidence quality"
      >
        <ShieldCheck size={18} />
      </SectionHeading>
      <div className="quant-score-grid">
        {Object.entries(SCORE_LABELS).map(([key, title]) => (
          <div className="metric-cell" key={key}>
            <span>{title}</span>
            <strong>
              {num(scores[key], 1)}
              <small className="muted"> /10</small>
            </strong>
            <p className="scope-note">
              Evidence confidence:{" "}
              {pct(
                key === "overall_investment_attractiveness"
                  ? adapter.confidence
                  : adapter.categories?.find((row: Bag) => row.key === key)
                      ?.confidence,
              )}
            </p>
            {scores.weights?.[key] != null && (
              <p className="scope-note">
                {pct(scores.weights[key])} model weight
              </p>
            )}
            {scores.contributions &&
              !Array.isArray(scores.contributions) &&
              scores.contributions[key] != null && (
                <p className="scope-note">
                  {num(scores.contributions[key])} weighted contribution
                </p>
              )}
          </div>
        ))}
      </div>
      <p className="panel-footnote">
        These are research scores, not probabilities. A strong company can still
        have an unattractive valuation or no eligible trade setup. Missing
        assessments stay unavailable.
      </p>
      <div className="quant-evidence-grid">
        <div className="metric-cell">
          <span>Evidence confidence</span>
          <strong>{pct(evidence.confidence)}</strong>
          <p className="scope-note">Coverage of the required evidence</p>
        </div>
        <div className="metric-cell">
          <span>Data freshness</span>
          <strong className="metric-text">
            {evidenceMetric(evidence, "data_freshness")}
          </strong>
        </div>
        <div className="metric-cell">
          <span>Model uncertainty</span>
          <strong className="metric-text">
            {evidenceMetric(evidence, "model_uncertainty")}
          </strong>
        </div>
        <div className="metric-cell">
          <span>Sample reliability</span>
          <strong className="metric-text">
            {evidenceMetric(evidence, "sample_reliability")}
          </strong>
          {reliability && (
            <p className="scope-note">
              N={num(reliability.sample_size, 0)} · minimum{" "}
              {num(reliability.min_samples, 0)}
            </p>
          )}
        </div>
      </div>
      {(sourceRows.length > 0 ||
        freshness.quote_at ||
        freshness.decision_bar_as_of) && (
        <details className="limitations">
          <summary>Source freshness and availability</summary>
          {freshness.quote_at && (
            <p>Quoted trade timestamp: {dateTime(freshness.quote_at)}</p>
          )}
          {freshness.decision_bar_as_of && (
            <p>Decision bar as of: {dateTime(freshness.decision_bar_as_of)}</p>
          )}
          {freshness.completion_rule && <p>{freshness.completion_rule}</p>}
          {sourceRows.map(([name, status]) => (
            <DataStatus
              key={name}
              label={label(name)}
              status={status as DataSectionStatus}
            />
          ))}
        </details>
      )}
      {uncertainty && <Limitations items={uncertainty.limitations} />}
      {scores.formula && (
        <details className="limitations">
          <summary>Scoring formula, weights and news adjustment</summary>
          <p>{scores.formula}</p>
          <p>
            Investment horizon: {scores.horizon || "Not specified"} · Known
            weighted coverage: {pct(scores.coverage)} · Bounded news adjustment:{" "}
            {num(scores.news_modifier)} score points.
          </p>
          <Evidence
            items={Object.entries(scores.weight_mapping || {}).map(
              ([key, value]) =>
                `${SCORE_LABELS[key as keyof typeof SCORE_LABELS] || label(key)}: ${value}`,
            )}
          />
        </details>
      )}
      <Limitations items={evidence.limitations} />
    </section>
  );
}
function ValuationEvidence({
  data = {},
  symbol,
}: {
  data?: Bag;
  symbol: string;
}) {
  const models = Object.entries(data.models || {}) as [string, Bag][];
  const peers = data.peer_comparison || {},
    history = data.historical_comparison || {};
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="EXPLICIT ASSUMPTIONS, SHARED MODEL RISKS"
        title="Valuation scenarios & comparisons"
      />
      {data.applicable === false ? (
        <p className="panel-footnote">
          Corporate valuation models are not applicable to this instrument.
        </p>
      ) : (
        <>
          {models.length ? (
            <DataTable
              rows={models.map(([name, values]) => ({
                model: label(name),
                bear: amount(values.bear, symbol),
                base: amount(values.base, symbol),
                bull: amount(values.bull, symbol),
              }))}
            />
          ) : (
            <p className="panel-footnote">
              No explicit valuation model is available for this request. Enter
              defensible assumptions above to evaluate scenarios.
            </p>
          )}
          {data.valuation_range && (
            <div className="quant-probability-meta">
              <span>
                Combined bear / base / bull:{" "}
                <strong>
                  {["bear", "base", "bull"]
                    .map((key) => amount(data.valuation_range[key], symbol))
                    .join(" / ")}
                </strong>
              </span>
              <span>
                Margin of safety to model base:{" "}
                <strong>{pct(data.margin_of_safety)}</strong>
              </span>
            </div>
          )}
          {data.model_uncertainty?.aggregation && (
            <p className="panel-footnote">
              {data.model_uncertainty.aggregation}
            </p>
          )}
          <Limitations items={data.model_uncertainty?.limitations} />
          <details className="limitations">
            <summary>Comparable peers and historical valuations</summary>
            <p>
              Peer evidence: {peers.status || "Not supplied"} · minimum{" "}
              {num(peers.minimum_peers, 0)} peers · median P/E{" "}
              {num(peers.median_pe)}.
            </p>
            {peers.peers?.length > 0 && (
              <DataTable
                rows={peers.peers.map((row: Bag) => ({
                  ticker: row.ticker,
                  company: row.name,
                  trailing_pe: row.trailing_pe,
                  industry: row.industry,
                  currency: row.currency,
                  fetched_at: dateTime(row.fetched_at),
                }))}
              />
            )}
            <Evidence
              items={(peers.excluded || []).map(
                (row: Bag) => `${row.ticker}: ${row.reason}`,
              )}
              empty="No excluded peer results were returned."
            />
            <Limitations items={peers.limitations} />
            <p>
              Historical evidence: {history.status || "Not supplied"} ·
              observations {num(history.observations?.length, 0)} · median P/E{" "}
              {num(history.median_pe)}.
            </p>
            {typeof history.source === "string" && (
              <p>Source: {history.source}</p>
            )}
            {history.observations?.length > 0 && (
              <DataTable
                rows={history.observations.map((row: Bag) => ({
                  date: dateOnly(row.date),
                  trailing_pe: row.trailing_pe,
                }))}
              />
            )}
            <Limitations items={history.limitations} />
          </details>
        </>
      )}
      <Limitations items={data.limitations} />
    </section>
  );
}
function TimeframeEvidence({
  data,
  loading,
  symbol,
}: {
  data?: QuantResearchResponse["timeframes"];
  loading: boolean;
  symbol: string;
}) {
  const frames: QuantTimeframe[] = FRAMES.map(
    (timeframe) =>
      data?.timeframes?.find((row) => row.timeframe === timeframe) || {
        timeframe,
        status: loading ? "loading" : "unavailable",
        limitations: [
          "No completed-bar evidence was returned for this timeframe.",
        ],
      },
  );
  const alignment = data?.alignment;
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="RELATED TIMEFRAMES, NOT INDEPENDENT VOTES"
        title="Multi-timeframe evidence"
      >
        <Badge>{available(alignment)}</Badge>
      </SectionHeading>
      <p className="panel-footnote">
        Weekly, daily and intraday observations overlap. Agreement provides
        context; five matching timeframes are not five independent
        confirmations.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Timeframe</th>
              <th>Availability</th>
              <th>Trend</th>
              <th>Momentum</th>
              <th>Volatility</th>
              <th>Support</th>
              <th>Resistance</th>
              <th>Bars</th>
              <th>Last included bar</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {frames.map((frame) => (
              <tr key={frame.timeframe}>
                <td>{label(frame.timeframe)}</td>
                <td>
                  <Badge>{label(frame.status)}</Badge>
                </td>
                <td>{available(frame.trend)}</td>
                <td>{available(frame.momentum)}</td>
                <td>{available(frame.volatility)}</td>
                <td>
                  {Array.isArray(frame.support)
                    ? frame.support
                        .map((value) => amount(value, symbol))
                        .join(", ")
                    : amount(frame.support, symbol)}
                </td>
                <td>
                  {Array.isArray(frame.resistance)
                    ? frame.resistance
                        .map((value) => amount(value, symbol))
                        .join(", ")
                    : amount(frame.resistance, symbol)}
                </td>
                <td>{num(frame.bars, 0)}</td>
                <td>
                  {frame.last_bar_end
                    ? dateTime(frame.last_bar_end)
                    : frame.last_bar_at
                      ? `Session label: ${dateTime(frame.last_bar_at)}`
                      : "Not available"}
                </td>
                <td>
                  {typeof frame.source === "string"
                    ? frame.source
                    : frame.source?.name ||
                      frame.source?.provider ||
                      frame.source?.source ||
                      "Not available"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {alignment && typeof alignment === "object" && (
        <>
          <h3 className="subsection-title">Alignment & conflicts</h3>
          <Evidence
            items={[
              ...strings(alignment.contradictions || alignment.conflicts),
              ...strings(alignment.evidence),
              ...strings(alignment.limitations),
            ]}
            empty="No explicit conflict interpretation was returned."
          />
        </>
      )}
      <Limitations
        items={[
          ...(data?.limitations || []),
          ...frames.flatMap((frame) =>
            (frame.limitations || []).map(
              (item) => `${frame.timeframe}: ${item}`,
            ),
          ),
        ]}
      />
    </section>
  );
}
function Recommendation({
  data = {},
  strategies,
  symbol,
}: {
  data?: QuantRecommendation;
  strategies: QuantStrategy[];
  symbol: string;
}) {
  const selected = strategies.find(
    (strategy) => strategy.id === data.best_strategy,
  );
  const invalidation = Array.isArray(data.invalidation)
    ? data.invalidation
    : data.invalidation?.condition
      ? [data.invalidation.condition]
      : [];
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="CONDITIONAL, COST-AWARE DECISION SUPPORT"
        title="Selected investment plan"
      >
        <Badge
          tone={
            /buy/i.test(data.recommendation || "")
              ? "green"
              : /avoid|sell/i.test(data.recommendation || "")
                ? "red"
                : "neutral"
          }
        >
          {data.recommendation || "Insufficient Data"}
        </Badge>
      </SectionHeading>
      <p className="partial-summary">
        Selected strategy:{" "}
        {selected?.name ||
          data.best_strategy ||
          "No eligible strategy selected"}
      </p>
      {data.status && <p className="panel-footnote">{data.status}</p>}
      {data.entry_condition && (
        <p className="panel-footnote">{data.entry_condition}</p>
      )}
      <div className="metric-grid">
        <div className="metric-cell">
          <span>Potential entry zone</span>
          <strong className="metric-text">
            {zone(data.entry_zone, symbol)}
          </strong>
        </div>
        <div className="metric-cell">
          <span>Stop / invalidation</span>
          <strong>{amount(data.stop, symbol)}</strong>
        </div>
        <div className="metric-cell">
          <span>First-target net reward/risk</span>
          <strong>{ratio(data.risk_reward)}</strong>
        </div>
        <div className="metric-cell">
          <span>Suggested additional shares</span>
          <strong>{num(data.position_size, 0)}</strong>
        </div>
      </div>
      {Boolean(data.targets?.length) && (
        <p className="panel-footnote">
          Targets:{" "}
          {data.targets
            ?.map((value, index) => `T${index + 1} ${amount(value, symbol)}`)
            .join(" · ")}
        </p>
      )}
      <Evidence
        items={data.event_warnings}
        empty="No event-risk interpretation was returned. This is not evidence of an event-free calendar."
      />
      <details className="limitations">
        <summary>Conditions, invalidation and calculations</summary>
        <Evidence
          items={[...strings(data.calculation), ...strings(invalidation)]}
        />
      </details>
      <Limitations items={data.limitations} />
    </section>
  );
}
function probabilityDetail(probabilities: QuantProbability, key: string) {
  const raw =
    probabilities.estimates?.[
      key as keyof NonNullable<QuantProbability["estimates"]>
    ];
  const object = raw && typeof raw === "object" ? raw : null;
  const details =
    object ||
    probabilities.estimate_details?.[key] ||
    (key === "target_2_before_stop" ? probabilities.target_2 : {}) ||
    {};
  const value = finite(
    object?.value ?? object?.estimate ?? object?.probability ?? raw,
  );
  const ownN = finite(
    details.sample_size ??
      probabilities.sample_sizes?.[key] ??
      probabilities[`${key}_sample_size`],
  );
  const n =
    ownN ??
    (key === "target_2_before_stop" ? null : finite(probabilities.sample_size));
  const minimum = finite(probabilities.min_samples);
  const status = details.status || probabilities.status;
  const bounds = interval(probabilities.confidence_intervals?.[key]);
  const validInterval = Boolean(
    bounds &&
      finite(bounds[0]) != null &&
      finite(bounds[1]) != null &&
      Number(bounds[0]) >= 0 &&
      Number(bounds[1]) <= 1 &&
      Number(bounds[0]) <= Number(bounds[1]) &&
      value != null &&
      Number(bounds[0]) <= value &&
      value <= Number(bounds[1]),
  );
  const eligible =
    String(status).toLowerCase() === "available" &&
    n != null &&
    minimum != null &&
    n >= minimum &&
    value != null;
  return { value, n, minimum, bounds, eligible: eligible && validInterval };
}
export function ProbabilityEvidence({
  probabilities,
  loading = false,
}: {
  probabilities?: QuantProbability;
  loading?: boolean;
}) {
  const p = probabilities || {};
  const period = p.validation_period;
  const periodText =
    typeof period === "string"
      ? period
      : period
        ? `${dateOnly(period.start)} – ${dateOnly(period.end)}`
        : "Not supplied";
  const topAvailable =
    String(p.status).toLowerCase() === "available" &&
    finite(p.sample_size) != null &&
    finite(p.min_samples) != null &&
    Number(p.sample_size) >= Number(p.min_samples);
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="HISTORICAL FREQUENCIES, NOT A CALIBRATED FORECAST"
        title="Conditional outcome evidence"
      >
        <Badge>
          {loading && !probabilities
            ? "Loading validation"
            : p.status || "Insufficient historical evidence"}
        </Badge>
      </SectionHeading>
      <div className="quant-probability-meta">
        <span>
          Comparable nonoverlapping observations:{" "}
          <strong>{num(p.sample_size, 0)}</strong>
        </span>
        <span>
          Minimum sample: <strong>{num(p.min_samples, 0)}</strong>
        </span>
        <span>
          Validation period: <strong>{periodText}</strong>
        </span>
      </div>
      {!topAvailable && (
        <div className="notice">
          <ShieldCheck size={16} />
          <p>
            {loading && !probabilities
              ? "Historical validation is still running. No outcome estimate is inferred while it loads."
              : "Insufficient historical evidence. Probability and expected-outcome estimates are withheld; no default success rate is substituted."}
          </p>
        </div>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Historical event</th>
              <th>Frequency</th>
              <th>95% confidence interval</th>
              <th>Eligible N</th>
              <th>Evidence status</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["target_1_before_stop", "Target 1 before stop"],
              ["target_2_before_stop", "Target 2 before stop"],
              ["stop_before_target", "Stop before target"],
            ].map(([key, title]) => {
              const detail = probabilityDetail(p, key);
              const show =
                topAvailable &&
                detail.eligible &&
                detail.value! >= 0 &&
                detail.value! <= 1;
              return (
                <tr key={key}>
                  <td>{title}</td>
                  <td>{show ? pct(detail.value) : "Withheld"}</td>
                  <td>
                    {show
                      ? `${pct(detail.bounds?.[0])} – ${pct(detail.bounds?.[1])}`
                      : "Not available"}
                  </td>
                  <td>{num(detail.n, 0)}</td>
                  <td>
                    {show
                      ? "Historical frequency"
                      : "Insufficient historical evidence"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="quant-mean-outcomes">
        <span>
          Mean historical net return:{" "}
          <strong>
            {topAvailable
              ? pct(
                  typeof p.estimates?.expected_return === "number"
                    ? p.estimates.expected_return
                    : (p.estimates?.expected_return as Bag)?.value,
                )
              : "Withheld"}
          </strong>
        </span>
        <span>
          Mean historical holding period:{" "}
          <strong>
            {topAvailable
              ? `${num(typeof p.estimates?.expected_holding_bars === "number" ? p.estimates.expected_holding_bars : (p.estimates?.expected_holding_bars as Bag)?.value, 1)} bars`
              : "Withheld"}
          </strong>
        </span>
      </div>
      {p.counts && (
        <p className="panel-footnote">
          Observed outcomes: target {num(p.counts.target, 0)} · stop{" "}
          {num(p.counts.stop, 0)} · timeout {num(p.counts.timeout, 0)}.
          Boundary-censored observations are excluded from the comparison
          sample.
        </p>
      )}
      {topAvailable && interval(p.confidence_intervals?.expected_return) && (
        <p className="panel-footnote">
          Mean net-return 95% interval:{" "}
          {pct(interval(p.confidence_intervals?.expected_return)?.[0])} –{" "}
          {pct(interval(p.confidence_intervals?.expected_return)?.[1])}. This
          uses the model’s disclosed mean-return interval method, not the Wilson
          binary-frequency interval.
        </p>
      )}
      {p.metadata && (
        <details className="limitations">
          <summary>Sample definition and calibration diagnostics</summary>
          {p.comparison && <DataTable rows={[p.comparison]} />}
          <Evidence
            items={[
              p.metadata.cohort,
              p.metadata.denominator,
              p.metadata.return_basis,
              p.calibration?.method,
            ].filter(Boolean)}
          />
          {p.calibration && (
            <>
              <p className="panel-footnote">
                Calibration diagnostic status:{" "}
                {p.calibration.status || "Not available"}
              </p>
              <DataTable
                rows={[
                  {
                    held_out_predictions: p.calibration.prediction_count,
                    minimum_predictions: p.calibration.min_predictions,
                    brier_score: p.calibration.brier_score,
                    expanding_history_baseline_brier:
                      p.calibration.history_mean_baseline_brier,
                  },
                ]}
              />
              <Limitations items={p.calibration.limitations} />
            </>
          )}
        </details>
      )}
      <p className="panel-footnote">
        Intervals describe uncertainty in an observed frequency, not a
        guaranteed future range. Target 2 requires its own sample. Timeouts
        remain a third outcome; target and stop frequencies need not sum to
        100%.
      </p>
      <Limitations items={p.limitations} />
    </section>
  );
}
function validationMetrics(metrics: Bag, symbol: string) {
  return Object.fromEntries(
    Object.entries(metrics || {}).map(([key, value]) => [
      key,
      typeof value !== "number"
        ? value
        : /return|_percent$|drawdown|win_rate|average_mae|average_mfe/.test(key)
          ? pct(value)
          : [
                "starting_capital",
                "ending_equity",
                "average_gain",
                "average_loss",
                "expectancy",
              ].includes(key)
            ? amount(value, symbol)
            : /trades|^sample_size$/.test(key)
              ? num(value, 0)
              : num(value),
    ]),
  );
}
function HistoricalValidation({
  validation,
  symbol,
}: {
  validation?: QuantResearchResponse["validation"];
  symbol: string;
}) {
  const rows = STRATEGIES.map(([id, name]) => {
    const entry = validation?.strategies?.[id] || {},
      metrics = entry.metrics || {};
    return {
      strategy: name,
      status: entry.status || "Not available",
      sample_size: entry.sample_size,
      win_rate: metrics.win_rate,
      total_return: metrics.total_return ?? metrics.cost_adjusted_return,
      maximum_drawdown: metrics.maximum_drawdown ?? metrics.max_drawdown,
      sharpe_ratio: metrics.sharpe_ratio ?? metrics.sharpe,
      holding_bars: metrics.average_holding_bars ?? metrics.holding_period,
    };
  });
  return (
    <section className="panel">
      <SectionHeading
        eyebrow="POINT-IN-TIME RULES, CHRONOLOGICAL HOLDOUT"
        title="Historical strategy validation"
      >
        <FlaskConical size={18} />
      </SectionHeading>
      <DataTable rows={rows.map((row) => validationMetrics(row, symbol))} />
      {validation?.benchmark && (
        <p className="panel-footnote">
          Same-window buy-and-hold return:{" "}
          {pct(validation.benchmark.buy_and_hold_return)} · selected benchmark
          return: {pct(validation.benchmark.benchmark_return)}. Benchmark
          results are historical comparisons.
        </p>
      )}
      <p className="panel-footnote">
        These are historical rule results after modeled costs. Current financial
        statements, news and revised macro releases cannot support earlier
        simulated decisions. Descriptive results with a small sample do not
        establish a reliable edge.
      </p>
      {STRATEGIES.map(([id, name]) => {
        const entry = validation?.strategies?.[id];
        if (!entry) return null;
        const holdout = entry.out_of_sample;
        return (
          <details className="limitations" key={id}>
            <summary>{name} — holdout, walk-forward and sensitivity</summary>
            <h3 className="subsection-title">
              Descriptive performance and excursions
            </h3>
            <DataTable
              rows={[validationMetrics(entry.metrics || {}, symbol)]}
            />
            <p className="panel-footnote">
              Known-path excursion bounds from completed held bars and execution
              points; exact exit-bar excursions are unavailable. Signed adverse
              excursion is an upper bound; favorable excursion is a lower bound.
            </p>
            {holdout?.metrics && (
              <>
                <h3 className="subsection-title">Out-of-sample results</h3>
                <p className="panel-footnote">
                  {dateOnly(holdout.start)} – {dateOnly(holdout.end)} · trades{" "}
                  {num(holdout.sample_size, 0)} · mature probability
                  observations {num(holdout.probability_sample_size, 0)} ·
                  overlapping training observations purged{" "}
                  {num(holdout.training_samples_purged, 0)}.
                </p>
                <p className="panel-footnote">{holdout.method}</p>
                <DataTable
                  rows={[validationMetrics(holdout.metrics, symbol)]}
                />
              </>
            )}
            {Array.isArray(entry.walk_forward) &&
              entry.walk_forward.length > 0 && (
                <>
                  <h3 className="subsection-title">Walk-forward windows</h3>
                  <DataTable
                    rows={entry.walk_forward.map((fold: Bag) => ({
                      start: dateOnly(fold.start),
                      end: dateOnly(fold.end),
                      sample_size: fold.sample_size,
                      ...validationMetrics(fold.metrics, symbol),
                    }))}
                  />
                </>
              )}
            {Array.isArray(entry.sensitivity) &&
              entry.sensitivity.length > 0 && (
                <>
                  <h3 className="subsection-title">
                    Rule and cost sensitivity
                  </h3>
                  <p className="panel-footnote">
                    Training-only descriptive checks. No variant is selected for
                    its held-out return.
                  </p>
                  <DataTable
                    rows={entry.sensitivity.map((run: Bag) => ({
                      scenario: run.scenario,
                      scope: run.scope,
                      ...(run.changes || run.config),
                      ...validationMetrics(run.metrics, symbol),
                    }))}
                  />
                </>
              )}
            <Evidence
              items={entry.limitations}
              empty="No additional validation detail was returned."
            />
          </details>
        );
      })}
      <Limitations items={validation?.limitations} />
    </section>
  );
}

type QuantParameters = {
  benchmark_ticker: string;
  min_samples: number;
  commission_bps?: number;
  slippage_bps?: number;
  max_holding_bars?: number;
  margin_of_safety?: number;
  valuation_assumptions?: Bag;
  peer_tickers?: string[];
};
export default function QuantResearch({
  ticker,
  horizon = "swing",
  ready = false,
  baseConfig,
  initialParameters,
  core,
  currency,
  scopeKey = "",
  onResult,
}: {
  ticker: string;
  horizon?: string;
  ready?: boolean;
  baseConfig?: Bag;
  initialParameters?: Bag;
  core?: QuantCore;
  currency?: string;
  scopeKey?: string;
  onResult?: (result: QuantResearchResponse | null, scopeKey: string) => void;
}) {
  const restored = initialParameters || {};
  const restoredValuation = restored.valuation_assumptions || {};
  const [draftBenchmark, setDraftBenchmark] = useState(
    String(restored.benchmark_ticker || baseConfig?.benchmark_ticker || "SPY"),
  );
  const [draftN, setDraftN] = useState(restored.min_samples ?? 30),
    [commission, setCommission] = useState(
      restored.commission_bps == null ? "" : String(restored.commission_bps),
    ),
    [slippage, setSlippage] = useState(
      restored.slippage_bps == null ? "" : String(restored.slippage_bps),
    ),
    [holding, setHolding] = useState(
      restored.max_holding_bars == null
        ? ""
        : String(restored.max_holding_bars),
    );
  const [useValuation, setUseValuation] = useState(
      Boolean(restored.valuation_assumptions),
    ),
    [enableDcf, setEnableDcf] = useState(Boolean(restoredValuation.enable_dcf)),
    [growth, setGrowth] = useState((restoredValuation.growth ?? 0.05) * 100),
    [discount, setDiscount] = useState(
      (restoredValuation.discount_rate ?? 0.1) * 100,
    ),
    [terminal, setTerminal] = useState(
      (restoredValuation.terminal_growth ?? 0.02) * 100,
    ),
    [years, setYears] = useState(restoredValuation.years ?? 5),
    [multiples, setMultiples] = useState<string>(
      (restoredValuation.earnings_multiples || []).join(", "),
    ),
    [fcfYields, setFcfYields] = useState<string>(
      (restoredValuation.fcf_yields || [])
        .map((value: number) => value * 100)
        .join(", "),
    ),
    [peers, setPeers] = useState<string>(
      (restored.peer_tickers || []).join(", "),
    ),
    [margin, setMargin] = useState((restored.margin_of_safety ?? 0.2) * 100);
  const resultCallback = useRef(onResult);
  useEffect(() => {
    resultCallback.current = onResult;
  }, [onResult]);
  const [parameters, setParameters] = useState<QuantParameters | null>(
      (initialParameters as QuantParameters) || null,
    ),
    [parameterError, setParameterError] = useState("");
  const query = useQuery({
    queryKey: [
      "quantitative",
      ticker,
      horizon,
      scopeKey,
      baseConfig || null,
      parameters,
    ],
    queryFn: ({ signal }) =>
      parameters || baseConfig
        ? post<QuantResearchResponse>(
            `/stocks/${encodeURIComponent(ticker)}/quantitative`,
            { ...baseConfig, horizon, ...parameters },
            { signal },
          )
        : api<QuantResearchResponse>(
            `/stocks/${encodeURIComponent(ticker)}/quantitative?horizon=${encodeURIComponent(horizon)}&benchmark=SPY`,
            { signal },
          ),
    enabled: ready,
    retry: retryTransient,
    staleTime: 300000,
  });
  const data = query.data?.ticker === ticker ? query.data : undefined;
  const matchingCore =
    core?.ticker && core.ticker !== ticker ? undefined : core;
  const content: QuantCore = data || matchingCore || {};
  const symbol = currencySymbol(currency);
  useEffect(() => {
    resultCallback.current?.(
      ready && !query.isFetching && data ? data : null,
      scopeKey,
    );
  }, [ready, query.isFetching, data, scopeKey]);
  const apply = (event: FormEvent) => {
    event.preventDefault();
    const benchmark = normalizeTicker(draftBenchmark);
    if (!benchmark) {
      setParameterError("Enter a valid Yahoo Finance benchmark ticker.");
      return;
    }
    const peerValues = Array.from(
      new Set(
        peers
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    );
    const normalizedPeers = peerValues.map(normalizeTicker);
    if (
      peerValues.length > 5 ||
      normalizedPeers.some((value) => value == null)
    ) {
      setParameterError(
        "Enter up to five comma-separated Yahoo Finance peer tickers.",
      );
      return;
    }
    const triple = (text: string) =>
      text.trim() ? text.split(",").map((value) => Number(value.trim())) : null;
    const earnings = triple(multiples),
      yields = triple(fcfYields);
    if (
      useValuation &&
      earnings &&
      (earnings.length !== 3 ||
        earnings.some(
          (value) => !Number.isFinite(value) || value <= 0 || value > 100,
        ) ||
        earnings.some(
          (value, index) => index > 0 && value < earnings[index - 1],
        ))
    ) {
      setParameterError(
        "Enter three positive earnings multiples up to 100 in conservative, base, optimistic order.",
      );
      return;
    }
    if (
      useValuation &&
      yields &&
      (yields.length !== 3 ||
        yields.some(
          (value) => !Number.isFinite(value) || value <= 0 || value > 100,
        ) ||
        yields.some((value, index) => index > 0 && value > yields[index - 1]))
    ) {
      setParameterError(
        "Enter three positive FCF yields (%) in descending conservative, base, optimistic order.",
      );
      return;
    }
    if (useValuation && enableDcf && discount - 1 <= terminal) {
      setParameterError(
        "The optimistic discount rate (base minus 1%) must exceed terminal growth.",
      );
      return;
    }
    setParameterError("");
    setParameters({
      benchmark_ticker: benchmark,
      min_samples: draftN,
      margin_of_safety: margin / 100,
      peer_tickers: normalizedPeers as string[],
      ...(useValuation
        ? {
            valuation_assumptions: {
              enable_dcf: enableDcf,
              growth: growth / 100,
              discount_rate: discount / 100,
              terminal_growth: terminal / 100,
              years,
              ...(earnings ? { earnings_multiples: earnings } : {}),
              ...(yields
                ? { fcf_yields: yields.map((value) => value / 100) }
                : {}),
            },
          }
        : {}),
      ...(commission !== "" ? { commission_bps: Number(commission) } : {}),
      ...(slippage !== "" ? { slippage_bps: Number(slippage) } : {}),
      ...(holding !== "" ? { max_holding_bars: Number(holding) } : {}),
    });
  };
  return (
    <div className="detail-stack quant-research">
      <section className="panel">
        <SectionHeading
          eyebrow="TRANSPARENT MODELS, EXPLICIT LIMITS"
          title="Quantitative research"
        >
          <Badge>
            Methodology{" "}
            {data?.methodology_version || content.methodology_version || "2.0"}
          </Badge>
        </SectionHeading>
        <p className="panel-footnote">
          Regime, strategy rules and historical validation answer different
          questions. Evidence confidence is kept separate from empirical outcome
          frequencies and model uncertainty.
        </p>
        {baseConfig && (
          <p className="panel-footnote">
            Applied position sizing: {amount(baseConfig.capital, symbol)}{" "}
            capital · {pct(baseConfig.risk_per_trade)} maximum risk per trade ·
            minimum reward/risk {ratio(baseConfig.min_reward_risk)}. Update
            these through Customize analysis.
          </p>
        )}
        <form onSubmit={apply}>
          <div className="form-grid quant-controls">
            <label>
              Benchmark ticker
              <input
                value={draftBenchmark}
                onChange={(event) => setDraftBenchmark(event.target.value)}
                maxLength={32}
                required
              />
            </label>
            <label>
              Minimum comparable observations
              <input
                type="number"
                min="30"
                max="1000"
                value={draftN}
                onChange={(event) => setDraftN(Number(event.target.value))}
                required
              />
            </label>
            <label>
              Commission (bps, optional)
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={commission}
                onChange={(event) => setCommission(event.target.value)}
                placeholder="Default rule"
              />
            </label>
            <label>
              Slippage (bps, optional)
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={slippage}
                onChange={(event) => setSlippage(event.target.value)}
                placeholder="Default rule"
              />
            </label>
            <label>
              Maximum holding bars (optional)
              <input
                type="number"
                min="1"
                max="252"
                value={holding}
                onChange={(event) => setHolding(event.target.value)}
                placeholder="Default rule"
              />
            </label>
          </div>
          {content.valuation?.applicable !== false && (
            <details className="limitations">
              <summary>
                Optional valuation scenarios and peer comparisons
              </summary>
              <p className="panel-footnote">
                These explicit assumptions apply only to this quantitative
                request. The separate Valuation tab keeps its own model inputs.
                A missing model or unsuitable company remains unavailable.
              </p>
              <div className="form-grid quant-controls">
                <label>
                  Peer tickers (up to 5)
                  <input
                    value={peers}
                    onChange={(event) => setPeers(event.target.value)}
                    placeholder="MSFT, ORCL, GOOGL"
                  />
                </label>
                <label>
                  Margin of safety (%)
                  <input
                    type="number"
                    min="0"
                    max="60"
                    value={margin}
                    onChange={(event) => setMargin(Number(event.target.value))}
                  />
                </label>
              </div>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={useValuation}
                  onChange={(event) => setUseValuation(event.target.checked)}
                />
                <span>Use explicit valuation assumptions</span>
              </label>
              {useValuation && (
                <>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enableDcf}
                      onChange={(event) => setEnableDcf(event.target.checked)}
                    />
                    <span>
                      Enable the corporate cash-flow DCF for this request
                    </span>
                  </label>
                  <div className="form-grid quant-controls">
                    <label>
                      Earnings multiples (conservative, base, optimistic)
                      <input
                        value={multiples}
                        onChange={(event) => setMultiples(event.target.value)}
                        placeholder="12, 18, 24"
                      />
                    </label>
                    <label>
                      FCF yields % (conservative, base, optimistic)
                      <input
                        value={fcfYields}
                        onChange={(event) => setFcfYields(event.target.value)}
                        placeholder="8, 6, 4"
                      />
                    </label>
                    {enableDcf && (
                      <>
                        <label>
                          DCF annual growth (%)
                          <input
                            type="number"
                            min="-30"
                            max="30"
                            step="0.1"
                            value={growth}
                            onChange={(event) =>
                              setGrowth(Number(event.target.value))
                            }
                          />
                        </label>
                        <label>
                          DCF discount rate (%)
                          <input
                            type="number"
                            min="1.01"
                            max="40"
                            step="0.01"
                            value={discount}
                            onChange={(event) =>
                              setDiscount(Number(event.target.value))
                            }
                          />
                        </label>
                        <label>
                          DCF terminal growth (%)
                          <input
                            type="number"
                            min="-5"
                            max="5"
                            step="0.1"
                            value={terminal}
                            onChange={(event) =>
                              setTerminal(Number(event.target.value))
                            }
                          />
                        </label>
                        <label>
                          DCF projection years
                          <input
                            type="number"
                            min="1"
                            max="20"
                            value={years}
                            onChange={(event) =>
                              setYears(Number(event.target.value))
                            }
                          />
                        </label>
                      </>
                    )}
                  </div>
                </>
              )}
            </details>
          )}
          {content.valuation?.applicable === false && (
            <p className="panel-footnote">
              Corporate DCF, earnings-multiple and cash-flow yield scenarios are
              not applicable to this fund. Price-based strategy validation
              remains available.
            </p>
          )}
          <div className="quant-actions">
            <button
              className="button primary"
              disabled={!ready || query.isFetching}
            >
              <SlidersHorizontal size={14} />
              Update quantitative research
            </button>
            <button
              className="text-button"
              type="button"
              onClick={() => query.refetch()}
              disabled={!ready || query.isFetching}
            >
              <RefreshCw size={12} />
              Refresh
            </button>
            <span>
              <Clock3 size={12} />
              As of{" "}
              {data?.as_of || content.as_of
                ? dateTime(data?.as_of || content.as_of)
                : "Not available"}
            </span>
          </div>
          {parameterError && (
            <p role="alert" className="red small-text">
              {parameterError}
            </p>
          )}
        </form>
        {!ready && (
          <p className="partial-summary">
            Waiting for the current stock’s core research before retrieving
            extended history.
          </p>
        )}
        {query.isFetching && (
          <div className="loading-strip staged">
            <LoaderCircle size={14} className="spin" />
            Retrieving completed timeframes and validating historical strategy
            rules. Missing or restricted data will remain unavailable.
          </div>
        )}
        {query.isError && (
          <ErrorBox error={query.error} onRetry={() => query.refetch()} />
        )}
      </section>
      <ScoreEvidence
        scores={content.scores}
        evidence={content.evidence}
        adapter={content.score_adapter}
      />
      <ValuationEvidence data={content.valuation} symbol={symbol} />
      <RegimeContext regime={content.regime} />
      <TimeframeEvidence
        data={data?.timeframes}
        loading={query.isFetching || !ready}
        symbol={symbol}
      />
      <StrategyTable strategies={content.strategies || []} symbol={symbol} />
      <Recommendation
        data={pendingQuantPlan(
          content.recommendation,
          Boolean(data) && !query.isFetching,
        )}
        strategies={content.strategies || []}
        symbol={symbol}
      />
      <ProbabilityEvidence
        probabilities={data?.probabilities}
        loading={query.isFetching || !ready}
      />
      <HistoricalValidation validation={data?.validation} symbol={symbol} />
    </div>
  );
}
