import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StockSearch from "./StockSearch";
import { api, ApiError } from "./api";
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, api: vi.fn() };
});
const lookup = vi.mocked(api);
const result = (symbol = "ORCL", name = "Oracle Corporation") => ({
  query: name,
  results: [{ symbol, name, exchange: "NYSE", asset_type: "EQUITY" }],
  source: "Yahoo test fixture",
  fetched_at: "2026-10-26T00:00:00Z",
  cache_stale: false,
});
function mount() {
  const onSelect = vi.fn(),
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
  render(
    <QueryClientProvider client={client}>
      <StockSearch onSelect={onSelect} />
    </QueryClientProvider>,
  );
  return {
    onSelect,
    input: screen.getByRole("combobox"),
    form: screen.getByRole("search"),
  };
}
async function advance(ms = 305) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}
beforeEach(() => {
  vi.useFakeTimers();
  lookup.mockReset();
  lookup.mockResolvedValue(result());
});
describe("dynamic stock lookup", () => {
  it("debounces company names for 300ms and exposes company, exchange and asset type", async () => {
    const { input } = mount();
    fireEvent.change(input, { target: { value: "Oracle" } });
    await advance(299);
    expect(lookup).not.toHaveBeenCalled();
    await advance(6);
    expect(lookup).toHaveBeenCalledWith(
      "/search?q=Oracle",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      screen.getByRole("option", {
        name: /ORCL Oracle Corporation NYSE · EQUITY/,
      }),
    ).toBeVisible();
  });
  it("uses keyboard selection and Enter to analyze the resolved listing", async () => {
    const { input, form, onSelect } = mount();
    fireEvent.change(input, { target: { value: "Oracle" } });
    await advance();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant");
    fireEvent.submit(form);
    expect(onSelect).toHaveBeenCalledWith("ORCL");
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("aria-expanded", "false");
  });
  it("resolves an early Enter on Oracle instead of analyzing ORACLE", async () => {
    const { input, form, onSelect } = mount();
    fireEvent.change(input, { target: { value: "Oracle" } });
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(onSelect).toHaveBeenCalledWith("ORCL");
    expect(onSelect).not.toHaveBeenCalledWith("ORACLE");
  });
  it("resolves an uppercase company name from its retrieved name rather than treating it as a ticker", async () => {
    const { input, form, onSelect } = mount();
    fireEvent.change(input, { target: { value: "ORACLE" } });
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(onSelect).toHaveBeenCalledWith("ORCL");
  });
  it("selects the exact symbol before another matching listing", async () => {
    lookup.mockResolvedValue({
      ...result(),
      results: [
        {
          symbol: "ORCL.MX",
          name: "Oracle Mexico",
          exchange: "MEX",
          asset_type: "EQUITY",
        },
        ...result().results,
      ],
    });
    const { input, form, onSelect } = mount();
    fireEvent.change(input, { target: { value: "orcl" } });
    await advance();
    fireEvent.submit(form);
    expect(onSelect).toHaveBeenCalledWith("ORCL");
  });
  it.each([
    "AAPL",
    "MSFT",
    "NVDA",
    "ORCL",
    "TSLA",
    "AMD",
    "AMZN",
    "GOOGL",
    "META",
    "PLTR",
    "SOFI",
    "TSM",
    "JPM",
    "BRK-B",
    "0700.HK",
    "M&M.NS",
  ])(
    "allows the arbitrary valid symbol %s when lookup has no matching listing",
    async (symbol) => {
      lookup.mockResolvedValue({ ...result(), results: [] });
      const { input, form, onSelect } = mount();
      fireEvent.change(input, { target: { value: symbol } });
      await act(async () => {
        fireEvent.submit(form);
      });
      expect(onSelect).toHaveBeenCalledWith(symbol);
    },
  );
  it("analyzes an exact uppercase ticker rather than a different fuzzy listing", async () => {
    lookup.mockResolvedValue(result("ABCD", "Other company"));
    const { input, form, onSelect } = mount();
    fireEvent.change(input, { target: { value: "ABC" } });
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(onSelect).toHaveBeenCalledWith("ABC");
  });
  it("provides an empty-search and invalid-symbol message without analyzing either", async () => {
    lookup.mockResolvedValue({ ...result(), results: [] });
    const { input, form, onSelect } = mount();
    fireEvent.submit(form);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a ticker");
    fireEvent.change(input, { target: { value: "BAD/TICKER" } });
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("No matching listing");
    expect(onSelect).not.toHaveBeenCalled();
  });
  it("shows a loading state, preserves rate-limit errors and offers a retry", async () => {
    lookup.mockRejectedValueOnce(
      new ApiError(
        "Yahoo search is rate limited. Please wait.",
        "RATE_LIMITED",
        true,
        429,
      ),
    );
    const { input } = mount();
    fireEvent.change(input, { target: { value: "Tesla" } });
    expect(screen.getByRole("status")).toHaveTextContent("Searching listings");
    await advance();
    expect(screen.getByRole("alert")).toHaveTextContent("rate limited");
    lookup.mockResolvedValueOnce(result("TSLA", "Tesla, Inc."));
    fireEvent.click(screen.getByRole("button", { name: "Retry search" }));
    await advance(5);
    expect(screen.getByRole("option", { name: /TSLA Tesla/ })).toBeVisible();
  });
  it("does not offer automatic retry for a permanent lookup failure", async () => {
    lookup.mockRejectedValueOnce(
      new ApiError("Invalid search query.", "INVALID_QUERY", false, 422),
    );
    const { input } = mount();
    fireEvent.change(input, { target: { value: "?" } });
    await advance();
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid search query");
    expect(
      screen.queryByRole("button", { name: "Retry search" }),
    ).not.toBeInTheDocument();
  });
  it("ignores a late company-name resolution after the input changes", async () => {
    let resolve!: (value: unknown) => void;
    lookup.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const { input, form, onSelect } = mount();
    fireEvent.change(input, { target: { value: "Oracle" } });
    fireEvent.submit(form);
    fireEvent.change(input, { target: { value: "Tesla" } });
    await act(async () => {
      resolve(result());
    });
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveAttribute("aria-expanded", "false");
  });
  it("ignores malformed stored display fields without crashing search", () => {
    window.localStorage.setItem(
      "equitylens.recent-searches",
      JSON.stringify([
        { symbol: "ORCL", name: { invalid: true }, exchange: 42 },
        null,
        { symbol: "../BAD" },
      ]),
    );
    const { input } = mount();
    fireEvent.focus(input);
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option")).toHaveTextContent("ORCL");
  });
  it("offers recent searches, supports keyboard selection and bounds storage to eight symbols", async () => {
    window.localStorage.setItem(
      "equitylens.recent-searches",
      JSON.stringify(
        Array.from({ length: 10 }, (_, i) => ({
          symbol: `TEST${i}`,
          name: `Test fixture ${i}`,
          exchange: null,
          asset_type: null,
        })),
      ),
    );
    const { input, form, onSelect } = mount();
    fireEvent.focus(input);
    expect(screen.getAllByRole("option")).toHaveLength(8);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.submit(form);
    expect(onSelect).toHaveBeenCalledWith("TEST0");
    expect(
      JSON.parse(window.localStorage.getItem("equitylens.recent-searches")!),
    ).toHaveLength(8);
  });
});
