import json
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.providers.demo import DemoProvider
from app.providers.yahoo import DataUnavailable


class SmallFixture(DemoProvider):
    def history(self,ticker,period='1y',interval='1d'):
        result=super().history(ticker,period,interval)
        return {**result,'prices':result['prices'][-320:]}
    def intraday(self,*args):raise DataUnavailable('Synthetic intraday outage')
    def valuation_history(self,ticker):
        return {'rows':[{'date':f'202{i}-12-31','values':{'Trailing P/E':20+i}} for i in range(2,6)],'source':'Synthetic vendor snapshots'}


def test_full_quantitative_api_is_finite_and_reuses_unchanged_validation(tmp_path,monkeypatch):
    from app.analysis import quantitative
    original=quantitative.validate_strategies;calls=[]
    def observed(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(quantitative,'validate_strategies',observed)
    settings=Settings(_env_file=None,database_url='sqlite:///:memory:',data_dir=tmp_path,demo=True,background_refresh=False,request_limit=1000)
    with TestClient(create_app(settings,SmallFixture())) as client:
        r=client.get('/api/stocks/TEST/quantitative')
        assert r.status_code==200,r.text
        data=r.json();json.dumps(data,allow_nan=False)
        assert data['ticker']=='TEST' and data['methodology_version']=='2.0'
        assert len(data['strategies'])==4 and len(data['timeframes']['timeframes'])==5
        assert all(s['status'] in ('wait','eligible','avoid','insufficient_data','not_applicable') for s in data['strategies'])
        assert data['probabilities']['status']=='Insufficient historical evidence'
        assert data['probabilities']['estimates']['target_1_before_stop'] is None
        assert data['validation']['strategies']['fundamental_value']['status']=='Insufficient historical evidence'
        assert data['evidence']['model_uncertainty']['calibrated'] is False
        assert 'Historical probability evidence' in data['report']['markdown']
        assert client.get('/api/stocks/TEST/quantitative').status_code==200
        assert len(calls)==1
        saved=client.post('/api/stocks/TEST/quantitative/report',json={})
        assert saved.status_code==200 and 'Historical probability evidence' in saved.json()['markdown']
        assert len(calls)==1
        custom=client.post('/api/stocks/TEST/quantitative',json={'valuation_assumptions':{'enable_dcf':True,'growth':.05,'discount_rate':.1,'terminal_growth':.02,'earnings_multiples':[10,20,30]}})
        assert custom.status_code==200,custom.text
        assert custom.json()['valuation']['valuation_range']['base']>0
        assert len(calls)==1
        assert client.post('/api/stocks/TEST/quantitative',json={'min_samples':1}).status_code==422
        assert client.post('/api/stocks/TEST/quantitative',json={'valuation_assumptions':{'fcf_yields':[.02,.05,.1]}}).status_code==422


def test_current_company_report_uses_new_core_and_explains_wait(tmp_path):
    settings=Settings(_env_file=None,database_url='sqlite:///:memory:',data_dir=tmp_path,demo=True,background_refresh=False)
    with TestClient(create_app(settings,SmallFixture())) as client:
        r=client.get('/api/stocks/TEST/research')
        assert r.status_code==200,r.text
        data=r.json()
        assert data['quant_core']['methodology_version']=='2.0'
        assert data['quant_core']['recommendation']['position_size']==0
        assert data['quant_core']['recommendation']['recommendation']!='Buy candidate'
        assert data['score']==data['quant_core']['score_adapter']
        assert data['trade_plan']==data['quant_core']['recommendation']
        assert data['valuation']==data['quant_core']['valuation']
        assert 'V2 basis: Insufficient valuation evidence' in data['report']['markdown']
        assert '25000.00' in client.post('/api/stocks/TEST/reports',json={'capital':25000}).json()['markdown']


def test_observed_calendar_span_does_not_certify_event_completeness():
    from app.analysis.quantitative import event_risk
    base={'macro':{'coverage':{'first_scheduled_at':'2026-01-01T00:00:00Z','last_scheduled_at':'2027-01-01T00:00:00Z'}}}
    assert event_risk(base,now='2026-10-26T12:00:00Z')['coverage_status']=='incomplete'


def test_shared_strategy_backtest_api_keeps_legacy_default_and_supports_comparison(tmp_path):
    settings=Settings(_env_file=None,database_url='sqlite:///:memory:',data_dir=tmp_path,demo=True,background_refresh=False,request_limit=1000)
    with TestClient(create_app(settings,SmallFixture())) as client:
        result=client.post('/api/backtest',json={'ticker':'TEST','strategy':'all'})
        assert result.status_code==200,result.text
        data=result.json();json.dumps(data,allow_nan=False)
        assert set(data['validation']['strategies'])=={'trend_following','breakout','mean_reversion','fundamental_value'}
        assert data['validation']['strategies']['fundamental_value']['status']=='Insufficient historical evidence'
        legacy=client.post('/api/backtest',json={'ticker':'TEST'})
        assert legacy.status_code==200 and 'equity_curve' in legacy.json()


def test_future_reported_quote_is_rejected_for_current_valuation():
    from datetime import datetime,timedelta,timezone
    from app.service import overview_from
    bundle=SmallFixture().bundle('TEST')
    for timestamp in ((datetime.now(timezone.utc)+timedelta(hours=12)).timestamp(),1e99):
        bundle['info']['regularMarketTime']=timestamp
        bundle['info']['regularMarketPrice']=42
        result=overview_from(bundle)
        assert result['price']==bundle['history']['prices'][-1]['close']
        assert result['quote_timestamp_precision']=='Synthetic fixture timestamp'
