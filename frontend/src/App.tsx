import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Download,
  FileText,
  FlaskConical,
  Globe2,
  Layers3,
  LineChart,
  LoaderCircle,
  Menu,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  Target,
  Trash2,
  TrendingUp,
  X,
} from "lucide-react";
import Chart from "./Chart";
import StockSearch from "./StockSearch";
import DataStatus from "./DataStatus";
import QuantResearch, { pendingQuantPlan } from "./QuantResearch";
import { useTickerLocation } from "./tickerState";
import { useRequestScope, type RequestScope } from "./useRequestScope";
import { api, post } from "./api";
import {
  CATEGORY_LABELS,
  DEFAULT_WEIGHTS,
  type Bag,
  type Research,
  type HistoryResponse,
  type CategoryResult,
  type DataSectionStatus,
  type QuantResearchResponse,
} from "./types";

import CalendarPage from "./CalendarPage";
import ReportsPage from "./ReportsPage";
import BacktestPage from "./BacktestPage";
import TechScreener from "./TechScreener";
import {
  TradePanel,
  EventPreview,
  Financials,
  Valuation,
  News,
  Macro,
} from "./ResearchSections";
import {
  Empty,
  ErrorBox,
  Badge,
  SectionHeading,
  Limitations,
  Evidence,
  Markdown,
  ScoreRing,
  PageIntro,
  num,
  compact,
  label,
  dateTime,
  dateOnly,
  currencySymbol,
  scoreColor,
  download,
} from "./ui";
type Page =
  | "research"
  | "screener"
  | "calendar"
  | "watchlist"
  | "reports"
  | "backtest";
export default function App() {
  const [ticker, setTicker] = useTickerLocation();
  const [page, setPage] = useState<Page>("research"),
    [period, setPeriod] = useState("1y"),
    [tab, setTab] = useState("overview"),
    [horizon, setHorizon] = useState("swing"),
    [settings, setSettings] = useState(false),
    [mobile, setMobile] = useState(false),
    [toast, setToast] = useState("");
  const [indicators, setIndicators] = useState(["sma20", "sma50", "levels"]);
  const [risk, setRisk] = useState("medium"),
    [capital, setCapital] = useState(10000),
    [riskPercent, setRiskPercent] = useState(1),
    [minRR, setMinRR] = useState(2),
    [existingShares, setExistingShares] = useState(0),
    [costBasis, setCostBasis] = useState(""),
    [weights, setWeights] = useState({ ...DEFAULT_WEIGHTS });
  const analysisInputs = {
    horizon,
    risk_tolerance: risk,
    capital,
    risk_per_trade: riskPercent / 100,
    min_reward_risk: minRR,
    existing_shares: existingShares,
    cost_basis: costBasis ? Number(costBasis) : null,
    weights,
  };
  const requestScope = useRequestScope(`${ticker}:${period}:${horizon}`);
  const client = useQueryClient();
  const research = useQuery({
    queryKey: ["research", ticker, period, horizon],
    queryFn: ({ signal }) =>
      api<Research>(
        `/stocks/${encodeURIComponent(ticker)}/research?period=${period}&horizon=${horizon}`,
        { signal },
      ),
    enabled: page === "research",
  });
  const overviewQuery = useQuery({
    queryKey: ["overview", ticker],
    queryFn: ({ signal }) =>
      api<Bag>(`/stocks/${encodeURIComponent(ticker)}/overview`, { signal }),
    enabled: page === "research",
  });
  const historyQuery = useQuery({
    queryKey: ["history", ticker, period],
    queryFn: ({ signal }) =>
      api<HistoryResponse>(
        `/stocks/${encodeURIComponent(ticker)}/history?period=${period}`,
        { signal },
      ),
    enabled: page === "research",
  });
  const technicalQuery = useQuery({
    queryKey: ["technical", ticker, period, horizon],
    queryFn: ({ signal }) =>
      api<CategoryResult>(
        `/stocks/${encodeURIComponent(ticker)}/technical?period=${period}&horizon=${horizon}`,
        { signal },
      ),
    enabled: page === "research",
  });
  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: ({ signal }) => api<{ items: Bag[] }>("/watchlist", { signal }),
  });
  const [customState, setCustom] = useState<{
    scope: RequestScope;
    data: Bag;
    inputs: Bag;
  } | null>(null);
  const custom =
    customState && requestScope.isCurrent(customState.scope)
      ? customState.data
      : null;
  const appliedInputs =
    customState && requestScope.isCurrent(customState.scope)
      ? customState.inputs
      : null;
  const quantConfig = appliedInputs || {
    horizon,
    risk_tolerance: "medium",
    capital: 10000,
    risk_per_trade: 0.01,
    min_reward_risk: 2,
    existing_shares: 0,
    cost_basis: null,
    weights: DEFAULT_WEIGHTS,
  };
  const quantRequestScope = requestScope.capture();
  const quantScopeKey = JSON.stringify([quantRequestScope, quantConfig]);
  const [advancedState, setAdvanced] = useState<{
    scopeKey: string;
    data: QuantResearchResponse;
  } | null>(null);
  const advanced =
    advancedState?.scopeKey === quantScopeKey &&
    advancedState.data.ticker === ticker
      ? advancedState.data
      : null;
  useEffect(() => {
    setCustom(null);
  }, [ticker, period, horizon]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [page]);
  useEffect(() => {
    if (toast) {
      const timer = window.setTimeout(() => setToast(""), 5000);
      return () => window.clearTimeout(timer);
    }
  }, [toast]);
  useEffect(() => {
    if (!settings) return;
    const previous = document.activeElement as HTMLElement | null;
    const modal = document.querySelector<HTMLElement>(".settings-modal");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    modal?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSettings(false);
      if (event.key !== "Tab" || !modal) return;
      const controls = Array.from(
        modal.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
        ),
      ).filter((el) => el.offsetParent !== null);
      const first = controls[0],
        last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, [settings]);
  const addWatch = useMutation({
    mutationFn: (symbol: string) => post("/watchlist", { ticker: symbol }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["watchlist"] });
      setToast("Added to your watchlist.");
    },
    onError: (e) => setToast(e.message),
  });
  const removeWatch = useMutation({
    mutationFn: (symbol: string) =>
      api(`/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["watchlist"] });
      setToast("Removed from watchlist.");
    },
    onError: (e) => setToast(e.message),
  });
  type ResearchMutation = {
    ticker: string;
    scope: RequestScope;
    inputs: Bag;
    quantitative?: boolean;
  };
  const trade = useMutation({
    mutationFn: ({ ticker: requestedTicker, inputs }: ResearchMutation) =>
      post<Bag>(
        `/stocks/${encodeURIComponent(requestedTicker)}/trade-plan`,
        inputs,
      ),
    onSuccess: (data, request) => {
      if (!requestScope.isCurrent(request.scope)) return;
      setAdvanced(null);
      client.invalidateQueries({ queryKey: ["quantitative", request.ticker] });
      setCustom({ scope: request.scope, data, inputs: request.inputs });
      setSettings(false);
      setToast("Analysis updated with your assumptions.");
    },
    onError: (error, request) => {
      if (requestScope.isCurrent(request.scope)) setToast(error.message);
    },
  });
  const saveReport = useMutation({
    mutationFn: ({
      ticker: requestedTicker,
      inputs,
      quantitative,
    }: ResearchMutation) =>
      post<Bag>(
        `/stocks/${encodeURIComponent(requestedTicker)}/${quantitative ? "quantitative/report" : "reports"}`,
        inputs,
      ),
    onSuccess: (_data, request) => {
      client.invalidateQueries({ queryKey: ["reports"] });
      if (requestScope.isCurrent(request.scope))
        setToast("Research report saved.");
    },
    onError: (error, request) => {
      if (requestScope.isCurrent(request.scope)) setToast(error.message);
    },
  });
  const openStock = (symbol: string) => {
    setTicker(symbol.trim().toUpperCase());
    setPage("research");
    setMobile(false);
  };
  const current = research.data?.ticker === ticker ? research.data : undefined;
  const historyData = current?.history || historyQuery.data;
  const technical = current?.technical || technicalQuery.data;
  const sections: Record<string, DataSectionStatus> = {
    ...overviewQuery.data?.source_metadata,
    ...current?.data_quality?.sections,
  };
  const historyStatus =
    sections.history ||
    (historyQuery.data
      ? ({
          status:
            historyQuery.data.from_cache || historyQuery.data.cache_stale
              ? "cached"
              : "available",
          fetched_at: historyQuery.data.fetched_at,
          cache_stale: historyQuery.data.cache_stale,
        } as DataSectionStatus)
      : undefined);
  const refreshResearch = () => {
    setAdvanced(null);
    client.invalidateQueries({ queryKey: ["quantitative", ticker] });
    research.refetch();
    overviewQuery.refetch();
    historyQuery.refetch();
    technicalQuery.refetch();
  };
  const quantCore = custom?.quant_core || current?.quant_core;
  const quantScores = advanced?.scores || quantCore?.scores;
  const quantRegime = advanced?.regime || quantCore?.regime;
  const technicalAssessment =
    advanced?.technical_assessment ||
    quantCore?.technical_assessment ||
    technical;
  const overview = current?.overview || overviewQuery.data || {},
    scores =
      advanced?.score_adapter ||
      quantCore?.score_adapter ||
      custom?.score ||
      current?.score ||
      {},
    legacyPlan =
      custom?.trade_plan ||
      custom?.plan ||
      (custom?.recommendation ? custom : current?.trade_plan) ||
      {},
    plan =
      advanced?.recommendation ||
      (quantCore?.recommendation
        ? pendingQuantPlan(quantCore.recommendation)
        : legacyPlan),
    report = advanced?.report || custom?.report || current?.report,
    priceSymbol = currencySymbol(overview.currency),
    isWatched = (watchlist.data?.items || []).some((x) => x.ticker === ticker);
  const nav = [
    { id: "research", label: "Stock research", icon: LineChart },
    { id: "screener", label: "Tech Stock Screener", icon: Layers3 },
    { id: "calendar", label: "Economic calendar", icon: CalendarDays },
    { id: "watchlist", label: "My watchlist", icon: Star },
    { id: "reports", label: "Saved reports", icon: FileText },
    { id: "backtest", label: "Strategy lab", icon: FlaskConical },
  ] as const;
  const pageNames = {
    research: "Stock research",
    screener: "Tech Stock Screener",
    calendar: "Economic calendar",
    watchlist: "My watchlist",
    reports: "Saved research",
    backtest: "Strategy lab",
  };
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobile ? "open" : ""}`}>
        <button
          className="brand"
          onClick={() => {
            setPage("research");
            setMobile(false);
          }}
          aria-label="EquityLens home"
        >
          <span className="brand-mark">
            <span />
            <span />
            <span />
            <i />
          </span>
          <span>
            Equity<span className="brand-light">Lens</span>
          </span>
          <small>RESEARCH</small>
        </button>
        <div className="workspace">
          <span className="workspace-avatar">P</span>
          <div>
            <strong>Personal workspace</strong>
            <span>Research with perspective</span>
          </div>
          <ChevronDown size={14} />
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav>
          {nav.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${page === n.id ? "active" : ""}`}
              onClick={() => {
                setPage(n.id);
                setMobile(false);
              }}
            >
              <n.icon size={18} />
              <span>{n.label}</span>
              {n.id === "watchlist" && !!watchlist.data?.items.length && (
                <small>{watchlist.data.items.length}</small>
              )}
              {page === n.id && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-watchlist">
          <div className="nav-label">
            ON YOUR RADAR <Star size={12} />
          </div>
          {(watchlist.data?.items || []).slice(0, 6).map((item) => (
            <button
              className="radar-item"
              key={item.ticker}
              onClick={() => openStock(item.ticker)}
            >
              <span className="radar-symbol">{item.ticker.slice(0, 1)}</span>
              <span>{item.ticker}</span>
              <ArrowUpRight size={13} />
            </button>
          ))}
          {!watchlist.data?.items.length && (
            <p className="radar-empty">
              Save a stock to keep your next research session close.
            </p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="research-note">
            <ShieldCheck size={21} />
            <strong>Evidence over prediction.</strong>
            <p>Transparent research. Clear assumptions. Your decisions.</p>
          </div>
          <div className="profile">
            <span className="profile-avatar">Y</span>
            <div>
              <strong>Your research desk</strong>
              <span>Personal · Local workspace</span>
            </div>
            <span className="status-dot" />
          </div>
        </div>
      </aside>
      {mobile && (
        <button
          className="sidebar-scrim"
          onClick={() => setMobile(false)}
          aria-label="Close menu"
        />
      )}
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              onClick={() => setMobile(!mobile)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{pageNames[page]}</strong>
            {page === "research" && (
              <>
                <ChevronRight size={13} />
                <span className="breadcrumb-ticker">{ticker}</span>
              </>
            )}
          </div>
          <div className="topbar-right">
            <span className="local-status">
              <span className="status-dot" />
              Personal research platform
            </span>
            <a
              href="https://finance.yahoo.com/"
              target="_blank"
              rel="noopener noreferrer"
              className="icon-button"
              aria-label="Open Yahoo Finance"
            >
              <Globe2 size={18} />
            </a>
          </div>
        </header>
        <div className="page-content">
          {page === "research" && (
            <>
              <div className="page-title-row">
                <div>
                  <p className="eyebrow">
                    <span className="tiny-line" /> YOUR EDGE STARTS WITH
                    UNDERSTANDING
                  </p>
                  <h1>
                    See the whole picture<span className="green">.</span>
                  </h1>
                  <p className="subtitle">
                    Company quality. Market context. A clearer investment
                    decision.
                  </p>
                </div>
                <button
                  className="button secondary"
                  onClick={() => setSettings(true)}
                >
                  <SlidersHorizontal size={15} />
                  Customize analysis
                </button>
              </div>
              <div className="search-strip">
                <StockSearch key={ticker} onSelect={openStock} />
                <div className="quick-search">
                  <span>Explore</span>
                  {["AAPL", "MSFT", "NVDA"].map((x) => (
                    <button
                      key={x}
                      className={ticker === x ? "selected" : ""}
                      onClick={() => openStock(x)}
                    >
                      {x}
                    </button>
                  ))}
                </div>
              </div>
              {current?.data_quality?.mode &&
                /synthetic|demo|sample/i.test(current.data_quality.mode) && (
                  <div className="notice warning">
                    <FlaskConical size={18} />
                    <div>
                      <strong>Sample data preview</strong>
                      <p>
                        This workspace is displaying labeled test fixtures.
                        These values are not current market observations and
                        cannot support an investment decision.
                      </p>
                    </div>
                  </div>
                )}
              {research.isError && (
                <ErrorBox error={research.error} onRetry={refreshResearch} />
              )}
              <section className="company-header">
                <div className="company-identity">
                  <div
                    className={`company-logo ${ticker === "NVDA" ? "nvidia" : ""}`}
                  >
                    {ticker === "NVDA" ? (
                      <span className="nvidia-eye">◉</span>
                    ) : (
                      ticker.slice(0, 1)
                    )}
                  </div>
                  <div>
                    <div className="company-title">
                      <h2>{overview.name || ticker}</h2>
                      <Badge>{ticker}</Badge>
                      <span className="company-market">
                        {[overview.exchange, overview.asset_type]
                          .filter(Boolean)
                          .join(" · ") ||
                          overview.currency ||
                          "Instrument details pending"}
                      </span>
                    </div>
                    <p>
                      {[overview.sector, overview.industry]
                        .filter(Boolean)
                        .join(" · ") || "Source-backed company research"}
                      {overview.market_cap != null && (
                        <>
                          {" "}
                          <span className="subtle-divider">|</span>{" "}
                          {priceSymbol}
                          {compact(overview.market_cap)} market cap
                        </>
                      )}
                    </p>
                  </div>
                </div>
                <div className="company-quote">
                  <div>
                    <strong>
                      {priceSymbol}
                      {num(overview.price)}
                    </strong>
                    {overview.change_percent != null && (
                      <span
                        className={`price-change ${overview.change_percent >= 0 ? "green" : "red"}`}
                      >
                        {overview.change_percent >= 0 ? (
                          <ArrowUpRight size={16} />
                        ) : (
                          <ArrowDownRight size={16} />
                        )}{" "}
                        {overview.change_percent > 0 ? "+" : ""}
                        {num(overview.change_percent)}%
                      </span>
                    )}
                  </div>
                  <p>
                    <Clock3 size={12} />
                    {overview.quote_at
                      ? dateTime(overview.quote_at)
                      : research.isFetching
                        ? "Retrieving source data…"
                        : "Quote unavailable"}
                  </p>
                </div>
                <button
                  className={`icon-button watch-toggle ${isWatched ? "green" : ""}`}
                  title={
                    isWatched ? "Remove from watchlist" : "Add to watchlist"
                  }
                  aria-label={
                    isWatched ? "Remove from watchlist" : "Add to watchlist"
                  }
                  disabled={addWatch.isPending || removeWatch.isPending}
                  onClick={() =>
                    isWatched
                      ? removeWatch.mutate(ticker)
                      : addWatch.mutate(ticker)
                  }
                >
                  <Star size={19} fill={isWatched ? "currentColor" : "none"} />
                </button>
              </section>
              <div className="quote-footnote">
                <span className="status-dot" />
                {overview.stale
                  ? "Stale source snapshot"
                  : overview.quote_type || "Delayed / end-of-day data"}
                <span>·</span>
                {overview.source || "Yahoo Finance via yfinance"}
                <span>·</span>
                {overview.currency || "Currency unavailable"} ·{" "}
                {overview.exchange_timezone || "Exchange timezone unavailable"}
                <span className="quote-refresh">
                  <button
                    onClick={refreshResearch}
                    disabled={research.isFetching}
                    className="text-button"
                  >
                    <RefreshCw
                      size={12}
                      className={research.isFetching ? "spin" : ""}
                    />
                    {research.isFetching ? "Refreshing" : "Refresh analysis"}
                  </button>
                </span>
              </div>
              <div className="source-refresh-status">
                <DataStatus
                  label="Company information"
                  status={sections.company_info}
                  loading={research.isPending}
                  error={
                    !current && research.isError ? research.error : undefined
                  }
                  onRetry={refreshResearch}
                />
              </div>
              <div className="score-cards">
                <div className="score-card featured">
                  <div>
                    <p>
                      Investment attractiveness{" "}
                      <CircleHelp size={12}>
                        <title>
                          Weighted business, valuation, technical, setup and
                          macro evidence with a bounded news adjustment. Missing
                          evidence reduces confidence.
                        </title>
                      </CircleHelp>
                    </p>
                    <div className="score-description">
                      <h3>
                        {scores.overall == null
                          ? "Awaiting evidence"
                          : scores.overall >= 7
                            ? "Worth a closer look"
                            : scores.overall >= 5
                              ? "A balanced picture"
                              : "Proceed with caution"}
                      </h3>
                      <span>
                        {scores.overall == null
                          ? "Insufficient data for a rating"
                          : `${num((scores.confidence || 0) * 100, 0)}% evidence confidence`}
                      </span>
                    </div>
                  </div>
                  <ScoreRing value={scores.overall} />
                </div>
                <div className="score-card">
                  <div>
                    <p>
                      Company quality <ShieldCheck size={14} />
                    </p>
                    <strong className="simple-score">
                      {num(scores.company_quality, 1)}
                      <small>/10</small>
                    </strong>
                    <span className="score-card-note">
                      The underlying business
                    </span>
                  </div>
                  <ShieldCheck className="score-decoration" size={35} />
                </div>
                <div className="score-card">
                  <div>
                    <p>
                      Technical outlook <Activity size={14} />
                    </p>
                    <strong
                      className={`simple-score ${scoreColor(quantScores ? quantScores.technical_strength : technical?.score)}`}
                    >
                      {num(
                        quantScores
                          ? quantScores.technical_strength
                          : technical?.score,
                        1,
                      )}
                      <small>/10</small>
                    </strong>
                    <span className="score-card-note">
                      {quantRegime?.regime ||
                        (technical?.regime
                          ? label(technical.regime)
                          : "Trend & momentum")}
                    </span>
                  </div>
                  <Activity className="score-decoration" size={36} />
                </div>
                <div className="score-card">
                  <div>
                    <p>
                      Macro environment <Globe2 size={14} />
                    </p>
                    <strong
                      className={`simple-score ${scoreColor(quantScores ? quantScores.macroeconomic_environment : current?.macro?.score)}`}
                    >
                      {num(
                        quantScores
                          ? quantScores.macroeconomic_environment
                          : current?.macro?.score,
                        1,
                      )}
                      <small>/10</small>
                    </strong>
                    <span className="score-card-note">
                      {current?.macro?.outlook || "Calendar evidence needed"}
                    </span>
                  </div>
                  <div className="macro-orbit">
                    <Globe2 size={38} />
                  </div>
                </div>
              </div>
              <div
                className="research-tabs"
                role="tablist"
                aria-label="Research sections"
              >
                {[
                  ["overview", "Overview"],
                  ["quantitative", "Quantitative research"],
                  ["financials", "Financials"],
                  ["valuation", "Valuation"],
                  ["news", "News & earnings"],
                  ["macro", "Macro & events"],
                  ["report", "Research report"],
                ].map(([id, name]) => (
                  <button
                    role="tab"
                    aria-selected={tab === id}
                    key={id}
                    className={tab === id ? "active" : ""}
                    onClick={() => setTab(id)}
                  >
                    {name}
                    {id === "report" && <Sparkles size={12} />}
                  </button>
                ))}
              </div>
              {research.isLoading && (
                <div className="loading-strip">
                  <LoaderCircle size={15} className="spin" />
                  {historyData?.prices?.length
                    ? "Price history is available. Optional company research is still loading."
                    : "Building the evidence trail from Yahoo Finance. Available price history and technical analysis will appear first."}
                </div>
              )}
              {tab === "overview" && (
                <>
                  <div className="analysis-grid">
                    <section className="panel chart-panel">
                      <div className="chart-heading">
                        <div>
                          <h3>Price & market structure</h3>
                          <p>
                            {ticker} · Daily candles{" "}
                            <span className="green-dot" />{" "}
                            {overview.currency || "—"}
                          </p>
                        </div>
                        <div className="period-switch">
                          {[
                            ["3mo", "3M"],
                            ["6mo", "6M"],
                            ["1y", "1Y"],
                            ["5y", "5Y"],
                            ["max", "ALL"],
                          ].map(([v, l]) => (
                            <button
                              key={v}
                              className={period === v ? "active" : ""}
                              onClick={() => setPeriod(v)}
                            >
                              {l}
                            </button>
                          ))}
                        </div>
                      </div>
                      <DataStatus
                        label="Price history"
                        status={historyStatus}
                        loading={historyQuery.isPending && !historyData}
                        error={historyQuery.error}
                        onRetry={() => historyQuery.refetch()}
                      />
                      <DataStatus
                        label="Technical analysis"
                        status={technical ? historyStatus : undefined}
                        loading={technicalQuery.isPending && !technical}
                        error={technicalQuery.error}
                        onRetry={() => technicalQuery.refetch()}
                      />
                      <div className="indicator-bar">
                        {[
                          ["sma20", "SMA 20"],
                          ["sma50", "SMA 50"],
                          ["sma200", "SMA 200"],
                          ["ema21", "EMA 21"],
                          ["bb_upper", "Bollinger"],
                          ["levels", "Key levels"],
                        ].map(([key, name], i) => (
                          <button
                            key={key}
                            className={indicators.includes(key) ? "active" : ""}
                            onClick={() =>
                              setIndicators((prev) =>
                                prev.includes(key)
                                  ? prev.filter(
                                      (k) =>
                                        k !== key &&
                                        !(
                                          key === "bb_upper" && k === "bb_lower"
                                        ),
                                    )
                                  : [
                                      ...prev,
                                      key,
                                      ...(key === "bb_upper"
                                        ? ["bb_lower"]
                                        : []),
                                    ],
                              )
                            }
                          >
                            <span
                              style={{
                                background: indicators.includes(key)
                                  ? [
                                      "#c8ee9b",
                                      "#7c9fea",
                                      "#f2bd71",
                                      "#bc9de8",
                                      "#68c5bb",
                                      "#9faeb6",
                                    ][i]
                                  : undefined,
                              }}
                            />
                            {name}
                          </button>
                        ))}
                      </div>
                      {historyData?.prices?.length ? (
                        <Chart
                          prices={historyData.prices}
                          technical={technical}
                          plan={plan}
                          indicators={indicators}
                        />
                      ) : (
                        <div className="empty-chart">
                          <LineChart size={32} />
                          <strong>
                            {research.isFetching
                              ? "Retrieving price history"
                              : "Price history unavailable"}
                          </strong>
                          <p>
                            Charts appear when verified source data is
                            available.
                          </p>
                          <div className="chart-grid-placeholder" />
                        </div>
                      )}
                      <div className="chart-footer">
                        <span>
                          <Activity size={12} />{" "}
                          {technical?.trend
                            ? label(String(technical.trend))
                            : "Daily OHLCV"}{" "}
                        </span>
                        <span>Scroll to inspect · Drag to pan</span>
                      </div>
                    </section>
                    <TradePanel
                      plan={plan}
                      symbol={priceSymbol}
                      onCustomize={() => setSettings(true)}
                    />
                  </div>
                  <div className="bottom-grid">
                    <section className="panel">
                      <SectionHeading
                        eyebrow="THE EVIDENCE, WEIGHTED"
                        title="What’s driving the rating"
                      >
                        <button
                          className="icon-button"
                          onClick={() => setSettings(true)}
                          aria-label="Edit score weights"
                        >
                          <Settings2 size={16} />
                        </button>
                      </SectionHeading>
                      <div className="category-list">
                        {(
                          scores.categories ||
                          Object.entries(DEFAULT_WEIGHTS).map(
                            ([key, weight]) => ({
                              key,
                              label: CATEGORY_LABELS[key],
                              weight,
                              score: null,
                            }),
                          )
                        ).map((category: Bag) => (
                          <div className="category-row" key={category.key}>
                            <span
                              className={`category-icon ${scoreColor(category.score)}`}
                            >
                              {["technical", "technical_strength"].includes(
                                category.key,
                              ) ? (
                                <TrendingUp size={15} />
                              ) : [
                                  "macro",
                                  "macroeconomic_environment",
                                ].includes(category.key) ? (
                                <Globe2 size={15} />
                              ) : ["risk", "trade_setup_quality"].includes(
                                  category.key,
                                ) ? (
                                <ShieldCheck size={15} />
                              ) : category.key === "news" ? (
                                <BookOpen size={15} />
                              ) : [
                                  "valuation",
                                  "valuation_attractiveness",
                                ].includes(category.key) ? (
                                <Target size={15} />
                              ) : (
                                <Layers3 size={15} />
                              )}
                            </span>
                            <div className="category-name">
                              <strong>
                                {category.label ||
                                  CATEGORY_LABELS[category.key]}
                              </strong>
                              <span>
                                {num(category.weight * 100, 0)}% weight{" "}
                                {category.contribution != null
                                  ? `· ${num(category.contribution)} contribution`
                                  : ""}
                              </span>
                            </div>
                            <div className="category-track">
                              <span
                                style={{
                                  width: `${(category.score || 0) * 10}%`,
                                }}
                              />
                            </div>
                            <strong
                              className={`category-value ${scoreColor(category.score)}`}
                            >
                              {num(category.score, 1)}
                            </strong>
                          </div>
                        ))}
                      </div>
                      <p className="panel-footnote">
                        Quality measures the business. Attractiveness also
                        considers its price, technical setup and market context.
                      </p>
                      <Limitations items={scores.limitations} />
                    </section>
                    <section className="panel outlook-panel">
                      <SectionHeading
                        eyebrow="A WIDER PERSPECTIVE"
                        title="The research brief"
                      >
                        <span className="ai-icon">
                          <Sparkles size={15} />
                        </span>
                      </SectionHeading>
                      <div className="brief-section">
                        <span className="brief-label">
                          <TrendingUp size={14} />
                          Technical perspective
                        </span>
                        <Evidence
                          items={(technicalAssessment?.signals || []).slice(
                            0,
                            2,
                          )}
                          empty="Technical conclusions need sufficient price history."
                        />
                      </div>
                      <div className="brief-section">
                        <span className="brief-label">
                          <CalendarDays size={14} />
                          Upcoming catalysts
                        </span>
                        <EventPreview
                          events={current?.macro?.upcoming_events || []}
                          onCalendar={() => setPage("calendar")}
                        />
                      </div>
                      <button
                        className="text-button green brief-link"
                        onClick={() => setTab("report")}
                      >
                        Read the full research report <ArrowRight size={14} />
                      </button>
                    </section>
                  </div>
                </>
              )}
              {tab === "financials" && (
                <Financials
                  data={current?.fundamentals || {}}
                  status={sections.statements}
                  loading={research.isPending}
                  error={!current ? research.error : undefined}
                  onRetry={refreshResearch}
                />
              )}
              {tab === "quantitative" && (
                <QuantResearch
                  key={quantScopeKey}
                  ticker={ticker}
                  horizon={horizon}
                  ready={Boolean(current)}
                  baseConfig={quantConfig}
                  initialParameters={advanced?.configuration}
                  core={quantCore}
                  currency={overview.currency}
                  scopeKey={quantScopeKey}
                  onResult={(data, resolvedKey) => {
                    if (
                      resolvedKey !== quantScopeKey ||
                      !requestScope.isCurrent(quantRequestScope)
                    )
                      return;
                    if (data && data.ticker !== ticker) return;
                    setAdvanced((previous) =>
                      data
                        ? previous?.scopeKey === resolvedKey &&
                          previous.data === data
                          ? previous
                          : { scopeKey: resolvedKey, data }
                        : previous?.scopeKey === resolvedKey
                          ? null
                          : previous,
                    );
                  }}
                />
              )}
              {tab === "valuation" && (
                <Valuation
                  key={ticker}
                  data={current?.valuation || {}}
                  status={sections.company_info}
                  loading={research.isPending}
                  error={!current ? research.error : undefined}
                  onRetry={refreshResearch}
                  symbol={priceSymbol}
                  ticker={ticker}
                />
              )}
              {tab === "news" && (
                <News
                  data={current?.news || {}}
                  overview={overview}
                  status={sections.news}
                  earningsStatus={sections.earnings}
                  analystStatus={sections.analyst}
                  loading={research.isPending}
                  error={!current ? research.error : undefined}
                  onRetry={refreshResearch}
                />
              )}
              {tab === "macro" && (
                <Macro
                  data={current?.macro || {}}
                  onCalendar={() => setPage("calendar")}
                />
              )}
              {tab === "report" && (
                <section className="panel report-panel">
                  <SectionHeading
                    eyebrow="THE COMPLETE PICTURE"
                    title={`${ticker} investment research`}
                  >
                    <div className="action-group">
                      <button
                        className="button secondary small"
                        onClick={() => {
                          if (report?.markdown)
                            download(`${ticker}-research.md`, report.markdown);
                        }}
                        disabled={!report?.markdown}
                      >
                        <Download size={14} />
                        Export
                      </button>
                      <button
                        className="button primary small"
                        disabled={!current || saveReport.isPending}
                        onClick={() =>
                          saveReport.mutate({
                            ticker,
                            scope: requestScope.capture(),
                            inputs: advanced?.configuration ||
                              appliedInputs || { horizon },
                            quantitative: Boolean(advanced?.report),
                          })
                        }
                      >
                        {saveReport.isPending ? (
                          <LoaderCircle size={14} className="spin" />
                        ) : (
                          <Plus size={14} />
                        )}
                        Save report
                      </button>
                    </div>
                  </SectionHeading>
                  <p className="panel-footnote">
                    Evidence synthesis generated from the retrieved dataset.
                    Every rating is conditional on data coverage and the
                    disclosed assumptions.
                    {advanced?.report
                      ? " This report includes the completed quantitative review and its applied configuration."
                      : quantCore
                        ? " This core snapshot precedes the extended quantitative review. Open Quantitative research for benchmark, timeframe and historical validation evidence."
                        : ""}
                  </p>
                  {report?.markdown ? (
                    <Markdown text={report.markdown} />
                  ) : (
                    <Empty title="Your report needs source data">
                      Retrieve a stock to generate a grounded research report.
                    </Empty>
                  )}
                </section>
              )}
              {current && (
                <Limitations items={current.data_quality?.limitations} />
              )}
            </>
          )}
          {page === "calendar" && <CalendarPage onToast={setToast} />}
          {page === "screener" && (
            <TechScreener
              openStock={(symbol) => {
                openStock(symbol);
                setTab("overview");
              }}
              onToast={setToast}
            />
          )}
          {page === "watchlist" && (
            <>
              <PageIntro
                eyebrow="KEEP THE RIGHT COMPANIES CLOSE"
                title="Your watchlist"
                subtitle="A focused list for your next research decision."
              />
              <section className="panel">
                <SectionHeading title="Companies on your radar">
                  <Badge>{watchlist.data?.items.length || 0} saved</Badge>
                </SectionHeading>
                {watchlist.isError ? (
                  <ErrorBox error={watchlist.error} />
                ) : watchlist.data?.items.length ? (
                  <div className="watchlist-grid">
                    {watchlist.data.items.map((item) => (
                      <div className="watchlist-card" key={item.ticker}>
                        <span className="watchlist-logo">
                          {item.ticker.slice(0, 1)}
                        </span>
                        <h3>{item.ticker}</h3>
                        <p>Added {dateOnly(item.created_at)}</p>
                        <div>
                          <button
                            className="button secondary small"
                            onClick={() => openStock(item.ticker)}
                          >
                            Open research <ArrowRight size={13} />
                          </button>
                          <button
                            className="icon-button"
                            onClick={() => removeWatch.mutate(item.ticker)}
                            aria-label={`Remove ${item.ticker}`}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="Build your research shortlist"
                    icon={<Star size={28} />}
                  >
                    Find a company in Stock research and select the star to save
                    it here.
                    <button
                      className="button primary"
                      onClick={() => setPage("research")}
                    >
                      Research a stock <ArrowRight size={14} />
                    </button>
                  </Empty>
                )}
              </section>
            </>
          )}
          {page === "reports" && <ReportsPage openStock={openStock} />}
          {page === "backtest" && <BacktestPage initialTicker={ticker} />}
          <footer className="footer">
            <div>
              <span className="brand-dot" />
              EquityLens <span>·</span> Research with perspective
            </div>
            <p>
              Decision support only. Returns are uncertain. Data may be delayed
              or incomplete.
            </p>
            <span>v1.0</span>
          </footer>
        </div>
      </main>
      {toast && (
        <div className="toast" role="status">
          <Check size={16} />
          {toast}
          <button onClick={() => setToast("")} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}
      {settings && (
        <div className="modal-backdrop" onClick={() => setSettings(false)}>
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Customize analysis"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <p className="eyebrow">MAKE YOUR ASSUMPTIONS EXPLICIT</p>
                <h2>Customize your analysis</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => setSettings(false)}
                aria-label="Close settings"
              >
                <X size={20} />
              </button>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                trade.mutate({
                  ticker,
                  scope: requestScope.capture(),
                  inputs: analysisInputs,
                });
              }}
            >
              <div className="form-grid">
                <label>
                  Investment horizon
                  <select
                    value={horizon}
                    onChange={(e) => setHorizon(e.target.value)}
                  >
                    <option value="short">Short-term</option>
                    <option value="swing">Swing trade</option>
                    <option value="long">Long-term</option>
                  </select>
                </label>
                <label>
                  Risk tolerance
                  <select
                    value={risk}
                    onChange={(e) => setRisk(e.target.value)}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
                <label>
                  Available capital ({overview.currency || "quote currency"})
                  <input
                    type="number"
                    min="1"
                    max="1000000000"
                    value={capital}
                    required
                    onChange={(e) => setCapital(Number(e.target.value))}
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
                    required
                    onChange={(e) => setRiskPercent(Number(e.target.value))}
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
                    required
                    onChange={(e) => setMinRR(Number(e.target.value))}
                  />
                </label>
                <label>
                  Existing shares
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={existingShares}
                    onChange={(e) => setExistingShares(Number(e.target.value))}
                  />
                </label>
                <label>
                  Cost basis per share ({overview.currency || "quote currency"},
                  optional)
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={costBasis}
                    placeholder="Per share"
                    onChange={(e) => setCostBasis(e.target.value)}
                  />
                </label>
              </div>
              <div className="weights-header">
                <h3>Evidence weights</h3>
                <span
                  className={
                    Math.abs(
                      Object.values(weights).reduce((a, b) => a + b, 0) - 1,
                    ) < 0.0001
                      ? "green"
                      : "amber"
                  }
                >
                  {num(
                    Object.values(weights).reduce((a, b) => a + b, 0) * 100,
                    0,
                  )}
                  % of 100%
                </span>
              </div>
              <p className="muted small-text">
                Weights must total 100%. Missing categories reduce confidence
                and are never treated as favorable evidence.
                {quantCore &&
                  " Business, valuation, technical, trade setup and macro weights are adjusted for your horizon. News contributes a bounded adjustment; it cannot overpower the other evidence."}
              </p>
              <div className="weight-controls">
                {Object.entries(weights).map(([key, value]) => (
                  <label key={key}>
                    <span>
                      {quantCore && key === "risk"
                        ? "Trade setup quality"
                        : CATEGORY_LABELS[key]}
                    </span>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="5"
                      value={Math.round(value * 100)}
                      onChange={(e) =>
                        setWeights({
                          ...weights,
                          [key]: Number(e.target.value) / 100,
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
                onClick={() => setWeights({ ...DEFAULT_WEIGHTS })}
              >
                Restore default weights
              </button>
              {trade.isError && <ErrorBox error={trade.error} />}
              <div className="modal-actions">
                <span>
                  <ShieldCheck size={14} />
                  Maximum capital risk: {priceSymbol}
                  {num((capital * riskPercent) / 100)}
                </span>
                <button
                  className="button primary"
                  disabled={
                    trade.isPending ||
                    Math.abs(
                      Object.values(weights).reduce((a, b) => a + b, 0) - 1,
                    ) > 0.0001
                  }
                >
                  {trade.isPending ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : (
                    <RefreshCw size={15} />
                  )}
                  Update analysis
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
