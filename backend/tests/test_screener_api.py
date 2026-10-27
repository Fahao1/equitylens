"""Synthetic adapter integration; CI never discovers or prices actual securities."""
import json
from threading import Event
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.providers.demo import DemoProvider
from app.providers.yahoo import DataUnavailable
from app.utils import iso_now


class SyntheticPrices(DemoProvider):
    def history(self,*args,**kwargs):
        result=super().history(*args,**kwargs)
        return {**result,'prices':result['prices'][-260:]}
    def intraday(self,*args,**kwargs):raise DataUnavailable('Synthetic intraday outage','provider_unavailable',503,True)
    def valuation_history(self,*args,**kwargs):return {'rows':[],'source':'Synthetic empty vendor history'}


class SyntheticUniverse:
    def __init__(self,wait=None,error=None):self.calls=0;self.wait=wait;self.error=error
    def discover(self,config):
        self.calls+=1
        if self.wait:self.wait.wait(10)
        if self.error:raise self.error
        return {'members':[{'ticker':t,'name':f'Synthetic {t}','sector':'Technology','exchange':'NMS','listing_country':'US','market_cap':1e11-i*1e9,'average_volume':500000,'currency':'USD','quoteType':'EQUITY'} for i,t in enumerate(['TESTA','TESTB','TESTC'])],
            'source':'Explicit synthetic universe fixture','fetched_at':iso_now(),'coverage':{'comprehensive':False,'pagination_complete':True},'limitations':['Synthetic test observations, not actual listings.']}


def settings(tmp_path):return Settings(_env_file=None,database_url=f'sqlite:///{tmp_path}/test.db',data_dir=tmp_path,demo=True,background_refresh=False,request_limit=1000,screener_request_delay=0)


def test_background_screen_publishes_both_distinct_horizons_and_persists(tmp_path):
    universe=SyntheticUniverse();config=settings(tmp_path)
    app=create_app(config,SyntheticPrices(),universe_provider=universe)
    with TestClient(app) as client:
        initial=client.get('/api/screener/tech/rankings').json()
        assert initial['rankings']==[] and initial['run_id'] is None and universe.calls==0
        response=client.post('/api/screener/tech/refresh',json={'max_deep_analysis':2,'auto_refresh':False})
        assert response.status_code==202,response.text
        run_id=response.json()['job']['id']
        app.state.screener.future.result(timeout=30)
        status=client.get('/api/screener/tech/status').json()
        assert status['job']['status']=='completed',status
        a=client.get('/api/screener/tech/rankings?horizon=short_term').json()
        b=client.get('/api/screener/tech/rankings?horizon=long_term').json()
        json.dumps([a,b],allow_nan=False)
        assert a['run_id']==b['run_id']==run_id
        assert a['weights']!=b['weights']
        assert a['coverage']['total_eligible']==3 and a['coverage']['deep_analyzed']==2
        assert a['coverage']['comprehensive'] is False
        assert any(row['analysis_stage']=='broad' for row in a['unranked'])
        assert all(not row['eligible_buy'] for row in a['rankings']+a['unranked'])
        assert client.get('/api/screener/tech/top-candidate').json()['message']=='No qualified buy candidate found.'
        assert client.get('/api/screener/tech/watchlist-candidates').status_code==200
        assert len(client.get('/api/screener/tech/universe').json()['members'])==3
        assert universe.calls==1
        backtest=client.post('/api/screener/tech/backtest',json={'top_n':5}).json()
        assert backtest['status']=='Insufficient historical evidence' and backtest['metrics'] is None
    with TestClient(create_app(config,SyntheticPrices(),universe_provider=SyntheticUniverse())) as client:
        assert client.get('/api/screener/tech/rankings').json()['run_id']==run_id


def test_duplicate_background_request_does_not_start_parallel_work(tmp_path):
    release=Event();universe=SyntheticUniverse(wait=release)
    app=create_app(settings(tmp_path),SyntheticPrices(),universe_provider=universe)
    with TestClient(app) as client:
        first=client.post('/api/screener/tech/refresh',json={'max_deep_analysis':1}).json()
        try:
            second=client.post('/api/screener/tech/refresh',json={'horizon':'long_term'}).json()
            assert second['accepted'] is False and second['job']['id']==first['job']['id']
            assert client.get('/api/screener/tech/status').json()['job']['status'] in ('queued','running')
        finally:release.set()
        app.state.screener.future.result(timeout=30)
        assert universe.calls==1


def test_outage_and_restart_of_unfinished_job_do_not_fabricate_rankings(tmp_path):
    app=create_app(settings(tmp_path),SyntheticPrices(),universe_provider=SyntheticUniverse(error=DataUnavailable('Synthetic discovery outage','provider_unavailable',503,True)))
    with TestClient(app) as client:
        client.post('/api/screener/tech/refresh',json={});app.state.screener.future.result(timeout=10)
        data=client.get('/api/screener/tech/rankings').json()
        assert data['rankings']==[] and data['job']['status']=='failed' and data['provider_errors']
        for body in ({'horizon':'daily'},{'max_deep_analysis':100},{'weights':{'technical_strength':1}},{'existing_shares':1},{'filters':{'market_cap_min':100,'market_cap_max':10}}):
            assert client.post('/api/screener/tech/refresh',json=body).status_code==422
