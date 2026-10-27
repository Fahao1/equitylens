"""Yahoo Finance adapter. Incomplete upstream fields remain incomplete."""
from datetime import datetime, timezone, timedelta
import logging
import re
import random
import socket
from threading import Lock
import time
from typing import Protocol
import pandas as pd
import yfinance as yf
from app.utils import clean, number, safe_url, iso_now
from app.instruments import is_fund, instrument_type

log = logging.getLogger(__name__)
TICKER = re.compile(r"^[A-Z0-9^][A-Z0-9.^=&\-]{0,31}$")
PERIODS = {"3mo": 3, "6mo": 6, "1y": 12, "5y": 60, "max": None}


ERROR_CODES = {
    "invalid_ticker": "INVALID_TICKER_FORMAT", "symbol_not_found": "UNKNOWN_TICKER",
    "provider_unavailable": "DATA_PROVIDER_UNAVAILABLE", "network_error": "DATA_PROVIDER_NETWORK_ERROR",
    "upstream_rate_limit": "DATA_PROVIDER_RATE_LIMIT", "request_timeout": "DATA_PROVIDER_TIMEOUT",
    "no_history": "MISSING_HISTORICAL_PRICES", "provider_response_error": "DATA_PROVIDER_RESPONSE_ERROR",
}


class DataUnavailable(Exception):
    def __init__(self, message: str, code: str = "provider_unavailable", status: int = 503, retryable: bool | None = None, ticker: str | None = None):
        super().__init__(message)
        self.code, self.status, self.ticker = code, status, ticker
        self.retryable = retryable if retryable is not None else status >= 500 or status == 429
        self.error_code = ERROR_CODES.get(code, code.upper())

    def payload(self):
        return {"ticker": self.ticker, "status": "error", "code": self.code, "error_code": self.error_code,
                "message": str(self), "retryable": self.retryable}


def validate_ticker(ticker: str):
    value = ticker.strip().upper()
    if not TICKER.fullmatch(value):
        raise DataUnavailable("Enter a Yahoo Finance ticker using up to 32 letters, numbers, ., -, ^, & or =.", "invalid_ticker", 422, False, value)
    return value


def classify_provider_error(exc: Exception, ticker: str | None = None) -> DataUnavailable:
    if isinstance(exc, DataUnavailable):
        if exc.ticker is None:
            exc.ticker = ticker
        return exc
    name, message = type(exc).__name__.lower(), str(exc).lower()
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    if status == 429 or "ratelimit" in name or "too many requests" in message or "rate limit" in message or re.search(r"\b(?:http(?:\s+error)?|status(?:\s+code)?)\s*[:=]?\s*429\b", message):
        return DataUnavailable("Yahoo Finance rate limit reached. Wait before retrying; repeated requests will not help.", "upstream_rate_limit", 429, True, ticker)
    if isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in message or "curl: (28)" in message:
        return DataUnavailable("Yahoo Finance request timed out. Please retry after checking backend connectivity.", "request_timeout", 504, True, ticker)
    if isinstance(exc, socket.gaierror) or any(term in name for term in ("dns", "connection", "connecterror", "transport")) or any(term in message for term in ("could not resolve", "failed to establish a new connection", "could not connect", "curl: (6)", "curl: (7)")):
        return DataUnavailable("The backend cannot resolve or connect to Yahoo Finance. Check its internet access, DNS and network permissions.", "network_error", 503, True, ticker)
    if status in (401, 403) or "unauthorized" in message or "forbidden" in message:
        return DataUnavailable("Yahoo Finance denied this request. Access restrictions are not bypassed; retry later or use an authorized provider.", "provider_unavailable", 503, False, ticker)
    if status == 404 or "quote not found for symbol" in message or "no such ticker" in message:
        return DataUnavailable("Yahoo Finance did not recognize this ticker. Check its symbol and exchange suffix.", "symbol_not_found", 404, False, ticker)
    if "pricesmissing" in name or "tzmissing" in name or "tickerMissing".lower() in name:
        return DataUnavailable("Yahoo returned no usable historical prices for this symbol/window. This does not by itself prove the ticker is unsupported.", "no_history", 404, False, ticker)
    if (status and status >= 500) or any(term in message for term in ("currently down", "will be right back", "temporarily unavailable")):
        return DataUnavailable("Yahoo Finance is temporarily unavailable. Please retry later.", "provider_unavailable", 503, True, ticker)
    return DataUnavailable("Yahoo Finance returned an unusable response for this section.", "provider_response_error", 502, False, ticker)


def retry_call(fn, ticker=None):
    """Two attempts for transient transport failures; never immediately retry 429/access/empty data."""
    for attempt in range(2):
        try:
            return fn()
        except Exception as exc:
            error = classify_provider_error(exc, ticker)
            if attempt == 1 or not error.retryable or error.code == "upstream_rate_limit":
                raise error from exc
            time.sleep(.25 * (2 ** attempt) + random.uniform(0, .15))


class MarketProvider(Protocol):
    def history(self, ticker: str, period: str = "1y", interval: str = "1d") -> dict: ...
    def bundle(self, ticker: str, period: str = "1y") -> dict: ...


def frame_records(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    frame = frame.sort_index()
    result = []
    for index, row in frame.iterrows():
        stamp = pd.Timestamp(index)
        # Daily bar timestamps are session labels, not last-trade timestamps.
        result.append({"date": stamp.isoformat(), "open": number(row.get("Open")), "high": number(row.get("High")),
                       "low": number(row.get("Low")), "close": number(row.get("Close")),
                       "adj_close": number(row.get("Adj Close")), "volume": number(row.get("Volume")),
                       "dividends": number(row.get("Dividends")), "stock_splits": number(row.get("Stock Splits"))})
    return result


def records_frame(records):
    if not records:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"])
    frame = pd.DataFrame(records).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "adj_close": "Adj Close", "volume": "Volume", "dividends": "Dividends", "stock_splits": "Stock Splits"})
    frame.index = pd.to_datetime(frame.pop("date"), utc=True)
    return frame


def statement_records(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    return [{"date": pd.Timestamp(col).date().isoformat(), "values": {str(k): number(v) for k, v in frame[col].items()}} for col in sorted(frame.columns, reverse=True)]


def normalize_news(items):
    normalized = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item
        if not isinstance(content, dict):
            continue
        title = content.get("title")
        url_field = content.get("canonicalUrl") or content.get("clickThroughUrl") or content.get("link")
        url = safe_url(url_field.get("url") if isinstance(url_field, dict) else url_field)
        if not title or not url:
            continue
        provider = content.get("provider", {})
        published = content.get("pubDate") or content.get("displayTime") or content.get("providerPublishTime")
        if isinstance(published, (float, int)):
            published = datetime.fromtimestamp(published, timezone.utc).isoformat()
        try:
            published = pd.Timestamp(published).isoformat() if published else None
        except (ValueError, TypeError):
            published = None
        summary = content.get("summary") or content.get("description")
        normalized.append({"id": str(content.get("id") or item.get("id") or url), "title": str(title),
                           "url": url, "publisher": provider.get("displayName") if isinstance(provider, dict) else str(provider),
                           "published_at": published, "summary": summary, "content_scope": "summary" if summary else "headline",
                           "relevance": "Returned by Yahoo for the selected ticker; company relevance is not independently verified."})
    return normalized


class YahooFinanceProvider:
    def __init__(self, store, settings, ticker_factory=None):
        self.store, self.settings = store, settings
        self.ticker_factory = ticker_factory or yf.Ticker
        self.locks = [Lock() for _ in range(32)]
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(settings.data_dir / "yfinance"))

    def _cached(self, key, ttl, fetch, ticker=None):
        with self.locks[hash(key) % len(self.locks)]:
            cached = self.store.cache_get(key)
            if cached and cached["age"] <= ttl:
                return {**cached["value"], "cache_age_seconds": round(cached["age"]), "cache_stale": False, "from_cache": True}
            try:
                value = clean(fetch())
                self.store.cache_set(key, value)
                return {**value, "cache_age_seconds": 0, "cache_stale": False, "from_cache": False}
            except Exception as exc:
                error = classify_provider_error(exc, ticker)
                log.warning("provider_request_failed provider=yahoo ticker=%s stage=%s error_code=%s retryable=%s", ticker, key, error.error_code, error.retryable)
                if cached:
                    return {**cached["value"], "cache_age_seconds": round(cached["age"]), "cache_stale": True, "from_cache": True,
                            "upstream_error": error.payload(), "cache_warning": "Cached data: refresh failed. The original source timestamp is retained; this is not a current quote."}
                raise error from exc

    @staticmethod
    def _status(snapshot, available=True):
        return {"status": "cached" if snapshot.get("from_cache") and available else "available" if available else "unavailable",
                "fetched_at": snapshot.get("fetched_at"), "cache_age_seconds": snapshot.get("cache_age_seconds", 0),
                "cache_stale": snapshot.get("cache_stale", False), "from_cache": snapshot.get("from_cache", False),
                "error": snapshot.get("upstream_error"), "message": snapshot.get("cache_warning")}

    def history(self, ticker, period="1y", interval="1d"):
        ticker = validate_ticker(ticker)
        if period not in PERIODS or interval not in ("1d", "1wk"):
            raise DataUnavailable("Supported windows: 3mo, 6mo, 1y, 5y, max; intervals: 1d, 1wk.", "invalid_history_window", 422, False, ticker)
        download_period = "max" if period == "max" else "5y"
        def fetch():
            frame = retry_call(lambda: self.ticker_factory(ticker).history(period=download_period, interval=interval, auto_adjust=False, actions=True, timeout=12, raise_errors=True), ticker)
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise DataUnavailable("Yahoo returned no historical prices for this ticker/window. Check the symbol and listing; an empty response is not treated as a confirmed unknown ticker.", "no_history", 404, False, ticker)
            return {"prices": frame_records(frame), "fetched_at": iso_now(), "source": "Yahoo Finance via yfinance", "interval": interval,
                    "adjustment": "Yahoo split-adjusted OHLC; separate Adj Close includes dividend adjustments. Daily dates are session labels."}
        value = self._cached(f"yahoo:history:{ticker}:{download_period}:{interval}", self.settings.history_cache_seconds, fetch, ticker)
        return {**value, "period": period}

    def price_snapshot(self, ticker, period="1y"):
        """The chart/technical stage never waits for optional company endpoints."""
        ticker = validate_ticker(ticker)
        history = self.history(ticker, period)
        return {"ticker": ticker, "history": history, "info": {}, "statements": {}, "articles": [], "company_calendar": {},
                "fetched_at": history.get("fetched_at"), "limitations": [history["cache_warning"]] if history.get("cache_warning") else [],
                "sections": {"history": self._status(history)}}

    def overview(self, ticker):
        return self.bundle(ticker, overview_only=True)

    def intraday(self, ticker, interval='1h'):
        ticker=validate_ticker(ticker)
        if interval not in ('1h','15m'):
            raise DataUnavailable('Supported native intraday frames are 1h and 15m; 4h is derived with explicit session boundaries.','invalid_timeframe',422,False,ticker)
        def fetch():
            start=(datetime.now(timezone.utc)-timedelta(days=59)).date().isoformat()
            frame=retry_call(lambda:self.ticker_factory(ticker).history(start=start,interval=interval,auto_adjust=False,prepost=False,actions=False,timeout=12,raise_errors=True),ticker)
            if not isinstance(frame,pd.DataFrame) or frame.empty:
                raise DataUnavailable('Yahoo returned no candles for this intraday window.','no_history',404,False,ticker)
            return {'prices':frame_records(frame),'fetched_at':iso_now(),'source':'Yahoo Finance via yfinance',
                    'interval':interval,'period':'up to 59 calendar days','regular_session_only':True}
        return self._cached(f'yahoo:intraday:v1:{ticker}:{interval}',300 if interval=='15m' else 900,fetch,ticker)

    def company_info(self,ticker):
        ticker=validate_ticker(ticker)
        def fetch():
            info=retry_call(lambda:self.ticker_factory(ticker).get_info(),ticker)
            return {'data':info if isinstance(info,dict) else {},'fetched_at':iso_now()}
        return self._cached(f'yahoo:section:v3:{ticker}:company_info',self.settings.fundamentals_cache_seconds,fetch,ticker)

    def valuation_history(self,ticker):
        ticker=validate_ticker(ticker)
        def fetch():
            table=retry_call(lambda:self.ticker_factory(ticker).get_valuation_measures(freq='quarterly',periods=8),ticker)
            rows=[]
            if isinstance(table,pd.DataFrame):
                for col in table.columns:
                    if str(col).lower()=='current':continue
                    try:
                        parsed=pd.Timestamp(col)
                        if pd.isna(parsed):continue
                        stamp=parsed.date().isoformat()
                    except (ValueError,TypeError):continue
                    rows.append({'date':stamp,'values':{str(k):number(v) for k,v in table[col].items()}})
            return {'rows':rows,'fetched_at':iso_now(),'source':'Yahoo Finance vendor historical valuation table; not verified point-in-time vintages'}
        return self._cached(f'yahoo:valuation_history:v1:{ticker}',86400,fetch,ticker)

    def bundle(self, ticker, period="1y", overview_only=False):
        ticker = validate_ticker(ticker)
        history = self.history(ticker, period)
        obj = self.ticker_factory(ticker)
        limitations, sections, snapshots = [], {"history": self._status(history)}, []
        blocked_error = None
        def section(name, getter, default, transform=lambda value: value):
            nonlocal blocked_error
            def fetch():
                if blocked_error is not None:
                    raise blocked_error
                data = transform(retry_call(getter, ticker))
                return {"data": clean(data), "fetched_at": iso_now()}
            try:
                snapshot = self._cached(f"yahoo:section:v3:{ticker}:{name}", self.settings.fundamentals_cache_seconds, fetch, ticker)
                available = bool(snapshot["data"])
                status = self._status(snapshot, available)
                if not available:
                    limitations.append(f"Yahoo {name.replace('_',' ')} is unavailable; no value was invented.")
                if snapshot.get("cache_warning"):
                    limitations.append(f"{name}: {snapshot['cache_warning']}")
                if snapshot.get("upstream_error", {}).get("retryable"):
                    blocked_error = classify_provider_error(DataUnavailable(snapshot["upstream_error"]["message"], snapshot["upstream_error"]["code"], retryable=True, ticker=ticker))
                snapshots.append(snapshot)
                return snapshot["data"], status
            except DataUnavailable as error:
                limitations.append(f"Yahoo {name.replace('_',' ')} unavailable: {error}")
                if error.retryable:
                    blocked_error = error
                return default, {"status": "error", "fetched_at": None, "cache_stale": False, "from_cache": False, "error": error.payload()}
        info, sections["company_info"] = section("company_info", lambda: obj.get_info(), {}, lambda x: x if isinstance(x, dict) else {})
        base = {"ticker": ticker, "history": history, "info": info, "statements": {}, "articles": [], "company_calendar": {}, "limitations": limitations, "sections": sections}
        if overview_only:
            return {**base, "fetched_at": sections["company_info"].get("fetched_at") or history["fetched_at"]}
        if is_fund(info):
            reason = f"Yahoo identifies this instrument as {instrument_type(info)}. Corporate statements, earnings and analyst price targets are not applicable to this fund."
            for name in ("statements", "company_events", "analyst", "earnings"):
                sections[name] = {"status": "not_applicable", "fetched_at": sections["company_info"].get("fetched_at"),
                                  "cache_stale": False, "from_cache": False, "error": None, "message": reason}
            limitations.append(reason)
            articles, sections["news"] = section("news", lambda: obj.get_news(count=15), [], normalize_news)
            if history.get("cache_warning"):
                limitations.append(history["cache_warning"])
            return {**base, "articles": articles, "analyst_targets": {}, "earnings_history": [], "earnings_estimates": [],
                    "fetched_at": max((s.get("fetched_at") or "" for s in snapshots), default=history.get("fetched_at")),
                    "cache_stale": any(s.get("cache_stale") for s in snapshots)}
        statements, statement_statuses = {}, []
        for key, method, freq in [("annual_income", "get_income_stmt", "yearly"), ("quarterly_income", "get_income_stmt", "quarterly"),
                                  ("annual_balance", "get_balance_sheet", "yearly"), ("quarterly_balance", "get_balance_sheet", "quarterly"),
                                  ("annual_cashflow", "get_cash_flow", "yearly"), ("quarterly_cashflow", "get_cash_flow", "quarterly")]:
            statements[key], resource_status = section(key, lambda m=method, f=freq: getattr(obj, m)(freq=f, pretty=True), [], statement_records)
            statement_statuses.append(resource_status)
        def aggregate(statuses):
            known = [s for s in statuses if s["status"] in ("available", "cached")]
            dates = [s["fetched_at"] for s in known if s.get("fetched_at")]
            return {"status": "partial" if known and len(known)<len(statuses) else "cached" if known and all(s.get("from_cache") for s in known) else "available" if known else "error" if any(s["status"]=="error" for s in statuses) else "unavailable",
                    "fetched_at": min(dates) if dates else None, "cache_stale": any(s.get("cache_stale") for s in statuses),
                    "from_cache": bool(known) and all(s.get("from_cache") for s in known), "resources": statuses,
                    "error": next((s.get("error") for s in statuses if s.get("error")), None)}
        sections["statements"] = aggregate(statement_statuses)
        articles, sections["news"] = section("news", lambda: obj.get_news(count=15), [], normalize_news)
        calendar, sections["company_events"] = section("company_events", lambda: obj.get_calendar(), {}, lambda x: x if isinstance(x,dict) else {})
        targets, sections["analyst"] = section("analyst", lambda: obj.get_analyst_price_targets(), {}, lambda x: x if isinstance(x,dict) else {})
        def table_rows(frame):
            if not isinstance(frame, pd.DataFrame):
                return []
            return [{"period": str(i), **clean(row.to_dict())} for i, row in frame.iterrows()]
        earnings, earnings_status = section("earnings_history", lambda: obj.get_earnings_history(), [], table_rows)
        estimates, estimate_status = section("earnings_estimates", lambda: obj.get_earnings_estimate(), [], table_rows)
        sections["earnings"] = aggregate([earnings_status, estimate_status])
        fetched = max((s.get("fetched_at") or "" for s in snapshots), default=history.get("fetched_at"))
        if history.get("cache_warning"):
            limitations.append(history["cache_warning"])
        return {**base, "statements": statements, "articles": articles, "company_calendar": calendar, "analyst_targets": targets,
                "earnings_history": earnings, "earnings_estimates": estimates, "fetched_at": fetched,
                "cache_stale": any(s.get("cache_stale") for s in snapshots)}
