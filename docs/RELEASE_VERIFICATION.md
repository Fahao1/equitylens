# Public release verification

Verified October27,2026, America/Los_Angeles. This summary contains engineering results; retrieved source data, personal settings, databases and generated research reports are excluded from Git.

## Automated checks

- Backend: **403 passed, zero skipped** on Python3.13.7, including the real PostgreSQL persistence test.
- Linux compatibility: **403 passed, zero skipped** on Python3.11.18 with PostgreSQL. Conditional dependency locks selected NumPy2.2.6 for this interpreter.
- Frontend: **98 tests passed** across8files; TypeScript and Vite production build passed.
- Python compilation and dependency consistency passed.
- Docker Compose configuration, both production image builds and all three services' health checks passed.
- **15 isolated container smoke checks passed** through built nginx: frontend/security headers, backend proxy, labeled synthetic research, trade planning, calendar, PostgreSQL-backed watchlist/report persistence, quantitative research and screener endpoints.

The isolated stack used alternate loopback ports, dedicated test volumes and explicit synthetic mode. It did not replace the installed personal app or use application secrets. Only test-owned resources were removed afterward, and the originally stopped container engine was restored to stopped.

Observed runtime versions included PostgreSQL17.11, backend-container Python3.13.15, Node22.23.4 and nginx1.29.8. Host versions were Python3.13.7, yfinance1.7.0, pandas3.1.0 and NumPy2.5.4.

## Live and browser checks

Actual provider-backed HTTP checks passed for individual-company and ETF history, technical, overview, full research and quantitative endpoints. Representative screener research covered the15 requested example symbols. A fresh source discovery and bounded background screening were exercised separately from synthetic tests; detailed source timestamps and observations remain in ignored local verification files.

Browser checks covered company research, dynamic Top10 tables, independent short/long rankings, comparisons, existing research drilldown and evidence/abstention displays. The application never converted missing data or inadequate historical samples into a manufactured buy/probability.

The installed macOS service was healthy. A previously recorded controlled backend stop recovered both supervised services in2.5seconds, with successful research afterward. See [startup operation and data ownership](STARTUP.md).

## Reproduce

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -o addopts= -q
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python -m pip check
docker compose config --quiet
```

Set `EQUITYLENS_TEST_POSTGRES_URL` to a dedicated test database to include the PostgreSQL test; otherwise that one check intentionally skips. Live verification scripts deliberately contact external sources and are separate from offline CI. The CI workflow targets Python3.11/3.13, Node22 and PostgreSQL17.

The existing Plotly bundle-size warning and TestClient/httpx deprecation warning remain. No paid model call, investment profitability guarantee, complete-sector coverage or invented historical ranking performance is implied by these checks.
