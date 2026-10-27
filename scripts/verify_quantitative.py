"""Intentional live HTTP verification; no synthetic fallback or inferred probabilities."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--tickers',nargs='+',default=['MSFT','AAPL','NVDA','ORCL','QQQ','SPY'])
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=root/'docs'/'QUANT_LIVE_VERIFICATION.json'
    report={'verified_at':datetime.now(timezone.utc).isoformat(),'transport':'Actual HTTP to running FastAPI; vendor caches and freshness retained','results':[]}
    with httpx.Client(base_url=args.base_url,timeout=180) as client:
        report['health']=client.get('/health').json()
        for ticker in args.tickers:
            research=client.get(f'/api/stocks/{ticker}/research')
            response=client.get(f'/api/stocks/{ticker}/quantitative')
            base=research.json();data=response.json()
            row={'ticker':ticker,'http_status':{'research':research.status_code,'quantitative':response.status_code}}
            if response.is_success and research.is_success:
                json.dumps(data,allow_nan=False)
                strategies=data.get('strategies',[]);prob=data.get('probabilities',{})
                row.update(name=base['overview']['name'],asset_type=base['overview']['asset_type'],quote=base['overview']['price'],quote_at=base['overview']['quote_at'],
                    price_source=base['overview']['source'],market_fetched_at=base['history'].get('fetched_at'),source_sections=base['data_quality'].get('sections'),
                    decision_bar_as_of=data['source']['decision_bar_as_of'],regime=data['regime'],scores=data['scores'],
                    timeframes=[{k:t.get(k) for k in ('timeframe','status','bars','last_bar_end','source','confidence')} for t in data.get('timeframes',{}).get('timeframes',[])],
                    strategy_statuses={s['id']:{'status':s['status'],'eligible':s['eligible'],'avoid_reasons':s['avoid_reasons']} for s in strategies},
                    validation={k:{'status':v.get('status'),'metrics':v.get('metrics'),'out_of_sample':v.get('out_of_sample')} for k,v in data.get('validation',{}).get('strategies',{}).items()},
                    probabilities=prob,recommendation=data['recommendation']['recommendation'],event_risk=data['event_risk'],limitations=data['evidence']['limitations'])
                row['passed']=len(strategies)==4 and len(row['timeframes'])==5 and data['ticker']==ticker and base['overview']['price']>0 and base['data_quality']['mode']=='live provider'
                if base['overview']['is_fund']:
                    row['passed'] &= data['scores']['company_quality'] is None and data['scores']['overall_investment_attractiveness'] is None
                if prob.get('status')=='Insufficient historical evidence':
                    row['passed'] &= prob.get('estimates',{}).get('target_1_before_stop') is None
                (root/'data'/f'quantitative_{ticker}.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
                if ticker=='MSFT':
                    (root/'docs'/'reports'/'MSFT_quantitative.md').write_text(data.get('report',base['report'])['markdown']+'\n')
            else:row.update(passed=False,error=data)
            report['results'].append(row)
            output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            print(json.dumps({'ticker':ticker,'passed':row['passed'],'status':row['http_status'],'regime':row.get('regime',{}).get('regime'),'probability_status':row.get('probabilities',{}).get('status')}),flush=True)
    return 0 if all(r['passed'] for r in report['results']) else 1


if __name__=='__main__':raise SystemExit(main())
