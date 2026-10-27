"""Evidence-derived inactive scenarios never pretend their confirmations occurred."""
from app.analysis.execution import calculate_execution
from app.utils import number,clean


SCENARIOS=[('support_bounce','Support bounce','mean_reversion'),('breakout','Breakout','breakout'),
    ('trend_reversal','Trend reversal',None),('trend_continuation','Trend continuation','trend_following'),
    ('fundamental_accumulation','Fundamental accumulation','fundamental_value')]


def conditional_scenarios(quant,config,horizon):
    technical=quant.get('technical_assessment',{});ind=technical.get('indicators',{});structure=technical.get('structure',{})
    atr=number(ind.get('atr'));support=next((z for z in structure.get('support_zones',[]) if z.get('touches',0)>=2),None)
    resistance=next((z for z in structure.get('resistance_zones',[]) if z.get('touches',0)>=2),None)
    strategies={s['id']:s for s in quant.get('strategies',[])};out=[]
    buffer={'low':1.25,'medium':1,'high':.75}[config.get('risk_tolerance','medium')]
    if quant.get('regime',{}).get('volatility_regime')=='High':buffer+=.5
    for sid,name,strategy_id in SCENARIOS:
        strategy=strategies.get(strategy_id,{})
        row={'id':sid,'name':name,'status':'Insufficient evidence','entry_zone':None,'stop':None,'targets':[],
            'risk_reward':None,'position_size':0,'holding_horizon':'1–63 trading sessions' if horizon=='short_term' else '1–5+ years with periodic thesis review',
            'entry_condition':strategy.get('entry_condition'),'invalidation':strategy.get('invalidation'),
            'evidence':list(strategy.get('evidence',[])),'calculation':[],'limitations':['Conditional scenario; its confirmation is not assumed. No inactive scenario allocates new shares.']}
        if sid=='fundamental_accumulation':row['holding_horizon']='1–5+ years with periodic thesis review; valuation is not a short-term price target'
        if strategy.get('entry_zone') and strategy.get('stop'):
            row.update({k:strategy.get(k) for k in ('entry_zone','stop','targets','risk_reward','net_reward_risk','calculation','entry_condition','invalidation')})
            row['status']='Active' if strategy.get('eligible') and quant.get('recommendation',{}).get('recommendation')=='Buy candidate' and quant.get('recommendation',{}).get('best_strategy')==strategy_id else 'Waiting for confirmation'
            if strategy.get('status')=='avoid':row['status']='Invalidated'
        elif sid in ('support_bounce','trend_continuation','trend_reversal') and support and atr:
            entry=[max(support['lower'],support['price']-.25*atr),support['price']+.5*atr]
            stop=support['lower']-buffer*atr
            targets=[z['price'] for z in structure.get('resistance_zones',[]) if z.get('touches',0)>=2 and z['price']>entry[1]]
            execution=calculate_execution(entry,stop,targets,config)
            if execution['valid'] and targets:
                row.update({k:v for k,v in execution.items() if k not in ('position_size','position_value','estimated_capital_risk')})
                row.update(status='Waiting for confirmation',entry_condition={
                    'support_bounce':'Price must revisit repeated support and show a completed bullish reversal; regime, RSI/volume, cost and event gates must then be reevaluated.',
                    'trend_continuation':'A bullish regime, pullback to repeated support and completed momentum/volume recovery must all occur before entry.',
                    'trend_reversal':'A completed higher low and recovery above SMA50 with rising momentum must establish a reversal; a low RSI alone does not qualify.'}[sid])
                row['evidence'].append(f"Repeated support {support['price']} ({support['touches']} confirmed pivots); targets are repeated historical resistance.")
                row['invalidation']={'kind':'technical','price':execution['stop'],'condition':'Loss of structural support and its preselected ATR buffer.'}
        elif sid=='breakout' and resistance and atr:
            entry=[resistance['upper']+.05*atr,resistance['upper']+.75*atr]
            targets=[z['price'] for z in structure.get('resistance_zones',[]) if z.get('touches',0)>=2 and z['price']>entry[1]]
            execution=calculate_execution(entry,resistance['lower']-buffer*atr,targets,config)
            if execution['valid'] and targets:
                row.update({k:v for k,v in execution.items() if k not in ('position_size','position_value','estimated_capital_risk')})
                row.update(status='Not triggered',entry_condition='A completed close above repeated resistance, relative volume≥1.5 and acceptable consolidation/regime are required; do not assume an intrabar breakout holds.')
                row['evidence'].append(f"Resistance zone {resistance['lower']}–{resistance['upper']}, confirmed {resistance['touches']} times.")
                row['invalidation']={'kind':'technical','price':execution['stop'],'condition':'Failure back through the resistance zone and its ATR buffer.'}
        elif sid=='fundamental_accumulation':
            fair=quant.get('valuation',{}).get('valuation_range') or {};bear,base=number(fair.get('bear')),number(fair.get('base'))
            if bear and base:
                ceiling=base*(1-config.get('margin_of_safety',.2))
                row.update(status='Waiting for confirmation',entry_zone=[min(bear,ceiling),ceiling],
                    targets=[fair[k] for k in ('base','bull') if number(fair.get(k)) and fair[k]>ceiling],
                    entry_condition='Accumulate only after fresh filings, financial quality and the required margin of safety support the business thesis; scenario prices are not guaranteed outcomes.',
                    invalidation={'kind':'thesis','price':None,'condition':'Durable cash generation, competitive position or balance-sheet resilience deteriorates; reassess the valuation assumptions.'})
                row['evidence'].append(f"Bear/base scenario {bear}/{base}; accumulation ceiling=base×(1−margin of safety).")
                row['limitations'].append('No short-term ATR stop or position allocation is inferred for this fundamental-only scenario.')
        if row.get('risk_reward') is not None and row['risk_reward']<config.get('min_reward_risk',2):
            row['status']='Invalidated';row['limitations'].append('Net first-target reward/risk fails the configured threshold; original levels were retained.')
        row['position_size']=0
        out.append(row)
    return clean(out)
