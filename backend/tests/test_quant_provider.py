"""Offline capture tests for the quantitative Yahoo provider inputs."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.providers.yahoo import YahooFinanceProvider, DataUnavailable
from app.storage import Store, Cache


class CaptureFactory:
    def __init__(self):
        self.calls = Counter()
        self.symbols = []
        self.history_kwargs = []
        self.valuation_kwargs = []
        self.history_error = self.info_error = self.valuation_error = None
        self.info = {'longName':'SYNTHETIC company fixture','quoteType':'EQUITY','currency':'USD','trailingPE':np.float64(25)}
        close = np.arange(8,dtype=float)+100
        self.prices = pd.DataFrame({'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':1000},
                                   index=pd.date_range('2026-01-02T14:30:00Z',periods=8,freq='1h'))
        self.valuation = pd.DataFrame({'Current':{'Trailing P/E':30},'12/31/2025':{'Trailing P/E':25}})
        self.forbidden = []

    def __call__(self,symbol):
        self.symbols.append(symbol)
        owner = self
        class Ticker:
            def history(self,**kwargs):
                owner.calls['history'] += 1
                owner.history_kwargs.append(kwargs)
                if owner.history_error:
                    raise owner.history_error
                return owner.prices

            def get_info(self):
                owner.calls['info'] += 1
                if owner.info_error:
                    raise owner.info_error
                return owner.info

            def get_valuation_measures(self,**kwargs):
                owner.calls['valuation'] += 1
                owner.valuation_kwargs.append(kwargs)
                if owner.valuation_error:
                    raise owner.valuation_error
                return owner.valuation

            def get_news(self,**kwargs):
                owner.calls['news'] += 1
                return []

            def corporate(self,*args,**kwargs):
                owner.forbidden.append('corporate getter')
                raise AssertionError('ETF corporate endpoints must not be requested')

            get_income_stmt = corporate
            get_balance_sheet = corporate
            get_cash_flow = corporate
            get_calendar = corporate
            get_analyst_price_targets = corporate
            get_earnings_history = corporate
            get_earnings_estimate = corporate
        return Ticker()


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr('app.providers.yahoo.time.sleep',lambda _:None)
    settings = Settings(_env_file=None,data_dir=tmp_path,database_url='sqlite:///:memory:',background_refresh=False)
    store = Store(settings.database_url)
    factory = CaptureFactory()
    yield YahooFinanceProvider(store,settings,factory),store,factory
    store.engine.dispose()


def expire(store,key,seconds):
    with store.session.begin() as session:
        row = session.get(Cache,key)
        assert row is not None
        row.updated_at = datetime.now(timezone.utc)-timedelta(seconds=seconds)


@pytest.mark.parametrize('interval,ttl',[('1h',900),('15m',300)])
def test_native_intraday_window_options_and_bounded_cache(setup,interval,ttl):
    provider,store,factory = setup
    first = provider.intraday('orcl',interval)
    second = provider.intraday('ORCL',interval)
    assert first['interval'] == interval
    assert first['regular_session_only'] is True
    assert first['cache_stale'] is False
    assert second['from_cache'] is True
    assert factory.calls['history'] == 1
    kwargs = factory.history_kwargs[0]
    assert kwargs['interval'] == interval
    assert kwargs['auto_adjust'] is kwargs['prepost'] is kwargs['actions'] is False
    assert kwargs['timeout'] == 12 and kwargs['raise_errors'] is True
    start = date.fromisoformat(kwargs['start'])
    today = datetime.now(timezone.utc).date()
    assert today-timedelta(days=59) <= start <= today
    assert all(symbol == 'ORCL' for symbol in factory.symbols)
    assert second['fetched_at'] == first['fetched_at']
    expire(store,f'yahoo:intraday:v1:ORCL:{interval}',ttl+1)
    third = provider.intraday('ORCL',interval)
    assert third['from_cache'] is False
    assert factory.calls['history'] == 2


@pytest.mark.parametrize('interval',['4h','60m','5m','1d'])
def test_unsupported_native_intervals_are_explicit_not_silently_resampled(setup,interval):
    provider,_,factory = setup
    with pytest.raises(DataUnavailable) as caught:
        provider.intraday('ORCL',interval)
    assert caught.value.status == 422
    assert caught.value.code == 'invalid_timeframe'
    assert factory.calls['history'] == 0


@pytest.mark.parametrize('missing',[None,[],{},pd.DataFrame()])
def test_missing_intraday_data_is_typed_and_not_cached_as_prices(setup,missing):
    provider,store,factory = setup
    factory.prices = missing
    with pytest.raises(DataUnavailable) as caught:
        provider.intraday('ORCL','1h')
    assert caught.value.code == 'no_history'
    assert caught.value.status == 404
    assert caught.value.retryable is False
    assert store.cache_get('yahoo:intraday:v1:ORCL:1h') is None


def test_failed_intraday_refresh_retains_dated_prices_and_explicit_staleness(setup):
    provider,store,factory = setup
    first = provider.intraday('ORCL','1h')
    expire(store,'yahoo:intraday:v1:ORCL:1h',3600)
    factory.history_error = TimeoutError('Synthetic private network diagnostics')
    result = provider.intraday('ORCL','1h')
    assert result['cache_stale'] is result['from_cache'] is True
    assert result['fetched_at'] == first['fetched_at']
    assert result['prices'] == first['prices']
    assert result['upstream_error']['error_code'] == 'DATA_PROVIDER_TIMEOUT'
    assert result['upstream_error']['ticker'] == 'ORCL'
    assert 'private network diagnostics' not in result['upstream_error']['message']
    assert result['cache_warning']
    assert factory.calls['history'] == 3  # Initial request and two bounded timeout attempts.


def test_uncached_intraday_rate_limit_is_not_immediately_retried(setup):
    provider,_,factory = setup
    factory.history_error = DataUnavailable('Synthetic rate limit','upstream_rate_limit',429,True)
    with pytest.raises(DataUnavailable) as caught:
        provider.intraday('ORCL','15m')
    assert caught.value.status == 429
    assert factory.calls['history'] == 1


def test_company_info_uses_persistent_shared_section_cache_and_native_fields(setup):
    provider,store,factory = setup
    first = provider.company_info('orcl')
    second = provider.company_info('ORCL')
    assert first['data']['longName'] == 'SYNTHETIC company fixture'
    assert first['data']['trailingPE'] == 25.
    assert second['from_cache'] is True
    assert first['fetched_at'] == second['fetched_at']
    assert factory.calls['info'] == 1
    assert store.cache_get('yahoo:section:v3:ORCL:company_info') is not None


@pytest.mark.parametrize('missing',[None,[],123,'malformed'])
def test_missing_company_metadata_does_not_invent_names_or_financial_fields(setup,missing):
    provider,_,factory = setup
    factory.info = missing
    result = provider.company_info('ORCL')
    assert result['data'] == {}
    assert result['fetched_at']
    assert result['cache_stale'] is False


def test_company_info_failed_refresh_retains_metadata_timestamp_and_safe_error(setup):
    provider,store,factory = setup
    first = provider.company_info('ORCL')
    expire(store,'yahoo:section:v3:ORCL:company_info',provider.settings.fundamentals_cache_seconds+1)
    factory.info_error = ConnectionError('Synthetic private diagnostics')
    result = provider.company_info('ORCL')
    assert result['cache_stale'] is True
    assert result['data'] == first['data']
    assert result['fetched_at'] == first['fetched_at']
    assert result['upstream_error']['code'] == 'network_error'
    assert factory.calls['info'] == 3


def test_valuation_history_excludes_current_invalid_and_undated_columns(setup):
    provider,_,factory = setup
    factory.valuation = pd.DataFrame({
        'Current':{'Trailing P/E':30},'CURRENT':{'Trailing P/E':31},
        '12/31/2025':{'Trailing P/E':25,'Price/Sales':np.nan},
        pd.Timestamp('2026-03-31'):{'Trailing P/E':26},
        'bad-date':{'Trailing P/E':99},pd.NaT:{'Trailing P/E':100}})
    result = provider.valuation_history('ORCL')
    assert {row['date'] for row in result['rows']} == {'2025-12-31','2026-03-31'}
    assert all(row['values']['Trailing P/E'] in (25.,26.) for row in result['rows'])
    assert next(row for row in result['rows'] if row['date']=='2025-12-31')['values']['Price/Sales'] is None
    assert factory.valuation_kwargs == [{'freq':'quarterly','periods':8}]
    assert 'not verified point-in-time' in result['source']


@pytest.mark.parametrize('missing',[None,[],{},'malformed',pd.DataFrame()])
def test_missing_valuation_table_stays_an_explicit_empty_source_result(setup,missing):
    provider,_,factory = setup
    factory.valuation = missing
    result = provider.valuation_history('ORCL')
    assert result['rows'] == []
    assert result['source'] and result['fetched_at']
    assert result['cache_stale'] is False


def test_valuation_table_cache_reuse_and_stale_failure_preserve_vintage_dates(setup):
    provider,store,factory = setup
    first = provider.valuation_history('ORCL')
    second = provider.valuation_history('orcl')
    assert second['from_cache'] is True
    assert factory.calls['valuation'] == 1
    expire(store,'yahoo:valuation_history:v1:ORCL',86401)
    factory.valuation_error = TimeoutError('Synthetic valuation timeout')
    stale = provider.valuation_history('ORCL')
    assert stale['cache_stale'] is True
    assert stale['fetched_at'] == first['fetched_at']
    assert stale['rows'] == first['rows']
    assert stale['upstream_error']['code'] == 'request_timeout'
    assert factory.calls['valuation'] == 3


def test_etf_company_info_cache_does_not_trigger_corporate_endpoints(setup):
    provider,_,factory = setup
    factory.info = {'symbol':'QQQ','quoteType':'ETF','longName':'SYNTHETIC fund fixture','currency':'USD'}
    metadata = provider.company_info('qqq')
    result = provider.bundle('QQQ')
    assert metadata['data']['quoteType'] == 'ETF'
    assert result['info']['quoteType'] == 'ETF'
    assert factory.calls['info'] == 1
    assert result['sections']['statements']['status'] == 'not_applicable'
    assert factory.calls['valuation'] == 0
    assert factory.forbidden == []
