"""One bounded worker: discover broadly, deeply research a disclosed liquid subset."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone
from threading import Event,Lock
from uuid import uuid4
import logging
import time
from app.utils import clean,iso_now,number
from app.instruments import is_fund
from app.providers.yahoo import DataUnavailable,records_frame
from app.providers.bar_times import completed_bars
from app.analysis.quantitative import build_quant_core,source_zone,_recommendation
from app.analysis.quant_scoring import quality_score
from .schemas import ScreenRequest,SHORT_WEIGHTS,LONG_WEIGHTS
from .scoring import calculate_scores,rank_rows
from .scenarios import conditional_scenarios

log=logging.getLogger('equitylens.screener')
HORIZONS=('short_term','long_term')


def default_valuation():
    return {'enable_dcf':True,'growth':.05,'discount_rate':.10,'terminal_growth':.02,'years':5}


def _broad_row(member):
    def first(*names):return next((member.get(k) for k in names if member.get(k) is not None),None)
    return {'ticker':first('ticker','symbol'),'name':first('name','longName','shortName'),'price':number(first('price','regularMarketPrice')),
        'currency':member.get('currency'),'industry':member.get('industry'),'sector':member.get('sector'),'exchange':member.get('exchange'),
        'country':member.get('country'),'listing_country':member.get('listing_country'),'market_cap':number(first('market_cap','marketCap')),
        'average_volume':number(first('average_volume','averageDailyVolume3Month','averageDailyVolume10Day')),
        'overall_score':None,'company_quality':None,'valuation_attractiveness':None,'technical_strength':None,'trade_setup_quality':None,
        'historical_evidence':None,'risk_score':None,'confidence':0,'data_completeness':0,'metrics_evaluated':0,
        'missing_information':['Full financial, technical and strategy analysis has not been performed for this broad-stage member.'],
        'quote_at':first('quote_at','regularMarketTime'),'fetched_at':member.get('fetched_at'),'cache_stale':member.get('cache_stale',False),
        'analysis_stage':'broad','recommendation':'Insufficient Evidence','eligible_buy':False,'scores':{},'ranking_explanation':[],
        'risks':['Broad-stage membership is not an investment recommendation.'],'buy_triggers':[],'thesis_invalidation':[],
        'plan':None,'scenarios':[],'fair_value':None,'margin_of_safety':None,'classification_basis':member.get('classification_basis')}


def evaluate_row(base,quant,horizon,config):
    overview=base['overview'];financial=base['fundamentals'];valuation=quant.get('valuation',{})
    weights=config.get('weights') if config['horizon']==horizon else None
    assessment=calculate_scores(base,quant,horizon,weights)
    score=assessment['overall_score'];plan=deepcopy(quant.get('recommendation',{}))
    stale=bool(overview.get('stale') or any(base.get('data_quality',{}).get('sections',{}).get(k,{}).get('cache_stale') for k in ('history','company_info','statements')))
    age=number(financial.get('statement_age_days'))
    if age is not None and age>550:stale=True
    probability=quant.get('probabilities',{})
    historical=quant.get('evidence',{}).get('sample_reliability',{})
    strategies=quant.get('strategies',[]);eligible=[s for s in strategies if s.get('eligible')]
    if horizon=='long_term':eligible=[s for s in eligible if s['id']=='fundamental_value']
    confidence=assessment['confidence'];reasons=[]
    currency_ok=overview.get('currency')==config.get('capital_currency','USD')
    current=plan.get('recommendation')=='Buy candidate'
    buy=bool(score is not None and score>=7 and confidence>=.6 and not stale and currency_ok and eligible and current)
    if horizon=='short_term':
        empirical=number(probability.get('estimates',{}).get('expected_return'))
        reliable=historical.get('sample_size',0)>=30 and empirical is not None and empirical>0
        buy=buy and reliable
        if not reliable:reasons.append('At least30 comparable mature observations and positive historical net expectancy are required for a short-term buy candidate; descriptive single trades do not qualify.')
    else:
        fair=valuation.get('valuation_range') or {};base_value=number(fair.get('base'));quoted=number(overview.get('price'))
        margin=(base_value-quoted)/base_value if base_value and quoted else None
        buy=buy and plan.get('best_strategy')=='fundamental_value' and margin is not None and margin>=config.get('margin_of_safety',.2) and quality_score(financial) is not None and quality_score(financial)>=7
        reasons.append('Long-term eligibility requires the fundamental-value strategy, explicit scenarios, financial quality and margin of safety; an ATR stop alone is insufficient.')
    if stale or score is None:recommendation='Insufficient Evidence'
    elif buy:recommendation='Buy Candidate'
    elif score<4:recommendation='Avoid'
    elif score>=6:recommendation='Watchlist Candidate'
    else:recommendation='Wait'
    if not current:reasons.append(plan.get('status','Current entry conditions are not satisfied.'))
    if not currency_ok:reasons.append('Capital and quote currencies differ or are unavailable; no FX conversion or position allocation is inferred.')
    selected=next((s for s in eligible if s.get('id')==plan.get('best_strategy')),None)
    plan['maximum_planned_loss']=selected.get('estimated_capital_risk') if buy and selected else 0
    for field in ('upside_percent','downside_percent','risk_budget','risk_per_share'):
        if selected and selected.get(field) is not None:plan[field]=selected[field]
    plan['position_size']=plan.get('position_size',0) if buy else 0
    plan['recommendation']=recommendation
    if not buy:plan['status']='No qualified current buy. Review the entry conditions and evidence limitations.'
    scenarios=conditional_scenarios(quant,config,horizon)
    if not buy:
        for scenario in scenarios:
            if scenario['status']=='Active':scenario['status']='Waiting for confirmation'
    metrics=financial.get('metrics',{})
    strongest=sorted(((key,value) for key,value in assessment['scores'].items() if value is not None),key=lambda item:item[1]*assessment['weights'][item[0]],reverse=True)[:2]
    strengths=[f"{key.replace('_',' ').capitalize()} {value:.2f}/10 contributes {value*assessment['weights'][key]:.2f} weighted points before coverage normalization." for key,value in strongest]
    row={
        'ticker':overview['ticker'],'name':overview['name'],'price':overview.get('price'),'currency':overview.get('currency'),
        'sector':overview.get('sector'),'industry':overview.get('industry'),'exchange':overview.get('exchange'),
        'country':base.get('company_country'),'market_cap':overview.get('market_cap'),'average_volume':base.get('average_volume'),
        **assessment,'company_quality':quality_score(financial),'valuation_attractiveness':valuation.get('score'),
        'technical_strength':quant.get('technical_assessment',{}).get('group_scores',{}).get('trend'),
        'trade_setup_quality':assessment['setup_score'],'risk_score':financial.get('risk_score'),
        'historical_evidence':historical.get('sample_size',0),'historical_performance':{'strategies':{key:{
            'status':item.get('status'),'sample_size':item.get('sample_size'),'metrics':item.get('metrics'),
            'out_of_sample':{k:v for k,v in (item.get('out_of_sample') or {}).items() if k!='equity_curve'},
            'limitations':item.get('limitations',[])} for key,item in quant.get('validation',{}).get('strategies',{}).items()},
            'limitations':quant.get('validation',{}).get('limitations',[])},
        'confidence':confidence,'fetched_at':overview.get('fetched_at'),'quote_at':overview.get('quote_at'),'cache_stale':stale,
        'source_freshness':base.get('data_quality',{}).get('sections',{}),'analysis_stage':'deep','recommendation':recommendation,'eligible_buy':buy,
        'ranking_explanation':[f"{horizon.replace('_',' ')} score uses this horizon's independent category weights.",*strengths,assessment['setup_score_basis'],*reasons],
        'risks':list(dict.fromkeys(plan.get('event_warnings',[])+financial.get('limitations',[])+valuation.get('limitations',[])+assessment['limitations'])),
        'buy_triggers':[s['entry_condition'] for s in eligible] or [plan.get('entry_condition','Wait for confirmation and sufficient evidence.')],
        'thesis_invalidation':[s.get('invalidation',{}).get('condition') for s in strategies if s.get('invalidation',{}).get('condition')],
        'plan':plan,'scenarios':scenarios,'fair_value':valuation.get('valuation_range'),'margin_of_safety':valuation.get('margin_of_safety'),
        'valuation_assumptions':valuation.get('scenario_assumptions'),'valuation_basis':valuation.get('score_basis'),
        'revenue_growth':metrics.get('revenue_growth_yoy'),'net_income':metrics.get('net_income'),
        'forward_pe':valuation.get('metrics',{}).get('forward_pe'),'regime':quant.get('regime'),
        'timeframes':{'alignment':quant.get('timeframes',{}).get('alignment'),'summaries':[
            {k:t.get(k) for k in ('timeframe','status','trend','momentum','volatility','confidence','last_bar_end')} for t in quant.get('timeframes',{}).get('timeframes',[])]},
        'holding_horizon':'1–63 trading sessions' if horizon=='short_term' else '1–5+ years; revisit filings and thesis periodically',
        'financial_reporting_date':financial.get('reporting_date'),'model_uncertainty':quant.get('evidence',{}).get('model_uncertainty')}
    return clean(row)


class TechnologyScreenerService:
    def __init__(self,provider,universe,base,quant,store,settings):
        self.provider,self.universe,self.base,self.quant,self.store,self.settings=provider,universe,base,quant,store,settings
        self.lock=Lock();self.stop=Event();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='equitylens-screen')
        self.future=None;self.current=None;self.last_started=0
        for record in store.screening_runs(limit=1):
            if record['status'] in ('queued','running'):
                payload=record['payload'];payload['job'].update(status='failed',stage='interrupted',message='The previous process stopped before publication. Refresh to retry; older published evidence is retained.')
                store.save_screening(record['id'],payload,'failed')

    def _publish_job(self,payload):
        self.current=deepcopy(payload['job'])
        self.store.save_screening(payload['job']['id'],clean(payload),payload['job']['status'])

    def refresh(self,request):
        config=request.model_dump(mode='json') if isinstance(request,ScreenRequest) else ScreenRequest(**request).model_dump(mode='json')
        if config.get('valuation_assumptions'):config['valuation_assumptions']={k:v for k,v in config['valuation_assumptions'].items() if v is not None}
        with self.lock:
            if self.future is not None and not self.future.done():
                return {'accepted':False,'horizon':config['horizon'],'run_id':self.current['id'],'job':deepcopy(self.current)}
            if self.last_started and time.monotonic()-self.last_started<30:
                raise DataUnavailable('Please wait30seconds before starting another screening run. Cached results remain available.','screening_refresh_limit',429,True)
            run_id=str(uuid4());job={'id':run_id,'status':'queued','stage':'discovery','total':0,'processed':0,'deep_total':0,'deep_processed':0,'message':'Queued dynamic discovery.','started_at':iso_now()}
            payload={'job':job,'configuration':config,'provider_errors':[],'results':{}}
            self._publish_job(payload);self.last_started=time.monotonic()
            self.future=self.pool.submit(self._run,payload)
            return {'accepted':True,'horizon':config['horizon'],'run_id':run_id,'job':deepcopy(job)}

    def _run(self,payload):
        job=payload['job'];config=payload['configuration'];errors=payload['provider_errors']
        try:
            job.update(status='running',message='Discovering the requested source-defined technology universe.');self._publish_job(payload)
            universe=self.universe.discover(config['filters'])
            universe=clean(universe);self.store.cache_set('screener:universe:last',universe)
            errors.extend(universe.get('coverage',{}).get('errors',[])+universe.get('upstream_errors',[]))
            payload['universe_metadata']={k:universe.get(k) for k in ('source','fetched_at','coverage','cache_stale')}
            if any(e.get('code')=='upstream_rate_limit' for e in errors):raise DataUnavailable('Universe source rate limit reached; deep requests were not started.','upstream_rate_limit',429,True)
            members=universe.get('members',[])
            rows={h:[_broad_row(m) for m in members] for h in HORIZONS}
            # Liquidity/capitalization determine analysis priority, never fabricated investment scores.
            leading=sorted(members,key=lambda m:(-(_broad_row(m)['market_cap'] or 0),-(_broad_row(m)['average_volume'] or 0),_broad_row(m)['ticker']))[:config['max_deep_analysis']]
            job.update(stage='deep_analysis',total=len(members),processed=len(members),deep_total=len(leading),message='Broad metadata evaluated; researching a bounded liquidity-prioritized subset.');self._publish_job(payload)
            index={m['ticker'] if 'ticker' in m else m['symbol']:i for i,m in enumerate(members)}
            for member in leading:
                if self.stop.is_set():raise InterruptedError('Screening interrupted during application shutdown; no partial ranking was published.')
                ticker=member.get('ticker') or member['symbol']
                job['message']=f'Researching {ticker}; Yahoo requests are serialized and cached.';self._publish_job(payload)
                try:
                    base=self.base.research(ticker,include_core=False)
                    bundle=self.provider.bundle(ticker,'5y')
                    if is_fund(bundle.get('info',{})):raise ValueError('Provider identified a fund; corporate rankings exclude it.')
                    base={**base,'company_country':bundle.get('info',{}).get('country'),'average_volume':number(bundle.get('info',{}).get('averageVolume')) or _broad_row(member)['average_volume']}
                    common={k:config[k] for k in ('capital','risk_per_trade','risk_tolerance','min_reward_risk','commission_bps','slippage_bps','cost_basis')}
                    common['existing_shares']=config['existing_shares'] if config.get('position_ticker')==ticker else 0
                    common['cost_basis']=config.get('cost_basis') if config.get('position_ticker')==ticker else None
                    common['margin_of_safety']=config.get('margin_of_safety',.2)
                    common['valuation_assumptions']=config.get('valuation_assumptions') or default_valuation()
                    short=self.quant.analyze(ticker,{**common,'horizon':'swing','max_holding_bars':63,'benchmark_ticker':'QQQ'})
                    # Long business/value research shares source evidence, not short-horizon backtest statistics.
                    benchmark=None
                    try:benchmark=completed_bars(records_frame(self.provider.history('QQQ','5y')['prices']),'1d',source_zone(bundle.get('info',{})))
                    except DataUnavailable:pass
                    long=build_quant_core(bundle,base,{**common,'horizon':'long','max_holding_bars':252,'benchmark_ticker':'QQQ'},benchmark,short.get('timeframes'),short.get('valuation'),True)
                    long['recommendation']=_recommendation([s for s in long['strategies'] if s['id']=='fundamental_value'],base,{**common,'horizon':'long'},long['event_risk'],True)
                    long['evidence']['limitations'].append('Historical long-term fundamental/ranking success is unavailable without archived point-in-time inputs; short-term results are not relabeled long-term evidence.')
                    for horizon,result in [('short_term',short),('long_term',long)]:
                        row=evaluate_row(base,result,horizon,{**config,**common})
                        row['listing_country']=member.get('listing_country');row['classification_basis']=member.get('classification_basis')
                        rows[horizon][index[ticker]]=row
                except Exception as exc:
                    error=exc.payload() if isinstance(exc,DataUnavailable) else {'code':'analysis_failed','message':str(exc)[:300],'retryable':False}
                    errors.append({'ticker':ticker,**error})
                    log.warning('Screening analysis failed ticker=%s type=%s',ticker,type(exc).__name__)
                    if isinstance(exc,DataUnavailable) and exc.status==429:
                        job['message']='Yahoo rate limit reached; remaining requests stopped. Refresh later using the existing cache.'
                        break
                job['deep_processed']+=1;self._publish_job(payload)
                if self.stop.wait(self.settings.screener_request_delay):raise InterruptedError('Screening interrupted during application shutdown.')
            published=iso_now()
            ranking_filters=deepcopy(config['filters'])
            scope=universe.get('coverage',{}).get('scope',{})
            if ranking_filters.get('countries') and scope.get('regions'):ranking_filters['countries']=scope['regions']
            if ranking_filters.get('exchanges') and scope.get('exchanges'):ranking_filters['exchanges']=scope['exchanges']
            for horizon in HORIZONS:
                ranked,unranked=rank_rows(rows[horizon],ranking_filters)
                deep=[r for r in rows[horizon] if r['analysis_stage']=='deep']
                coverage={'total_discovered':len(members),'total_eligible':len(members),'successfully_analyzed':len(deep),'deep_analyzed':len(deep),
                    'incomplete':sum(r.get('data_completeness',0)<1 for r in rows[horizon]),'excluded':len(unranked),'ranked':len(ranked),
                    'broad_screened':len(members),'not_deep_analyzed':len(members)-len(deep),
                    'source':universe.get('source'),'comprehensive':False,'universe':universe.get('coverage',{})}
                weights=(config.get('weights') if config['horizon']==horizon else None) or (SHORT_WEIGHTS if horizon=='short_term' else LONG_WEIGHTS)
                payload['results'][horizon]={'horizon':horizon,'run_id':job['id'],'as_of':published,'methodology_version':'tech-screen-1.0',
                    'weights':weights,'rankings':ranked,'unranked':unranked,'coverage':coverage,'configuration':config,
                    'top_ranked':ranked[0] if ranked else None,'best_eligible':next((r for r in ranked if r['eligible_buy']),None),
                    'buy_candidates':[r for r in ranked if r['eligible_buy']],'watchlist_candidates':[r for r in ranked if r['recommendation']=='Watchlist Candidate'],
                    'provider_errors':errors,'source':universe.get('source'),'limitations':list(universe.get('limitations',[]))+[
                        'Rankings cover only the disclosed deep-analysis subset of this source-defined universe, not the entire technology sector.',
                        'Stage1 uses supplied discovery metadata; deep-analysis priority is capitalization/liquidity, not an investment ranking. Broad-only members remain unranked.',
                        'Default DCF reference assumptions are5% growth,10% discount,2% terminal growth over5years; inspect or replace them. Scenario values are not price forecasts.',
                        'International market caps/volume are source units; FX-normalized size comparisons are not supplied. Position sizing requires matching capital/quote currencies.',
                        'Calendar completeness and insufficient historical cohorts can block every buy candidate. No qualified buy candidate is manufactured.']}
            job.update(status='completed',stage='complete',completed_at=published,message='Published both horizon rankings. Review source coverage, missing data and eligibility gates.')
            self.current=deepcopy(job)
            self.store.save_screening(job['id'],clean(payload),'completed',published=True)
        except Exception as exc:
            error=exc.payload() if isinstance(exc,DataUnavailable) else {'code':'screening_failed','message':str(exc)[:300]}
            errors.append(error);job.update(status='failed',stage='interrupted' if isinstance(exc,InterruptedError) else 'failed',message=error['message'],completed_at=iso_now())
            self._publish_job(payload)

    def universe_snapshot(self):
        cached=self.store.cache_get('screener:universe:last')
        value=cached['value'] if cached else {'members':[],'source':'No dynamic discovery run has been published.','coverage':{'comprehensive':False},'limitations':['Start screening to retrieve a source-defined universe; no popular-stock list is substituted.']}
        members=value.get('members',[])
        taxonomy=getattr(self.universe,'industries',{})
        supported={name for name,sector in taxonomy.items() if sector=='Technology'}|{'Internet Content & Information','Internet Retail'}
        return {**value,'as_of':value.get('fetched_at'),'industries':sorted(supported|{m['industry'] for m in members if m.get('industry')}),
            'exchanges':sorted({m['exchange'] for m in members if m.get('exchange')}),'countries':sorted({m.get('listing_country') or m.get('country') for m in members if m.get('listing_country') or m.get('country')})}

    def rankings(self,horizon,filters=None):
        needs_filter=filters is not None
        latest=self.store.screening_runs(published_only=True,limit=1)
        value=deepcopy(latest[0]['payload'].get('results',{}).get(horizon,{})) if latest else {}
        if not value:value={'horizon':horizon,'run_id':None,'as_of':None,'rankings':[],'unranked':[],'top_ranked':None,'best_eligible':None,'buy_candidates':[],
            'watchlist_candidates':[],'coverage':{'comprehensive':False},'provider_errors':[],'weights':SHORT_WEIGHTS if horizon=='short_term' else LONG_WEIGHTS,'limitations':['No completed screening run. Start a background screen; no ranking is fabricated.']}
        if value.get('as_of'):
            elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(value['as_of'])).total_seconds()
            value['screening_stale']=elapsed>self.settings.screener_refresh_seconds
            if value['screening_stale']:
                for row in value['rankings']+value['unranked']:
                    row.update(cache_stale=True,eligible_buy=False,recommendation='Insufficient Evidence')
                    if row.get('plan'):row['plan'].update(position_size=0,recommendation='Wait')
                filters=filters or {}
                needs_filter=True
                value['limitations'].append('This published screening snapshot has aged beyond the refresh interval; current rankings and buy eligibility are withheld.')
        if needs_filter:
            ranked,excluded=rank_rows(value['rankings']+value['unranked'],filters)
            value.update(rankings=ranked,unranked=excluded,top_ranked=ranked[0] if ranked else None,best_eligible=next((r for r in ranked if r['eligible_buy']),None),buy_candidates=[r for r in ranked if r['eligible_buy']],watchlist_candidates=[r for r in ranked if r['recommendation']=='Watchlist Candidate'])
        value['job']=deepcopy(self.current) if self.current else None
        recent=self.store.screening_runs(limit=1)
        if recent and recent[0]['status']=='failed':value['provider_errors']=value.get('provider_errors',[])+recent[0]['payload'].get('provider_errors',[])
        return clean(value)

    def status(self,horizon):
        value=self.rankings(horizon)
        return {k:value.get(k) for k in ('horizon','run_id','as_of','job','coverage','provider_errors')}

    def auto_refresh(self):
        recent=self.store.screening_runs(limit=1)
        if recent and recent[0]['status']=='failed' and (datetime.now(timezone.utc)-datetime.fromisoformat(recent[0]['created_at'])).total_seconds()<900:return
        latest=self.store.screening_runs(published_only=True,limit=1)
        if latest:
            stamp=datetime.fromisoformat(latest[0]['published_at'])
            if (datetime.now(timezone.utc)-stamp).total_seconds()<self.settings.screener_refresh_seconds:return
            config=latest[0]['payload']['configuration']
        else:config=recent[0]['payload'].get('configuration') if recent else {'max_deep_analysis':self.settings.screener_max_deep_analysis}
        if self.future is None or self.future.done():self.refresh(config)

    def has_schedule(self):
        latest=self.store.screening_runs(limit=1)
        return bool(latest and latest[0]['payload'].get('configuration',{}).get('auto_refresh'))

    def close(self):
        self.stop.set();self.pool.shutdown(wait=True,cancel_futures=True)
