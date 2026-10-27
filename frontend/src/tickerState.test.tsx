import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  normalizeTicker,
  tickerFromLocation,
  useTickerLocation,
} from "./tickerState";
function LocationFixture() {
  const [ticker, select] = useTickerLocation();
  return (
    <>
      <span data-testid="ticker">{ticker}</span>
      <button onClick={() => select("brk-b")}>Select Berkshire</button>
    </>
  );
}
describe("ticker URL state", () => {
  it.each([
    [" orcl ", "ORCL"],
    ["brk-b", "BRK-B"],
    ["0700.hk", "0700.HK"],
    ["m&m.ns", "M&M.NS"],
    ["^gspc", "^GSPC"],
    ["eurusd=x", "EURUSD=X"],
  ])("normalizes valid Yahoo symbol %s", (value, expected) =>
    expect(normalizeTicker(value)).toBe(expected),
  );
  it.each([
    "",
    "M\\M.NS",
    "Oracle Corporation",
    "../AAPL",
    "<script>",
    "A".repeat(33),
  ])("rejects an unsafe or malformed symbol %s", (value) =>
    expect(normalizeTicker(value)).toBeNull(),
  );
  it("normalizes the initial URL, preserves unrelated parameters and reacts to browser history", () => {
    window.history.replaceState(null, "", "/?ticker=orcl&view=research");
    expect(tickerFromLocation()).toBe("ORCL");
    render(<LocationFixture />);
    expect(window.location.search).toContain("ticker=ORCL");
    fireEvent.click(screen.getByRole("button", { name: "Select Berkshire" }));
    expect(screen.getByTestId("ticker")).toHaveTextContent("BRK-B");
    expect(window.location.search).toContain("view=research");
    act(() => {
      window.history.replaceState(null, "", "/?ticker=tsla");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(screen.getByTestId("ticker")).toHaveTextContent("TSLA");
  });
});
