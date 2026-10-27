"""Quantitative research orchestration; all numerical conclusions remain rule/source bound."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib
import json
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import pandas as pd
from app.providers.yahoo import records_frame,DataUnavailable
from app.providers.bar_times import completed_bars,derived_weekly,derived_four_hour
from app.analysis.features import build_features,snapshot_at
from app.analysis.regime import classify_regime
from app.analysis.timeframes import analyze_timeframes
from app.analysis.technical import analyze_technical
from app.analysis.strategies import evaluate_strategies
from app.analysis.quant_scoring import quantitative_scores,quality_score
from app.analysis.valuation_models import enhance_valuation
from app.analysis.validation import validate_strategies
from app.analysis.probability import estimate_probabilities
from app.utils import clean,iso_now,number

VERSION='2.0'
RULE_CACHE_VERSION='quant-rules-2.0.2'


def normalize_config(config):
    result={'horizon':'swing','risk_tolerance':'medium','capital':10000,'risk_per_trade':.01,'min_reward_risk':2,
            'commission_bps':5,'slippage_bps':5,'benchmark_ticker':'SPY','min_samples':30,'margin_of_safety':.2,**(config or {})}
    if result.get('max_holding_bars') is None:result['max_holding_bars']={'short':5,'swing':40,'long':252}[result['horizon']]
    return result


def source_zone(info):
    value=info.get('exchangeTimezoneName') or 'UTC'
    try:ZoneInfo(value);return value
    except (ZoneInfoNotFoundError,ValueError,TypeError):return 'UTC'


def event_risk(base,horizon='swing',now=None):
    now=pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:now=now.tz_localize('UTC')
    window={'short':1,'swing':3,'long':7}[horizon]
    events=[];warnings=[]
    macro=base.get('macro',{})
    for event in macro.get('upcoming_events',[]):
        if str(event.get('impact','')).lower()!='high' or event.get('status')=='canceled':continue
        try:stamp=pd.Timestamp(event['scheduled_at'])
        except (ValueError,KeyError,TypeError):continue
        if stamp.tzinfo is not None and now<=stamp<=now+pd.Timedelta(days=window):
            events.append({'kind':'macro','title':event.get('title'),'scheduled_at':stamp.isoformat(),'source_url':event.get('source_url'),'time_precision':event.get('time_precision','time')})
    calendar=base.get('overview',{}).get('company_calendar',{})
    dates=calendar.get('Earnings Date',[]) if isinstance(calendar,dict) else []
    if not isinstance(dates,list):dates=[dates]
    zone=source_zone({'exchangeTimezoneName':base.get('overview',{}).get('exchange_timezone')})
    for value in dates:
        try:
            stamp=pd.Timestamp(value)
            if stamp.tzinfo is None:stamp=stamp.tz_localize(zone)
            # A date-only estimate is a full-day risk window; do not invent a release time.
            if stamp.normalize()<=now.tz_convert(zone)+pd.Timedelta(days=window) and stamp.normalize()+pd.Timedelta(days=1)>=now.tz_convert(zone):
                events.append({'kind':'earnings','title':'Estimated company earnings window','scheduled_at':stamp.isoformat(),'time_precision':'date/estimate','source_url':'https://finance.yahoo.com/'})
        except (ValueError,TypeError):continue
    for event in events:warnings.append(f"{event['title']} ({event['scheduled_at']}): announcement risk may increase gaps and invalidate assumed fills; no outcome is predicted.")
    coverage=macro.get('coverage',{})
    first,last=coverage.get('first_scheduled_at'),coverage.get('last_scheduled_at');covered=False
    if first and last and coverage.get('completeness_verified') is True:
        try:covered=pd.Timestamp(first)<=now and pd.Timestamp(last)>=now+pd.Timedelta(days=window)
        except (ValueError,TypeError):pass
    if not covered:warnings.append('Imported economic-calendar coverage does not span the full strategy window. Absence of a listed event does not establish safety.')
    return {'blocked':bool(events),'events':events,'warnings':warnings,'window_days':window,'coverage_status':'covered' if covered else 'incomplete','limitations':['Expected event risk is separate from measured volatility. Forecasts do not reveal release outcomes. Earnings dates may be estimated.']}


def _recommendation(strategies,base,config,risk,full_context):
    eligible=[s for s in strategies if s.get('eligible')]
    best=max(eligible,key=lambda s:(s.get('risk_reward') or 0,s['id'])) if eligible else None
    default={'ticker':base.get('ticker') or base.get('overview',{}).get('ticker'),'recommendation':'Wait','status':'No favorable setup','best_strategy':None,'best_strategy_name':None,'entry_zone':None,'stop':None,'targets':[],
      'risk_reward':None,'net_reward_risk':[],'position_size':0,'risk_budget':config['capital']*config['risk_per_trade'],
      'entry_condition':'Wait for a strategy to meet its completed-bar confirmation and net risk requirements.',
      'calculation':[f"Allocated capital {config['capital']:.2f} × risk {config['risk_per_trade']:.2%} = {config['capital']*config['risk_per_trade']:.2f} risk budget before existing holdings."],'invalidation':[],'event_warnings':risk['warnings'],'limitations':[],
      'holding_horizon':config['horizon'],'quoted_price':base.get('overview',{}).get('price'),'quote_at':base.get('overview',{}).get('quote_at')}
    if not best:
        default['calculation'].extend(f"{s['name']}: "+'; '.join(s.get('avoid_reasons',[])) for s in strategies)
        if all(s['status'] in ('insufficient_data','not_applicable') for s in strategies):default['recommendation']='Insufficient Data'
        return default
    plan={**default,**{key:deepcopy(best[key]) for key in ('entry_zone','stop','targets','risk_reward','net_reward_risk','position_size','entry_condition','calculation','holding_horizon')},
          'best_strategy':best['id'],'best_strategy_name':best['name'],'invalidation':[best['invalidation']['condition']],
          'status':'Conditions confirmed; entry remains conditional on the proposed zone and execution costs.'}
    quoted=number(base.get('overview',{}).get('price'))
    if not full_context:
        plan.update(recommendation='Wait',position_size=0,status='Daily rules evaluated. Full benchmark/timeframe and historical review is pending.')
    elif risk['blocked'] or risk['coverage_status']!='covered':
        plan.update(recommendation='Wait',position_size=0,status='Review imminent events and complete the economic-calendar coverage before a new entry.')
    elif quoted is None or not best['entry_zone'][0]<=quoted<=best['entry_zone'][1]:
        plan.update(recommendation='Wait',position_size=0,status='Setup fits the rules; the current quote is outside the proposed entry zone. Do not chase.')
    else:
        plan['recommendation']='Hold/Manage' if config.get('existing_shares',0) else 'Buy candidate'
    plan['limitations'].append('Rule eligibility is not a statistically established success probability. Inspect sample reliability and every original price-level assumption.')
    plan['calculation'].insert(0,default['calculation'][0])
    return plan


def build_quant_core(bundle,base,config=None,benchmark=None,timeframes=None,valuation=None,full_context=False):
    config=normalize_config(config);info=bundle.get('info',{});zone=source_zone(info)
    daily=completed_bars(records_frame(bundle['history']['prices']),'1d',zone)
    features=build_features(daily,benchmark);snapshot=snapshot_at(features)
    regime=classify_regime(snapshot)
    valuation=valuation or enhance_valuation({**info,'currentPrice':base['overview']['price']},base['fundamentals'],base['valuation'],config.get('valuation_assumptions'))
    risk=event_risk(base,config['horizon'])
    context={'regime':regime,'fundamentals':base['fundamentals'],'valuation':valuation,'company_quality':quality_score(base['fundamentals']),
             'event_risk':risk,'timeframes':timeframes or {},'stale':base['overview'].get('stale') or bundle['history'].get('cache_stale',False),
             'is_fund':base['overview'].get('is_fund',False)}
    strategies=evaluate_strategies(snapshot,context,config)
    scoring_base={**base,'technical':analyze_technical(daily)}
    scores=quantitative_scores(scoring_base,strategies,config,valuation)
    recommendation=_recommendation(strategies,base,config,risk,full_context)
    def bounded_confidence(value):return max(0,min(1,number(value) or 0))
    category_confidence={'company_quality':bounded_confidence(base['fundamentals'].get('confidence')) if scores['company_quality'] is not None else 0,
        'technical_strength':bounded_confidence(scoring_base['technical'].get('confidence'))*regime['confidence']*(.25 if context['stale'] else 1),
        'valuation_attractiveness':bounded_confidence(valuation.get('confidence')) if scores['valuation_attractiveness'] is not None else 0,
        'trade_setup_quality':min(regime['confidence'],bounded_confidence(scoring_base['technical'].get('confidence')))*(0 if context['stale'] else 1) if scores['trade_setup_quality'] is not None else 0,
        'macroeconomic_environment':bounded_confidence(base.get('macro',{}).get('confidence')) if scores['macroeconomic_environment'] is not None else 0}
    confidence=sum(category_confidence[k]*w for k,w in scores['weights'].items())
    labels={'company_quality':'Company Quality','valuation_attractiveness':'Valuation Attractiveness','technical_strength':'Technical Strength','trade_setup_quality':'Trade Setup Quality','macroeconomic_environment':'Macroeconomic Environment'}
    adapter={'ticker':bundle['ticker'],'overall':scores['overall_investment_attractiveness'],'company_quality':scores['company_quality'],'confidence':confidence,'coverage':scores['coverage'],
      'categories':[{'key':key,'label':labels[key],'score':scores[key],'weight':weight,'contribution':scores['contributions'][key],'confidence':category_confidence[key]} for key,weight in scores['weights'].items()],
      'limitations':scores['limitations'],'formula':scores['formula'],'methodology_version':VERSION}
    evidence={'confidence':confidence,'data_freshness':{'sections':bundle.get('sections',{}),'quote_at':base['overview'].get('quote_at'),'quote_stale':base['overview'].get('stale'),
              'decision_bar_as_of':snapshot.get('as_of'),'completion_rule':'Current source-local daily session is conservatively excluded until the next midnight.'},
      'model_uncertainty':{'kind':'Deterministic reference rules and explicit valuation assumptions','calibrated':False,'limitations':['No predictive accuracy improvement has been established merely by adding indicators or strategies. Thresholds require independent evaluation.', 'Regime and overlapping timeframes are context gates, not additional independent votes.']},
      'sample_reliability':{'status':'Insufficient historical evidence','sample_size':0,'min_samples':config.get('min_samples',30)},
      'limitations':['Evidence confidence is feature completeness, not a win probability. Financial statement publication vintages and historical event calendars are not inferred.']}
    return clean({'methodology_version':VERSION,'ticker':bundle['ticker'],'as_of':iso_now(),'regime':regime,'strategies':strategies,
      'technical_assessment':{k:scoring_base['technical'].get(k) for k in ('score','confidence','signals','limitations','group_scores','indicators','structure')},
      'recommendation':recommendation,'scores':scores,'score_adapter':adapter,'evidence':evidence,'valuation':valuation,'event_risk':risk,
      'source':{'market':bundle['history'].get('source'),'decision_bar_as_of':snapshot.get('as_of'),'benchmark':config.get('benchmark_ticker'),'horizon':config['horizon']}})


class QuantitativeResearchService:
    def __init__(self,base,provider,store,settings):
        self.base,self.provider,self.store,self.settings=base,provider,store,settings

    def analyze(self,ticker,config=None):
        config=normalize_config(config)
        assumptions=config.get('valuation_assumptions')
        dcf=assumptions if assumptions and assumptions.get('enable_dcf',False) else None
        base=self.base.research(ticker,config=config,assumptions=dcf,include_core=False)
        bundle=self.provider.bundle(ticker,'5y');zone=source_zone(bundle.get('info',{}))
        daily=completed_bars(records_frame(bundle['history']['prices']),'1d',zone)
        limits=[];benchmark=None
        try:
            source=self.provider.history(config['benchmark_ticker'],'5y')
            benchmark=completed_bars(records_frame(source['prices']),'1d',zone)
            if base['overview'].get('currency') not in (None,'USD') and config['benchmark_ticker']=='SPY':
                limits.append('Default USD SPY benchmark is not currency-matched to this listing; relative-strength scoring is withheld until a suitable benchmark is selected.')
                benchmark=None
        except (DataUnavailable,AttributeError) as exc:limits.append('Benchmark unavailable; no relative-strength or index return was invented.')
        frames={'daily':daily,'weekly':derived_weekly(daily,zone)}
        metadata={name:{'source':bundle['history']['source'],'exchange_timezone':zone,'completion_verified':False,
            'cache_stale':bundle['history'].get('cache_stale',False),'fetched_at':bundle['history'].get('fetched_at')} for name in ('daily','weekly')}
        for name,interval in [('1h','1h'),('15m','15m')]:
            try:
                source=self.provider.intraday(ticker,interval)
                frames[name]=completed_bars(records_frame(source['prices']),interval,zone)
                metadata[name]={'source':source['source'],'exchange_timezone':zone,'completion_verified':False,'source_window':source.get('period'),'fetched_at':source.get('fetched_at'),'cache_stale':source.get('cache_stale',False)}
            except (DataUnavailable,AttributeError):
                limits.append(f'{name} unavailable from the provider; no candles were synthesized.')
        if '1h' in frames:
            anchor='09:30' if zone=='America/New_York' and bundle.get('info',{}).get('quoteType') in ('ETF','EQUITY','INDEX') else None
            frames['4h']=derived_four_hour(frames['1h'],zone,anchor)
            metadata['4h']={'source':'Derived from Yahoo regular-session 1h candles','exchange_timezone':zone,'completion_verified':False,
                'cache_stale':metadata.get('1h',{}).get('cache_stale',False),'fetched_at':metadata.get('1h',{}).get('fetched_at'),
                'limitations':['Four-hour buckets use a fixed 09:30 local anchor for supported New York cash instruments; otherwise the first observed session hour. Gapped buckets are omitted. Nominal completion is conservative; exchange holidays/half-days are not independently supplied.']}
        timeframes=analyze_timeframes(frames,metadata=metadata)
        peers=[]
        for peer in config.get('peer_tickers',[]):
            if peer==ticker:continue
            try:
                source=self.provider.company_info(peer)
                peers.append({'ticker':peer,'info':source['data'],'fetched_at':source.get('fetched_at'),'cache_stale':source.get('cache_stale',False)})
            except (DataUnavailable,AttributeError):limits.append(f'Peer {peer} unavailable; no peer multiple was invented.')
        history=None
        if not base['overview'].get('is_fund'):
            try:history=self.provider.valuation_history(ticker)
            except (DataUnavailable,AttributeError):limits.append('Vendor historical valuation table unavailable.')
        valuation=enhance_valuation({**bundle.get('info',{}),'currentPrice':base['overview']['price']},base['fundamentals'],base['valuation'],assumptions,peers,history)
        core=build_quant_core(bundle,base,config,benchmark,timeframes,valuation,True)
        relevant={k:config.get(k) for k in ('capital','risk_per_trade','horizon','risk_tolerance','min_reward_risk','commission_bps','slippage_bps','max_holding_bars','min_samples')}
        def fingerprint(frame):
            return hashlib.sha256(pd.util.hash_pandas_object(frame[['Open','High','Low','Close','Volume']],index=True).values.tobytes()).hexdigest() if frame is not None and not frame.empty else None
        key='quant:validation:'+hashlib.sha256(json.dumps([RULE_CACHE_VERSION,ticker,fingerprint(daily),fingerprint(benchmark),relevant],sort_keys=True).encode()).hexdigest()
        cached=self.store.cache_get(key)
        if cached:
            validation=cached['value']
        else:
            validation=clean(validate_strategies(daily,config,benchmark))
            self.store.cache_set(key,validation)
        best=next((s for s in core['strategies'] if s['id']==core['recommendation'].get('best_strategy')),None)
        records=validation.get('strategies',{}).get(best['id'],{}).get('probability_records',[]) if best else []
        probabilities=estimate_probabilities(records,best or {'as_of':core['as_of']},as_of=core['as_of'],min_samples=config['min_samples'])
        if not best:probabilities['limitations'].append('No eligible current strategy exists; no current trade probability is implied by a backtest table.')
        core['evidence']['sample_reliability']={'status':probabilities['status'],'sample_size':probabilities['sample_size'],'min_samples':config['min_samples'],'validation_period':probabilities['validation_period']}
        core['evidence']['limitations'].extend(limits)
        core['evidence']['model_uncertainty']['limitations'].append('Historical validation excludes unavailable historical earnings/macro/intraday-alignment gates. It validates shared daily price rules, not every live context filter.')
        result=clean({**core,'timeframes':timeframes,'validation':validation,'probabilities':probabilities,'configuration':config})
        from app.service import render_report
        report_data={**base,'quant_core':result,'score':result['score_adapter'],'trade_plan':result['recommendation'],'valuation':result['valuation']}
        result['report']={'markdown':render_report(report_data),'generator':'Deterministic version2 quantitative evidence synthesis','llm_used':False}
        return result
