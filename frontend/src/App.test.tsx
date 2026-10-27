import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { api, post } from "./api";
import type { Bag } from "./types";
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, api: vi.fn(), post: vi.fn() };
});
vi.mock("./Chart", () => ({
  default: ({ prices }: { prices: Bag[] }) => (
    <div data-testid="price-chart">Chart close {prices[0]?.close}</div>
  ),
  EquityChart: () => null,
}));
const get = vi.mocked(api),
  send = vi.mocked(post);
const names: Record<string, string> = {
  NVDA: "NVIDIA test fixture",
  MSFT: "Microsoft test fixture",
  ORCL: "Oracle test fixture",
  TSLA: "Tesla test fixture",
};
function dataset(ticker: string) {
  const category = { score: 6, confidence: 0.8, signals: [], limitations: [] };
  const status = {
    status: "available",
    fetched_at: "2026-10-26T00:00:00Z",
    cache_stale: false,
    error: null,
  };
  return {
    ticker,
    as_of: "2026-10-26T00:00:00Z",
    overview: {
      name: names[ticker] || ticker,
      price: ticker === "NVDA" ? 100 : 200,
      currency: "USD",
      sector: "Technology",
      quote_at: "2026-10-23T20:00:00Z",
    },
    history: {
      prices: [
        {
          date: "2026-10-23T00:00:00Z",
          open: 100,
          high: 105,
          low: 95,
          close: ticker === "NVDA" ? 100 : 200,
          volume: 1000,
        },
      ],
      source: "Yahoo test fixture",
      interval: "1d",
      period: "1y",
      fetched_at: status.fetched_at,
    },
    technical: { ...category, series: [], regime: "Trending" },
    fundamentals: { ...category, metrics: {}, periods: [] },
    valuation: { ...category, metrics: {}, scenarios: {} },
    news: { ...category, articles: [] },
    macro: { ...category, outlook: "Insufficient Data", upcoming_events: [] },
    score: {
      overall: 6,
      company_quality: 6,
      confidence: 0.8,
      categories: [],
      limitations: [],
    },
    trade_plan: {
      recommendation: "Wait",
      status: `${ticker} conditional plan`,
      entry_zone: null,
      targets: [],
      calculation: [],
      event_warnings: [],
    },
    report: { markdown: `# ${ticker} current report` },
    data_quality: {
      mode: "live provider",
      limitations: [],
      sections: Object.fromEntries(
        [
          "history",
          "company_info",
          "statements",
          "news",
          "analyst",
          "earnings",
        ].map((key) => [key, status]),
      ),
    },
  };
}
let delayResearch = false;
function mount(initial = "NVDA") {
  window.history.replaceState(null, "", `/?ticker=${initial}`);
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 60000 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  delayResearch = false;
  get.mockReset();
  send.mockReset();
  get.mockImplementation(async (path) => {
    if (path === "/watchlist") return { items: [] };
    const match = path.match(
      /^\/stocks\/([^/]+)\/(research|history|technical|overview)/,
    );
    if (match) {
      const data = dataset(decodeURIComponent(match[1]));
      if (match[2] === "research") {
        if (delayResearch) return new Promise(() => {});
        return data;
      }
      if (match[2] === "overview")
        return {
          ...data.overview,
          source_metadata: data.data_quality.sections,
        };
      return data[match[2] as "history" | "technical"];
    }
    throw new Error(`Unexpected test route ${path}`);
  });
  send.mockResolvedValue({});
});
describe("ticker-bound dashboard requests", () => {
  it("opens the technology screener from the sidebar and drills into existing stock research", async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (path, options) => {
      if (path.includes("/screener/tech/rankings"))
        return {
          horizon: "short_term",
          rankings: [
            {
              ticker: "ORCL",
              name: "Oracle screener fixture",
              rank: 1,
              overall_score: 7,
              analysis_stage: "broad",
              recommendation: "Wait",
            },
          ],
        };
      if (path.includes("/screener/tech/status"))
        return { horizon: "short_term" };
      if (path.includes("/screener/tech/universe")) return {};
      return original(path, options);
    });
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    fireEvent.click(
      screen.getByRole("button", { name: "Tech Stock Screener" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open ORCL research" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Oracle test fixture" }),
    ).toBeVisible();
    expect(window.location.search).toContain("ticker=ORCL");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
  it("uses v2 scores, gates preliminary buys, and promotes a full-context plan across tabs", async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (path, options) => {
      const response = (await original(path, options)) as Bag;
      return path.includes("/research")
        ? {
            ...response,
            quant_core: {
              ticker: "NVDA",
              score_adapter: {
                overall: 9.3,
                company_quality: 8.7,
                confidence: 0.8,
                categories: [],
              },
              recommendation: {
                recommendation: "Buy candidate",
                status: "PRELIMINARY PLAN",
                position_size: 20,
              },
            },
          }
        : response;
    });
    let resolve!: (value: unknown) => void;
    send.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    expect(screen.getByText("9.3")).toBeVisible();
    expect(screen.queryByText("Buy candidate")).not.toBeInTheDocument();
    expect(screen.getByText("0 shares")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Quantitative research" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        "/stocks/NVDA/quantitative",
        expect.objectContaining({
          capital: 10000,
          risk_per_trade: 0.01,
          horizon: "swing",
        }),
        expect.any(Object),
      ),
    );
    await act(async () => {
      resolve({
        ticker: "NVDA",
        as_of: "2026-10-26T00:00:00Z",
        methodology_version: "2.0",
        recommendation: {
          recommendation: "Buy candidate",
          status: "FULL CONTEXT NVDA PLAN",
          position_size: 4,
        },
        score_adapter: { overall: 7.4, company_quality: 8.7, categories: [] },
        report: { markdown: "# NVDA full quantitative report" },
        configuration: {
          horizon: "swing",
          capital: 10000,
          benchmark_ticker: "SPY",
          min_samples: 30,
        },
      });
    });
    await screen.findByText("7.4");
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(await screen.findByText("FULL CONTEXT NVDA PLAN")).toBeVisible();
    expect(screen.getByText("4 shares")).toBeVisible();
    expect(screen.getByText("7.4")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Research report" }));
    expect(
      screen.getByRole("heading", { name: "NVDA full quantitative report" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(
        "/stocks/NVDA/quantitative/report",
        expect.objectContaining({
          capital: 10000,
          benchmark_ticker: "SPY",
          min_samples: 30,
        }),
      ),
    );
  });
  it("does not promote a late quantitative plan after a ticker switch", async () => {
    let resolve!: (value: unknown) => void;
    send.mockImplementation((path) =>
      path.includes("/NVDA/")
        ? new Promise((done) => {
            resolve = done;
          })
        : Promise.resolve({
            ticker: "MSFT",
            as_of: "2026-10-26T00:00:00Z",
            methodology_version: "2.0",
            recommendation: {
              recommendation: "Wait",
              status: "FULL CONTEXT MSFT PLAN",
            },
          }),
    );
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    fireEvent.click(screen.getByRole("tab", { name: "Quantitative research" }));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    fireEvent.click(screen.getByRole("button", { name: "MSFT" }));
    await screen.findByRole("heading", { name: "Microsoft test fixture" });
    await act(async () => {
      resolve({
        ticker: "NVDA",
        recommendation: {
          recommendation: "Buy candidate",
          status: "STALE ADVANCED NVDA",
        },
      });
    });
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(await screen.findByText("FULL CONTEXT MSFT PLAN")).toBeVisible();
    expect(screen.queryByText("STALE ADVANCED NVDA")).not.toBeInTheDocument();
    expect(window.location.search).toContain("ticker=MSFT");
  });
  it("labels cached prices while optional company requests are still pending", async () => {
    get.mockImplementation(async (path) => {
      if (path === "/watchlist") return { items: [] };
      const data = dataset("ORCL");
      if (path.includes("/research") || path.includes("/overview"))
        return new Promise(() => {});
      if (path.includes("/history"))
        return { ...data.history, from_cache: true };
      if (path.includes("/technical")) return data.technical;
      throw new Error(`Unexpected test route ${path}`);
    });
    mount("ORCL");
    await screen.findByTestId("price-chart");
    expect(
      screen.getByLabelText("Price history data status"),
    ).toHaveTextContent("Cached data");
    expect(
      screen.getByLabelText("Price history data status"),
    ).toHaveTextContent("Updated");
  });
  it("renders history and technical evidence before optional company research completes", async () => {
    delayResearch = true;
    mount("ORCL");
    expect(await screen.findByTestId("price-chart")).toHaveTextContent("200");
    expect(
      screen.getByLabelText("Technical analysis data status"),
    ).toHaveTextContent("Available");
    expect(
      screen.getByText(
        "Price history is available. Optional company research is still loading.",
      ),
    ).toBeInTheDocument();
  });
  it("keeps available charts when financial statements fail, and shows the section error", async () => {
    get.mockImplementation(async (path) => {
      if (path === "/watchlist") return { items: [] };
      const data = dataset("ORCL");
      data.data_quality.sections.statements = {
        status: "unavailable",
        fetched_at: "2026-10-26T00:00:00Z",
        cache_stale: false,
        error: {
          code: "MISSING_STATEMENTS",
          message: "Financial statements were not returned for ORCL.",
          retryable: false,
        },
      } as any;
      data.fundamentals = {
        score: null,
        confidence: 0,
        signals: [],
        limitations: [],
        metrics: {},
        periods: [],
      } as any;
      if (path.includes("/history")) return data.history;
      if (path.includes("/technical")) return data.technical;
      if (path.includes("/overview"))
        return {
          ...data.overview,
          source_metadata: data.data_quality.sections,
        };
      return data;
    });
    mount("ORCL");
    expect(
      await screen.findByRole("heading", { name: "Oracle test fixture" }),
    ).toBeVisible();
    expect(screen.getByTestId("price-chart")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Financials" }));
    expect(
      screen.getByLabelText("Financial statements data status"),
    ).toHaveTextContent("Financial statements were not returned for ORCL.");
    expect(
      screen.getByLabelText("Financial statements data status"),
    ).toHaveTextContent("Unavailable");
  });
  it("does not let an older company-name resolution override a newer shortcut selection", async () => {
    let resolve!: (value: unknown) => void;
    get.mockImplementation(async (path) => {
      if (path.startsWith("/search?"))
        return new Promise((done) => {
          resolve = done;
        });
      if (path === "/watchlist") return { items: [] };
      const symbol = path.match(/^\/stocks\/([^/]+)/)?.[1] || "NVDA";
      const data = dataset(symbol);
      if (path.includes("/overview"))
        return {
          ...data.overview,
          source_metadata: data.data_quality.sections,
        };
      if (path.includes("/history")) return data.history;
      if (path.includes("/technical")) return data.technical;
      return data;
    });
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "Oracle" },
    });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => expect(resolve).toBeTypeOf("function"));
    fireEvent.click(screen.getByRole("button", { name: "MSFT" }));
    await screen.findByRole("heading", { name: "Microsoft test fixture" });
    await act(async () => {
      resolve({
        query: "Oracle",
        results: [
          {
            symbol: "ORCL",
            name: "Oracle test fixture",
            exchange: "NYSE",
            asset_type: "EQUITY",
          },
        ],
      });
      await new Promise((done) => setTimeout(done, 10));
    });
    expect(
      screen.queryByRole("heading", { name: "Oracle test fixture" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Microsoft test fixture" }),
    ).toBeInTheDocument();
  });
  it("does not apply a late custom plan or report after switching to a different ticker", async () => {
    let resolve!: (value: unknown) => void;
    send.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    fireEvent.click(screen.getByRole("button", { name: "Customize analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "Update analysis" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        "/stocks/NVDA/trade-plan",
        expect.any(Object),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    fireEvent.click(screen.getByRole("button", { name: "MSFT" }));
    await screen.findByRole("heading", { name: "Microsoft test fixture" });
    await act(async () => {
      resolve({
        recommendation: "STALE NVDA PLAN",
        score: { overall: 10, company_quality: 10, categories: [] },
        report: { markdown: "# STALE NVDA REPORT" },
      });
      await new Promise((done) => setTimeout(done, 10));
    });
    expect(screen.queryByText("STALE NVDA PLAN")).not.toBeInTheDocument();
    expect(screen.getByText("MSFT conditional plan")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Research report" }));
    expect(
      screen.getByRole("heading", { name: "MSFT current report" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("STALE NVDA REPORT")).not.toBeInTheDocument();
    expect(window.location.search).toContain("ticker=MSFT");
  });
  it("rejects the first ticker’s old plan even after switching away and back", async () => {
    let resolve!: (value: unknown) => void;
    send.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    fireEvent.click(screen.getByRole("button", { name: "Customize analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "Update analysis" }));
    await waitFor(() => expect(send).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    fireEvent.click(screen.getByRole("button", { name: "MSFT" }));
    await screen.findByRole("heading", { name: "Microsoft test fixture" });
    fireEvent.click(screen.getByRole("button", { name: "NVDA" }));
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    await act(async () => {
      resolve({
        recommendation: "STALE FIRST NVDA PLAN",
        report: { markdown: "STALE REPORT" },
      });
      await new Promise((done) => setTimeout(done, 10));
    });
    expect(screen.queryByText("STALE FIRST NVDA PLAN")).not.toBeInTheDocument();
    expect(screen.getByText("NVDA conditional plan")).toBeInTheDocument();
  });
  it("clears DCF state when switching tickers and ignores the previous ticker’s late response", async () => {
    let resolve!: (value: unknown) => void;
    send.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    mount();
    await screen.findByRole("heading", { name: "NVIDIA test fixture" });
    fireEvent.click(screen.getByRole("tab", { name: "Valuation" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate scenarios" }),
    );
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith(
        "/stocks/NVDA/valuation",
        expect.any(Object),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "MSFT" }));
    await screen.findByRole("heading", { name: "Microsoft test fixture" });
    await act(async () => {
      resolve({
        score: 10,
        signals: ["STALE NVDA DCF"],
        scenarios: { base: { value_per_share: 99999 } },
      });
      await new Promise((done) => setTimeout(done, 10));
    });
    expect(screen.queryByText("STALE NVDA DCF")).not.toBeInTheDocument();
    expect(screen.queryByText("$99,999.00")).not.toBeInTheDocument();
  });
});
