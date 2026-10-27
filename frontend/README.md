# EquityLens dashboard

React + TypeScript + Vite, Tailwind CSS, TanStack Query and Plotly. All displayed market observations come from the backend response; missing data stays unavailable. Synthetic previews are prominently labeled when the backend explicitly enables demo mode.

## Run

Start the FastAPI service on port 8000 using the repository README, then:

```sh
npm ci
npm run dev
```

Open the printed local URL. The development server forwards `/api` to `http://127.0.0.1:8000`. Set `VITE_API_PROXY` to use a different development backend. `VITE_API_URL` optionally sets an absolute browser-facing API origin at build time; configure backend CORS accordingly. Never put provider or AI secrets in `VITE_*` variables.

```sh
npm run test
npm run build
npm run preview
```

Production output is `dist/`; the repository Docker configuration serves it with an API reverse proxy. The standalone Vite preview server serves static output and needs `VITE_API_URL` configured for API access.

## Source layout

- `App.tsx`: workspace navigation, independently loaded price/overview/technical stages, conditional plan settings and score weights.
- `StockSearch.tsx`, `tickerState.ts`: Yahoo company-name autocomplete, keyboard selection, recent searches and validated ticker URL/history state.
- `DataStatus.tsx`: per-section loading, unavailable/error, cached-data and source freshness states.
- `useRequestScope.ts`: ticker/generation guards for asynchronous plan and valuation results.
- `ResearchSections.tsx`: financials, valuation/DCF, linked news/earnings and stock-specific macro outlook.
- `CalendarPage.tsx`: authorized export import, replacement option, timezones, date/impact/country filters and countdowns.
- `ReportsPage.tsx`: persistent research library and Markdown export.
- `BacktestPage.tsx`: execution assumptions, historical metrics, equity curves, holdout/walk-forward results and trade ledger.
- `Chart.tsx`: lazily loaded Plotly candlesticks, volume, technical overlays and equity curves.
- `ui.tsx`, `types.ts`, `api.ts`: shared display helpers, primary response interfaces and bounded API requests.

## Verification

`npm run test` runs offline Vitest/Testing Library checks for 300ms debouncing, company-name resolution, exact symbol submission, keyboard/recent selection, structured failures, cancellation, URL/back state, staged chart loading, optional statement failures and stale mutation responses during rapid ticker switching. Fixtures are explicitly synthetic test data.

Production TypeScript/Vite builds pass. Browser checks with actual Yahoo observations verified NVDA price/financials, DCF scenarios, configurable capital risk, matching customized research report assumptions, saved reports/watchlists, invalid calendar rejection and historical backtest results against SPY. Desktop and 390px mobile research/calendar layouts and navigation were visually inspected.

No authorized real calendar export was supplied, so browser QA did not import invented announcements into the live database; parser fixtures and integration tests are maintained in the backend test suite. Plotly is a large dependency (about 1.46 MB compressed) and loads separately when a chart is first needed.

The stock-search fix was also checked in the live browser on 2026-10-26: entering `Oracle` returned the ORCL listing with company name, exchange and asset type; Arrow Down + Enter selected it. Entering `Tesla` then selected TSLA, updated the URL to `?ticker=TSLA`, replaced the company heading and conditional price levels, and removed the Oracle heading. Automated tests separately exercise unsupported/malformed symbols, provider failures and rapid-switch races using mocks; mocked ticker acceptance is not a claim of a successful live quote.
