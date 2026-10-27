# Verification record

The latest GitHub publication checks are recorded in [the public release summary](RELEASE_VERIFICATION.md):403 backend passes with real PostgreSQL on Python3.13 and Linux3.11,98 frontend passes, successful production image builds and15 isolated container smoke checks. The sections below preserve the earlier implementation history and its then-current limits.

Verified locally on October 26, 2026, America/Los_Angeles, using Python 3.13.7, yfinance 1.7.0 and Node 25.6.1. The locked dependencies and CI target Python 3.11/3.13 and Node 22. Remote CI was not executed in this workspace.

## Public-repository scope

This document preserves engineering methods, test counts and observed pass/fail summaries. Actual downloaded Yahoo JSON, generated research reports, the raw startup diagnostic record and personal databases/logs are excluded from the public repository and retained locally. References shown as local artifact filenames require a deliberate verification run; they are not missing distributable fixtures. The scripts in `scripts/verify_*.py` and `scripts/generate_reports.py` document how to produce your own authorized personal research outputs. No actual Forex Factory export is included.

## Completed local checks

- Backend: **402 passed, 1 skipped** in the final screener/startup run (`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -o addopts= -q`). The earlier 187-test run measured **92% statement coverage**; coverage was not recomputed for this upgrade. The skipped check requires a real PostgreSQL URL; SQLite does not impersonate it.
- Frontend: **98 passed** in8files (`cd frontend && npm test`). Coverage includes existing research/search/report behavior plus screener horizon/configuration changes, no forced buys, filtering/sorting missing values, three-stock comparison, job publication, per-stock positions and explicit DCF assumptions.
- TypeScript/Vite production build: passed. Plotly is lazy loaded, but its chart bundle is still large (about 1.46 MB gzip); Vite reports a size warning.
- Python compilation and dependency consistency: passed (`compileall`, `pip check`).
- Docker Compose configuration: passed (`docker compose config --quiet`).
- Browser checks: actual NVDA research, financials, DCF scenarios, custom capital/risk plans and matching saved reports, watchlist persistence, calendar input rejection, backtest with SPY, desktop/mobile navigation; then company search Oracle→ORCL followed by Tesla→TSLA, URL updates, company replacement and ticker-specific levels.

The backend run emitted a Starlette TestClient/httpx deprecation warning and intermittent SQLite connection ResourceWarnings from test fixture teardown. They did not fail checks. Production app shutdown explicitly disposes the connection pool. Future dependency updates should revisit the test client compatibility warning.

## Actual external data checks

Initial AAPL/MSFT/NVDA verification (`LIVE_VERIFICATION.json`, retained locally) and their sample research reports (`reports/`, retained locally) preserve observed timestamps. The later fresh 14-ticker verification (`SEARCH_LIVE_VERIFICATION.json`, retained locally) used a new temporary database and yfinance cache, so existing example snapshots could not satisfy those requests.

All fourteen required tickers retrieved live: AAPL, MSFT, NVDA, ORCL, TSLA, AMD, AMZN, GOOGL, META, PLTR, SOFI, TSM, JPM and BRK-B. Each returned 1,255 daily bars and company/statement data, with the normalized selected ticker preserved in the score and trade plan. Financial-sector score abstentions remained explicit. Live name search (`SEARCH_NAME_VERIFICATION.json`, retained locally) verified ORCL, Oracle, Tesla and Taiwan Semiconductor; the latter resolved to TSM and other supplied listings. Syntax support for additional suffixes and ampersands is also mock-tested; it is not a claim that every possible Yahoo listing was live-verified.

The restricted-process ORCL failure was reproduced as a DNS/network failure. A normal-network local API request returned HTTP 200 and Oracle Corporation. Server logs subsequently showed successful company search, price, technical, overview and research endpoints for ORCL and TSLA. The environment must continue permitting backend outbound DNS/HTTPS; code cannot restore connectivity that the operating environment blocks.

Yahoo returned no usable company articles in the fourteen-ticker live run. News sentiment abstains; no news was invented. No real Forex Factory export was provided. JSON/CSV/XML/ICS parsing, timezone/DST handling, actual-versus-forecast math, canceled/delayed/revised releases and point-in-time exclusion are verified using clearly labeled test observations. No calendar scraping or access bypass is enabled.

## Unverified or intentionally absent

- Docker image builds and runtime PostgreSQL: the Docker daemon was not running. A PostgreSQL service test is supplied in CI and skips locally without `EQUITYLENS_TEST_POSTGRES_URL`.
- A live paid AI call: the optional Responses adapter is mock-tested. Keys were not supplied and no paid request was made.
- SEC EDGAR verification, reliable historical peer valuation data, point-in-time fundamentals/news/macro for backtests, event-price causality and full geographic revenue exposure are not implemented or claimed.
- Broad internet deployment: this is a personal local application. Multiuser authentication/isolation, TLS, migrations beyond the supplied widening SQL, monitoring and distributed scheduling/rate limits are required before remote multiuser operation.

These are observed verification boundaries, not guarantees about future data availability or investment performance. See [search diagnosis and changed files](SEARCH_RELIABILITY.md), [analysis methods](METHODOLOGY_ANALYSIS.md), [risk/scoring methods](METHODOLOGY_SCORING.md), and [calendar source terms](SOURCES_CALENDAR.md).

## Later QQQ/runtime regression

A subsequent empty Vite HTTP 500 was traced to no FastAPI listener on port 8000. The project environment was verified as Python 3.13.7/yfinance 1.7.0. After runtime/launcher/proxy and ETF applicability fixes, actual HTTP checks returned 200 for history/technical/overview/research for AAPL, NVDA, ORCL, QQQ and SPY. [Exact diagnosis and scope](QQQ_RUNTIME_FIX.md), HTTP evidence (`ETF_API_VERIFICATION.json`, retained locally). The updated suite has 215 backend passes (one PostgreSQL skip), 62 frontend passes and a successful build; the earlier 92% coverage measurement predates these new tests and was not recomputed in this pass.

## Quantitative methodology version2

Completed the audit, price/risk corrections, multi-feature regimes, completed multi-timeframe summaries, four shared strategies, cost-aware execution, chronological statistical validation, empirical-frequency abstention, scenario/relative valuation, separate scores and dashboard/report integration. Focused tests were run for the phase modules before integration; the final full suites passed as recorded above. A date-sensitive old calendar fixture was corrected to use a fixed publication timestamp after the verification crossed UTC midnight; the future-release guard itself was retained.

Actual HTTP evidence (`QUANT_LIVE_VERIFICATION.json`, retained locally) records successful research and full quantitative responses for MSFT, AAPL, NVDA, ORCL, QQQ and SPY. All five timeframe rows were available in this observed run. ETF corporate quality/valuation remained unavailable. Sparse historical cohorts returned Insufficient historical evidence and null probability estimates; the one observed NVDA breakout trade is descriptive, not a success-rate forecast. No artificial observations were added to meet the30-sample requirement.

Native1h/15m request policy, interval TTL/cache reuse, vendor valuation-date normalization, current-column exclusion, stale fallback and no extra ETF corporate calls have26 additional offline provider tests. Signal and outcome availability, independent target2 timestamps, conservative stop-first execution, share caps, Wilson references, cohort deduplication, holdout purging and past-only diagnostics are tested. Future-dated or out-of-range Yahoo quote timestamps fall back to history; five minutes is the explicit tolerated clock skew.

Browser verification used separate NVDA and QQQ QA tabs: regime/benchmark, five timeframes, four strategies, finite score/validation tables, sample abstention, Wait/zero shares and ETF control exclusions. A QQQ full quantitative report was saved through `/quantitative/report`, then reopened from the report library. Full reports use the same completed technical assessment and valuation basis as the full dashboard. The main API was restarted with the final code; Vite remains available on5173 and FastAPI on8000.

Final compileall, dependency consistency and Docker Compose configuration checks passed. No packages were installed globally. Remote CI, Docker image runtime, PostgreSQL and paid model access remain outside this local verification. Plotly's existing large-bundle warning and the TestClient/httpx deprecation warning remain.

The current five-year full-review window and non-overlapping maximum-holding embargo can make30 comparable held-out outcomes impossible for longer horizons. The engine abstains; the backtest API can separately evaluate maximum available price history. Current vendor history is not a point-in-time publication archive. Fundamental-value historical validation and unavailable historical macro/news/live-context filters are explicitly excluded. Imported Forex Factory span does not certify completeness, so final entry recommendations remain Wait pending calendar review. Predictive accuracy and profitability are not established by these implementation checks.

The current [audit, strategy/scoring formulas and changed areas](QUANT_AUDIT.md), [regime methods](REGIME_METHODS.md), [statistical methods](STATISTICAL_VALIDATION.md) and MSFT example report (`reports/MSFT_quantitative.md`, retained locally) document the exact behavior.

## Tech screener and recurring startup failure

The recurring access screenshot was reproduced with the frontend listening on5173 and no backend listener on8000. Previous API launches belonged to transient tool/terminal sessions without an OS supervisor. No application traceback proves the exact earlier termination signal. A direct Desktop-based LaunchAgent was then tested and rejected by macOS folder privacy. The final service deploys actual application/dependency copies to private Application Support, migrates SQLite transactionally, preserves settings/data across updates, and runs both app processes under a user LaunchAgent. No global dependencies or privacy-setting changes were used.

Actual recovery evidence (`STARTUP_LIVE_VERIFICATION.json`, retained locally) records a controlled stop of the verified backend, replacement backend/frontend process IDs in2.5seconds, and NVDA researchHTTP200 afterward. Both supervisor children run from the private runtime; the supervisor's parent is macOS launchd. Final service status confirms ready=true for both services after the final code deployment. [Operational instructions](STARTUP.md) include source/runtime distinction and removal/data-preservation behavior.

The new screener's final actual HTTP record (`SCREENER_LIVE_VERIFICATION.json`, retained locally) contains428 dynamically discovered equity listings across4source pages,15complete deep reviews and14ranked observations for each independent horizon, with no provider errors. All requested representative research endpoints passed: AAPL,MSFT,NVDA,AMD,META,GOOGL,AMZN,ORCL,CRM,PLTR,INTC,MU,AVGO,ADBE,CRWD. Missing news/metrics remained visible; no qualified current buy was manufactured. The broad source set is not an authoritative sector census, and broad-only stocks remain unranked.

Browser checks verified job progress and automatic publication, distinct short/long leaders and weights, three actual stock comparisons, clearing comparisons on horizon change, and TSM drilldown into the existing research page. The existing chart/design/navigation remain. The final portfolio endpoint correctly returned Insufficient historical evidence because archived publications have no subsequent historical sessions yet. Synthetic hand calculations separately verify published top5/top10 equal weighting, self-financing costs/rebalancing, publication timing, missing/delisted members, source-timezone completion, benchmark currency and chronological evaluation.

Startup has19focused tests; screener scoring/scenarios/eligibility has28; discovery/portfolio replay has41. Full backend402passed/1PostgreSQLskip and frontend98passed are recorded above. Production build, compileall, dependency consistency and Compose configuration passed. The existing Plotly bundle-size and TestClient deprecation warnings remain. Docker runtime, real PostgreSQL, remote GitHub Actions and predictive investment performance were not established by these checks.

Changed areas: `backend/app/screener/` (typed API, scores, scenarios, worker), `providers/universe.py`, `analysis/screener_backtest.py`, `main.py`, `storage.py`, `config.py`, and compact completed technical evidence in `analysis/quantitative.py`; frontend `TechScreener.tsx`, its types/tests, `App.tsx` and styles; launcher `scripts/service.py`, `scripts/dev.sh`, `EquityLens.command`; verification scripts, tests and documentation. See [the complete screener methods](TECH_SCREENER.md).
