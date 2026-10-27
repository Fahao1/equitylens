from app.analysis.execution import calculate_execution
from app.utils import number

NAMES={'trend_following':'Trend following','breakout':'Breakout trading','mean_reversion':'Mean reversion','fundamental_value':'Fundamental value investing'}


def result(strategy,snapshot,context,config):
    return {'id':strategy,'name':NAMES[strategy],'status':'wait','eligible':False,'entry_condition':'Required confirmations have not all occurred.',
      'entry_zone':None,'entry_reference':None,'stop':None,'targets':[],'net_reward_risk':[],'risk_reward':None,'position_size':0,
      'holding_horizon':{'short':'1–5 sessions','swing':'2–8 weeks','long':'1–3 years'}.get(config.get('horizon','swing'),'2–8 weeks'),
      'horizon':config.get('horizon','swing'),'max_holding_bars':config.get('max_holding_bars',20),
      'atr':snapshot.get('atr'),'regime':context.get('regime',{}).get('regime','Insufficient Data'),
      'evidence':[],'avoid_reasons':[],'invalidation':{'price':None,'kind':'technical','condition':'No confirmed setup.'},
      'target_methodology':[],'calculation':[],'as_of':snapshot.get('as_of')}


def reject(out,reason,status='wait'):
    out['avoid_reasons'].append(reason)
    out['status']=status
    return out


def prerequisites(out,snapshot,context):
    if not snapshot.get('atr') or not snapshot.get('close') or snapshot.get('bars',0)<200:
        reject(out,'At least 200 completed daily bars, a positive price and ATR are required.','insufficient_data');return False
    if context.get('stale') or context.get('incomplete'):
        reject(out,'Current source evidence is stale or the decision candle is incomplete.','insufficient_data');return False
    if context.get('event_risk',{}).get('blocked'):
        reject(out,'A known imminent earnings or high-impact macro event blocks new entries under this strategy.');return False
    alignment=context.get('timeframes',{}).get('alignment',{})
    if alignment.get('status') in ('contradictory','conflicting') or alignment.get('contradictions'):
        reject(out,'Higher-timeframe context contradicts the proposed long setup.');return False
    return True


def support_zone(snapshot):
    close=snapshot.get('close') or 0
    return next((z for z in snapshot.get('support_zones',[]) if z.get('touches',0)>=2 and 0<z['price']<=close),None)


def technical_stop(zone,atr,context,config):
    buffer={'low':1.25,'medium':1.,'high':.75}[config.get('risk_tolerance','medium')]
    if context.get('regime',{}).get('volatility_regime')=='High':buffer+=.5
    return zone['lower']-buffer*atr,buffer


def finalize(out,entry,stop,targets,snapshot,context,config):
    targets=sorted(set(float(t) for t in targets if number(t) is not None and t>entry[1]))[:3]
    execution=calculate_execution(entry,stop,targets,config,existing_price=snapshot['close'])
    out.update({k:v for k,v in execution.items() if k not in ('errors','calculation')})
    out['calculation'].extend(execution['calculation'])
    if out['invalidation']['kind']=='technical':
        out['invalidation']['price']=execution.get('stop')
    else:
        out['capital_risk_stop']=execution.get('stop')
    if not execution['valid']:
        return reject(out,'Invalid entry/stop geometry: '+'; '.join(execution['errors']),'avoid')
    if not targets:
        return reject(out,'No independently justified target above entry.','avoid')
    if not execution['risk_qualified']:
        out['position_size']=0
        out['position_value']=0
        out['estimated_capital_risk']=execution.get('existing_capital_risk',0)
        return reject(out,'First-target net reward/risk or capital/risk capacity fails the configured minimum.','avoid')
    out.update(status='eligible',eligible=True)
    return out
