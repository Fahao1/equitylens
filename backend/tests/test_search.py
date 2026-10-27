from types import SimpleNamespace
import pytest

from app.config import Settings
from app.providers import yahoo
from app.providers.yahoo import DataUnavailable, classify_provider_error
from app.providers.search import YahooFinanceSearchProvider, normalize_query
from app.storage import Store


class MemoryStore:
    def __init__(self):
        self.entries = {}
        self.writes = 0

    def cache_get(self,key):
        return self.entries.get(key)

    def cache_set(self,key,value):
        self.entries[key] = {'value':value,'age':0}
        self.writes += 1


class SearchFactory:
    def __init__(self,quotes=None,response=None,error=None):
        self.quotes = quotes if quotes is not None else []
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self,query,**kwargs):
        self.calls.append((query,kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(quotes=self.quotes,response=self.response)


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(yahoo.time,'sleep',lambda _:None)


def provider(factory,store=None):
    return YahooFinanceSearchProvider(store or MemoryStore(),Settings(),factory)


def test_company_search_uses_yahoo_without_symbol_whitelist():
    factory = SearchFactory([{'symbol':'orcl','longname':'Oracle Corporation','shortname':'Oracle',
                              'exchDisp':'NYSE','exchange':'NYQ','quoteType':'EQUITY'}])
    result = provider(factory).search('  Oracle   Corporation  ')
    assert result['query'] == 'Oracle Corporation'
    assert result['results'] == [{'symbol':'ORCL','name':'Oracle Corporation','exchange':'NYSE','asset_type':'EQUITY'}]
    assert result['cache_stale'] is False
    assert result['cache_age_seconds'] == 0
    assert result['fetched_at'].endswith('+00:00')
    assert 'Yahoo' in result['source']
    assert factory.calls == [('Oracle Corporation',{'max_results':8,'news_count':0,'lists_count':0,
                                                   'include_cb':False,'timeout':8,'raise_errors':True})]


def test_symbol_normalization_duplicates_and_available_metadata_only():
    factory = SearchFactory([None,'bad',{}, {'symbol':'<invalid>'}, {'symbol':'ORCL'},
                             {'symbol':'orcl','longname':'Duplicate'},
                             {'symbol':'BRK-B','shortname':'Berkshire Hathaway B','exchange':'NYQ','typeDisp':'Equity'},
                             {'symbol':'^GSPC','longname':None,'exchDisp':None,'quoteType':None}])
    result = provider(factory).search('finance')
    assert result['results'] == [
        {'symbol':'ORCL','name':None,'exchange':None,'asset_type':None},
        {'symbol':'BRK-B','name':'Berkshire Hathaway B','exchange':'NYQ','asset_type':'Equity'},
        {'symbol':'^GSPC','name':None,'exchange':None,'asset_type':None}]


def test_unicode_company_queries_are_accepted_without_ascii_allowlist():
    factory = SearchFactory([{'symbol':'OR.PA','longname':"L’Oréal S.A."}])
    result = provider(factory).search('L’Oréal')
    assert result['query'] == 'L’Oréal'
    assert result['results'][0]['symbol'] == 'OR.PA'


@pytest.mark.parametrize('query',['',' '*10,'a'*101,'hello\nworld','hello\tworld','hello\x00world','hello\x7fworld','hello\u200bworld',None,42])
def test_invalid_query_rejected_before_request(query):
    factory = SearchFactory()
    with pytest.raises(DataUnavailable) as caught:
        provider(factory).search(query)
    assert caught.value.status == 422
    assert caught.value.code == 'invalid_search_query'
    assert caught.value.retryable is False
    assert factory.calls == []


def test_result_count_capped_at_eight_even_when_upstream_ignores_limit():
    factory = SearchFactory([{'symbol':f'SYM{i}'} for i in range(20)])
    assert len(provider(factory).search('company')['results']) == 8


def test_empty_search_is_not_an_outage_and_is_cached():
    factory,store = SearchFactory([]),MemoryStore()
    search = provider(factory,store)
    first = search.search('unmatched company')
    second = search.search('UNMATCHED COMPANY')
    assert first['results'] == second['results'] == []
    assert first['cache_stale'] is False
    assert len(factory.calls) == 1
    assert store.writes == 1
    assert next(iter(store.entries)).startswith('yahoo:search:v1:')
    assert 'company' not in next(iter(store.entries))


def test_expired_cache_with_timeout_is_explicit_stale_fallback():
    store = MemoryStore()
    initial = provider(SearchFactory([{'symbol':'ORCL','shortname':'Oracle'}]),store).search('oracle')
    entry = next(iter(store.entries.values()))
    entry['age'] = 3601
    failure = SearchFactory(error=TimeoutError('private upstream diagnostics'))
    result = provider(failure,store).search('ORACLE')
    assert result['cache_stale'] is True
    assert result['cache_age_seconds'] == 3601
    assert result['fetched_at'] == initial['fetched_at']
    assert result['results'] == initial['results']
    assert result['query'] == 'ORACLE'
    assert 'cached' in result['cache_warning'].lower()
    assert result['upstream_error']['code'] == classify_provider_error(TimeoutError()).code
    assert result['upstream_error']['retryable'] is True
    assert 'private upstream diagnostics' not in result['upstream_error']['message']
    assert store.writes == 1


def test_uncached_outage_propagates_typed_provider_error_instead_of_empty_matches():
    factory = SearchFactory(error=ConnectionError('DNS lookup failed private-detail'))
    with pytest.raises(DataUnavailable) as caught:
        provider(factory).search('Oracle')
    assert caught.value.code == classify_provider_error(ConnectionError()).code
    assert caught.value.status == 503
    assert caught.value.retryable is True
    assert 'private-detail' not in str(caught.value)
    assert 1 <= len(factory.calls) <= 3


def test_transient_network_failure_retried_then_success():
    calls = []
    def factory(query,**kwargs):
        calls.append(query)
        if len(calls) == 1:
            raise ConnectionError('temporary DNS failure')
        return SimpleNamespace(quotes=[{'symbol':'ORCL'}],response={})
    result = provider(factory).search('Oracle')
    assert result['results'][0]['symbol'] == 'ORCL'
    assert len(calls) == 2
    assert result['cache_stale'] is False


def test_rate_limit_preserves_specific_error():
    factory = SearchFactory(error=DataUnavailable('Wait before retrying Yahoo search.','upstream_rate_limit',429,retryable=True))
    with pytest.raises(DataUnavailable) as caught:
        provider(factory).search('Oracle')
    assert caught.value.code == 'upstream_rate_limit'
    assert caught.value.retryable is True
    assert caught.value.status == 429


def test_explicit_upstream_error_not_reported_as_no_results():
    factory = SearchFactory([],response={'finance':{'error':{'code':'Bad Gateway'}}})
    with pytest.raises(DataUnavailable) as caught:
        provider(factory).search('Oracle')
    assert caught.value.code == 'provider_response_error'
    assert caught.value.status == 502


def test_persistent_cache_shared_across_provider_instances(tmp_path):
    database = 'sqlite:///'+str(tmp_path/'search.sqlite')
    store = Store(database)
    first = provider(SearchFactory([{'symbol':'ORCL'}]),store).search('Oracle')
    store.engine.dispose()
    second_store = Store(database)
    unavailable = SearchFactory(error=ConnectionError('No network'))
    try:
        second = provider(unavailable,second_store).search('oracle')
        assert second['results'] == first['results']
        assert second['fetched_at'] == first['fetched_at']
        assert second['cache_stale'] is False
        assert unavailable.calls == []
    finally:
        second_store.engine.dispose()


def test_malformed_quote_collection_is_a_provider_error():
    def factory(query,**kwargs):
        return SimpleNamespace(quotes={'symbol':'ORCL'},response={})
    with pytest.raises(DataUnavailable) as caught:
        provider(factory).search('Oracle')
    assert caught.value.code == 'provider_response_error'
    assert caught.value.status == 502
    assert caught.value.retryable is False


def test_expired_cache_refreshes_when_search_recovers():
    store = MemoryStore()
    first = provider(SearchFactory([{'symbol':'ORCL'}]),store).search('Oracle')
    next(iter(store.entries.values()))['age'] = 3601
    factory = SearchFactory([{'symbol':'ORCL','longname':'Oracle Corporation'}])
    result = provider(factory,store).search('Oracle')
    assert result['cache_stale'] is False
    assert result['cache_age_seconds'] == 0
    assert result['results'][0]['name'] == 'Oracle Corporation'
    assert store.writes == 2
    assert len(factory.calls) == 1
