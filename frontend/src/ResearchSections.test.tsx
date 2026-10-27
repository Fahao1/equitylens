import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { Financials, Valuation } from "./ResearchSections";
describe("fund research applicability", () => {
  it("keeps source fund metrics and explanations but does not offer corporate DCF", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <Financials
          data={{
            applicable: false,
            score: null,
            metrics: {},
            periods: [],
            signals: [
              "Corporate financial health scoring does not apply to this fund.",
            ],
            limitations: [],
          }}
          status={{ status: "not_applicable" }}
        />
        <Valuation
          ticker="QQQ"
          symbol="$"
          data={{
            applicable: false,
            score: null,
            metrics: { portfolio_pe: 26.5 },
            signals: [
              "Fund valuation uses portfolio disclosures rather than corporate free cash flow.",
            ],
            limitations: [],
          }}
        />
      </QueryClientProvider>,
    );
    expect(
      screen.getByLabelText("Financial statements data status"),
    ).toHaveTextContent("Not applicable");
    expect(
      screen.getByRole("heading", {
        name: "Financial statements not applicable",
      }),
    ).toBeVisible();
    expect(screen.getByText("26.50")).toBeVisible();
    expect(
      screen.getByText(
        "Fund valuation uses portfolio disclosures rather than corporate free cash flow.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Calculate scenarios" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Discounted cash flow scenarios" }),
    ).not.toBeInTheDocument();
  });
});
