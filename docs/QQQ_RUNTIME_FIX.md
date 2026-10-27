# QQQ HTTP 500: runtime diagnosis and implemented fix

Verified October 26, 2026, America/Los_Angeles. The existing application and design were retained.

## Exact cause of this failure

At diagnosis, Vite was running on port 5173, but there was no FastAPI process or listener on port 8000. The actual browser proxy request `/api/stocks/QQQ/research` returned **HTTP 500**, `Content-Type: text/plain`, and an empty body. Direct requests to `http://127.0.0.1:8000/api/stocks/QQQ/{history,technical,overview,research}` all failed to connect with `[Errno 61] Connection refused`.

The captured Vite traceback (`QQQ_PROXY_FAILURE.txt`, retained locally) identified `connect ECONNREFUSED 127.0.0.1:8000`. The failing operation was the development proxy's TCP connection to the missing backend. The request did not reach a FastAPI route, Yahoo retrieval, financial processing, or JSON serialization.

**There is no Python traceback for this original HTTP 500.** It would be incorrect to invent one: no Python backend was running to throw an exception. The browser's 500 was Vite's default proxy error response. After starting the existing backend, all four QQQ endpoints returned HTTP 200 **before** the ETF-specific code changes. This confirms the primary failure was service availability, rather than missing yfinance or an ETF processing exception. The baseline HTTP results are preserved locally in `data/logs/qqq-before-fix.json` (after service startup, before the code fix).

The initial running Python backend's complete stdout/stderr was captured, then preserved in `data/logs/qqq-before-restart.log`; current complete logs append to `data/logs/backend.log`. The baseline log contains Yahoo's missing-fundamentals 404 messages followed by HTTP 200 research, not a Python traceback or a backend 500. Unexpected Python errors remain logged by the backend's existing exception handler; the proxy fix does not mask genuine upstream HTTP 500 responses.

## Verified project Python environment

Paths below use `<project>` in place of the original local checkout path. Exact machine-specific logs remain local and are excluded from the public repository.

The project launcher and restarted FastAPI process use:

- Executable: `<project>/.venv/bin/python`
- Environment prefix: `<project>/.venv`
- Python: **3.13.7**
- Base interpreter symlink: `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13`
- yfinance: **1.7.0**
- yfinance module: `<project>/.venv/lib/python3.13/site-packages/yfinance/__init__.py`

The restarted API's lifespan log independently confirms these values:

```text
EquityLens runtime python='<project>/.venv/bin/python' prefix='<project>/.venv' python_version=3.13.7 yfinance=1.7.0
```

This is separate from Conda base. No dependency was installed globally or into Conda as part of this fix. The correct project dependency was already installed.

## Implemented changes

1. **Service startup and supervision.** `scripts/dev.sh` prints the actual interpreter and yfinance version, checks for occupied ports without killing existing processes, starts the API using `.venv`, saves full backend logs, waits for `/health`, then launches Vite on a strict port. If either owned service exits, it stops the other. Missing dependencies or startup failure produce a clear message rather than leaving a frontend pointing at a missing API. Backend lifespan logging records the exact runtime for subsequent diagnosis.
2. **Accurate proxy errors.** A failed development proxy connection returns structured, retryable **HTTP 502 / RESEARCH_SERVICE_UNAVAILABLE** with instructions to start the backend. Actual backend HTTP 500 responses retain their status and body; they are not relabeled as Yahoo outages.
3. **Fund-specific retrieval.** Yahoo `quoteType` metadata identifies ETF and mutual-fund instruments; no ticker whitelist or QQQ/SPY-specific mapping was introduced. Funds skip six corporate statement getters, company earnings/calendar, analyst price targets and earnings history/estimate getters. This removes ten unnecessary corporate getter calls per cold fund aggregation. Available history, actions, metadata and ticker news retain their independent caching/error handling.
4. **Correct analysis scope.** Corporate financial-health/quality scores, corporate EPS/FCF yields and corporate DCF do not apply to fund shares. These are explicitly marked not applicable, even if accidental corporate fields or custom FCF assumptions are present. Available source-reported portfolio P/E, NAV and assets remain visible with their scope explained. Technical indicators and historical price-risk measurements remain available. No full fund-attractiveness model, holdings analysis or company-based trade candidate is invented.
5. **Existing UI preserved.** The dashboard retains its layout, colors and components. It adds an ETF type label, shows Not Applicable for corporate financial resources, and hides the corporate DCF form for funds. A missing corporate statement no longer looks like a fund-price failure.

## Actual API and browser verification

After applying changes, the backend was restarted with the project interpreter. **All 20 actual FastAPI checks returned HTTP 200:** history, technical, overview and research for each of AAPL, NVDA, ORCL, QQQ and SPY. Price histories were nonempty, technical scores were available, and score/plan identities followed the requested ticker. QQQ and SPY were identified as ETF; their corporate sections reported `not_applicable`.

ETF_API_VERIFICATION.json (`ETF_API_VERIFICATION.json`, retained locally) contains endpoint statuses, observed source timestamps, names, types, available price/analysis fields and section status. These are live HTTP checks through FastAPI, separate from mock-based unit tests; cached source metadata is explicitly recorded rather than claimed as fresh on every endpoint call.

Browser checks confirmed QQQ's Invesco QQQ Trust page loads its chart and technical evidence, displays an ETF label and Not Applicable corporate statements, and has no corporate DCF form. Switching to SPY updates the URL/company and retains the chart/technical evidence with the same fund safeguards. User-owned tabs were not repurposed for QA.

## Automated verification and request counts

- **215 backend tests passed; one real-PostgreSQL test skipped** because its service URL is not configured.
- **62 frontend tests passed; TypeScript/Vite production build passed.** The existing lazy Plotly bundle still produces a size warning.
- Six launcher tests cover backend readiness failure, backend/frontend exit supervision, strict-port/working-directory behavior, occupied ports, missing dependencies and cleanup of both owned services on SIGTERM. Shell syntax validation passes.
- Twenty-two fund tests cover ETF/mutual-fund identity, missing/accidental corporate data, no corporate scoring or DCF, validated source metadata and QQQ/SPY API integration. Across history/technical/overview/research plus a DCF request, each fund spy records exactly **one history getter, one metadata getter and one news getter**, with **zero corporate getters**. These are adapter-method counts, not a claim that yfinance internally makes only three raw HTTP requests. Warm repeated source requests use persistent caches.
- A real isolated proxy test verifies refused connections return the structured 502, while an upstream 500 is preserved unchanged. Existing stock financial/valuation behavior remains covered by regression tests.

## Main changed files

Backend: `app/instruments.py`, `app/providers/yahoo.py`, `app/analysis/fundamentals.py`, `app/analysis/valuation.py`, `app/service.py`, `app/main.py`, plus fund/launcher regression tests. Paths are relative to `backend/`.

Frontend: `vite.config.ts`, `devProxy.ts`, `src/DataStatus.tsx`, `src/types.ts`, `src/App.tsx`, `src/ResearchSections.tsx`, and focused proxy/fund UI tests. Paths are relative to `frontend/`.

Startup/verification: `scripts/dev.sh`, `scripts/verify_api.py`, README updates and this diagnosis/evidence record. No frontend redesign or global package installation was performed.

## Running it later

For a fresh session with neither service running, start both from a normal terminal at the repository root:

```bash
./scripts/dev.sh
```

Keep that terminal open. The launcher stops its owned services when interrupted. If Vite is already running and only the backend needs to be started, use:

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

The launcher intentionally refuses busy ports and never kills another process to take them. Installing yfinance in Conda base does not start FastAPI or change the project's `.venv`. External Yahoo fields can still be missing or rate-limited; those conditions remain explicit source errors/limitations rather than a blanket explanation for every HTTP 500.
