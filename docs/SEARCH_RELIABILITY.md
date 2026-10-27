# Dynamic stock search and data reliability

EquityLens accepts validated Yahoo Finance symbols dynamically. AAPL, MSFT and NVDA are example inputs, not an allowlist. Company-specific data requests, analysis snapshots, scores and conditional plans use the normalized selected symbol. Lowercase input normalizes to uppercase; Yahoo-style class shares (`BRK-B`), exchange suffixes (`0700.HK`, `VOW3.DE`) and index symbols (`^GSPC`) remain supported syntactically. A valid symbol format does not guarantee Yahoo has data or that the instrument is appropriate for ordinary-company scoring.

## Cause of the apparent three-stock limit

The previous development environment had saved data for the three initial verification symbols. During a later restricted-network run, those snapshots remained available while a newly entered symbol needed a fresh Yahoo request. This made the working examples look like a list of supported companies. The ticker validator and provider had no three-symbol allowlist. A normal-network ORCL request succeeded during diagnosis. Availability of a saved snapshot and evidence of a new successful request must be kept distinct.

External data failures still matter even after symbol routing is correct. Yahoo may return an unavailable statement, a missing news feed, an empty price history, a timeout, or a rate limit. These outcomes should not all appear as “invalid ticker.” An unavailable optional field should remain missing and lower completeness/confidence; available price-based analysis should remain useful. Cached evidence must keep its source timestamp and stale-data warning. No live error may silently select a sample company or turn on fictional preview mode.

## Repeatable fresh verification

From the repository root:

```bash
.venv/bin/python scripts/verify_tickers.py
```

The default sequential list is AAPL, MSFT, NVDA, ORCL, TSLA, AMD, AMZN, GOOGL, META, PLTR, SOFI, TSM, JPM and BRK-B. To choose symbols or another output path:

```bash
.venv/bin/python scripts/verify_tickers.py --tickers ORCL INTC MU BAC --output /tmp/equitylens-ticker-check.json
```

The script uses a new temporary SQLite database and yfinance cache for every run. It does not read the application's saved provider snapshots. It performs the normal research pipeline once per ticker, waits at least 0.5 seconds between symbols, and leaves bounded retries to the provider. No automated retry loop or parallel request burst is added. It never invokes an optional paid model.

The JSON records request and source timestamps, company identity, source, quote status, daily bar count, statement availability, technical/financial/combined scores, the plan's selected quote, source limitations, and precise failure codes. A score of `null` is distinct from a missing data request: for example, specialized financial-sector scoring may correctly abstain even when JPM statements are present. A company-name or financial-statement gap is recorded as a partial result. The process exits unsuccessfully if any symbol fails, while retaining the per-symbol evidence already collected.

`docs/SEARCH_LIVE_VERIFICATION.json` is the saved outcome of an intentional live check. It is a timestamped observation, not a guarantee that Yahoo will remain available or that every listed symbol has complete coverage later. A successful run establishes retrieval at those times; market quotes can still be delayed or reflect a market closure.

## Offline regression coverage

```bash
cd backend
../.venv/bin/python -m pytest tests/test_dynamic_tickers.py
```

These table-driven tests inject explicitly fictional Yahoo-shaped observations. They cover all fourteen default symbols, lowercase normalization, class-share hyphens, exchange suffixes, indices, missing history, transport timeouts, rate limits, optional statement failures and repeated symbol switching. Research identity, price history, category calculations and the plan quote must follow the selected company. These are deterministic regression tests, not proof of current upstream access. Live evidence is recorded separately by the script above.

## Recorded live outcome

On **October 26, 2026, 12:24–12:25 a.m. America/Los_Angeles** (07:24–07:25 UTC), all fourteen default symbols retrieved successfully using the isolated fresh-cache script. Each returned 1,255 daily bars, matching company identity, available financial statement records, and a score/plan calculation carrying the selected ticker. All fourteen history, company-info and statement sections were fresh network retrievals (`from_cache=false`), rather than previously saved application evidence. The source timestamps and complete per-section status are preserved in SEARCH_LIVE_VERIFICATION.json (`SEARCH_LIVE_VERIFICATION.json`, retained locally).

Yahoo returned no usable company news in this run for any of the fourteen symbols; the news section is explicitly unavailable. SOFI, JPM and BRK-B had statement records but no generic operating-company financial score because the financial-sector safeguards abstained. That is an analysis limitation, not a search failure. No real economic calendar was imported into the temporary verification database. These observations do not establish completeness of every Yahoo field or future upstream availability.

## Implemented fix

- Yahoo price retrieval accepts the validated selected symbol directly. There is no company-specific data map. Price and technical endpoints are independent of the optional company aggregation stage.
- Each optional source resource has its own persistent cache, source timestamp, status and structured error. A failed statement, analyst or news request cannot discard available prices. A transport/rate failure stops further uncached optional requests in that aggregation to avoid a request storm; already cached resources remain usable and explicitly dated.
- Retry classification distinguishes invalid format, confirmed unknown symbol, empty historical data, DNS/connectivity, timeout, rate limit, denied access and malformed provider responses. Transient transport failures receive at most two attempts with exponential backoff/jitter; 429 and permanent failures are not immediately retried. History uses an explicit 12-second timeout, search 8 seconds; yfinance's optional metadata requests use its bounded 30-second network default. No private Yahoo endpoints or anti-bot bypass were added.
- `GET /api/search?q=...` uses the library's Yahoo search functionality and one-hour persistent caching. Source-provided company names, symbols, exchange and asset types remain distinct. Empty results are not replaced by invented matches.
- The existing search field now has a 300ms debounced dropdown, keyboard selection, exact-symbol submission, source error/retry messages and local recent searches. All three existing shortcuts remain. The URL tracks the selected ticker, old requests are canceled and late plan/DCF/report responses cannot overwrite a new ticker, including A→B→A transitions.
- Section status rows show loading, available, partially available, unavailable/error and cached evidence with original retrieval times. Newly available charts/technical evidence can render while optional company requests are pending. Unavailable currency is not silently displayed as USD.

The live company-name search evidence (`SEARCH_NAME_VERIFICATION.json`, retained locally) records Oracle→ORCL, Tesla→TSLA and Taiwan Semiconductor→TSM plus the other Yahoo listings. No static name-to-symbol dictionary is used for those matches.

## Main files changed

Backend: `app/providers/yahoo.py` (dynamic source stages/cache/retries/errors), `app/providers/search.py` (new discovery adapter), `app/main.py` (search/staged APIs/structured errors), `app/service.py` (selected-ticker identity and source freshness), `app/schemas.py` (search response), and `app/storage.py` (32-character ticker persistence). Paths are relative to `backend/`.

Frontend: `src/StockSearch.tsx`, `src/DataStatus.tsx`, `src/tickerState.ts`, `src/useRequestScope.ts`, `src/App.tsx`, `src/ResearchSections.tsx`, `src/api.ts`, `src/types.ts`, `src/ui.tsx`, `src/main.tsx`, `src/styles.css`, the Vitest configuration, package/lock files and focused regression tests. Paths are relative to `frontend/`. The existing layout/colors and working research screens were retained.

Verification/documentation: `scripts/verify_tickers.py`, `scripts/verify_search.py`, backend search/dynamic/reliability tests, frontend search/API/state/dashboard tests, README files, this record, JSON evidence and `.github/workflows/ci.yml` (frontend tests added).

Final local results: **187 backend tests passed, one real-PostgreSQL test skipped; 52 frontend tests passed; production build passed; Docker Compose configuration passed.** See [full verification boundaries](VERIFICATION.md).

## Existing PostgreSQL installations

New schemas use 32-character ticker columns. Existing PostgreSQL deployments created with 20-character columns must widen them before saving longer valid symbols:

```bash
docker compose exec -T db psql -U equitylens -d equitylens < backend/migrations/001_expand_ticker.sql
```

The SQL only widens `watchlist.ticker` and `reports.ticker`; it does not drop rows. Back up an existing deployment before applying migrations. Local SQLite already accepts these lengths. PostgreSQL runtime was not available locally, so the migration was provided but not run against a live server here.

## Remaining source limits and alternate provider

Yahoo is an external, unofficial research source and can change schemas, rate-limit access, withhold fields or become unreachable. Restarting a backend inside a restricted environment can reproduce the original DNS problem; grant ordinary DNS/HTTPS connectivity or run the documented local launcher from your terminal. Caching must not be mistaken for provider health.

For licensed alternate coverage, [Alpha Vantage documents daily prices, quotes and symbol search](https://www.alphavantage.co/documentation/). It requires an API key and an appropriate data license/plan for the intended fields and use. A new adapter can implement the existing provider interface. No alternate provider is configured or silently substituted in this fix, and no access restriction is bypassed.
