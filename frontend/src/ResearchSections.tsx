import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowDownRight,
  CalendarDays,
  ChevronDown,
  Globe2,
  Settings2,
  Target,
  ArrowUpRight,
  BookOpen,
  LoaderCircle,
} from "lucide-react";
import { post } from "./api";
import DataStatus from "./DataStatus";
import { useRequestScope, type RequestScope } from "./useRequestScope";
type SectionSource = {
  status?: DataSectionStatus;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
};
import type { Bag, CalendarEvent, DataSectionStatus } from "./types";
import {
  IconBox,
  Empty,
  ErrorBox,
  Badge,
  SectionHeading,
  LinkOut,
  Evidence,
  Limitations,
  MetricGrid,
  ScoreRing,
  DataTable,
  num,
  compact,
  pct,
  label,
  dateTime,
  strings,
  displayEventValue,
} from "./ui";
export function TradePanel({
  plan,
  symbol,
  onCustomize,
}: {
  plan: Bag;
  symbol: string;
  onCustomize: () => void;
}) {
  const valid = plan.entry_zone?.length === 2;
  return (
    <section className="panel trade-panel">
      <div className="trade-title">
        <IconBox>
          <Target size={18} />
        </IconBox>
        <h3>A conditional plan</h3>
        <button
          className="icon-button"
          aria-label="Customize investment plan"
          onClick={onCustomize}
        >
          <Settings2 size={15} />
        </button>
      </div>
      <div className="plan-recommendation">
        <Badge
          tone={
            /buy/i.test(plan.recommendation)
              ? "green"
              : /sell|avoid/i.test(plan.recommendation)
                ? "red"
                : "amber"
          }
        >
          {plan.recommendation || "Insufficient Data"}
        </Badge>
        <p>
          {plan.status ||
            "A sensible setup requires enough evidence and a favorable reward-to-risk ratio."}
        </p>
      </div>
      <div className="trade-level buy">
        <div>
          <span>
            <span className="level-dot" />
            Potential entry zone
          </span>
          <strong>
            {valid
              ? `${symbol}${num(plan.entry_zone[0])} – ${num(plan.entry_zone[1])}`
              : "No favorable setup"}
          </strong>
        </div>
        <ArrowDownRight size={19} />
      </div>
      <div className="target-rows">
        <div>
          <span>
            <i className="level-dot green-bg" />
            Profit target 01
          </span>
          <strong>
            {plan.targets?.[0] != null ? symbol + num(plan.targets[0]) : "—"}
          </strong>
        </div>
        <div>
          <span>
            <i className="level-dot green-bg" />
            Profit target 02
          </span>
          <strong>
            {plan.targets?.[1] != null ? symbol + num(plan.targets[1]) : "—"}
          </strong>
        </div>
        {plan.targets?.[2] != null && (
          <div>
            <span>
              <i className="level-dot green-bg" />
              Profit target 03
            </span>
            <strong>{symbol + num(plan.targets[2])}</strong>
          </div>
        )}
        <div>
          <span>
            <i className="level-dot red-bg" />
            Stop / invalidation
          </span>
          <strong className="red">
            {plan.stop != null ? symbol + num(plan.stop) : "—"}
          </strong>
        </div>
      </div>
      <div className="trade-summary">
        <div>
          <span>Reward / risk</span>
          <strong>
            {plan.risk_reward != null ? `${num(plan.risk_reward, 1)} : 1` : "—"}
          </strong>
        </div>
        <div>
          <span>Position size</span>
          <strong>
            {plan.position_size != null
              ? `${num(plan.position_size, 0)} shares`
              : "—"}
          </strong>
        </div>
      </div>
      <div className="trade-event">
        <CalendarDays size={15} />
        <p>
          {strings(plan.event_warnings)[0] ||
            "Calendar coverage may be incomplete. Check upcoming high-impact releases before acting."}
        </p>
      </div>
      <details className="plan-details">
        <summary>
          How these levels are calculated <ChevronDown size={13} />
        </summary>
        <Evidence items={plan.calculation} />
        {plan.breakout_entry != null && (
          <p>
            Breakout alternative: {symbol}
            {num(plan.breakout_entry)}
          </p>
        )}
        <p>
          Potential upside: {num(plan.upside_percent, 1)}% · downside:{" "}
          {num(plan.downside_percent, 1)}%
        </p>
        <p>Expected horizon: {plan.holding_horizon || "Not established"}</p>
        <Evidence
          items={
            Array.isArray(plan.invalidation)
              ? plan.invalidation
              : plan.invalidation?.condition
                ? [plan.invalidation.condition]
                : plan.invalidation
          }
        />
      </details>
    </section>
  );
}
export function EventPreview({
  events,
  onCalendar,
}: {
  events: CalendarEvent[];
  onCalendar: () => void;
}) {
  return (
    <>
      {events.length ? (
        <div className="event-preview">
          {events.slice(0, 3).map((event, i) => (
            <div key={event.id || i}>
              <span
                className={`impact-dots ${String(event.impact).toLowerCase()}`}
              >
                ▰▰▰
              </span>
              <div>
                <strong>{event.title}</strong>
                <p>
                  {event.currency || event.country} ·{" "}
                  {dateTime(event.scheduled_at)}
                </p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted small-text">
          No upcoming events in the imported calendar. This does not confirm an
          absence of event risk.
        </p>
      )}
      <button className="text-button" onClick={onCalendar}>
        Open economic calendar <ArrowUpRight size={13} />
      </button>
    </>
  );
}
export function Financials({
  data,
  status,
  loading,
  error,
  onRetry,
}: { data: Bag } & SectionSource) {
  const periods = data.periods || [];
  return (
    <div className="detail-stack">
      <section className="panel">
        <SectionHeading
          eyebrow="THE UNDERLYING BUSINESS"
          title="Financial health & growth"
        >
          <ScoreRing value={data.score} />
        </SectionHeading>
        <DataStatus
          label="Financial statements"
          status={status}
          loading={loading}
          error={error}
          onRetry={onRetry}
        />
        <Evidence items={data.signals} />
        <MetricGrid metrics={data.metrics || {}} />
        <Limitations items={data.limitations} />
      </section>
      <section className="panel">
        <SectionHeading title="Across reporting periods">
          <Badge>Annual statements</Badge>
        </SectionHeading>
        <p className="panel-footnote">
          Reporting period end dates. Publication dates may be unavailable;
          current statements are not used in historical backtests.
        </p>
        {periods.length ? (
          <DataTable rows={periods} />
        ) : (
          <Empty
            title={
              data.applicable === false
                ? "Financial statements not applicable"
                : loading
                  ? "Loading financial statements"
                  : "Financial statements unavailable"
            }
          >
            {data.applicable === false
              ? "Corporate financial statements are not applicable to this instrument."
              : loading
                ? "Available reporting periods will appear when this retrieval finishes."
                : "The provider did not return enough reporting periods."}
          </Empty>
        )}
      </section>
      {data.quarterly_periods?.length > 0 && (
        <section className="panel">
          <SectionHeading title="Quarterly performance" />
          <DataTable rows={data.quarterly_periods} />
        </section>
      )}
    </div>
  );
}
export function Valuation({
  data,
  symbol,
  ticker,
  status,
  loading,
  error,
  onRetry,
}: {
  data: Bag;
  symbol: string;
  ticker: string;
} & SectionSource) {
  const [growth, setGrowth] = useState(5),
    [discount, setDiscount] = useState(10),
    [terminal, setTerminal] = useState(2),
    [years, setYears] = useState(5),
    [fcf, setFcf] = useState(""),
    [shares, setShares] = useState("");
  const dcfScope = useRequestScope(ticker);
  const [dcfResult, setDcfResult] = useState<{
    scope: RequestScope;
    data: Bag;
  } | null>(null);
  const assumptions = {
    growth: growth / 100,
    discount_rate: discount / 100,
    terminal_growth: terminal / 100,
    years,
    ...(fcf ? { base_fcf: Number(fcf) } : {}),
    ...(shares ? { shares: Number(shares) } : {}),
  };
  const dcf = useMutation({
    mutationFn: (request: {
      ticker: string;
      scope: RequestScope;
      assumptions: Bag;
    }) =>
      post<Bag>(
        `/stocks/${encodeURIComponent(request.ticker)}/valuation`,
        request.assumptions,
      ),
    onSuccess: (result, request) => {
      if (dcfScope.isCurrent(request.scope))
        setDcfResult({ scope: request.scope, data: result });
    },
  });
  const dcfPending =
    dcf.isPending &&
    Boolean(dcf.variables && dcfScope.isCurrent(dcf.variables.scope));
  const dcfError =
    dcf.variables && dcfScope.isCurrent(dcf.variables.scope) ? dcf.error : null;
  const result =
    data.applicable === false
      ? data
      : dcfResult && dcfScope.isCurrent(dcfResult.scope)
        ? dcfResult.data
        : data;
  const scenarios = Array.isArray(result.scenarios)
    ? result.scenarios
    : Object.entries(result.scenarios || {}).map(([scenario, values]) => ({
        scenario,
        ...(typeof values === "object" ? (values as Bag) : { value: values }),
      }));
  return (
    <div className="detail-stack">
      <section className="panel">
        <SectionHeading
          eyebrow="A BUSINESS AND ITS PRICE"
          title="Valuation evidence"
        >
          <ScoreRing value={result.score} />
        </SectionHeading>
        <DataStatus
          label="Valuation inputs"
          status={status}
          loading={loading}
          error={error}
          onRetry={onRetry}
        />
        <Evidence items={result.signals} />
        <MetricGrid metrics={result.metrics || {}} />
        <Limitations items={result.limitations} />
      </section>
      {data.applicable !== false && (
        <section className="panel">
          <SectionHeading title="Discounted cash flow scenarios">
            <Badge>Assumption dependent</Badge>
          </SectionHeading>
          <p className="panel-footnote">
            Set explicit assumptions to calculate an equity cash-flow proxy.
            Outputs are sensitivity estimates, not precise intrinsic values or
            future price targets. Provider cash flow and share count are used
            unless you supply an override.
          </p>
          <form
            className="dcf-form"
            onSubmit={(e) => {
              e.preventDefault();
              dcf.mutate({ ticker, scope: dcfScope.capture(), assumptions });
            }}
          >
            <div className="form-grid">
              <label>
                Annual FCF growth (%)
                <input
                  type="number"
                  value={growth}
                  min="-30"
                  max="30"
                  step="0.5"
                  onChange={(e) => setGrowth(Number(e.target.value))}
                  required
                />
              </label>
              <label>
                Discount rate (%)
                <input
                  type="number"
                  value={discount}
                  min="1.01"
                  max="40"
                  step="0.01"
                  onChange={(e) => setDiscount(Number(e.target.value))}
                  required
                />
              </label>
              <label>
                Terminal growth (%)
                <input
                  type="number"
                  value={terminal}
                  min="-5"
                  max="5"
                  step="0.25"
                  onChange={(e) => setTerminal(Number(e.target.value))}
                  required
                />
              </label>
              <label>
                Projection years
                <input
                  type="number"
                  value={years}
                  min="1"
                  max="20"
                  onChange={(e) => setYears(Number(e.target.value))}
                  required
                />
              </label>
              <label>
                Base annual FCF (optional)
                <input
                  type="number"
                  value={fcf}
                  min="1"
                  placeholder="Provider value"
                  onChange={(e) => setFcf(e.target.value)}
                />
              </label>
              <label>
                Shares outstanding (optional)
                <input
                  type="number"
                  value={shares}
                  min="1"
                  placeholder="Provider value"
                  onChange={(e) => setShares(e.target.value)}
                />
              </label>
            </div>
            <div className="dcf-actions">
              <span>
                Base growth ±3%; discount rate +2% / −1% for conservative /
                optimistic scenarios.
              </span>
              <button
                className="button primary"
                disabled={dcfPending || discount - 1 <= terminal}
              >
                {dcfPending ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Target size={15} />
                )}
                Calculate scenarios
              </button>
            </div>
            {discount - 1 <= terminal && (
              <p className="amber small-text">
                Discount rate must exceed terminal growth in every scenario,
                including the optimistic discount rate minus 1%.
              </p>
            )}
          </form>
          {dcfError && <ErrorBox error={dcfError} />}
          <div className="scenario-grid">
            {scenarios.map((scenario: Bag, i: number) => (
              <div key={i} className="scenario-card">
                <p>{label(scenario.scenario || scenario.name || String(i))}</p>
                <strong>
                  {symbol}
                  {num(
                    scenario.value_per_share ??
                      scenario.per_share ??
                      scenario.fair_value ??
                      scenario.value,
                  )}
                </strong>
                <MetricGrid
                  metrics={{
                    growth: scenario.assumptions?.growth,
                    discount_rate: scenario.assumptions?.discount_rate,
                    terminal_growth: scenario.assumptions?.terminal_growth,
                    terminal_value_share: scenario.terminal_value_share,
                  }}
                />
                <details className="limitations">
                  <summary>
                    Projected cash flows <ChevronDown size={12} />
                  </summary>
                  <Evidence
                    items={(scenario.projected_cash_flows || []).map(
                      (v: number, index: number) =>
                        `Year ${index + 1}: ${symbol}${compact(v)}`,
                    )}
                  />
                </details>
              </div>
            ))}
          </div>
          {result.assumptions && (
            <details className="limitations">
              <summary>
                Model assumptions <ChevronDown size={13} />
              </summary>
              <MetricGrid metrics={result.assumptions} />
            </details>
          )}
          <p className="panel-footnote">
            Scenario calculations do not change the saved dashboard rating. The
            dashboard continues to use its disclosed market-yield evidence until
            a new research snapshot is generated.
          </p>
        </section>
      )}
    </div>
  );
}

export function News({
  data,
  overview,
  status,
  earningsStatus,
  analystStatus,
  loading,
  error,
  onRetry,
}: {
  data: Bag;
  overview: Bag;
  earningsStatus?: DataSectionStatus;
  analystStatus?: DataSectionStatus;
} & SectionSource) {
  return (
    <div className="detail-stack">
      <section className="panel">
        <SectionHeading
          eyebrow="WHAT CHANGED, AND WHY IT MATTERS"
          title="News & earnings assessment"
        >
          <ScoreRing value={data.score} />
        </SectionHeading>
        <DataStatus
          label="Company news"
          status={status}
          loading={loading}
          error={error}
          onRetry={onRetry}
        />
        <Evidence items={data.signals} />
        <div className="news-perspectives">
          <div>
            <h3 className="green">Bullish developments</h3>
            <Evidence
              items={data.bullish}
              empty="No supported bullish development identified."
            />
          </div>
          <div>
            <h3 className="red">Bearish developments</h3>
            <Evidence
              items={data.bearish}
              empty="No supported bearish development identified."
            />
          </div>
        </div>
        <Limitations items={data.limitations} />
      </section>
      <section className="panel">
        <SectionHeading title="Company events & earnings">
          <Badge>Yahoo Finance</Badge>
        </SectionHeading>
        <div className="section-statuses">
          <DataStatus
            label="Earnings"
            status={earningsStatus}
            loading={loading}
            error={error}
            onRetry={onRetry}
          />
          <DataStatus
            label="Analyst estimates"
            status={analystStatus}
            loading={loading}
            error={error}
            onRetry={onRetry}
          />
        </div>
        <p className="panel-footnote">
          Provider-reported earnings dates and estimates may change. An estimate
          is not a management commitment.
        </p>
        <MetricGrid metrics={overview.company_calendar || {}} />
        {overview.earnings_history?.length > 0 && (
          <>
            <h3 className="subsection-title">
              Reported earnings versus estimates
            </h3>
            <DataTable rows={overview.earnings_history} />
          </>
        )}
        {overview.earnings_estimates?.length > 0 && (
          <>
            <h3 className="subsection-title">
              Available analyst earnings estimates
            </h3>
            <DataTable rows={overview.earnings_estimates} />
          </>
        )}
        {overview.analyst_targets &&
          Object.keys(overview.analyst_targets).length > 0 && (
            <>
              <h3 className="subsection-title">Analyst price targets</h3>
              <p className="panel-footnote">
                Source estimates are opinions, not the platform’s trade targets
                or guaranteed outcomes.
              </p>
              <MetricGrid metrics={overview.analyst_targets} />
            </>
          )}
      </section>
      <section className="panel">
        <SectionHeading title="Source-linked company coverage">
          <Badge>Yahoo Finance</Badge>
        </SectionHeading>
        {data.articles?.length ? (
          <div className="news-list">
            {data.articles.map((article: Bag, i: number) => (
              <article key={article.id || i} className="news-card">
                <div className="news-icon">
                  <BookOpen size={19} />
                </div>
                <div>
                  <div className="news-meta">
                    <span>{article.publisher || "Publisher unavailable"}</span>
                    <span>·</span>
                    <span>{dateTime(article.published_at)}</span>
                    <Badge
                      tone={
                        article.sentiment === "positive"
                          ? "green"
                          : article.sentiment === "negative"
                            ? "red"
                            : "neutral"
                      }
                    >
                      {article.sentiment || "uncertain"}
                    </Badge>
                  </div>
                  <h3>
                    <LinkOut href={article.url}>{article.title}</LinkOut>
                  </h3>
                  {article.summary && <p>{article.summary}</p>}
                  <span className="scope-note">
                    Analysis scope: {article.content_scope || "headline only"} ·
                    Relevance:{" "}
                    {typeof article.relevance === "number"
                      ? pct(article.relevance)
                      : article.relevance || "company-linked source"}
                  </span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty title="No company news returned" icon={<BookOpen size={28} />}>
            The source may not provide coverage for this company. No sentiment
            is inferred from missing news.
          </Empty>
        )}
      </section>
    </div>
  );
}
export function Macro({
  data,
  onCalendar,
}: {
  data: Bag;
  onCalendar: () => void;
}) {
  return (
    <div className="detail-stack">
      <section className="panel">
        <SectionHeading
          eyebrow="CONTEXT, NOT CAUSATION"
          title="How upcoming economic events may affect this stock"
        >
          <ScoreRing value={data.score} />
        </SectionHeading>
        <div className="macro-status">
          <Badge
            tone={
              data.outlook === "Bullish"
                ? "green"
                : data.outlook === "Bearish"
                  ? "red"
                  : "amber"
            }
          >
            {data.outlook || "Insufficient Data"}
          </Badge>
          <span>
            {num((data.confidence || 0) * 100, 0)}% evidence confidence
          </span>
        </div>
        <Evidence items={data.signals} />
        <div className="stock-impacts">
          {(data.stock_impacts || []).map((item: any, i: number) => (
            <div key={i}>
              <Globe2 size={17} />
              <div>
                {typeof item === "string" ? (
                  item
                ) : (
                  <>
                    <strong>
                      {item.title ||
                        item.factor ||
                        item.channel ||
                        "Possible transmission channel"}
                    </strong>
                    <p>
                      {item.explanation ||
                        item.impact ||
                        item.hypothesis ||
                        item.description ||
                        JSON.stringify(item)}
                    </p>
                  </>
                )}
                <span className="scope-note">
                  Scenario / exposure hypothesis. A market reaction is not
                  guaranteed.
                </span>
              </div>
            </div>
          ))}
        </div>
        <Limitations items={data.limitations} />
      </section>
      <div className="bottom-grid">
        <section className="panel">
          <SectionHeading title="Upcoming economic catalysts" />
          <EventPreview
            events={data.upcoming_events || []}
            onCalendar={onCalendar}
          />
        </section>
        <section className="panel">
          <SectionHeading title="Recent releases" />
          {data.recent_events?.length ? (
            <DataTable
              rows={data.recent_events.map((e: Bag) => ({
                event: e.title,
                date: dateTime(e.scheduled_at),
                actual: e.actual,
                forecast: e.forecast,
                surprise: displayEventValue(e.surprise ?? e.economic_surprise),
                interpretation:
                  e.surprise?.interpretation || e.interpretation || "Uncertain",
              }))}
            />
          ) : (
            <p className="muted">
              No valid actual-versus-forecast releases in this calendar
              snapshot.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
