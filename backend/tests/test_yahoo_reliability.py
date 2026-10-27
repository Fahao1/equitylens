"""Independent Yahoo reliability regressions. All upstream values are synthetic mocks."""
from datetime import datetime, timedelta, timezone
from collections import Counter

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.providers.demo import DemoProvider
from app.providers.yahoo import YahooFinanceProvider, DataUnavailable, classify_provider_error, retry_call, records_frame
from app.storage import Store, Cache


class FixtureFactory:
    def __init__(self):
        self.demo = DemoProvider()
        self.calls = Counter()
        self.info_error = None
        self.history_error = None
        self.empty_history = False

    def __call__(self, symbol):
        owner = self
        fixture = self.demo.bundle(symbol)

        class Ticker:
            def history(self, **kwargs):
                owner.calls['history'] += 1
                if owner.history_error:
                    raise owner.history_error
                return pd.DataFrame() if owner.empty_history else records_frame(fixture['history']['prices'])

            def get_info(self):
                owner.calls['company_info'] += 1
                if owner.info_error:
                    raise owner.info_error
                return {**fixture['info'], 'longName': f'Fixture business {symbol}'}

            def statement(self, kind, freq, pretty):
                owner.calls[kind] += 1
                assert pretty is True
                records = fixture['statements'][f"{'annual' if freq=='yearly' else 'quarterly'}_{kind}"]
                return pd.DataFrame({pd.Timestamp(row['date']):row['values'] for row in records})

            def get_income_stmt(self, *, freq, pretty):
                return self.statement('income',freq,pretty)

            def get_balance_sheet(self, *, freq, pretty):
                return self.statement('balance',freq,pretty)

            def get_cash_flow(self, *, freq, pretty):
                return self.statement('cashflow',freq,pretty)

            def get_news(self, **kwargs):
                owner.calls['news'] += 1
                return [{'content':{'id':'synthetic-story','title':'Fixture company announces a partnership',
                        'summary':'This is explicitly synthetic source material.',
                        'canonicalUrl':{'url':'https://example.com/synthetic-story'},
                        'provider':{'displayName':'Fixture publisher'},'pubDate':datetime.now(timezone.utc).isoformat()}}]

            def get_calendar(self):
                return {}

            def get_analyst_price_targets(self):
                return {'mean':123}

            def get_earnings_history(self):
                return None

            def get_earnings_estimate(self):
                return None

        return Ticker()


def make_provider(tmp_path, factory=None):
    settings = Settings(_env_file=None,database_url='sqlite:///:memory:',data_dir=tmp_path,
                        demo=False,background_refresh=False,request_limit=1000)
    store = Store(settings.database_url)
    factory = factory or FixtureFactory()
    return YahooFinanceProvider(store,settings,factory),store,settings,factory


def expire_sections(store, names=None):
    with store.session.begin() as session:
        for record in session.scalars(select(Cache)):
            if record.key.startswith('yahoo:section:v3:') and (names is None or record.key.rsplit(':',1)[-1] in names):
                record.updated_at = datetime.now(timezone.utc)-timedelta(days=2)


def http_error(status):
    request = httpx.Request('GET','https://query.example.test/quote')
    return httpx.HTTPStatusError('Synthetic upstream error',request=request,response=httpx.Response(status,request=request))


def test_explicit_http404_and_empty_history_have_distinct_codes(tmp_path):
    provider,store,_,factory = make_provider(tmp_path)
    try:
        factory.history_error = http_error(404)
        with pytest.raises(DataUnavailable) as unknown:
            provider.history('UNLISTED99')
        assert (unknown.value.code,unknown.value.error_code,unknown.value.status,unknown.value.retryable) == ('symbol_not_found','UNKNOWN_TICKER',404,False)
        assert factory.calls['history'] == 1
        factory.history_error = None
        factory.empty_history = True
        with pytest.raises(DataUnavailable) as empty:
            provider.history('ORCL')
        assert (empty.value.code,empty.value.error_code,empty.value.status,empty.value.retryable) == ('no_history','MISSING_HISTORICAL_PRICES',404,False)
        assert factory.calls['history'] == 2
        assert 'confirmed unknown ticker' in str(empty.value)
    finally:
        store.engine.dispose()


@pytest.mark.parametrize('exception,code,status,retryable',[
    (TimeoutError('synthetic timeout'),'request_timeout',504,True),
    (ConnectionError('synthetic failed connection'),'network_error',503,True),
    (http_error(429),'upstream_rate_limit',429,True),
    (http_error(403),'provider_unavailable',503,False),
    (http_error(502),'provider_unavailable',503,True),
    (ValueError('malformed synthetic response'),'provider_response_error',502,False),
])
def test_provider_failure_classification_retains_ticker_and_safe_payload(exception,code,status,retryable):
    error = classify_provider_error(exception,'ORCL')
    assert (error.code,error.status,error.retryable,error.ticker) == (code,status,retryable,'ORCL')
    assert error.payload()['status'] == 'error'
    assert error.payload()['error_code']
    assert 'query.example.test' not in error.payload()['message']


@pytest.mark.parametrize('jitter',[0,.15])
def test_transient_retry_count_and_jitter_bounds(monkeypatch,jitter):
    calls,waits,ranges = [],[],[]
    def fail():
        calls.append(1)
        raise TimeoutError('synthetic timeout')
    def random_value(a,b):
        ranges.append((a,b))
        return jitter
    monkeypatch.setattr('app.providers.yahoo.time.sleep',waits.append)
    monkeypatch.setattr('app.providers.yahoo.random.uniform',random_value)
    with pytest.raises(DataUnavailable) as error:
        retry_call(fail,'ORCL')
    assert error.value.code == 'request_timeout'
    assert len(calls) == 2
    assert ranges == [(0,.15)]
    assert len(waits) == 1 and .25 <= waits[0] <= .4
    assert waits[0] == pytest.approx(.25+jitter)


@pytest.mark.parametrize('error',[http_error(429),http_error(403),http_error(404),ValueError('bad response')])
def test_rate_access_unknown_and_malformed_failures_do_not_immediately_retry(monkeypatch,error):
    calls,waits = [],[]
    def fail():
        calls.append(1)
        raise error
    monkeypatch.setattr('app.providers.yahoo.time.sleep',waits.append)
    with pytest.raises(DataUnavailable):
        retry_call(fail,'ORCL')
    assert len(calls) == 1
    assert waits == []


def test_cached_optional_timeout_preserves_usable_fields_and_original_timestamps(tmp_path,monkeypatch):
    monkeypatch.setattr('app.providers.yahoo.time.sleep',lambda _:None)
    provider,store,_,factory = make_provider(tmp_path)
    try:
        first = provider.bundle('ORCL')
        expire_sections(store)
        factory.info_error = TimeoutError('synthetic metadata timeout')
        second = provider.bundle('ORCL')
        assert second['info'] == first['info']
        assert second['statements'] == first['statements']
        assert second['articles'] == first['articles']
        assert second['analyst_targets'] == first['analyst_targets']
        for key in ('company_info','statements','news','analyst'):
            assert second['sections'][key]['cache_stale'] is True
            assert second['sections'][key]['fetched_at'] == first['sections'][key]['fetched_at']
            assert second['sections'][key]['error']['code'] == 'request_timeout'
        assert factory.calls['company_info'] == 3
        assert factory.calls['income'] == 2
        assert second['cache_stale'] is True
        assert any('original source timestamp' in text.lower() for text in second['limitations'])
    finally:
        store.engine.dispose()


def test_one_expired_optional_section_does_not_mark_fresh_cached_statements_stale(tmp_path,monkeypatch):
    monkeypatch.setattr('app.providers.yahoo.time.sleep',lambda _:None)
    provider,store,_,factory = make_provider(tmp_path)
    try:
        first = provider.bundle('ORCL')
        expire_sections(store,{'company_info'})
        factory.info_error = TimeoutError('synthetic metadata timeout')
        second = provider.bundle('ORCL')
        assert second['sections']['company_info']['cache_stale'] is True
        assert second['sections']['statements']['cache_stale'] is False
        assert second['sections']['statements']['status'] == 'cached'
        assert second['statements'] == first['statements']
        assert second['sections']['news']['cache_stale'] is False
        assert second['sections']['news']['from_cache'] is True
    finally:
        store.engine.dispose()


def test_uncached_info_timeout_preserves_research_and_independent_technical_stage(tmp_path,monkeypatch):
    monkeypatch.setattr('app.providers.yahoo.time.sleep',lambda _:None)
    provider,store,settings,factory = make_provider(tmp_path)
    factory.info_error = TimeoutError('synthetic optional metadata timeout')
    with TestClient(create_app(settings,provider,store)) as client:
        technical = client.get('/api/stocks/ORCL/technical')
        assert technical.status_code == 200,technical.text
        assert technical.json()['ticker'] == 'ORCL'
        assert technical.json()['score'] is not None
        assert factory.calls['company_info'] == 0
        response = client.get('/api/stocks/ORCL/research')
        assert response.status_code == 200,response.text
        data = response.json()
        assert data['ticker'] == data['score']['ticker'] == data['trade_plan']['ticker'] == 'ORCL'
        assert data['technical']['score'] is not None
        assert data['overview']['price'] > 0
        assert data['overview']['name'] == 'ORCL'
        info = data['data_quality']['sections']['company_info']
        assert info['status'] == 'error'
        assert info['error']['code'] == 'request_timeout'
        assert info['error']['retryable'] is True
        assert data['fundamentals']['score'] is None
        assert factory.calls['company_info'] == 2


def test_search_endpoint_preserves_stale_cache_metadata(tmp_path):
    provider,store,settings,_ = make_provider(tmp_path)
    class Search:
        def search(self,query):
            return {'query':query,'results':[{'symbol':'ORCL','name':'Oracle Corporation','exchange':'NYSE','asset_type':'EQUITY'}],
                    'source':'Synthetic Yahoo search mock','fetched_at':'2026-01-01T00:00:00+00:00',
                    'cache_stale':True,'cache_age_seconds':7200,'cache_warning':'Cached search results.',
                    'upstream_error':DataUnavailable('Synthetic timeout','request_timeout',504,True).payload()}
    with TestClient(create_app(settings,provider,store,Search())) as client:
        response = client.get('/api/search',params={'q':'Oracle'})
        assert response.status_code == 200,response.text
        data = response.json()
        assert data['results'][0]['symbol'] == 'ORCL'
        assert data['cache_stale'] is True
        assert data['cache_age_seconds'] == 7200
        assert data['upstream_error']['error_code'] == 'DATA_PROVIDER_TIMEOUT'
        assert data['cache_warning']


def test_search_endpoint_rate_limit_uses_specific_error_and_retry_header(tmp_path):
    provider,store,settings,_ = make_provider(tmp_path)
    class Search:
        def search(self,query):
            raise DataUnavailable('Synthetic search rate limit','upstream_rate_limit',429,True)
    with TestClient(create_app(settings,provider,store,Search())) as client:
        response = client.get('/api/search',params={'q':'Oracle'})
        assert response.status_code == 429
        assert response.headers['Retry-After'] == '60'
        assert response.json()['error_code'] == 'DATA_PROVIDER_RATE_LIMIT'
        assert response.json()['retryable'] is True


def test_ticker_digits_are_not_a_rate_limit_and_direct_dns_is_network():
    import socket
    assert classify_provider_error(ValueError('Unable to parse Yahoo result for symbol 4291.T')).code=='provider_response_error'
    assert classify_provider_error(socket.gaierror(8,'nodename nor servname provided, or not known')).code=='network_error'


def test_selected_quote_has_matching_retrieval_timestamp():
    from app.providers.demo import DemoProvider
    from app.service import overview_from
    from datetime import datetime, timezone, timedelta
    b=DemoProvider().bundle('TEST')
    now=datetime.now(timezone.utc)
    b['history']['fetched_at']=(now-timedelta(hours=1)).isoformat()
    b['sections']={'company_info':{'fetched_at':now.isoformat()}}
    b['info']['regularMarketTime']=(now-timedelta(minutes=1)).timestamp()
    b['info']['regularMarketPrice']=123
    o=overview_from(b)
    assert o['price']==123 and o['fetched_at']==now.isoformat()
