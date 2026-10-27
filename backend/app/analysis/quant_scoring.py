"""Horizon-aware scores kept separate from evidence quality and statistical reliability."""
from statistics import mean
from app.utils import number


def quality_score(financial):
    a=number(financial.get('score'));b=number(financial.get('risk_score'))
    return round(.7*a+.3*b,2) if a is not None and b is not None else None


def quantitative_scores(base,strategies,config,valuation):
    quality=quality_score(base.get('fundamentals',{}));technical=number(base.get('technical',{}).get('score'))
    eligible=[s for s in strategies if s.get('eligible')]
    setup=None
    if eligible:
        best=max(eligible,key=lambda s:s.get('risk_reward') or 0)
        # Setup score describes risk geometry/confirmation, never repeats RSI/trend votes.
        rr=best['risk_reward'];setup=min(10,5+max(0,rr-config.get('min_reward_risk',2))*1.5)
    values={'company_quality':quality,'valuation_attractiveness':number(valuation.get('score')),'technical_strength':technical,
            'trade_setup_quality':setup,'macroeconomic_environment':number(base.get('macro',{}).get('score'))}
    original=config.get('weights') or {'financial':.25,'valuation':.2,'technical':.2,'risk':.15,'macro':.1,'news':.1}
    mapping={'company_quality':'financial','valuation_attractiveness':'valuation','technical_strength':'technical','trade_setup_quality':'risk','macroeconomic_environment':'macro'}
    multipliers={'short':[.5,.5,1.25,1.5,1.],'swing':[1.,.75,1.25,1.25,1.],'long':[1.5,1.5,.5,.5,.75]}[config.get('horizon','swing')]
    weights={key:float(original.get(old,0))*mult for (key,old),mult in zip(mapping.items(),multipliers)}
    total=sum(weights.values());weights={key:value/total for key,value in weights.items()} if total else weights
    coverage=sum(weights[key] for key,value in values.items() if value is not None)
    contributions={key:(value*weights[key] if value is not None else None) for key,value in values.items()}
    sufficient=coverage>=.7 and quality is not None and technical is not None and not base.get('overview',{}).get('is_fund')
    overall=sum(v for v in contributions.values() if v is not None)/coverage if sufficient else None
    news=number(base.get('news',{}).get('score'));modifier=(news-5)*min(.1,float(original.get('news',0)))*.5 if news is not None else 0
    if overall is not None:overall=max(0,min(10,overall+modifier))
    return {**values,'overall_investment_attractiveness':round(overall,2) if overall is not None else None,
      'weights':weights,'contributions':contributions,'coverage':coverage,'news_modifier':modifier,
      'weight_mapping':{**mapping,'news':'Bounded narrative modifier; not an independent business-quality score.'},
      'horizon':config.get('horizon','swing'),'formula':'Normalize horizon-adjusted known category weights. Withhold overall below70% coverage or absent company quality/technical evidence. Missing data never earns points.',
      'limitations':['Scores are deterministic reference rules, not calibrated probabilities or expected-return estimates. Setup risk geometry is not counted as an additional trend/momentum vote.']}
