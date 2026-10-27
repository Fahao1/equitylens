"""Disjoint research categories; scores never substitute for missing evidence."""
from statistics import mean
import numpy as np
from app.utils import number,clean
from .schemas import SHORT_WEIGHTS,LONG_WEIGHTS


def average(values,minimum=1):
    values=[number(v) for v in values if number(v) is not None]
    return mean(values) if len(values)>=minimum else None


def reference(value,points):
    value=number(value)
    return float(np.interp(value,[p[0] for p in points],[p[1] for p in points])) if value is not None else None


def calculate_scores(base,quant,horizon,weights=None):
    financial=base.get('fundamentals',{});metrics=financial.get('metrics',{});groups=financial.get('group_scores',{})
    technical=quant.get('technical_assessment',{});indicators=technical.get('indicators',{})
    price=number(base.get('overview',{}).get('price'))
    # MA alignment/slopes share one group. Momentum/participation are excluded here.
    trend=number(technical.get('group_scores',{}).get('trend'))
    strategies=[s for s in quant.get('strategies',[]) if s.get('id')!='fundamental_value']
    eligible=[s for s in strategies if s.get('eligible')]
    setup=None
    setup_basis='Setup inputs are incomplete.'
    if eligible:
        rr=max((number(s.get('risk_reward')) or 0) for s in eligible)
        setup=min(10,5+max(0,rr-2)*1.5);setup_basis='Confirmed daily strategy, graded by cost-aware risk geometry.'
    elif strategies and indicators.get('atr') and all(s.get('status') not in ('insufficient_data','not_applicable') for s in strategies):
        setup=2 if any(s.get('status')=='wait' for s in strategies) else 0
        setup_basis='Rules were evaluated and found no confirmed setup; low score describes observed ineligibility, not absent data.'
    momentum=reference(indicators.get('rsi'),[(0,1),(30,2),(50,6),(65,8),(80,4),(100,1)])
    participation=reference(indicators.get('relative_volume'),[(0,1),(.7,3),(1,5),(1.5,8),(2.5,10)])
    momentum_volume=average([momentum,participation],2)
    operating_quality=average([groups.get(k) for k in ('profitability','cash_generation','capital_efficiency')],2)
    resilience=number(financial.get('risk_score'))
    growth=average([groups.get('growth'),reference(metrics.get('revenue_consistency'),[(0,0),(.5,5),(1,10)])])
    if horizon=='short_term':
        values={'technical_strength':trend,'trade_setup_quality':setup,'momentum_volume':momentum_volume,
            'news_catalysts':number(base.get('news',{}).get('score')),
            'fundamentals_risk':average([operating_quality,resilience],2)}
        required=('technical_strength','momentum_volume')
        confidence_sources={'technical_strength':technical.get('confidence'),'trade_setup_quality':quant.get('regime',{}).get('confidence'),
            'momentum_volume':technical.get('confidence'),'news_catalysts':base.get('news',{}).get('confidence'),'fundamentals_risk':financial.get('confidence')}
    else:
        values={'financial_quality_growth':operating_quality,'valuation_attractiveness':number(quant.get('valuation',{}).get('score')),
            'growth_outlook':growth,'financial_resilience':resilience,'technical_entry_timing':trend}
        required=('financial_quality_growth','valuation_attractiveness','growth_outlook')
        confidence_sources={'financial_quality_growth':financial.get('confidence'),'valuation_attractiveness':quant.get('valuation',{}).get('confidence'),
            'growth_outlook':financial.get('confidence'),'financial_resilience':financial.get('confidence'),'technical_entry_timing':technical.get('confidence')}
    weights=weights or (SHORT_WEIGHTS if horizon=='short_term' else LONG_WEIGHTS)
    coverage=sum(weights[k] for k,v in values.items() if v is not None)
    valid=coverage>=.7 and all(values[k] is not None for k in required) and not base.get('overview',{}).get('is_fund')
    score=sum(values[k]*weights[k] for k in values if values[k] is not None)/coverage if valid else None
    confidence=sum(max(0,min(1,number(confidence_sources.get(k)) or 0))*weights[k] for k,v in values.items() if v is not None)
    metric_keys=('revenue_growth_yoy','eps_growth_yoy','operating_margin','free_cash_flow','fcf_margin','roic','debt_to_equity','current_ratio','revenue_consistency')
    missing=[k for k,v in values.items() if v is None]
    return clean({'overall_score':round(score,2) if score is not None else None,'scores':values,'weights':weights,'data_completeness':coverage,
        'confidence':confidence,'missing_information':missing,'metrics_evaluated':sum(metrics.get(k) is not None for k in metric_keys)+sum(indicators.get(k) is not None for k in ('sma_50','sma_200','adx','atr','rsi','relative_volume')),
        'setup_score':setup,'setup_score_basis':setup_basis,'growth_score':growth,'price_available':price is not None,
        'contributions':{k:values[k]*weights[k] if values[k] is not None else None for k in values},
        'methodology':'Known weighted category sum / known weight, minimum70% coverage and required horizon categories. Confidence is separate. These are configurable reference assumptions, not optimized return forecasts.',
        'limitations':['MA trend excludes RSI/volume; operating quality excludes separately scored growth and resilience. Setup confirmation is an eligibility gate; only risk geometry grades an eligible setup. News cannot replace financial evidence.',
            'Growth outlook describes historical reported growth/consistency, not a verified moat, management skill or future earnings forecast.']})


def rank_rows(rows,filters=None):
    """Deterministic tie-breaking; unknown scores never become numeric zero."""
    filters=filters or {};eligible=[];excluded=[]
    for row in rows:
        reasons=[]
        if row.get('cache_stale'):reasons.append('Stale source evidence is excluded from current ranking.')
        if row.get('overall_score') is None:reasons.append('Required scoring evidence is incomplete.')
        if (number(row.get('confidence')) or 0)<.35:reasons.append('Evidence confidence is below the disclosed35% ranking floor.')
        for name,field in [('industries','industry'),('exchanges','exchange'),('countries','listing_country')]:
            if filters.get(name) and str(row.get(field) or '').casefold() not in [str(v).casefold() for v in filters[name]]:reasons.append(f'{field} does not match the selected filter.')
        for name,field,upper in [('market_cap_min','market_cap',False),('market_cap_max','market_cap',True),('average_volume_min','average_volume',False)]:
            threshold=filters.get(name)
            if threshold is not None:
                actual=number(row.get(field))
                if actual is None or (actual>threshold if upper else actual<threshold):reasons.append(f'{field} does not meet the selected size/liquidity filter.')
        checks=[('min_valuation','valuation_attractiveness',False),('min_technical','technical_strength',False),('min_overall','overall_score',False),('max_forward_pe','forward_pe',True),('min_revenue_growth','revenue_growth',False)]
        for requested,field,upper in checks:
            threshold=filters.get(requested)
            if threshold is None:continue
            value=number(row.get(field))
            if value is None or (value>threshold if upper else value<threshold):reasons.append(f'{field} does not meet the requested filter or is unavailable.')
        if filters.get('profitable_only') and (number(row.get('net_income')) is None or row['net_income']<=0):reasons.append('Positive reported net income required.')
        row={**row,'rank':None,'ranking_exclusions':reasons}
        (excluded if reasons else eligible).append(row)
    eligible.sort(key=lambda r:(-r['overall_score'],-(r.get('confidence') or 0),r['ticker']))
    for rank,row in enumerate(eligible,1):row['rank']=rank
    return eligible,excluded
