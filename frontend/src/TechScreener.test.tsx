import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TechScreener, { sortScreenerStocks } from "./TechScreener";
import { api, post } from "./api";
import type {
  ScreenerHorizon,
  ScreenerSnapshot,
  ScreenerStock,
} from "./techScreenerTypes";
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, api: vi.fn(), post: vi.fn() };
});
const get = vi.mocked(api),
  send = vi.mocked(post);
const openStock = vi.fn(),
  onToast = vi.fn();
function stock(ticker: string, score: number | null = 7): ScreenerStock {
  return {
    ticker,
    name: `${ticker} synthetic fixture`,
    rank: 1,
    price: 100,
    currency: "USD",
    overall_score: score,
    company_quality: 8,
    technical_strength: 6,
    valuation_attractiveness: null,
    trade_setup_quality: null,
    historical_evidence: null,
    confidence: 0.6,
    data_completeness: 0.7,
    metrics_evaluated: 8,
    missing_information: ["No dated company news"],
    fetched_at: "2026-10-27T00:00:00Z",
    analysis_stage: "broad",
    eligible_buy: false,
    recommendation: "Watchlist Candidate",
    ranking_explanation: [
      "Reference rule score from the supplied test metrics",
    ],
    buy_triggers: ["Wait for completed breakout confirmation"],
    risks: ["Calendar coverage is incomplete"],
    industry: "Software",
    market_cap: 1000000000,
  };
}
function snapshot(horizon: ScreenerHorizon = "short_term"): ScreenerSnapshot {
  const rows = [
    stock("TESTA", 7),
    stock("TESTB", 8),
    stock("TESTC", 5),
    stock("TESTD", null),
  ].map((row, index) => ({ ...row, rank: index + 1 }));
  return {
    horizon,
    run_id: `fixture-${horizon}`,
    as_of: "2026-10-27T00:00:00Z",
    methodology_version: "Synthetic unit-test rules",
    rankings: rows,
    top_ranked: rows[1],
    best_eligible: null,
    buy_candidates: [],
    watchlist_candidates: [rows[0]],
    coverage: {
      total_eligible: 100,
      successfully_analyzed: 4,
      incomplete: 2,
      excluded: 3,
      ranked: 3,
      deep_analyzed: 0,
      comprehensive: false,
      source: "Synthetic universe fixture",
    },
    provider_errors: [
      {
        ticker: "TESTX",
        code: "RATE_LIMITED",
        message: "Source requested a later retry",
      },
    ],
    limitations: ["Unit-test sample; not real market rankings"],
  };
}
function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 60000 },
      mutations: { retry: false },
    },
  });
  return {
    ...render(
      <QueryClientProvider client={client}>
        <TechScreener openStock={openStock} onToast={onToast} />
      </QueryClientProvider>,
    ),
    client,
  };
}
beforeEach(() => {
  get.mockReset();
  send.mockReset();
  openStock.mockReset();
  onToast.mockReset();
  get.mockImplementation(async (path) => {
    if (path.includes("/universe"))
      return {
        source: "Synthetic universe fixture",
        industries: ["Software"],
        exchanges: ["NASDAQ"],
        countries: ["United States"],
        members: [],
      };
    const horizon = path.includes("long_term") ? "long_term" : "short_term";
    if (path.includes("/status")) return { horizon };
    if (path.includes("/rankings")) return snapshot(horizon);
    throw new Error(`Unexpected route ${path}`);
  });
  send.mockResolvedValue({
    horizon: "short_term",
    accepted: true,
    job: {
      id: "job-test",
      status: "queued",
      stage: "broad",
      processed: 0,
      total: 100,
    },
  });
});
describe("technology screener", () => {
  it("sends disclosed DCF defaults and allows explicit abstention when disabled", async () => {
    mount();
    await screen.findByLabelText("Compare TESTA");
    expect(
      screen.getByText(
        /5% annual growth, 10% discount rate, 2% terminal growth/,
      ),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Optional DCF reference assumptions"));
    fireEvent.click(
      screen.getByLabelText(
        "Enable DCF sensitivities when reported cash flow and share data are suitable",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Apply & screen" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        "/screener/tech/refresh",
        expect.objectContaining({
          valuation_assumptions: { enable_dcf: false },
        }),
      ),
    );
  });
  it("rejects DCF discount/terminal assumptions that invalidate the optimistic scenario", async () => {
    mount();
    await screen.findByLabelText("Compare TESTA");
    fireEvent.click(screen.getByText("Optional DCF reference assumptions"));
    fireEvent.change(screen.getByLabelText("Discount rate (%)"), {
      target: { value: "3" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Apply & screen" }).closest("form")!,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "optimistic DCF discount rate",
    );
    expect(send).not.toHaveBeenCalled();
  });
  it("shows a buy only when the source explicitly reports a completed deep review and eligible setup", async () => {
    const best = {
      ...stock("QUALIFIED"),
      analysis_stage: "deep" as const,
      eligible_buy: true,
      recommendation: "Buy Candidate",
      plan: {
        entry_zone: [90, 95] as [number, number],
        stop: 80,
        targets: [125, 140],
        risk_reward: 2.1,
        position_size: 6,
      },
    };
    get.mockImplementation(async (path) =>
      path.includes("/rankings")
        ? { ...snapshot(), best_eligible: best, buy_candidates: [best] }
        : path.includes("/status")
          ? { horizon: "short_term" }
          : {},
    );
    mount();
    await screen.findAllByRole("button", { name: "Open QUALIFIED research" });
    expect(
      screen.queryByText("No qualified buy candidate"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText("Buy Candidate", { exact: true }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("$90.00 – $95.00")).toBeVisible();
    expect(screen.getByText("2.10 : 1")).toBeVisible();
  });
  it("updates coverage after a background job completes without rerunning Yahoo from the browser", async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (path, options) =>
      path.includes("/status")
        ? {
            horizon: "short_term",
            job: {
              id: "progress-test",
              status: "running",
              stage: "broad",
              total: 100,
              processed: 40,
              deep_total: 15,
              deep_processed: 2,
            },
          }
        : original(path, options),
    );
    const { client } = mount();
    expect(
      await screen.findByRole("progressbar", { name: "Screening progress" }),
    ).toHaveAttribute("value", "40");
    const calls = get.mock.calls.filter(([path]) =>
      path.includes("/rankings"),
    ).length;
    await act(async () => {
      client.setQueryData(["tech-status", "short_term"], {
        horizon: "short_term",
        job: {
          id: "progress-test",
          status: "completed",
          stage: "complete",
          total: 100,
          processed: 100,
          deep_total: 15,
          deep_processed: 15,
        },
      });
    });
    await waitFor(() =>
      expect(
        get.mock.calls.filter(([path]) => path.includes("/rankings")).length,
      ).toBeGreaterThan(calls),
    );
    expect(
      screen.getByRole("progressbar", { name: "Screening progress" }),
    ).toHaveAttribute("value", "100");
    expect(send).not.toHaveBeenCalled();
  });
  it("requires a position ticker and sends holdings only with that explicit identity", async () => {
    mount();
    await screen.findByLabelText("Compare TESTA");
    fireEvent.click(screen.getByText("Scoring weights & position sizing"));
    fireEvent.change(
      screen.getByLabelText("Existing shares in an analyzed company"),
      { target: { value: "5" } },
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Apply & screen" }).closest("form")!,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "ticker of your existing position",
    );
    expect(send).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Existing position ticker"), {
      target: { value: "testa" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply & screen" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        "/screener/tech/refresh",
        expect.objectContaining({
          existing_shares: 5,
          position_ticker: "TESTA",
          capital_currency: "USD",
        }),
      ),
    );
  });
  it("shows actual coverage, missing evidence and the highest-ranked company without forcing an eligible buy", async () => {
    mount();
    await screen.findByText("No qualified buy candidate");
    await screen.findByLabelText("Compare TESTA");
    expect(screen.getAllByText("TESTB").length).toBeGreaterThan(0);
    expect(screen.getByText(/Coverage is partial or unverified/)).toBeVisible();
    expect(screen.getAllByText(/RATE_LIMITED/).length).toBeGreaterThan(0);
    expect(
      screen.queryByText("Buy Candidate", { exact: true }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "No historical portfolio performance is inferred from today's stock rankings.",
        { exact: false },
      ),
    ).toBeVisible();
  });
  it.each([
    { stage: "broad", stale: false },
    { stage: "deep", stale: true },
  ])(
    "never labels a broad-only or stale snapshot as a current eligible buy ($stage, stale=$stale)",
    async ({ stage, stale }) => {
      get.mockImplementation(async (path) =>
        path.includes("/rankings")
          ? {
              ...snapshot(),
              best_eligible: {
                ...stock("EARLY"),
                analysis_stage: stage,
                cache_stale: stale,
                eligible_buy: true,
                recommendation: "Buy Candidate",
              },
            }
          : path.includes("/status")
            ? { horizon: "short_term" }
            : {},
      );
      mount();
      await screen.findByLabelText("Compare TESTA");
      expect(
        screen.queryByRole("button", { name: "Open EARLY research" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText("Buy Candidate", { exact: true }),
      ).not.toBeInTheDocument();
    },
  );
  it("changes ranking requests and defaults when switching investment horizons", async () => {
    mount();
    await screen.findByText("No qualified buy candidate");
    fireEvent.click(screen.getByText("Scoring weights & position sizing"));
    expect(screen.getByLabelText("Technical Strength weight")).toHaveValue(
      "30",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Long-Term Investing" }),
    );
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/screener/tech/rankings?horizon=long_term",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
    expect(
      screen.getByLabelText("Financial Quality Growth weight"),
    ).toHaveValue("30");
    expect(
      screen.queryByLabelText("Technical Strength weight"),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/1–5\+ years/)).toBeVisible();
  });
  it("sends validated filters, configurable weights and position settings to the background job", async () => {
    mount();
    await screen.findByText("No qualified buy candidate");
    fireEvent.change(screen.getByLabelText("Industries"), {
      target: { value: "Software, Semiconductors" },
    });
    fireEvent.change(screen.getByLabelText("Minimum revenue growth (%)"), {
      target: { value: "12" },
    });
    fireEvent.click(screen.getByLabelText("Profitable companies only"));
    fireEvent.click(screen.getByText("Scoring weights & position sizing"));
    fireEvent.change(screen.getByLabelText("Available capital"), {
      target: { value: "25000" },
    });
    fireEvent.change(screen.getByLabelText("Technical Strength weight"), {
      target: { value: "40" },
    });
    expect(
      screen.getByRole("button", { name: "Apply & screen" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Trade Setup Quality weight"), {
      target: { value: "15" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply & screen" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        "/screener/tech/refresh",
        expect.objectContaining({
          horizon: "short_term",
          capital: 25000,
          risk_per_trade: 0.01,
          min_reward_risk: 2,
          max_deep_analysis: 15,
          filters: expect.objectContaining({
            industries: ["Software", "Semiconductors"],
            min_revenue_growth: 0.12,
            profitable_only: true,
          }),
          weights: expect.objectContaining({
            technical_strength: 0.4,
            trade_setup_quality: 0.15,
          }),
        }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Screening started",
    );
  });
  it("limits comparisons to three companies and keeps stock drilldown available", async () => {
    mount();
    await screen.findByText("No qualified buy candidate");
    await screen.findByLabelText("Compare TESTA");
    for (const ticker of ["TESTA", "TESTB", "TESTC", "TESTD"])
      fireEvent.click(screen.getByLabelText(`Compare ${ticker}`));
    expect(screen.getByRole("status")).toHaveTextContent("up to three stocks");
    expect(screen.getByLabelText("Compare TESTD")).not.toBeChecked();
    const comparison = screen
      .getByRole("heading", { name: "Detailed stock comparison" })
      .closest("section")!;
    expect(
      within(comparison).getAllByRole("button", {
        name: /Open TEST.* research/,
      }),
    ).toHaveLength(3);
    fireEvent.click(
      screen.getAllByRole("button", { name: "Open TESTB research" })[0],
    );
    expect(openStock).toHaveBeenCalledWith("TESTB");
  });
  it("keeps missing sort values last rather than assigning a zero score", () => {
    expect(
      sortScreenerStocks(
        [stock("MISSING", null), stock("HIGH", 8), stock("LOW", 2)],
        "overall_score",
      ).map((row) => row.ticker),
    ).toEqual(["HIGH", "LOW", "MISSING"]);
    expect(
      sortScreenerStocks(
        [stock("MISSING", null), stock("HIGH", 8), stock("LOW", 2)],
        "overall_score",
        false,
      ).map((row) => row.ticker),
    ).toEqual(["LOW", "HIGH", "MISSING"]);
  });
  it("adds a watchlist candidate through the existing watchlist API", async () => {
    mount();
    const button = await screen.findByRole("button", {
      name: "Add to my watchlist",
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith("/watchlist", { ticker: "TESTA" }),
    );
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith("Added to your watchlist."),
    );
  });
  it("does not apply an old horizon's late refresh result to the new horizon", async () => {
    let resolve!: (value: unknown) => void;
    send.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    mount();
    await screen.findByText("No qualified buy candidate");
    fireEvent.click(screen.getByRole("button", { name: "Apply & screen" }));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    fireEvent.click(
      screen.getByRole("button", { name: "Long-Term Investing" }),
    );
    await act(async () => {
      resolve({
        horizon: "short_term",
        accepted: true,
        job: { id: "old-short", status: "running" },
      });
    });
    expect(
      screen.queryByText(
        "Screening started. Rankings update after the background run finishes.",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Apply & screen" }),
    ).toBeEnabled();
  });
  it("preserves explicit historical abstention without inventing a portfolio curve", async () => {
    send.mockResolvedValue({
      status: "Insufficient point-in-time evidence",
      reason: "Historical universe membership is unavailable",
      metrics: null,
      required_data: ["Publication-time financial snapshots"],
    });
    mount();
    await screen.findByText("No qualified buy candidate");
    fireEvent.click(
      screen.getByRole("button", { name: "Check historical evidence" }),
    );
    expect(
      await screen.findByText(/Historical universe membership is unavailable/),
    ).toBeVisible();
    expect(send).toHaveBeenCalledWith(
      "/screener/tech/backtest",
      expect.objectContaining({
        horizon: "short_term",
        top_n: 5,
        commission_bps: 5,
        slippage_bps: 5,
      }),
    );
    expect(screen.queryByText(/Sharpe ratio/)).not.toBeInTheDocument();
  });
  it("shows an empty persisted snapshot without fabricated stock rows", async () => {
    get.mockImplementation(async (path) =>
      path.includes("/rankings")
        ? {
            horizon: "short_term",
            rankings: [],
            coverage: { total_eligible: 0, comprehensive: false },
          }
        : path.includes("/status")
          ? { horizon: "short_term" }
          : {},
    );
    mount();
    await screen.findByText("No companies qualified for ranking");
    expect(screen.queryByLabelText(/Compare TEST/)).not.toBeInTheDocument();
    expect(screen.getByText("No qualified buy candidate")).toBeVisible();
  });
});
