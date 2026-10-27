"""Yahoo ticker/company discovery without a symbol whitelist or invented matches."""
from hashlib import sha256
from threading import Lock
import unicodedata

import yfinance as yf

from app.providers.yahoo import DataUnavailable, validate_ticker, classify_provider_error, retry_call
from app.utils import iso_now

SEARCH_CACHE_SECONDS = 3600


def normalize_query(query: str) -> str:
    if not isinstance(query, str) or not 1 <= len(query) <= 100:
        raise DataUnavailable('Enter a company name or ticker between 1 and 100 characters.', 'invalid_search_query', 422, retryable=False)
    if any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in query):
        raise DataUnavailable('Search queries cannot contain control characters.', 'invalid_search_query', 422, retryable=False)
    normalized = ' '.join(query.split())
    if not normalized:
        raise DataUnavailable('Enter a company name or ticker to search.', 'invalid_search_query', 422, retryable=False)
    return normalized


def _text(value):
    if not isinstance(value, str):
        return None
    return ' '.join(value.split()) or None


def _results(quotes):
    if not isinstance(quotes, list):
        raise DataUnavailable('Yahoo Finance returned an unreadable search response. Please retry later.', 'provider_response_error', 502, retryable=False)
    results, seen = [], set()
    for quote in quotes:
        if not isinstance(quote, dict) or not isinstance(quote.get('symbol'), str):
            continue
        try:
            symbol = validate_ticker(quote['symbol'])
        except DataUnavailable:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        results.append({'symbol': symbol,
                        'name': _text(quote.get('longname')) or _text(quote.get('shortname')),
                        'exchange': _text(quote.get('exchDisp')) or _text(quote.get('exchange')),
                        'asset_type': _text(quote.get('quoteType')) or _text(quote.get('typeDisp'))})
        if len(results) == 8:
            break
    return results


class YahooFinanceSearchProvider:
    def __init__(self, store, settings, search_factory=None):
        self.store, self.settings = store, settings
        self.search_factory = search_factory or yf.Search
        self.locks = [Lock() for _ in range(32)]

    def search(self, query: str) -> dict:
        query = normalize_query(query)
        key = 'yahoo:search:v1:' + sha256(query.casefold().encode('utf-8')).hexdigest()
        with self.locks[hash(key) % len(self.locks)]:
            cached = self.store.cache_get(key)
            if cached and cached['age'] <= SEARCH_CACHE_SECONDS:
                return {**cached['value'], 'query': query, 'cache_stale': False,
                        'cache_age_seconds': max(0, round(cached['age']))}

            def fetch():
                response = self.search_factory(query, max_results=8, news_count=0, lists_count=0,
                                               include_cb=False, timeout=8, raise_errors=True)
                raw = getattr(response, 'response', None)
                if isinstance(raw, dict):
                    finance = raw.get('finance')
                    if raw.get('error') or (isinstance(finance, dict) and finance.get('error')):
                        raise DataUnavailable('Yahoo Finance search is temporarily unavailable. Please retry later.',
                                              'provider_response_error', 502, retryable=False)
                return {'query': query, 'results': _results(response.quotes),
                        'source': 'Yahoo Finance via yfinance Search', 'fetched_at': iso_now()}

            try:
                value = retry_call(fetch)
            except Exception as exc:
                error = classify_provider_error(exc)
                if cached:
                    return {**cached['value'], 'query': query, 'cache_stale': True,
                            'cache_age_seconds': max(0, round(cached['age'])),
                            'cache_warning': 'Yahoo search is unavailable. Showing dated cached matches; this does not verify current symbol availability.',
                            'upstream_error': error.payload()}
                raise error from exc
            self.store.cache_set(key, value)
            return {**value, 'cache_stale': False, 'cache_age_seconds': 0}
