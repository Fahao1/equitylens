"""Intentional live checks through the running FastAPI HTTP endpoints, not provider mocks."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--tickers',nargs='+',default=['AAPL','NVDA','ORCL','QQQ','SPY'])
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'docs'/'ETF_API_VERIFICATION.json')
    args=parser.parse_args()
    report={'verified_at':datetime.now(timezone.utc).isoformat(),'base_url':args.base_url,'transport':'Actual HTTP requests to the running FastAPI service','results':[]}
    with httpx.Client(base_url=args.base_url,timeout=100) as client:
        health=client.get('/health');report['health']={'http_status':health.status_code,'body':health.json()}
        for symbol in args.tickers:
            row={'ticker':symbol,'endpoints':{}}
            for endpoint in ('history','technical','overview','research'):
                response=client.get(f'/api/stocks/{symbol}/{endpoint}')
                try: data=response.json()
                except ValueError: data={}
                item={'http_status':response.status_code,'error':data.get('detail')}
                if endpoint=='history':
                    item.update(bars=len(data.get('prices',[])),source=data.get('source'),fetched_at=data.get('fetched_at'),from_cache=data.get('from_cache'),cache_stale=data.get('cache_stale'))
                elif endpoint=='technical':
                    item.update(ticker=data.get('ticker'),technical_score=data.get('score'))
                elif endpoint=='overview':
                    item.update(ticker=data.get('ticker'),name=data.get('name'),asset_type=data.get('asset_type'),price=data.get('price'),quote_at=data.get('quote_at'))
                else:
                    item.update(ticker=data.get('ticker'),name=data.get('overview',{}).get('name'),asset_type=data.get('overview',{}).get('asset_type'),technical_score=data.get('technical',{}).get('score'),financial_score=data.get('fundamentals',{}).get('score'),financial_applicable=data.get('fundamentals',{}).get('applicable'),valuation_applicable=data.get('valuation',{}).get('applicable'),company_quality=data.get('score',{}).get('company_quality'),score_ticker=data.get('score',{}).get('ticker'),plan_ticker=data.get('trade_plan',{}).get('ticker'),sections=data.get('data_quality',{}).get('sections'))
                row['endpoints'][endpoint]=item
            row['passed']=all(x['http_status']==200 for x in row['endpoints'].values()) and row['endpoints']['history'].get('bars',0)>0 and row['endpoints']['technical'].get('technical_score') is not None and row['endpoints']['research'].get('score_ticker')==symbol and row['endpoints']['research'].get('plan_ticker')==symbol
            report['results'].append(row)
            args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            print(json.dumps({'ticker':symbol,'passed':row['passed'],'statuses':{k:v['http_status'] for k,v in row['endpoints'].items()},'asset_type':row['endpoints']['overview'].get('asset_type')}),flush=True)
    return 0 if all(r['passed'] for r in report['results']) else 1


if __name__=='__main__':
    sys.exit(main())
