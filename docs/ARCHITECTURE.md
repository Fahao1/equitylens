# EquityLens architecture and integration contract

Local-first personal research application. FastAPI serves typed REST endpoints; React/Vite consumes the research snapshot. SQLAlchemy uses SQLite locally and PostgreSQL in Compose. Providers cache source snapshots separately from deterministic analysis. No brokerage integration.

## Files
- backend/app/providers/yahoo.py: bounded Yahoo retrieval, source metadata and partial failures
- backend/app/providers/search.py: Yahoo company/ticker discovery with persistent search caching
- backend/app/providers/calendar.py: Forex Factory authorized file import and normalization
- backend/app/analysis/technical.py: technical indicators and grouped interpretation
- backend/app/analysis/fundamentals.py: statement ratios and financial health
- backend/app/analysis/valuation.py: metrics and optional DCF
- backend/app/analysis/news.py: linked headline/summary sentiment
- backend/app/analysis/macro.py: surprise, event risk and stock exposure hypotheses
- backend/app/analysis/scoring.py: configurable weighted categories
- backend/app/analysis/trade.py: conditional levels and position sizing
- backend/app/analysis/backtest.py: next-bar execution, costs and benchmarks
- backend/app/main.py, schemas.py, service.py, storage.py, config.py: application layer
- frontend/src/: React dashboard, research, calendar, watchlist, backtest
- backend/tests/: offline mathematical, parser, API and point-in-time tests
- docs/: methods, source access limitations and verification evidence

## Internal data contract
All analysis functions return JSON-safe dictionaries, missing numbers are null (never NaN). Datetimes ISO 8601 with offset. Category result contains `score: float|null`, `confidence: float` (0..1), `signals: list[str]`, `limitations: list[str]`.

`analyze_technical(history: pd.DataFrame) -> dict`: history has DatetimeIndex and Yahoo-style Open,High,Low,Close,Adj Close,Volume,Dividends,Stock Splits. Result additionally `indicators` (latest values), `series` (list of {date,...indicator values}), `structure` ({support:list[number],resistance:list[number],swing_high,swing_low,fibonacci:dict}), `regime`, `trend`, `volatility`.

`analyze_fundamentals(statements: dict, info: dict, now: datetime|None=None) -> dict`: statements = {annual_income,quarterly_income,annual_balance,quarterly_balance,annual_cashflow,quarterly_cashflow}; each list newest-first {date: 'YYYY-MM-DD', values:{Yahoo row name: number|null}}. Result additionally `metrics:dict`, `periods:list` for annual revenue/income/FCF/margins, `quarterly_periods:list`, `risk_score:number|null`.

`analyze_valuation(info:dict, fundamentals:dict, assumptions:dict|None=None) -> dict`: result metrics, scenarios, assumptions.

`analyze_news(articles:list[dict], now:datetime|None=None) -> dict`: normalized source article {id,title,publisher,published_at,url,summary,content_scope:'headline'|'summary',relevance}. Result additionally articles, bullish, bearish, upcoming_events.

`ForexFactoryCalendarProvider.parse(content:str, format:str='json', source_timezone:str='America/New_York') -> list[dict]`: normalized event {id,title,country,currency,scheduled_at,impact,forecast,previous,actual,revised_previous,status,source_url,last_updated,...}; input source strings preserved, numeric quantities separately. Fail closed ambiguous/nonexistent local times. No scheduled fetch by default.

`analyze_macro(events:list[dict], info:dict, horizon:str='swing', now:datetime|None=None) -> dict`: result additionally outlook, upcoming_events, recent_events, event_risk, stock_impacts.

`run_backtest(history:pd.DataFrame, config:dict, benchmark:pd.DataFrame|None=None) -> dict`: config starting_capital,commission_bps,slippage_bps,risk_per_trade,fast_period,slow_period; daily split-adjusted data, close-time signals next open execution. Fundamentals/news/macro excluded without verified point-in-time records. Result metrics, equity_curve, trades, limitations, validation.

## Frontend API contract
GET /api/stocks/{ticker}/research?period=1y&horizon=swing returns:
{ticker,as_of,overview,history:{prices:[{date,open,high,low,close,adj_close,volume}],source,interval,period},technical,fundamentals,valuation,news,macro,score,trade_plan,report:{markdown},data_quality:{mode,limitations,coverage}}
`overview`: ticker,name,sector,industry,currency,exchange_timezone,price,change_percent,quote_at,market_cap,source,quote_type,description,website.
`score`: overall,company_quality,confidence,categories:[{key,label,score,weight,contribution,confidence}],limitations.
`trade_plan`: recommendation,status,entry_zone:[low,high]|null,breakout_entry,targets:[number],stop,risk_reward,upside_percent,downside_percent,position_size,risk_budget,holding_horizon,calculation:list[str],invalidation:list[str],event_warnings:list[str].
POST /api/stocks/{ticker}/trade-plan body {horizon:'short'|'swing'|'long',risk_tolerance:'low'|'medium'|'high',capital:10000,risk_per_trade:0.01,min_reward_risk:2,existing_shares:0,cost_basis:null,weights:{financial:0.25,valuation:0.2,technical:0.2,news:0.1,macro:0.1,risk:0.15}} returns trade_plan plus score.
GET /api/economic-calendar?days=7&country=USD&impact=High&timezone=America/Los_Angeles returns {events,source,status,coverage,limitations}.
POST /api/economic-calendar/import body {content:string,format:'json'|'csv'|'xml'|'ics',source_timezone:'America/New_York'}.
GET /api/watchlist -> {items:[{ticker,created_at}]}; POST /api/watchlist body {ticker}; DELETE /api/watchlist/{ticker}.
GET /api/reports -> {items:[{id,ticker,created_at,markdown}]}; POST /api/stocks/{ticker}/reports -> saved report.
POST /api/backtest body {ticker,period:'5y',starting_capital:10000,commission_bps:5,slippage_bps:5,risk_per_trade:0.01,fast_period:20,slow_period:50}.
Errors {detail:{code,message}}. Live requests never silently fall back to sample data. Optional preview enabled only with EQUITYLENS_DEMO=true and prominent synthetic fixture labeling.

## Dynamic provider stages and errors

Yahoo symbols are normalized dynamically; no company allowlist exists. Validation allows up to 32 ASCII symbol characters (letters/numbers, ., -, ^, &, =). Search resolves names via `yfinance.Search`; the Yahoo adapter receives the selected symbol directly. `GET /api/search?q=...` returns results with symbol/name/exchange/asset_type and retrieval/cache metadata.

Each optional provider resource caches separately. `data_quality.sections` includes history, company_info, statements, news, analyst, earnings and company_events; each reports available/cached/partial/unavailable/error, fetched_at, cache_stale and a structured error when applicable. Price/history and `/technical` work independently of optional company endpoints. Score and plan include their selected ticker.

Errors preserve legacy `detail.code/message` and expose top-level ticker/status/error_code/message/retryable. DNS/connectivity503, timeout504, rate limit429, confirmed unknown404 and missing history404 remain distinct. Empty history alone is not called a confirmed unsupported ticker. Optional errors remain section-level HTTP200 research responses. The browser scopes asynchronous calculations to ticker+window+horizon, cancels superseded requests, and maintains ticker URLs and local recent searches.
