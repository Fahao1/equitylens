from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone as tz
import asyncio
import logging
import secrets
import time
import sys
import platform
from importlib.metadata import version
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.config import Settings, get_settings
from app.storage import Store
from app.providers.yahoo import YahooFinanceProvider, DataUnavailable, validate_ticker, records_frame
from app.providers.calendar import ForexFactoryCalendarProvider
from app.analysis.macro import economic_surprise
from app.analysis.backtest import run_backtest
from app.schemas import TradeRequest, BacktestRequest, TickerRequest, CalendarImport, CategoryResult, ResearchResponse, JsonResponse, DCFAssumptions, CalendarResponse, HistoryResponse, SearchResponse, QuantRequest
from app.service import ResearchService, display_history
from app.utils import clean

log = logging.getLogger("equitylens")


def create_app(settings: Settings | None = None, provider=None, store=None, search_provider=None,universe_provider=None):
    settings = settings or get_settings()
    store = store or Store(settings.database_url)
    if provider is None:
        if settings.demo:
            from app.providers.demo import DemoProvider
            provider = DemoProvider()
        else:
            provider = YahooFinanceProvider(store, settings)
    service = ResearchService(provider, store, settings)
    from app.analysis.quantitative import QuantitativeResearchService
    quant_service = QuantitativeResearchService(service,provider,store,settings)
    from app.providers.universe import TechnologyUniverseProvider
    from app.screener.service import TechnologyScreenerService
    from app.screener.routes import make_screener_router
    universe_provider=universe_provider or TechnologyUniverseProvider(store,settings)
    screener=TechnologyScreenerService(provider,universe_provider,service,quant_service,store,settings)
    if search_provider is None:
        from app.providers.search import YahooFinanceSearchProvider
        search_provider = YahooFinanceSearchProvider(store, settings)

    async def refresh():
        while True:
            await asyncio.sleep(settings.refresh_seconds)
            for item in store.watchlist()[:20]:
                try:
                    await asyncio.to_thread(provider.bundle, item["ticker"], "1y")
                except Exception as exc:
                    log.warning("Background refresh failed %s (%s)", item["ticker"], type(exc).__name__)

    async def refresh_screenings():
        while True:
            if settings.screener_auto_refresh or screener.has_schedule():
                try:await asyncio.to_thread(screener.auto_refresh)
                except Exception as exc:log.warning('Scheduled screening failed (%s)',type(exc).__name__)
            await asyncio.sleep(300)

    @asynccontextmanager
    async def lifespan(app):
        logging.getLogger("uvicorn.error").info("EquityLens runtime python=%r prefix=%r python_version=%s yfinance=%s", sys.executable, sys.prefix, platform.python_version(), version("yfinance"))
        task = asyncio.create_task(refresh()) if settings.background_refresh else None
        screen_task=asyncio.create_task(refresh_screenings()) if settings.background_refresh else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if screen_task:
            screen_task.cancel()
            try:await screen_task
            except asyncio.CancelledError:pass
        await asyncio.to_thread(screener.close)
        store.engine.dispose()

    app = FastAPI(title="EquityLens", version="1.0.0", description="Transparent personal equity research. No brokerage execution.", lifespan=lifespan)
    app.state.service, app.state.store = service, store
    app.state.screener=screener
    app.include_router(make_screener_router(screener,provider,store))
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization"])
    clients = defaultdict(deque)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api") and request.method != "OPTIONS":
            if settings.api_token:
                token = request.headers.get("authorization", "")
                if not secrets.compare_digest(token, f"Bearer {settings.api_token}"):
                    return JSONResponse(status_code=401, content={"detail": {"code": "unauthorized", "message": "A valid personal API token is required."}})
            now = time.monotonic()
            if len(clients) > 1024:
                for key in list(clients):
                    if not clients[key] or clients[key][-1] < now-60:
                        del clients[key]
            host = request.client.host if request.client else "unknown"
            bucket = clients[host]
            while bucket and bucket[0] < now-60:
                bucket.popleft()
            if len(bucket) >= settings.request_limit:
                return JSONResponse(status_code=429, headers={"Retry-After": "60"}, content={"detail": {"code": "rate_limit", "message": "Too many requests. Please wait one minute."}})
            bucket.append(now)
        if request.method == "POST":
            length, chunks = 0, []
            async for chunk in request.stream():
                length += len(chunk)
                if length > 3_000_000:
                    return JSONResponse(status_code=413, content={"detail": {"code": "file_too_large", "message": "Request exceeds 3 MB."}})
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.exception_handler(DataUnavailable)
    async def unavailable(request, exc):
        payload = exc.payload()
        return JSONResponse(status_code=exc.status, content={**payload, "detail": payload}, headers={"Retry-After": "60"} if exc.status==429 else None)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        payload = {"ticker": request.path_params.get("ticker"), "status": "error", "code": "invalid_input", "error_code": "INVALID_INPUT", "message": str(exc), "retryable": False}
        return JSONResponse(status_code=422, content={**payload, "detail": payload})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        message = "; ".join(".".join(str(part) for part in error["loc"]) + ": " + error["msg"] for error in exc.errors())
        payload = {"ticker": request.path_params.get("ticker"), "status": "error", "code": "invalid_request", "error_code": "INVALID_REQUEST", "message": message, "retryable": False}
        return JSONResponse(status_code=422, content={**payload, "detail": payload})

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        log.exception("internal_error path=%s ticker=%s type=%s", request.url.path, request.path_params.get("ticker"), type(exc).__name__)
        payload = {"ticker": request.path_params.get("ticker"), "status": "error", "code": "internal_error", "error_code": "INTERNAL_SERVER_ERROR", "message": "This research request could not be completed because of an internal error. Check the backend log.", "retryable": False}
        return JSONResponse(status_code=500, content={**payload, "detail": payload})

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0", "mode": "synthetic demo" if settings.demo else "live provider"}

    @app.get("/api/stocks/{ticker}/research", response_model=ResearchResponse)
    def research(ticker: str, period: Literal["3mo", "6mo", "1y", "5y", "max"] = "1y", horizon: Literal["short", "swing", "long"] = "swing"):
        return service.research(ticker, period, TradeRequest(horizon=horizon).model_dump(mode="json"))

    @app.get('/api/stocks/{ticker}/quantitative',response_model=JsonResponse)
    def quantitative(ticker:str,horizon:Literal['short','swing','long']='swing',benchmark:str='SPY'):
        return quant_service.analyze(ticker,QuantRequest(horizon=horizon,benchmark_ticker=benchmark).model_dump(mode='json'))

    @app.post('/api/stocks/{ticker}/quantitative',response_model=JsonResponse)
    def quantitative_custom(ticker:str,body:QuantRequest):
        return quant_service.analyze(ticker,body.model_dump(mode='json',exclude_none=True))

    @app.post('/api/stocks/{ticker}/quantitative/report',response_model=JsonResponse)
    def quantitative_report(ticker:str,body:QuantRequest):
        result=quant_service.analyze(ticker,body.model_dump(mode='json',exclude_none=True))
        return {**store.save_report(result['ticker'],result['report']['markdown']),'llm_used':False}

    @app.get("/api/stocks/{ticker}/history", response_model=HistoryResponse)
    def history(ticker: str, period: Literal["3mo", "6mo", "1y", "5y", "max"] = "1y", interval: Literal["1d", "1wk"] = "1d"):
        return display_history(provider.history(ticker, period, interval), period)

    @app.get("/api/stocks/{ticker}/overview", response_model=JsonResponse)
    def overview(ticker: str):
        from app.service import overview_from
        bundle = getattr(provider, "overview", provider.bundle)(ticker)
        return {**clean(overview_from(bundle)), "source_metadata": bundle.get("sections", {})}

    @app.get("/api/stocks/{ticker}/technical", response_model=CategoryResult)
    def technical(ticker: str, period: Literal["3mo", "6mo", "1y", "5y", "max"] = "1y"):
        return service.technical(ticker, period)

    @app.get("/api/search", response_model=SearchResponse)
    def search(q: str = Query(min_length=1, max_length=100)):
        if settings.demo:
            return {"query": q, "results": [], "source": "Synthetic demo: enter an exact fictional ticker", "fetched_at": None, "cache_stale": False, "cache_age_seconds": 0}
        return search_provider.search(q)

    # Each path is explicit in OpenAPI while sharing deterministic snapshot computation.
    for section, result_key in [("fundamentals", "fundamentals"), ("valuation", "valuation"), ("news", "news"), ("macro-impact", "macro")]:
        def make_handler(key):
            def handler(ticker: str, horizon: Literal["short", "swing", "long"] = "swing"):
                return service.research(ticker, config=TradeRequest(horizon=horizon).model_dump(mode="json"))[key]
            handler.__name__ = key
            return handler
        app.add_api_route(f"/api/stocks/{{ticker}}/{section}", make_handler(result_key), methods=["GET"], response_model=CategoryResult)

    @app.get("/api/stocks/{ticker}/score", response_model=JsonResponse)
    def score(ticker: str):
        return service.research(ticker)["score"]

    @app.post("/api/stocks/{ticker}/trade-plan", response_model=JsonResponse)
    def trade(ticker: str, body: TradeRequest):
        data = service.research(ticker, config=body.model_dump(mode="json"))
        core=data.get('quant_core',{})
        return {**core.get('recommendation',data['trade_plan']), "score": core.get('score_adapter',data['score']), "report": data["report"], 'quant_core':core}

    @app.post("/api/stocks/{ticker}/valuation", response_model=CategoryResult)
    def dcf(ticker: str, assumptions: DCFAssumptions):
        return service.research(ticker, assumptions=assumptions.model_dump(exclude_none=True))["valuation"]

    def calendar_data(days=7, country=None, impact=None, timezone="America/Los_Angeles", start_date=None, end_date=None, upcoming=False):
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown display timezone")
        now = datetime.now(tz.utc)
        events = store.events()
        stamps = sorted(e["scheduled_at"] for e in events if e.get("scheduled_at"))
        imported = max((e.get("imported_at") or "" for e in events), default=None)
        start = datetime.fromisoformat(start_date).replace(tzinfo=zone).astimezone(tz.utc) if start_date else (now if upcoming else (now-timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        end = datetime.fromisoformat(end_date).replace(tzinfo=zone).astimezone(tz.utc)+timedelta(days=1) if end_date else now+timedelta(days=days)
        if end <= start or (end-start).days > 366:
            raise ValueError("Calendar range must be positive and no longer than 366 days")
        result = []
        for event in events:
            if country and country.upper() not in (event.get("country"), event.get("currency")):
                continue
            if impact and event.get("impact", "").lower() != impact.lower():
                continue
            row = dict(event)
            if row.get("scheduled_at"):
                dt = datetime.fromisoformat(row["scheduled_at"])
                if not start <= dt <= end:
                    continue
                row["scheduled_local"] = dt.astimezone(zone).isoformat()
                row["seconds_until"] = int((dt-now).total_seconds())
            elif row.get("scheduled_date"):
                try:
                    day = datetime.fromisoformat(row["scheduled_date"]).date()
                    if not start.date() <= day <= end.date():
                        continue
                except ValueError:
                    pass
            row["surprise"] = economic_surprise(row, events, now)
            result.append(row)
        result.sort(key=lambda e: e.get("scheduled_at") or e.get("scheduled_date") or "9999")
        return {"events": result, "source": "Forex Factory (authorized file import)", "status": "imported" if events else "not_imported",
                "coverage": {"start": stamps[0] if stamps else None, "end": stamps[-1] if stamps else None, "last_imported_at": imported, "requested_end": end.isoformat(), "event_count": len(events), "timezone": timezone},
                "limitations": ["Calendar coverage is limited to imported files; an empty result does not mean no events are scheduled.", "Weekly exports may omit actuals, revisions, descriptions and dates outside the export. Missing fields remain unavailable.", "No automated Forex Factory API or scraping is enabled; use only files you have permission to use."]}

    @app.get("/api/economic-calendar", response_model=CalendarResponse)
    def calendar(days: int = Query(7, ge=1, le=30), country: str | None = Query(None, max_length=40), impact: str | None = Query(None, max_length=20), timezone: str = Query("America/Los_Angeles", max_length=64), start_date: str | None = None, end_date: str | None = None):
        return calendar_data(days, country, impact, timezone, start_date, end_date)

    @app.get("/api/economic-calendar/upcoming", response_model=CalendarResponse)
    def upcoming(days: int = Query(7, ge=1, le=30), timezone: str = "America/Los_Angeles"):
        return calendar_data(days=days, timezone=timezone, upcoming=True)

    @app.get("/api/economic-calendar/high-impact", response_model=CalendarResponse)
    def high_impact(days: int = Query(7, ge=1, le=30), timezone: str = "America/Los_Angeles"):
        return calendar_data(days=days, impact="High", timezone=timezone, upcoming=True)

    @app.post("/api/economic-calendar/import", response_model=JsonResponse)
    def import_calendar(body: CalendarImport):
        events = ForexFactoryCalendarProvider().parse(body.content, body.format, body.source_timezone)
        count = store.import_events(clean(events), body.replace_existing)
        return {"imported": count, "status": "imported", "source": "Forex Factory (authorized file import)", "limitations": ["Import does not grant redistribution rights. Dates cover only the imported export."]}

    @app.get("/api/watchlist", response_model=JsonResponse)
    def watchlist():
        return {"items": store.watchlist()}

    @app.post("/api/watchlist", response_model=JsonResponse)
    def add_watchlist(body: TickerRequest):
        store.add_watch(body.ticker)
        return {"items": store.watchlist()}

    @app.delete("/api/watchlist/{ticker}", response_model=JsonResponse)
    def remove_watchlist(ticker: str):
        store.remove_watch(validate_ticker(ticker))
        return {"items": store.watchlist()}

    @app.get("/api/reports", response_model=JsonResponse)
    def reports():
        return {"items": store.reports()}

    @app.post("/api/stocks/{ticker}/reports", response_model=JsonResponse)
    def save_report(ticker: str, body: TradeRequest | None = None):
        data = service.research(ticker, config=body.model_dump(mode="json") if body else None)
        markdown = data["report"]["markdown"]
        llm_used = False
        if settings.llm_api_key:
            import hashlib
            import json
            from app.analysis.llm import synthesize_news
            digest = hashlib.sha256(json.dumps([settings.llm_base_url, settings.llm_model, data["news"].get("articles", [])], sort_keys=True).encode()).hexdigest()
            key = "llm:news:" + digest
            cached = store.cache_get(key)
            synthesis = cached["value"] if cached and cached["age"] < 86400 else synthesize_news(data["news"].get("articles", []), settings)
            if synthesis["used"] and (not cached or cached["age"] >= 86400):
                store.cache_set(key, synthesis)
            if synthesis["used"]:
                markdown += "\n\n" + synthesis["markdown"]
                llm_used = True
            markdown += "\n\n" + "\n".join("- " + s for s in synthesis["limitations"])
        return {**store.save_report(data["ticker"], markdown), "llm_used": llm_used}

    @app.post("/api/backtest", response_model=JsonResponse)
    def backtest(body: BacktestRequest):
        prices = display_history(provider.history(body.ticker, body.period), body.period)
        benchmark = None
        limitations = []
        # Conservatively exclude today's session: the feed can include an unfinished daily bar.
        def completed_rows(rows):
            if not rows:
                return rows
            local_zone = datetime.fromisoformat(rows[-1]["date"]).tzinfo or tz.utc
            today = datetime.now(local_zone).date()
            return [row for row in rows if datetime.fromisoformat(row["date"]).date() < today]
        rows = completed_rows(prices["prices"])
        if len(rows) != len(prices["prices"]):
            limitations.append("The current source-local session was conservatively excluded to avoid an incomplete daily candle.")
        try:
            benchmark = records_frame(completed_rows(display_history(provider.history(body.benchmark_ticker, body.period), body.period)["prices"]))
        except DataUnavailable:
            limitations.append(f"Index benchmark {body.benchmark_ticker} unavailable; no substitute was invented.")
        if body.strategy!='sma':
            from app.analysis.validation import validate_strategies
            config=body.model_dump(mode='json')
            config['capital']=body.starting_capital
            if body.strategy=='all':config.pop('strategy')
            validation=clean(validate_strategies(records_frame(rows),config,benchmark))
            selected=validation.get('strategies',{}).get(body.strategy,{})
            return {**selected,'validation':validation,'source':prices['source'],'fetched_at':prices.get('fetched_at'),'limitations':validation.get('limitations',[])+limitations}
        result = run_backtest(records_frame(rows), body.model_dump(), benchmark)
        result["limitations"].extend(limitations)
        result["source"] = prices["source"]
        result["fetched_at"] = prices.get("fetched_at")
        return clean(result)

    return app


app = create_app()
