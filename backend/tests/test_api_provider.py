"""All upstream observations in these tests are explicit synthetic fixtures."""
from datetime import datetime,timezone,timedelta
import json
import pytest
import pandas as pd
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.providers.demo import DemoProvider
from app.providers.yahoo import YahooFinanceProvider, DataUnavailable, normalize_news
from app.storage import Store, Cache
from app.service import overview_from
from app.utils import clean


@pytest.fixture
def client(tmp_path):
    settings=Settings(database_url='sqlite:///:memory:',data_dir=tmp_path,background_refresh=False,demo=True,request_limit=1000)
    with TestClient(create_app(settings,DemoProvider())) as c: yield c


def test_api_research_and_individual_sections(client):
    r=client.get('/api/stocks/TEST/research')
    assert r.status_code==200,r.text
    data=r.json()
    assert data['fundamentals']['score'] is not None and data['score']['company_quality'] is not None
    assert data['macro']['score'] is None and data['news']['score'] is None
    assert data['overview']['stale'] is False and 'SYNTHETIC' in data['overview']['quote_type']
    assert 'NaN' not in r.text and 'Infinity' not in r.text
    for section in ['overview','history','technical','fundamentals','valuation','news','macro-impact','score']:
        assert client.get('/api/stocks/TEST/'+section).status_code==200


def test_watchlist_reports_trade_validation(client):
    assert client.post('/api/watchlist',json={'ticker':'test'}).json()['items'][0]['ticker']=='TEST'
    client.post('/api/watchlist',json={'ticker':'TEST'})
    assert len(client.get('/api/watchlist').json()['items'])==1
    assert client.post('/api/stocks/TEST/reports').status_code==200
    assert '# TEST' in client.get('/api/reports').json()['items'][0]['markdown']
    assert client.delete('/api/watchlist/TEST').json()['items']==[]
    assert client.post('/api/stocks/TEST/trade-plan',json={'capital':-1}).status_code==422
    assert client.post('/api/stocks/TEST/trade-plan',json={'weights':{'financial':.9}}).status_code==422
    assert client.get('/api/stocks/INVALID!TICKER/research').status_code==422
    assert client.post('/api/stocks/TEST/trade-plan',json={'capital':25000}).json()['risk_budget']==250


def test_calendar_import_timezone_and_missing_actual(client):
    assert client.get('/api/economic-calendar').json()['status']=='not_imported'
    content=json.dumps([{'title':'Synthetic CPI test','country':'USD','date':(datetime.now(timezone.utc)+timedelta(hours=6)).isoformat(),'impact':'High','forecast':'0.3%'}])
    r=client.post('/api/economic-calendar/import',json={'content':content,'format':'json'})
    assert r.status_code==200,r.text
    events=client.get('/api/economic-calendar/high-impact?timezone=America/Los_Angeles').json()['events']
    assert len(events)==1 and events[0]['actual'] is None and events[0]['surprise']['value'] is None
    assert events[0]['scheduled_local']!=events[0]['scheduled_at']
    assert client.get('/api/economic-calendar?timezone=Not/AZone').status_code==422
    assert client.post('/api/economic-calendar/import',json={'content':'<html>denied</html>','format':'json'}).status_code==422
    assert client.post('/api/economic-calendar/import',json={'content':'x'*3_000_001}).status_code==413


def test_backtest_and_explicit_dcf(client):
    r=client.post('/api/backtest',json={'ticker':'TEST','fast_period':10,'slow_period':30})
    assert r.status_code==200,r.text
    assert r.json()['validation']['macro_used'] is False
    assert len(r.json()['equity_curve'])>200
    assert client.post('/api/backtest',json={'ticker':'TEST','macro_score':10}).status_code==422
    r=client.post('/api/stocks/TEST/valuation',json={'growth':.05,'discount_rate':.1,'terminal_growth':.02})
    assert r.status_code==200 and r.json()['scenarios']['base']['value_per_share']>0


def test_auth_rate_limit_and_outage(tmp_path):
    s=Settings(database_url='sqlite:///:memory:',data_dir=tmp_path,background_refresh=False,api_token='fixture-secret',request_limit=2)
    with TestClient(create_app(s,DemoProvider())) as c:
        assert c.get('/api/watchlist').status_code==401
        h={'Authorization':'Bearer fixture-secret'}
        assert c.get('/api/watchlist',headers=h).status_code==200
        assert c.get('/api/watchlist',headers=h).status_code==200
        assert c.get('/api/watchlist',headers=h).status_code==429
    class Outage(DemoProvider):
        def bundle(self,*a):raise DataUnavailable('Synthetic outage')
    with TestClient(create_app(Settings(database_url='sqlite:///:memory:',data_dir=tmp_path,background_refresh=False),Outage())) as c:
        assert c.get('/api/stocks/TEST/research').status_code==503


def test_newer_price_bar_wins_over_old_info():
    b=DemoProvider().bundle('TEST')
    b['info']['regularMarketTime']=(datetime.now(timezone.utc)-timedelta(days=10)).timestamp()
    b['info']['regularMarketPrice']=1
    o=overview_from(b)
    assert o['price']==b['history']['prices'][-1]['close']


def test_newer_history_fetch_wins_over_same_session_cached_quote():
    b=DemoProvider().bundle('TEST')
    b['info']['regularMarketTime']=datetime.now(timezone.utc).timestamp()
    b['info']['regularMarketPrice']=1
    b['sections']={'company_info':{'fetched_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}}
    assert overview_from(b)['price']==b['history']['prices'][-1]['close']


def test_search_api_validation_and_price_stage_is_independent(tmp_path):
    class Search:
        def search(self,q):
            return {'query':q,'results':[{'symbol':'ORCL','name':'Oracle fixture','exchange':'NYSE','asset_type':'EQUITY'}],'source':'Mock search','fetched_at':'2026-01-01T00:00:00+00:00'}
    class SlowOptional(DemoProvider):
        def bundle(self,*args):
            raise DataUnavailable('Optional aggregate is unavailable')
    settings=Settings(database_url='sqlite:///:memory:',data_dir=tmp_path,background_refresh=False,demo=False)
    with TestClient(create_app(settings,SlowOptional(),search_provider=Search())) as c:
        assert c.get('/api/search?q=Oracle').json()['results'][0]['symbol']=='ORCL'
        assert c.get('/api/search?q=').status_code==422
        assert c.get('/api/stocks/ORCL/technical').status_code==200
        assert c.get('/api/stocks/ORCL/history').status_code==200
        assert c.get('/api/stocks/ORCL/research').status_code==503


def test_provider_pretty_labels_and_stale_cache(tmp_path):
    store=Store('sqlite:///:memory:')
    class Ticker:
        fail=False
        def __init__(self,*a): pass
        def history(self,**kw):
            if self.fail:raise DataUnavailable('Fixture outage')
            from app.providers.yahoo import records_frame
            return records_frame(DemoProvider().history('TEST')['prices'])
        def get_info(self):return {}
        def get_income_stmt(self,*,freq,pretty):
            assert pretty is True
            return pd.DataFrame({pd.Timestamp('2025-06-30'):{'Total Revenue':100}})
        get_balance_sheet=get_income_stmt
        get_cash_flow=get_income_stmt
        def get_news(self,**kw):return []
        def get_calendar(self):return {}
        def get_analyst_price_targets(self):return {}
        def get_earnings_history(self):return None
        def get_earnings_estimate(self):return None
    p=YahooFinanceProvider(store,Settings(data_dir=tmp_path),Ticker)
    assert p.bundle('TEST')['statements']['annual_income'][0]['values']['Total Revenue']==100
    Ticker.fail=True
    with store.session.begin() as s:
        s.get(Cache,'yahoo:history:TEST:5y:1d').updated_at=datetime.now(timezone.utc)-timedelta(hours=2)
    assert p.history('TEST')['cache_stale'] is True


def test_malformed_news_and_json_numbers():
    rows=normalize_news([None,'invalid',{'content':{'title':'Synthetic headline','canonicalUrl':{'url':'https://example.com/news'},'summary':'Fixture'}},{'title':'Unsafe','link':'javascript:alert(1)'}])
    assert len(rows)==1 and rows[0]['content_scope']=='summary'
    assert clean({'a':True,'b':float('nan')})=={'a':True,'b':None}


def test_saved_report_retains_custom_assumptions_and_ai_cache(tmp_path,monkeypatch):
    calls=[]
    def synthesize(articles,settings):
        calls.append(1)
        return {'used':True,'markdown':'## Optional AI test narrative\n\nSynthetic mocked text only.','limitations':['Synthetic AI test output.']}
    monkeypatch.setattr('app.analysis.llm.synthesize_news',synthesize)
    settings=Settings(database_url='sqlite:///:memory:',data_dir=tmp_path,background_refresh=False,demo=True,llm_api_key='fixture-only')
    with TestClient(create_app(settings,DemoProvider())) as c:
        r=c.post('/api/stocks/TEST/reports',json={'capital':25000})
        assert r.status_code==200 and r.json()['llm_used'] is True
        assert '25000.00' in r.json()['markdown']
        c.post('/api/stocks/TEST/reports',json={'capital':25000})
        assert len(calls)==1
