"""ETF safeguards use explicit synthetic prices/metadata; no real upstream requests."""
import math
from collections import Counter
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.analysis.fundamentals import analyze_fundamentals
from app.analysis.valuation import analyze_valuation
from app.config import Settings
from app.instruments import instrument_type, is_fund
from app.main import create_app
from app.providers.demo import DemoProvider
from app.providers.yahoo import YahooFinanceProvider, records_frame
from app.storage import Store


@pytest.mark.parametrize('info,kind,fund',[
    ({'quoteType':'ETF'},'ETF',True),
    ({'quoteType':' mutualfund '},'MUTUALFUND',True),
    ({'quoteType':'EQUITY'},'EQUITY',False),
    ({'symbol':'QQQ'},None,False),
    ({'symbol':'SPY','quoteType':None},None,False),
    ({'quoteType':''},None,False),
    ({'quoteType':True},None,False),
    (None,None,False),
])
def test_instrument_identity_uses_source_type_without_ticker_maps(info,kind,fund):
    assert instrument_type(info) == kind
    assert is_fund(info) is fund


@pytest.mark.parametrize('quote_type',['ETF','MUTUALFUND'])
def test_funds_do_not_score_missing_or_accidental_corporate_statements(quote_type):
    corporate = DemoProvider().bundle('SYNTHETIC')['statements']
    info = {'quoteType':quote_type,'sector':'Technology','industry':'Software'}
    for statements in ({},corporate):
        result = analyze_fundamentals(statements,info)
        assert result['applicable'] is False
        assert result['instrument_type'] == quote_type
        assert result['score'] is result['risk_score'] is None
        assert result['confidence'] == 0
        assert result['metrics'] == {}
        assert result['periods'] == result['quarterly_periods'] == []
        assert result['reporting_date'] is result['quarterly_reporting_date'] is None
        assert any('fund' in text for text in result['signals'])


@pytest.mark.parametrize('quote_type',['ETF','MUTUALFUND'])
def test_fund_valuation_keeps_portfolio_metadata_and_blocks_corporate_yields_and_dcf(quote_type):
    info = {'quoteType':quote_type,'trailingPE':30,'navPrice':100,'totalAssets':1e9,
            'currentPrice':101,'marketCap':1e9,'trailingEps':5,'freeCashflow':1e8,'sharesOutstanding':1e7}
    assumptions = {'base_fcf':1e8,'shares':1e7,'growth':.05,'discount_rate':.1,'terminal_growth':.02,'years':5}
    for requested in (None,assumptions):
        result = analyze_valuation(info,{},requested)
        assert result['applicable'] is False
        assert result['score'] is None
        assert result['confidence'] == 0
        assert result['scenarios'] == {}
        assert result['assumptions'] is None
        assert result['metrics'] == {'portfolio_pe':30.,'nav_price':100.,'total_assets':1e9}
        assert 'trailing_pe' not in result['metrics']
        assert 'earnings_yield' not in result['metrics']
        assert 'fcf_yield' not in result['metrics']
        assert any('portfolio' in text.lower() for text in result['signals'])
        assert any('DCF' in text for text in result['limitations'])


@pytest.mark.parametrize('bad',[None,0,-1,math.nan,math.inf,True,'unavailable'])
def test_fund_metrics_missing_invalid_nonpositive_are_not_invented(bad):
    result = analyze_valuation({'quoteType':'ETF','trailingPE':bad,'navPrice':bad,'totalAssets':bad},{})
    assert result['metrics'] == {'portfolio_pe':None,'nav_price':None,'total_assets':None}
    assert 'expense_ratio' not in result['metrics']


def test_normal_equity_dcf_and_specialized_bank_guards_remain_intact():
    info = {'quoteType':'EQUITY','currentPrice':100,'freeCashflow':100,'sharesOutstanding':10,
            'trailingEps':5,'trailingPE':20,'marketCap':1000}
    result = analyze_valuation(info,{}, {'growth':.05,'discount_rate':.1,'terminal_growth':.02})
    assert result['scenarios']['base']['value_per_share'] > 0
    assert result['score'] is not None
    assert result.get('applicable') is not False
    statements = DemoProvider().bundle('SYNTHETIC')['statements']
    operating = analyze_fundamentals(statements,{'quoteType':'EQUITY','sector':'Technology'})
    bank = analyze_fundamentals(statements,{'quoteType':'EQUITY','industry':'Banks - Diversified'})
    assert operating['score'] is not None
    assert bank['score'] is bank['risk_score'] is None
    assert bank['metrics']['roic'] is None
    assert any('Banks' in text for text in bank['limitations'])


class FundSpyFactory:
    """Any attempted corporate getter is recorded even if an adapter catches its error."""
    def __init__(self):
        self.demo = DemoProvider()
        self.calls = Counter()
        self.forbidden_calls = []

    def __call__(self,symbol):
        owner = self
        fixture = deepcopy(self.demo.bundle(symbol))
        class Ticker:
            def history(self,**kwargs):
                owner.calls['history'] += 1
                return records_frame(fixture['history']['prices'])

            def get_info(self):
                owner.calls['info'] += 1
                return {'symbol':symbol,'quoteType':'ETF','longName':f'SYNTHETIC {symbol} fund fixture',
                        'currency':'USD','regularMarketPrice':fixture['info']['regularMarketPrice'],
                        'regularMarketTime':fixture['info']['regularMarketTime'],
                        'trailingPE':30.,'navPrice':100.,'totalAssets':1e9}

            def get_news(self,**kwargs):
                owner.calls['news'] += 1
                return []

            def forbidden(self,*args,**kwargs):
                owner.forbidden_calls.append('corporate getter')
                raise AssertionError('Corporate getter must not run for a fund')

            get_income_stmt = forbidden
            get_balance_sheet = forbidden
            get_cash_flow = forbidden
            get_calendar = forbidden
            get_analyst_price_targets = forbidden
            get_earnings_history = forbidden
            get_earnings_estimate = forbidden
        return Ticker()


@pytest.mark.parametrize('symbol',['QQQ','SPY'])
def test_fund_full_api_preserves_prices_and_technical_analysis_without_corporate_calls(tmp_path,symbol):
    settings = Settings(_env_file=None,database_url='sqlite:///:memory:',data_dir=tmp_path,
                        demo=False,background_refresh=False,request_limit=1000)
    store = Store(settings.database_url)
    factory = FundSpyFactory()
    provider = YahooFinanceProvider(store,settings,factory)
    with TestClient(create_app(settings,provider,store)) as client:
        for endpoint in ('history','technical','overview','research'):
            response = client.get(f'/api/stocks/{symbol}/{endpoint}')
            assert response.status_code == 200,response.text
        data = response.json()
        assert data['ticker'] == data['overview']['ticker'] == symbol
        assert data['overview']['asset_type'] == 'ETF'
        assert data['overview']['is_fund'] is True
        assert data['overview']['price'] > 0
        assert len(data['history']['prices']) > 100
        assert data['technical']['score'] is not None
        assert data['risk']['score'] is not None
        assert data['fundamentals']['applicable'] is False
        assert data['valuation']['applicable'] is False
        assert data['valuation']['metrics']['portfolio_pe'] == 30
        assert data['score']['company_quality'] is data['score']['overall'] is None
        assert data['trade_plan']['position_size'] == 0
        for section in ('statements','company_events','analyst','earnings'):
            assert data['data_quality']['sections'][section]['status'] == 'not_applicable'
        assert 'Corporate financial statements' in data['report']['markdown']
        result = client.post(f'/api/stocks/{symbol}/valuation',json={
            'growth':.05,'discount_rate':.1,'terminal_growth':.02,'base_fcf':1e8,'shares':1e7})
        assert result.status_code == 200,result.text
        assert result.json()['applicable'] is False
        assert result.json()['scenarios'] == {}
        assert factory.calls == Counter({'history': 1, 'info': 1, 'news': 1})
        assert factory.forbidden_calls == []
