from .common import result,prerequisites,reject,support_zone,technical_stop,finalize
from app.utils import number


def evaluate(snapshot,context,config):
    out=result('fundamental_value',snapshot,context,config)
    out['holding_horizon']='1–3 years; valuation is not a short-term trading target'
    if context.get('historical'):
        return reject(out,'Insufficient historical evidence: verified point-in-time financial statements and valuation assumptions are unavailable.','not_applicable')
    if context.get('is_fund'):
        return reject(out,'Operating-company cash-flow value investing is not applicable to ETF or mutual-fund shares.','not_applicable')
    if config.get('horizon','swing')!='long':return reject(out,'Fundamental value strategy requires an explicit long-term horizon.','not_applicable')
    if not prerequisites(out,snapshot,context):return out
    financial=context.get('fundamentals',{});valuation=context.get('valuation',{})
    if financial.get('source_metadata',{}).get('cache_stale') or (financial.get('statement_age_days') or 0)>550:
        return reject(out,'Financial source evidence is stale; a current fundamental-value entry is withheld.','insufficient_data')
    metrics=financial.get('metrics',{});quality=number(context.get('company_quality'))
    if quality is None or quality<7 or (number(metrics.get('free_cash_flow')) or 0)<=0 or number(metrics.get('eps_growth_yoy')) is None or metrics['eps_growth_yoy']<0:
        return reject(out,'Requires company quality ≥7, positive reported free cash flow and nonnegative comparable EPS growth.','insufficient_data' if quality is None else 'avoid')
    scenarios=valuation.get('valuation_range') or {}
    base=number(scenarios.get('base'));bear=number(scenarios.get('bear'));bull=number(scenarios.get('bull'))
    if base is None or bear is None or base<=0:
        return reject(out,'Transparent bear/base valuation scenarios are required; a generic yield score is insufficient.','insufficient_data')
    mos=float(config.get('margin_of_safety',.2));ceiling=base*(1-mos);close=snapshot['close'];atr=snapshot['atr']
    if close>ceiling:return reject(out,f"Quoted decision close is above the required {mos:.0%} margin-of-safety ceiling ({ceiling:.4f}).")
    zone=support_zone(snapshot)
    if not zone:return reject(out,'No confirmed support is available for a separately defined capital-risk stop; thesis invalidation alone is not a price stop.')
    entry=[max(zone['lower'],min(close,bear)-.25*atr),min(close,ceiling)]
    stop,buffer=technical_stop(zone,atr,context,config)
    targets=[x for x in (base,bull) if x is not None]
    out.update(entry_condition='Long-horizon margin-of-safety price inside the supported zone, followed by review of business risks and new filings.',
      invalidation={'price':None,'kind':'thesis','condition':'Reassess if durable cash generation, competitive position or balance-sheet resilience deteriorates; this is separate from the technical capital-risk stop.'},
      evidence=[f"Company quality {quality:.2f}/10; base scenario {base:.4f}, margin-of-safety ceiling {ceiling:.4f}."],
      target_methodology=['Base/bull valuation scenarios are long-horizon sensitivity estimates, never short-term technical forecasts.'],
      calculation=[f"Valuation entry ceiling = base × (1 − {mos}); capital-risk stop uses support low −{buffer} ATR, independently of thesis invalidation."])
    return finalize(out,entry,stop,targets,snapshot,context,config)
