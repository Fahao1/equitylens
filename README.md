# EquityLens

[![Validation](https://github.com/Fahao1/equitylens/actions/workflows/ci.yml/badge.svg)](https://github.com/Fahao1/equitylens/actions/workflows/ci.yml)

A local-first personal stock research platform with explicit evidence, financial mathematics, conditional risk plans, and a responsive research dashboard. It uses FastAPI/Python, React/TypeScript/Vite, Tailwind, Plotly, TanStack Query and SQLAlchemy. SQLite is the local default; Docker Compose uses PostgreSQL.

**Research and decision support. No brokerage orders. No guaranteed returns.** Live requests never silently substitute sample data.

## Public source and local research data

The public repository contains application source, documentation and synthetic test fixtures. Retrieved Yahoo Finance JSON, generated research reports, personal databases, settings, cookie caches and machine logs remain local and are excluded from Git. Run the verification/report scripts for your own authorized personal research; local artifact filenames in the documentation are not bundled datasets. See [verification methods and observed engineering results](docs/VERIFICATION.md).

## Start locally

On macOS, install the project-local dependencies below, then run `.venv/bin/python scripts/service.py install --open` for supervised startup. Once installed, open [EquityLens](http://127.0.0.1:5173), or double-click **EquityLens.command**. The user service survives terminal/chat closure, starts at login and restarts its own failed services. [Startup instructions and data ownership](docs/STARTUP.md) explain the Application Support runtime and preserved data/settings. After source changes, run `.venv/bin/python scripts/service.py install` to update that runtime.

`./scripts/dev.sh` is the foreground development option. Stop an installed persistent service before using the same ports for development.

Python 3.13 is recommended (application supports 3.11+), Node 22+ and npm are required. Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.lock
cp .env.example .env
npm --prefix frontend ci
./scripts/dev.sh
```

Open http://127.0.0.1:5173. API docs: http://127.0.0.1:8000/docs. Stop both services with Ctrl+C. No Python editable installation is necessary; the launcher provides the application path. If you prefer separate terminals:

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```bash
npm --prefix frontend run dev -- --port 5173
```

For an explicitly fictional offline preview, set `EQUITYLENS_DEMO=true` in `.env`, then restart the backend. Every demo company/price is synthetic and labeled. Demo mode creates no news, earnings calendar, analyst targets or economic announcements.

## Docker / PostgreSQL

```bash
cp .env.example .env
# Change POSTGRES_PASSWORD in .env before any nonlocal use.
docker compose up --build
```

Open http://127.0.0.1:8080; API docs remain on localhost:8000. Named volumes preserve PostgreSQL and provider caches. `docker compose down` preserves data; removing volumes deletes it. Local SQLite files and API keys are ignored by version control and never copied into container images. Compose binds ports to loopback.

Both production Docker images were built and the isolated PostgreSQL/backend/nginx stack passed15 smoke checks. Backend tests passed on Python3.11 and3.13 with real PostgreSQL; the frontend production build also passed. CI repeats the Python matrix, PostgreSQL check and Node22 frontend validation. See the [public release verification](docs/RELEASE_VERIFICATION.md) for commands and observed limits.

## Research workflow

1. Search any supported Yahoo Finance ticker or company name. Autocomplete shows symbol, company, exchange and asset type; use arrow keys/Enter to select. AAPL, MSFT and NVDA are shortcuts, not a whitelist. Exchange suffixes, hyphens, ampersands, indices and lowercase ticker input are supported. Choose3months/6months/1year/5years/max and your investment horizon.
2. Examine the source, currency, quote timestamp and data limitations. Quotes are delayed/last reported rather than a real-time trading feed. Daily timestamps identify sessions. Market closure weekends are not filled with imaginary bars.
3. Review separate business-quality and price-attractiveness ratings, category contributions, confidence, charts, financial statements, valuation, source-linked news and macro hypotheses.
4. Edit six scoring weights, allocated capital, risk tolerance, maximum risk, minimum reward/risk, existing shares and cost basis. Apply assumptions to recompute the plan and report. Save a dated report or export it as Markdown.
5. Import an authorized Forex Factory file for upcoming-event risk. Missing calendar coverage or actuals remain missing. No favorable technical setup means no new suggested shares.
6. Open **Quantitative research** for the six-state regime, weekly/daily/4h/1h/15m context, four independent strategies, cost-aware levels, holdout/walk-forward/sensitivity results and empirical probability evidence. This explicit request retrieves intraday data and validates the shared rules; ordinary chart requests remain lightweight. Strategy lab preserves the original SMA crossover experiment. Historical performance is separate from future expectations.

### Tech Stock Screener

The **Tech Stock Screener** sidebar page discovers a dynamic source-covered technology/internet-platform universe, screens broad metadata, then deeply analyzes a disclosed subset with one bounded background worker. It has independent Short-Term and Long-Term scoring, editable weights, industry/listing/financial/risk filters, Top10 sorting, a highest-ranked stock separate from the eligible buy candidate, conditional scenarios, three-stock comparison, evidence/source details and existing research links. No qualified current setup displays **No qualified buy candidate found**.

The observed live run discovered428 equity listings, fully analyzed15 and ranked14 in each horizon. All15 requested representative tickers passed actual research API checks. Coverage is explicitly not a complete technology-sector census. Portfolio replay uses archived publication-time rankings; today's data never creates an imaginary historical top10. [Methods and API contracts](docs/TECH_SCREENER.md), [source rights/coverage](docs/SCREENER_UNIVERSE.md), [published-ranking replay](docs/SCREENER_BACKTEST.md), actual HTTP evidence (`docs/SCREENER_LIVE_VERIFICATION.json`, retained locally).

```bash
.venv/bin/python scripts/verify_screener.py --refresh
```

That command intentionally contacts the running live provider-backed service and is separate from offline CI. A manual screen schedules six-hour refreshes by default while background jobs are enabled; configuration and operational limits are documented in the methods guide.

### Quantitative methodology version2

Main ratings and conditional plans now use separate company-quality, valuation, technical, setup and macro components, with horizon-adjusted editable weights. Source confidence, freshness, model uncertainty and historical sample reliability are displayed separately. Explicit DCF/multiple/FCF-yield assumptions, user-selected comparable peers and available dated historical multiples support valuation; missing valuation evidence earns no points. The full review's report can be saved with the same settings and evidence.

Strategies abstain without required confirmations or adequate net reward/risk. Empirical frequencies require at least30 comparable mature observations and show intervals; sparse samples display **Insufficient historical evidence**. Imported calendar span cannot prove completeness, so final new-entry recommendations remain Wait pending calendar review. No accuracy or profitability improvement is assumed from adding models. Read the [initial audit, exact strategy/scoring rules and limits](docs/QUANT_AUDIT.md), [regime/timeframe methods](docs/REGIME_METHODS.md) and [statistical validation methods](docs/STATISTICAL_VALIDATION.md).

Endpoints: `GET/POST /api/stocks/{ticker}/quantitative`, `POST /api/stocks/{ticker}/quantitative/report`; `POST /api/backtest` accepts `strategy` = `all`, `trend_following`, `breakout`, `mean_reversion`, `fundamental_value` or the original default `sma`.

To deliberately verify actual stock/ETF requests against a running backend:

```bash
.venv/bin/python scripts/verify_quantitative.py
```

The live verification record (`docs/QUANT_LIVE_VERIFICATION.json`, retained locally) and MSFT research example (`docs/reports/MSFT_quantitative.md`, retained locally) contain retrieved evidence, timestamps and explicit abstentions.

### Forex Factory calendar: required compliant import pathway

The official calendar offers weekly JSON, CSV, XML and ICS exports. Export availability is not a documented unrestricted API license. Forex Factory's notices restrict copying/redistribution and methods of access. This application deliberately performs **no automated Forex Factory fetching or scraping**. Obtain authorization for your intended use, download an export through the provided interface, and import it on the Economic calendar page. Do not redistribute its contents with this repository.

Example API import (your authorized file):

```bash
python3 - <<'PY'
import json, pathlib, urllib.request
payload = json.dumps({
    'content': pathlib.Path('ff_calendar_thisweek.json').read_text(),
    'format': 'json',
    'source_timezone': 'America/New_York',
    'replace_existing': False
}).encode()
request = urllib.request.Request('http://127.0.0.1:8000/api/economic-calendar/import', data=payload, headers={'Content-Type':'application/json'})
print(urllib.request.urlopen(request).read().decode())
PY
```

JSON/CSV/XML/ICS fields are validated, original numeric strings preserved, percentages/K/M/B normalized, duplicates merged, and times stored UTC. Ambiguous/nonexistent daylight-saving times require an explicit offset. Unknown/all-day time remains unknown. Actual/revised values are only present when the input provides them. `replace_existing=true` replaces the imported calendar snapshot, useful when weekly files lack stable IDs and schedules change; keep the original file for reimport. Older revisions do not overwrite newer stored data.

References: [official calendar and export links](https://www.forexfactory.com/calendar), [official notices](https://www.forexfactory.com/notices). See [source investigation](docs/SOURCES_CALENDAR.md).

## Implemented capabilities

- Yahoo history, daily/weekly OHLC, adjusted close, volume, actions, company metadata, annual/quarterly statements, earnings history/calendar/estimates, analyst targets and available news, with persistent caches, per-key locks, bounded retries and partial-data handling.
- Trend/momentum/volatility/volume families: SMA/EMA, MACD, ADX, Ichimoku, SAR, RSI/stochastics/ROC/CCI/Williams%R, Bollinger/ATR/historicalvol/Keltner/Donchian, OBV/MFI/CMF/relativevolume, pivots, breakouts/crossovers,52week ranges and Fibonacci. Daily VWAP is correctly unavailable rather than inferred from daily bars.
- Date-matched financial ratios and growth, statement histories, negative-earnings/zero-denominator safeguards, freshness and banks/insurers/REIT abstention; valuation multiples and disclosed yield hurdles; explicit optional DCF with conservative/base/optimistic scenarios.
- News deduplication and bounded, recency-weighted headline/summary sentiment; linked bullish/bearish evidence and company events. Optional model-supported synthesis never changes scores or price levels.
- Macro surprise and comparable-history normalization, sector exposure hypotheses, upcoming-event warnings, windows of 24h/3 days/7 days/30 days within imported coverage.
- Editable scoring, distinct quality/attractiveness, conditional support/ATR/resistance levels and position sizes, no-favorable-setup abstention.
- Price-only backtesting, next-open signals, gap-aware stops, slippage/commissions, equity curves, buy-and-hold/index comparisons, return/drawdown/Sharpe/profitfactor and chronological validation. Current fundamentals/news/revised macro are excluded.
- Watchlist, saved dated research reports, calendar import, chart toggles and responsive layouts.

## API

All endpoints are under `/api`; interactive typed schemas are at `/docs`.

- `GET /search?q=Oracle` (cached company/ticker discovery)
- `GET /stocks/{ticker}/research`, `/overview`, `/history`, `/technical`, `/fundamentals`, `/valuation`, `/news`, `/macro-impact`, `/score`
- `POST /stocks/{ticker}/trade-plan`, `/valuation` (explicit DCF assumptions), `/reports`
- `GET /economic-calendar`, `/economic-calendar/upcoming`, `/economic-calendar/high-impact`
- `POST /economic-calendar/import`
- `GET /watchlist`, `POST /watchlist`, `DELETE /watchlist/{ticker}`
- `GET /reports`, `POST /backtest`

Errors preserve explicit invalid input, provider outage/rate limit and unavailable-data messages. Provider snapshots cache 30 minutes (history) and 6 hours (company data); unchanged analyses are reused. Optional company resources have independent caches and section-level status/freshness. Price/history and technical endpoints do not wait for financial statements, news or analyst endpoints. Transient network/timeouts receive at most two attempts with exponential backoff and jitter; rate limits/access denials/permanent missing data are not immediately retried. A background task refreshes up to 20 watchlist tickers hourly by reading those caches. Use one API worker to avoid duplicate scheduled jobs; a distributed job coordinator is required before horizontal scaling.

## Tests and validation

The public release passed403 backend tests on both supported Python CI versions and98 frontend tests. The [release verification summary](docs/RELEASE_VERIFICATION.md) includes container and live-check boundaries. Generated Yahoo data, reports, machine diagnostics, credentials and personal databases remain local and are ignored by Git.

```bash
cd backend
../.venv/bin/python -m pytest
cd ../frontend
npm test
npm run build
```

Tests run offline with explicit synthetic observations. They cover indicator reference calculations, flat/short/split/zero-volume history, financial ratios/missing/negative/mismatched/stale statements, DCF, scoring, position sizing/rounding, source shapes, cache outages, API validation/rate limits, persistence timezones, DST, canceled/delayed/revised/unreleased economic events, normalized surprises and future-information exclusion. PostgreSQL test skips unless `EQUITYLENS_TEST_POSTGRES_URL` is provided.

Intentional live verification is separate from CI:

```bash
.venv/bin/python scripts/verify_live.py
.venv/bin/python scripts/generate_reports.py
```

Actual Yahoo retrieval succeeded for AAPL/MSFT/NVDA on Oct 25, 2026 Los Angeles time. Verification evidence (`docs/LIVE_VERIFICATION.json`, retained locally) includes UTC timestamps, latest bars and available statement counts. Sample research reports (`docs/reports/`, retained locally) were generated from those retrieved snapshots. No Yahoo company articles were returned during that run, so news sentiment abstained. No real Forex Factory calendar is bundled or implied. Source observations and availability can change after this snapshot.

## Optional AI summaries

Default reports use deterministic evidence synthesis. An optional server-side model can explain supplied news only when configured. Set `EQUITYLENS_LLM_API_KEY`, `EQUITYLENS_LLM_MODEL` and optionally the Responses-compatible `EQUITYLENS_LLM_BASE_URL`; saved-report creation invokes it, while routine chart requests do not. Model responses require source IDs and exact supporting excerpts; unknown references, refusals or failed responses fall back to the deterministic report. The application does not fetch full article text or accept model-generated prices/scores. See [LLM notes](docs/LLM.md). Model access is mock-tested; no real paid model call was made during delivery.

## Documentation and operating limits

- [Architecture and file interfaces](docs/ARCHITECTURE.md)
- [Analysis formulas and reference thresholds](docs/METHODOLOGY_ANALYSIS.md)
- [Scoring, position-size math and conditional thresholds](docs/METHODOLOGY_SCORING.md)
- [Calendar ingestion, surprise and backtest methods](docs/SOURCES_CALENDAR.md)
- [Dynamic search diagnosis and fresh 14-ticker verification](docs/SEARCH_RELIABILITY.md)
- [Verification and release limits](docs/VERIFICATION.md)

Yahoo/yfinance is intended for personal research; Yahoo fields are not guaranteed complete or stable. Respect [yfinance's data-use notice](https://ranaroussi.github.io/yfinance/) and the linked Yahoo terms. Historical peer multiples, verified point-in-time financial/news calendars, SEC EDGAR verification, observed event causality and full geographic revenue exposure are not supplied by this release. DCF is assumption-sensitive; yield scores are generic reference hurdles rather than a claim of undervaluation against peers. No specialized bank/insurance/REIT score is manufactured.

This is a single-user local application. Before exposing it remotely, add authenticated user isolation, TLS, operational monitoring, backups, database migrations and a distributed job/rate-limit coordinator. The optional backend bearer token protects API calls but is not a multiuser login system; use an authenticated reverse proxy to protect browser access. Never put AI keys in frontend variables. Uploaded calendar text is parsed as data, never executed; imports are size-bounded, source URLs restricted to HTTP(S), XML entities rejected and browser text escaped.

## Search connectivity troubleshooting

A working cached stock does not prove current internet connectivity. The original ORCL failure was reproduced as a Yahoo DNS failure in a restricted backend process; the three shortcut stocks had cached snapshots. Running the backend with normal outbound DNS/HTTPS access fixed actual retrieval. Run `./scripts/dev.sh` from your normal terminal, or grant the backend appropriate network access in a managed environment. Do not disable access controls or attempt anti-bot bypasses. Distinct error codes identify invalid syntax, confirmed unknown symbols, missing history, network failure, timeout, rate limit and provider response errors. The frontend can keep dated cached evidence and price/technical sections visible when optional retrieval fails.

Fresh isolated-cache checks retrieved all fourteen requested tickers; `scripts/verify_tickers.py` and `scripts/verify_search.py` deliberately perform separate live verification. Company-name lookups for Oracle, Tesla and Taiwan Semiconductor returned ORCL, TSLA and TSM (plus other listings) in the recorded run. See the JSON evidence in `docs/SEARCH_LIVE_VERIFICATION.json` and `docs/SEARCH_NAME_VERIFICATION.json`.

If Yahoo access cannot be restored or your use requires licensed guaranteed coverage, an alternative adapter can target [Alpha Vantage's documented daily-price, quote and symbol-search APIs](https://www.alphavantage.co/documentation/). Obtain its API key and a license/plan covering your intended use and requested fields. This release does not silently switch providers or claim that the alternative is configured.

## QQQ/ETF HTTP 500 diagnosis

The later QQQ failure was a stopped backend: Vite was running, but port 8000 refused connections. Its default proxy returned an empty HTTP 500 before Python or Yahoo was called. The project backend uses `.venv/bin/python` (Python 3.13.7, yfinance 1.7.0), separate from Conda base. Startup now logs the actual runtime, saves complete logs in `data/logs/backend.log`, waits for health and supervises both services. Proxy connection failures return a clear retryable 502 while genuine backend 500s remain unchanged.

Funds identified by Yahoo `quoteType` skip corporate statements, earnings/calendar and analyst targets. Corporate company-quality/DCF scoring is Not Applicable for ETFs; price history, technical indicators and available portfolio P/E/NAV/assets remain accessible. This does not claim a dedicated fund quality or fair-value model.

The final check returned HTTP 200 for all four main endpoints for AAPL, NVDA, ORCL, QQQ and SPY. See [the exact diagnosis, environment, changed files and tests](docs/QQQ_RUNTIME_FIX.md) and actual HTTP evidence (`docs/ETF_API_VERIFICATION.json`, retained locally). Re-run it with `.venv/bin/python scripts/verify_api.py`.
