from typing import Literal
from fastapi import APIRouter,Query
from app.schemas import JsonResponse
from app.utils import clean
from .schemas import Horizon,ScreenRequest,ScreenResponse,ScreenerBacktestRequest


def make_screener_router(service,provider,store):
    router=APIRouter(prefix='/api/screener/tech',tags=['Tech Stock Screener'])

    @router.get('/universe',response_model=JsonResponse)
    def universe():return service.universe_snapshot()

    @router.get('/rankings',response_model=ScreenResponse)
    def rankings(horizon:Horizon='short_term',min_overall:float | None=Query(None,ge=0,le=10),min_technical:float | None=Query(None,ge=0,le=10),min_valuation:float | None=Query(None,ge=0,le=10)):
        filters={k:v for k,v in {'min_overall':min_overall,'min_technical':min_technical,'min_valuation':min_valuation}.items() if v is not None}
        return service.rankings(horizon,filters or None)

    @router.get('/top-candidate',response_model=JsonResponse)
    def top(horizon:Horizon='short_term'):
        data=service.rankings(horizon)
        return {'horizon':horizon,'run_id':data['run_id'],'as_of':data['as_of'],'top_ranked':data.get('top_ranked'),'best_eligible':data.get('best_eligible'),
            'message':'Highest-ranked eligible current buy candidate.' if data.get('best_eligible') else 'No qualified buy candidate found.','coverage':data['coverage']}

    @router.get('/watchlist-candidates',response_model=JsonResponse)
    def watch(horizon:Horizon='short_term'):
        data=service.rankings(horizon)
        return {'horizon':horizon,'run_id':data['run_id'],'watchlist_candidates':data['watchlist_candidates'],'as_of':data['as_of']}

    @router.get('/status',response_model=JsonResponse)
    def status(horizon:Horizon='short_term'):return service.status(horizon)

    @router.post('/refresh',response_model=JsonResponse,status_code=202)
    def refresh(body:ScreenRequest):return service.refresh(body)

    @router.post('/backtest',response_model=JsonResponse)
    def backtest(body:ScreenerBacktestRequest):
        from app.analysis.screener_backtest import replay_ranked_portfolio
        from app.providers.yahoo import records_frame,DataUnavailable
        from app.providers.bar_times import completed_bars
        from app.analysis.quantitative import source_zone
        import pandas as pd
        records=store.screening_runs(published_only=True,limit=1000)
        snapshots=[]
        for record in reversed(records):
            result=record['payload'].get('results',{}).get(body.horizon)
            if not result:continue
            universe=record['payload'].get('universe_metadata',{})
            snapshots.append({'id':record['id'],'published_at':record['published_at'],'membership_as_of':universe.get('fetched_at') or record['created_at'],
                'horizon':body.horizon,'point_in_time':True,'rankings':[{**r,'score':r['overall_score']} for r in result['rankings']]})
        if len(snapshots)<2:
            return {'status':'Insufficient historical evidence','reason':'At least two genuinely published ranking/membership snapshots and subsequent observed prices are required. Current financial data cannot reconstruct past rankings.',
                'snapshots_available':len(snapshots),'metrics':None,'equity_curve':[],'limitations':['No historical top5/top10 portfolio return is invented. Archive new screenings over time or supply verified point-in-time records.']}
        tickers={r['ticker'] for s in snapshots for r in s['rankings'][:body.top_n]}
        histories={};benchmarks={};errors=[]
        for ticker in sorted(tickers|{'QQQ','XLK'}):
            try:
                cached=store.cache_get(f'yahoo:history:{ticker}:max:1d') or store.cache_get(f'yahoo:history:{ticker}:5y:1d')
                if not cached:raise ValueError('No cached history for archived replay. Retrieve research first; this endpoint does not start unbounded historical downloads.')
                value=cached['value']
                frame=records_frame(value['prices'])
                info=store.cache_get(f'yahoo:section:v3:{ticker}:company_info')
                zone=source_zone(info['value'].get('data',{})) if info else None
                if zone:frame=completed_bars(frame,'1d',zone)
                else:frame['Bar End']=frame.index+pd.Timedelta(hours=36)
                if info:frame.attrs['currency']=info['value'].get('data',{}).get('currency')
                if value.get('cache_stale'):raise ValueError('Stale failed-refresh history cannot certify current replay coverage.')
                if ticker in tickers:histories[ticker]=frame
                if ticker in ('QQQ','XLK'):benchmarks[ticker]=frame
            except (DataUnavailable,ValueError) as exc:errors.append({'ticker':ticker,'message':str(exc)})
        result=replay_ranked_portfolio(snapshots,histories,body.model_dump(mode='json',exclude_none=True),benchmarks)
        return clean({**result,'provider_errors':errors})

    return router
