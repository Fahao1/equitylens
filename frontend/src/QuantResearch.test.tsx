import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import QuantResearch, {
  ProbabilityEvidence,
  pendingQuantPlan,
} from "./QuantResearch";
import { api, post, ApiError } from "./api";
import type { QuantProbability, QuantResearchResponse } from "./types";
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, api: vi.fn(), post: vi.fn() };
});
const get = vi.mocked(api),
  send = vi.mocked(post);
function fixture(ticker = "NVDA"): QuantResearchResponse {
  return {
    ticker,
    as_of: "2026-10-26T20:00:00Z",
    methodology_version: "2.0",
    regime: {
      regime: "Strong bullish trend",
      trend_strength: "Strong",
      volatility_regime: "Normal",
      confidence: 0.8,
      evidence: [
        "Completed daily close is above the long-term moving average.",
      ],
      features: { benchmark_trend: "Bullish" },
    },
    scores: {
      company_quality: 8,
      valuation_attractiveness: 3,
      technical_strength: 7,
      trade_setup_quality: 6,
      macroeconomic_environment: 5,
      overall_investment_attractiveness: 6,
    },
    evidence: {
      confidence: 0.7,
      data_freshness: {
        history: {
          status: "cached",
          fetched_at: "2026-10-26T20:00:00Z",
          cache_stale: false,
        },
      },
      model_uncertainty: {
        kind: "heuristic",
        calibrated: false,
        limitations: ["Rules are not calibrated return forecasts."],
      },
      sample_reliability: {
        status: "Insufficient historical evidence",
        sample_size: 6,
        min_samples: 30,
      },
    },
    timeframes: {
      timeframes: [
        {
          timeframe: "weekly",
          status: "available",
          trend: "Bullish",
          momentum: "Positive",
          volatility: "Normal",
          support: 95,
          resistance: 120,
          bars: 150,
          last_bar_at: "2026-10-23T20:00:00Z",
        },
        {
          timeframe: "daily",
          status: "available",
          trend: "Bearish",
          momentum: "Weak",
          volatility: "Normal",
          bars: 500,
          last_bar_at: "2026-10-23T20:00:00Z",
        },
        {
          timeframe: "15m",
          status: "unavailable",
          bars: 0,
          limitations: ["Intraday retention window is unavailable."],
        },
      ],
      alignment: {
        status: "Conflict",
        conflicts: ["Weekly trend is bullish while daily momentum is weak."],
      },
      limitations: [],
    },
    strategies: [
      {
        id: "trend_following",
        name: "Trend following",
        status: "eligible",
        eligible: true,
        entry_condition:
          "Next completed-bar confirmation and an affordable fill are required.",
        entry_zone: [100, 101],
        stop: 90,
        targets: [120, 130, 140],
        net_reward_risk: [1.5, 2.2, 3.1],
        position_size: 8,
        holding_horizon: "Swing",
        evidence: ["Trend is supported by the completed-bar structure."],
        avoid_reasons: [],
        target_methodology: [
          "Targets are the next three confirmed resistance zones.",
        ],
        calculation: [
          "Entry and stop execution include commissions and slippage.",
        ],
        invalidation: {
          price: 90,
          kind: "technical",
          condition: "A completed close below support invalidates this setup.",
        },
      },
      {
        id: "breakout",
        name: "Breakout",
        status: "wait",
        eligible: false,
        avoid_reasons: ["No completed breakout confirmation."],
      },
      {
        id: "mean_reversion",
        name: "Mean reversion",
        status: "avoid",
        eligible: false,
        avoid_reasons: ["The current regime is trending."],
      },
      {
        id: "fundamental_value",
        name: "Fundamental value",
        status: "insufficient_data",
        eligible: false,
        avoid_reasons: ["No reliable point-in-time fundamental value history."],
      },
    ],
    recommendation: {
      recommendation: "Buy candidate",
      best_strategy: "trend_following",
      entry_zone: [100, 101],
      stop: 90,
      targets: [120, 130, 140],
      risk_reward: 1.5,
      position_size: 8,
      entry_condition: "Conditional next-bar execution.",
      calculation: ["Costs are included in the adverse execution risk."],
      invalidation: { condition: "Reassess if support fails." },
      event_warnings: ["Imported economic coverage is incomplete."],
    },
    probabilities: {
      status: "Insufficient historical evidence",
      sample_size: 6,
      min_samples: 30,
      validation_period: { start: "2021-01-01", end: "2026-10-23" },
      estimates: {
        target_1_before_stop: null,
        target_2_before_stop: null,
        stop_before_target: null,
        expected_return: null,
        expected_holding_bars: null,
      },
      confidence_intervals: {},
      limitations: [
        "Comparable nonoverlapping observations are below the minimum sample.",
      ],
    },
    validation: {
      strategies: {
        trend_following: {
          status: "weak_evidence",
          sample_size: 12,
          metrics: {
            win_rate: 0.5,
            total_return: 0.02,
            maximum_drawdown: -0.1,
            sharpe_ratio: 0.2,
            average_holding_bars: 8,
          },
          limitations: ["Small descriptive sample."],
        },
      },
      limitations: ["Only historical price-derived inputs are included."],
    },
    source: "Synthetic unit-test fixture",
  };
}
function mount(
  ticker = "NVDA",
  ready = true,
  baseConfig?: Record<string, unknown>,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <QuantResearch
        ticker={ticker}
        horizon="swing"
        ready={ready}
        baseConfig={baseConfig}
        currency="USD"
      />
    </QueryClientProvider>,
  );
  return { ...view, client };
}
beforeEach(() => {
  get.mockReset();
  send.mockReset();
  get.mockResolvedValue(fixture());
  send.mockResolvedValue(fixture());
});
describe("quantitative research display", () => {
  it("retains ETF technical research without offering corporate valuation models", async () => {
    get.mockResolvedValue({
      ...fixture("QQQ"),
      valuation: { applicable: false },
      scores: {
        technical_strength: 6,
        company_quality: null,
        valuation_attractiveness: null,
      },
    });
    mount("QQQ");
    await screen.findByText("Strong bullish trend");
    expect(
      screen.getByText(
        /Corporate DCF, earnings-multiple and cash-flow yield scenarios are not applicable/,
      ),
    ).toBeVisible();
    expect(
      screen.queryByText("Optional valuation scenarios and peer comparisons"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Strategy comparison")).toBeVisible();
  });
  it("withholds a preliminary buy until the full-context result is authoritative", () => {
    const plan = fixture().recommendation;
    expect(pendingQuantPlan(plan)).toMatchObject({
      recommendation: "Wait",
      position_size: 0,
    });
    expect(pendingQuantPlan(plan, true)).toBe(plan);
  });
  it("only sends explicit valuation models and normalizes FCF yield percentages", async () => {
    mount();
    await screen.findByText("Strong bullish trend");
    fireEvent.click(
      screen.getByText("Optional valuation scenarios and peer comparisons"),
    );
    fireEvent.click(
      screen.getByLabelText("Use explicit valuation assumptions"),
    );
    fireEvent.change(
      screen.getByLabelText(
        "Earnings multiples (conservative, base, optimistic)",
      ),
      { target: { value: "12,18,24" } },
    );
    fireEvent.change(
      screen.getByLabelText("FCF yields % (conservative, base, optimistic)"),
      { target: { value: "8,6,4" } },
    );
    fireEvent.change(screen.getByLabelText("Peer tickers (up to 5)"), {
      target: { value: "msft,orcl" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Update quantitative research" }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(send).toHaveBeenLastCalledWith(
      "/stocks/NVDA/quantitative",
      expect.objectContaining({
        margin_of_safety: 0.2,
        peer_tickers: ["MSFT", "ORCL"],
        valuation_assumptions: expect.objectContaining({
          enable_dcf: false,
          earnings_multiples: [12, 18, 24],
          fcf_yields: [0.08, 0.06, 0.04],
        }),
      }),
      expect.any(Object),
    );
  });
  it("rejects inverted valuation scenarios before making a request", async () => {
    mount();
    await screen.findByText("Strong bullish trend");
    fireEvent.click(
      screen.getByText("Optional valuation scenarios and peer comparisons"),
    );
    fireEvent.click(
      screen.getByLabelText("Use explicit valuation assumptions"),
    );
    fireEvent.change(
      screen.getByLabelText(
        "Earnings multiples (conservative, base, optimistic)",
      ),
      { target: { value: "24,18,12" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Update quantitative research" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "positive earnings multiples",
    );
    expect(send).not.toHaveBeenCalled();
  });
  it("restores the last applied quantitative assumptions when returning to the view", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const parameters = {
      benchmark_ticker: "QQQ",
      min_samples: 40,
      commission_bps: 7,
      peer_tickers: ["ORCL"],
      valuation_assumptions: {
        enable_dcf: false,
        earnings_multiples: [10, 15, 20],
        fcf_yields: [0.08, 0.06, 0.04],
      },
    };
    render(
      <QueryClientProvider client={client}>
        <QuantResearch
          ticker="NVDA"
          ready
          baseConfig={{ capital: 25000 }}
          initialParameters={parameters}
        />
      </QueryClientProvider>,
    );
    await screen.findByText("Strong bullish trend");
    expect(screen.getByLabelText("Benchmark ticker")).toHaveValue("QQQ");
    fireEvent.click(
      screen.getByText("Optional valuation scenarios and peer comparisons"),
    );
    expect(
      screen.getByLabelText("Use explicit valuation assumptions"),
    ).toBeChecked();
    expect(
      screen.getByLabelText(
        "Earnings multiples (conservative, base, optimistic)",
      ),
    ).toHaveValue("10, 15, 20");
    expect(
      screen.getByLabelText("FCF yields % (conservative, base, optimistic)"),
    ).toHaveValue("8, 6, 4");
    expect(send).toHaveBeenCalledWith(
      "/stocks/NVDA/quantitative",
      expect.objectContaining({
        ...parameters,
        capital: 25000,
        horizon: "swing",
      }),
      expect.any(Object),
    );
  });
  it("shows source-bound scenario ranges and rejected peer limitations", async () => {
    get.mockResolvedValue({
      ...fixture(),
      valuation: {
        models: { earnings_multiple: { bear: 80, base: 100, bull: 120 } },
        valuation_range: { bear: 80, base: 100, bull: 120 },
        margin_of_safety: -0.1,
        model_uncertainty: {
          aggregation: "Models share earnings and cash-flow risks.",
        },
        peer_comparison: {
          status: "Insufficient comparable peers",
          minimum_peers: 3,
          excluded: [
            {
              ticker: "TEST",
              reason: "Industry/currency comparability was not established.",
            },
          ],
        },
      },
    });
    mount();
    await screen.findByText("Models share earnings and cash-flow risks.");
    expect(screen.getByText("$80.00 / $100.00 / $120.00")).toBeVisible();
    fireEvent.click(
      screen.getByText("Comparable peers and historical valuations"),
    );
    expect(
      screen.getByText(
        "TEST: Industry/currency comparability was not established.",
      ),
    ).toBeVisible();
  });
  it("does not retrieve expensive evidence before core research is ready", () => {
    mount("NVDA", false);
    expect(get).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByText(/Waiting for the current stock/)).toBeVisible();
  });
  it("shows six distinct scores and keeps confidence, freshness, uncertainty and sample reliability separate", async () => {
    mount();
    await screen.findByText("Strong bullish trend");
    for (const title of [
      "Company quality",
      "Valuation attractiveness",
      "Technical strength",
      "Trade setup quality",
      "Macroeconomic environment",
      "Overall investment attractiveness",
    ])
      expect(screen.getByText(title, { exact: true })).toBeVisible();
    expect(
      screen.getByText("Evidence confidence", { exact: true }),
    ).toBeVisible();
    expect(screen.getByText("Data freshness", { exact: true })).toBeVisible();
    expect(
      screen.getByText("Model uncertainty", { exact: true }),
    ).toBeVisible();
    expect(
      screen.getByText("Sample reliability", { exact: true }),
    ).toBeVisible();
    expect(screen.getByText("Not calibrated")).toBeVisible();
    expect(get).toHaveBeenCalledWith(
      "/stocks/NVDA/quantitative?horizon=swing&benchmark=SPY",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
  it("shows timeframe conflicts, missing intraday evidence and all four strategy eligibility results", async () => {
    mount();
    await screen.findByText("Strong bullish trend");
    expect(
      screen.getByText("Weekly trend is bullish while daily momentum is weak."),
    ).toBeVisible();
    expect(
      screen.getByText(
        /five matching timeframes are not five independent confirmations/,
      ),
    ).toBeVisible();
    const trend = screen.getByRole("row", { name: /Trend following Eligible/ });
    expect(trend).toHaveTextContent("$100.00 – $101.00");
    expect(trend).toHaveTextContent("$140.00");
    expect(trend).toHaveTextContent("1.50 : 1 / 2.20 : 1 / 3.10 : 1");
    expect(screen.getByRole("row", { name: /Breakout Wait/ })).toBeVisible();
    expect(
      screen.getByRole("row", { name: /Mean reversion Avoid/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("row", { name: /Fundamental value Insufficient Data/ }),
    ).toBeVisible();
    expect(screen.getByRole("row", { name: /15m Unavailable/ })).toBeVisible();
  });
  it("submits explicit model assumptions while preserving inherited trade settings", async () => {
    mount("NVDA", true, {
      capital: 25000,
      risk_per_trade: 0.01,
      risk_tolerance: "low",
    });
    await screen.findByText("Strong bullish trend");
    fireEvent.change(screen.getByLabelText("Benchmark ticker"), {
      target: { value: "qqq" },
    });
    fireEvent.change(screen.getByLabelText("Commission (bps, optional)"), {
      target: { value: "7.5" },
    });
    fireEvent.change(screen.getByLabelText("Slippage (bps, optional)"), {
      target: { value: "8" },
    });
    fireEvent.change(screen.getByLabelText("Maximum holding bars (optional)"), {
      target: { value: "50" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Update quantitative research" }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(send).toHaveBeenLastCalledWith(
      "/stocks/NVDA/quantitative",
      expect.objectContaining({
        capital: 25000,
        risk_tolerance: "low",
        horizon: "swing",
        benchmark_ticker: "QQQ",
        min_samples: 30,
        commission_bps: 7.5,
        slippage_bps: 8,
        max_holding_bars: 50,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
  it("ignores an older ticker’s quantitative response when switching stocks", async () => {
    let resolve!: (value: QuantResearchResponse) => void;
    get
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      )
      .mockResolvedValueOnce({
        ...fixture("TSLA"),
        regime: {
          regime: "High-volatility regime",
          evidence: ["Tesla fixture context."],
        },
      });
    const { rerender, client } = mount();
    rerender(
      <QueryClientProvider client={client}>
        <QuantResearch ticker="TSLA" ready currency="USD" />
      </QueryClientProvider>,
    );
    await screen.findByText("High-volatility regime");
    await act(async () => {
      resolve({ ...fixture(), regime: { regime: "STALE NVDA REGIME" } });
      await new Promise((done) => setTimeout(done, 10));
    });
    expect(screen.queryByText("STALE NVDA REGIME")).not.toBeInTheDocument();
    expect(screen.getByText("High-volatility regime")).toBeVisible();
  });
  it("keeps actual core evidence visible if extended validation is temporarily unavailable", async () => {
    get.mockRejectedValue(
      new ApiError(
        "Extended validation is temporarily unavailable.",
        "DATA_PROVIDER_UNAVAILABLE",
        false,
        503,
      ),
    );
    const core = fixture();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <QuantResearch ticker="NVDA" ready core={core} />
      </QueryClientProvider>,
    );
    await screen.findByText("Extended validation is temporarily unavailable.");
    expect(screen.getByText("Strong bullish trend")).toBeVisible();
    expect(
      screen.getByText(/Insufficient historical evidence. Probability/),
    ).toBeVisible();
  });
});
describe("empirical probability abstention", () => {
  it("never substitutes a success probability when evidence is insufficient", () => {
    render(
      <ProbabilityEvidence
        probabilities={{
          status: "Insufficient historical evidence",
          sample_size: 6,
          min_samples: 30,
          estimates: { target_1_before_stop: 0.9, expected_return: 0.5 },
          validation_period: { start: "2021-01-01", end: "2026-10-23" },
        }}
      />,
    );
    expect(screen.queryByText("90.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("50.0%")).not.toBeInTheDocument();
    expect(screen.getAllByText("Withheld").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("Jan 1, 2021 – Oct 23, 2026")).toBeVisible();
  });
  it("requires each probability’s interval and its own eligible target2 sample", () => {
    const p: QuantProbability = {
      status: "available",
      sample_size: 40,
      min_samples: 30,
      estimates: {
        target_1_before_stop: 0.6,
        target_2_before_stop: 0.5,
        stop_before_target: 0.2,
        expected_return: 0.03,
        expected_holding_bars: 8,
      },
      target_2: { status: "Insufficient historical evidence", sample_size: 10 },
      confidence_intervals: {
        target_1_before_stop: [0.45, 0.74],
        target_2_before_stop: [0.2, 0.8],
        stop_before_target: [0.1, 0.35],
      },
    };
    render(<ProbabilityEvidence probabilities={p} />);
    expect(
      within(
        screen.getByRole("row", { name: /Target 1 before stop/ }),
      ).getByText("60.0%"),
    ).toBeVisible();
    expect(
      screen.getByRole("row", { name: /Target 1 before stop/ }),
    ).toHaveTextContent("45.0% – 74.0%");
    expect(
      screen.getByRole("row", { name: /Target 2 before stop/ }),
    ).toHaveTextContent("Withheld");
    expect(
      screen.getByRole("row", { name: /Target 2 before stop/ }),
    ).toHaveTextContent("10");
    expect(screen.getByText(/third outcome/)).toBeVisible();
  });
  it.each([null, [0.7, 0.9]])(
    "withholds an estimate without a valid compatible interval %j",
    (bounds) => {
      render(
        <ProbabilityEvidence
          probabilities={{
            status: "available",
            sample_size: 40,
            min_samples: 30,
            estimates: { target_1_before_stop: 0.6 },
            confidence_intervals: {
              target_1_before_stop: bounds as [number, number] | null,
            },
          }}
        />,
      );
      expect(screen.queryByText("60.0%")).not.toBeInTheDocument();
      expect(
        screen.getByRole("row", { name: /Target 1 before stop/ }),
      ).toHaveTextContent("Withheld");
    },
  );
  it("does not allow an available status to override an inadequate minimum sample", () => {
    render(
      <ProbabilityEvidence
        probabilities={{
          status: "available",
          sample_size: 5,
          min_samples: 30,
          estimates: { target_1_before_stop: 0.6 },
          confidence_intervals: { target_1_before_stop: [0.4, 0.8] },
        }}
      />,
    );
    expect(screen.queryByText("60.0%")).not.toBeInTheDocument();
    expect(
      screen.getByText(/no default success rate is substituted/),
    ).toBeVisible();
  });
});
