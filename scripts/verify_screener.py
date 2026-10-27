"""Intentional live HTTP checks; test tickers never determine universe or ranking."""
import argparse
import json
import time
from datetime import datetime,timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=['AAPL','MSFT','NVDA','AMD','META','GOOGL','AMZN','ORCL','CRM','PLTR','INTC','MU','AVGO','ADBE','CRWD']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    report={'verified_at':datetime.now(timezone.utc).isoformat(),'transport':'Actual running FastAPI HTTP, original provider cache/source timestamps retained','base_url':args.base_url,'rankings':{},'representative_research':[]}
    with httpx.Client(base_url=args.base_url,timeout=120) as client:
        health=client.get('/health');health.raise_for_status();report['health']=health.json()
        if args.refresh:
            response=client.post('/api/screener/tech/refresh',json={'horizon':'short_term','max_deep_analysis':15,'valuation_assumptions':{'enable_dcf':True,'growth':.05,'discount_rate':.10,'terminal_growth':.02,'years':5}})
            response.raise_for_status();report['refresh']=response.json();deadline=time.monotonic()+900;previous=None
            while time.monotonic()<deadline:
                data=client.get('/api/screener/tech/status').json();job=data.get('job') or {}
                state=(job.get('status'),job.get('deep_processed'),job.get('message'))
                if state!=previous:print(json.dumps({'job':job}),flush=True);previous=state
                if job.get('status') in ('completed','failed'):break
                time.sleep(3)
            assert job.get('status')=='completed',job
        universe=client.get('/api/screener/tech/universe');universe.raise_for_status();u=universe.json()
        report['universe']={k:u.get(k) for k in ('source','as_of','coverage','limitations')}
        members={row['ticker'] for row in u.get('members',[])}
        assert members and len(members)==len(u['members']) and u['coverage']['comprehensive'] is False
        for horizon in ('short_term','long_term'):
            response=client.get('/api/screener/tech/rankings',params={'horizon':horizon});response.raise_for_status();data=response.json()
            json.dumps(data,allow_nan=False)
            rows=data['rankings'];assert all(r['ticker'] in members and r['analysis_stage']=='deep' for r in rows)
            assert [r['overall_score'] for r in rows]==sorted([r['overall_score'] for r in rows],reverse=True)
            assert all(not r.get('eligible_buy') or r.get('recommendation')=='Buy Candidate' for r in rows)
            assert all(r['plan']['position_size']==0 for r in rows if not r['eligible_buy'])
            report['rankings'][horizon]={k:data.get(k) for k in ('run_id','as_of','weights','coverage','configuration','provider_errors','limitations')}
            report['rankings'][horizon]['top10']=[{k:r.get(k) for k in ('rank','ticker','name','price','currency','overall_score','company_quality','technical_strength','valuation_attractiveness','recommendation','confidence','data_completeness','metrics_evaluated','missing_information','quote_at','fetched_at')} for r in rows[:10]]
            top=client.get('/api/screener/tech/top-candidate',params={'horizon':horizon});top.raise_for_status()
            report['rankings'][horizon]['candidate_message']=top.json()['message']
            report['rankings'][horizon]['best_eligible_ticker']=(top.json().get('best_eligible') or {}).get('ticker')
            assert client.get('/api/screener/tech/watchlist-candidates',params={'horizon':horizon}).status_code==200
        assert report['rankings']['short_term']['weights']!=report['rankings']['long_term']['weights']
        for ticker in EXAMPLES:
            response=client.get(f'/api/stocks/{ticker}/research');data=response.json();o=data.get('overview',{})
            row={'ticker':ticker,'http_status':response.status_code,'in_discovered_universe':ticker in members,'name':o.get('name'),'price':o.get('price'),'quote_at':o.get('quote_at'),
                'source':o.get('source'),'bars':len(data.get('history',{}).get('prices',[])),'technical_score':data.get('technical',{}).get('score'),'financial_score':data.get('fundamentals',{}).get('score'),
                'source_sections':data.get('data_quality',{}).get('sections'),'error':data.get('detail')}
            row['passed']=response.status_code==200 and data['ticker']==ticker and o.get('price',0)>0 and row['technical_score'] is not None and data['data_quality']['mode']=='live provider'
            report['representative_research'].append(row)
            print(json.dumps({'ticker':ticker,'passed':row['passed'],'http_status':response.status_code}),flush=True)
        replay=client.post('/api/screener/tech/backtest',json={'horizon':'long_term','top_n':5});replay.raise_for_status();report['published_ranking_backtest']=replay.json()
    report['passed']=all(r['passed'] for r in report['representative_research'])
    (ROOT/'docs'/'SCREENER_LIVE_VERIFICATION.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':report['passed'],'discovered':len(members),'deep_analyzed':report['rankings']['short_term']['coverage']['deep_analyzed'],'ranked':{h:r['coverage']['ranked'] for h,r in report['rankings'].items()},'backtest':report['published_ranking_backtest']['status']}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
