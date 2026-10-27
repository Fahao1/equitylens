"""Transparent assumption-driven scenarios and source-bound relative comparisons."""
from copy import deepcopy
from statistics import median
from datetime import datetime,timezone
from app.utils import number
from app.instruments import is_fund


def _positive(value):
    n=number(value)
    return n if n is not None and n>0 else None


def enhance_valuation(info,fundamentals,legacy,assumptions=None,peers=None,history=None):
    result=deepcopy(legacy)
    if is_fund(info):return result
    assumptions=assumptions or {};models={};limitations=result.setdefault('limitations',[])
    price=_positive(info.get('currentPrice')) or _positive(info.get('regularMarketPrice'))
    mismatch=bool(info.get('financialCurrency') and info.get('currency') and info['financialCurrency']!=info['currency'])
    verified_currency=bool(info.get('financialCurrency') and info.get('currency') and not mismatch)
    if not verified_currency:limitations.append('Quote and financial currencies are missing or different; intrinsic per-share scenarios are withheld until units are verified.')
    scenarios=legacy.get('scenarios',{})
    if verified_currency and all(_positive(scenarios.get(k,{}).get('value_per_share')) for k in ('conservative','base','optimistic')):
        models['dcf']={k:scenarios[name]['value_per_share'] for k,name in [('bear','conservative'),('base','base'),('bull','optimistic')]}
    eps=_positive(info.get('trailingEps'));fcf=_positive(info.get('freeCashflow'));shares=_positive(info.get('sharesOutstanding'))
    multiples=assumptions.get('earnings_multiples')
    if multiples is not None:
        if len(multiples)!=3 or not all(_positive(x) for x in multiples) or list(multiples)!=sorted(multiples):
            raise ValueError('Earnings multiples require three positive ordered bear/base/bull values.')
        if eps and verified_currency:
            models['earnings_multiple']={k:eps*float(m) for k,m in zip(('bear','base','bull'),multiples)}
        else:limitations.append('Earnings-multiple scenarios require positive EPS in a verified comparable quote currency.')
    yields=assumptions.get('fcf_yields')
    if yields is not None:
        if len(yields)!=3 or not all(_positive(x) and x<=1 for x in yields) or list(yields)!=sorted(yields,reverse=True):
            raise ValueError('FCF yield scenarios require positive bear/base/bull yields in descending order (fractions <=1).')
        if fcf and shares and verified_currency:
            models['fcf_yield']={k:fcf/shares/float(y) for k,y in zip(('bear','base','bull'),yields)}
        else:limitations.append('FCF-yield scenarios require positive trailing cash flow, a positive share count and compatible currencies.')
    result['models']=models
    result['valuation_range']={k:round(median(model[k] for model in models.values()),2) for k in ('bear','base','bull')} if models else None
    result['margin_of_safety']=(result['valuation_range']['base']-price)/result['valuation_range']['base'] if models and price else None
    result['scenario_assumptions']=assumptions
    result['model_uncertainty']={'independent_models':False,'aggregation':'Median of explicitly supplied model scenarios; models share earnings/cash-flow risks.',
        'base_dispersion':((max(m['base'] for m in models.values())-min(m['base'] for m in models.values()))/median(m['base'] for m in models.values())) if models else None,
        'limitations':['Scenario values are long-term sensitivities, not short-term targets or probabilities. More models do not imply calibrated confidence.']}
    comparable=[];rejected=[]
    for peer in peers or []:
        p=peer.get('info',{})
        if peer.get('cache_stale'):
            rejected.append({'ticker':peer.get('ticker'),'reason':'Peer refresh failed; stale evidence excluded from relative pricing.'});continue
        if is_fund(p) or not info.get('industry') or p.get('industry')!=info.get('industry') or not info.get('currency') or p.get('currency')!=info.get('currency'):
            rejected.append({'ticker':peer.get('ticker'),'reason':'Industry/currency comparability was not established.'});continue
        pe=_positive(p.get('trailingPE'))
        if pe and _positive(p.get('trailingEps')):
            comparable.append({'ticker':peer.get('ticker'),'name':p.get('longName'),'trailing_pe':pe,'industry':p.get('industry'),'currency':p.get('currency'),'fetched_at':peer.get('fetched_at')})
    own_pe=_positive(info.get('trailingPE'))
    result['peer_comparison']={'status':'available' if len(comparable)>=3 else 'Insufficient comparable peers','peers':comparable,'excluded':rejected,
      'minimum_peers':3,'median_pe':median(p['trailing_pe'] for p in comparable) if comparable else None,
      'limitations':['A lower multiple is relative pricing, not proof of undervaluation; growth, accounting and business risk can differ. Peers are user selected, not a survivorship-free universe.']}
    rows=[]
    today=datetime.now(timezone.utc).date().isoformat()
    for row in (history or {}).get('rows',[]):
        if row.get('date','9999')>today:continue
        values=row.get('values',{})
        pe=_positive(values.get('Trailing P/E')) or _positive(values.get('PeRatio'))
        if pe:rows.append({'date':row['date'],'trailing_pe':pe})
    historical_median=median(row['trailing_pe'] for row in rows) if len(rows)>=4 and not (history or {}).get('cache_stale') else None
    result['historical_comparison']={'status':'available' if historical_median else 'Insufficient historical valuation data',
      'observations':rows,'minimum_observations':4,'median_pe':historical_median,'source':(history or {}).get('source'),'fetched_at':(history or {}).get('fetched_at'),'cache_stale':(history or {}).get('cache_stale',False),
      'limitations':['Vendor historical multiples may be restated, are not verified publication-time vintages, and are excluded from backtests. Business mix and growth can change.']}
    if models and price:
        ratio=result['valuation_range']['base']/price-1
        import numpy as np
        result['score']=float(np.interp(ratio,[-.5,-.2,0,.2,.5],[0,2,5,7,10]))
        result['score_basis']='explicit_scenario_reference_scale'
    elif own_pe and len(comparable)>=3:
        result['score']=max(0,min(10,5+5*(result['peer_comparison']['median_pe']/own_pe-1)))
        result['score_basis']='same_industry_peer_relative_multiple'
    elif own_pe and historical_median:
        result['score']=max(0,min(10,5+5*(historical_median/own_pe-1)))
        result['score_basis']='own_historical_relative_multiple'
    else:
        result['score']=None;result['score_basis']=None
        limitations.append('V2 valuation attractiveness is withheld without explicit scenarios or sufficient reliable relative comparisons; the legacy generic yield hurdle is not treated as intrinsic value.')
    result['confidence']=min(float(legacy.get('confidence',0)),.5) if result['score'] is not None else 0
    result['signals']=[]
    if models:result['signals'].append(f"Explicit long-horizon bear/base/bull scenarios: {result['valuation_range']}; margin of safety {result['margin_of_safety']}. Assumptions are sensitivities, not short-term price predictions.")
    if len(comparable)>=3:result['signals'].append(f"{len(comparable)} supplied same-industry/currency peers have median trailing P/E {result['peer_comparison']['median_pe']:.2f}; current P/E {own_pe}. Growth and business risks may differ.")
    if historical_median:result['signals'].append(f"{len(rows)} dated vendor observations have median trailing P/E {historical_median:.2f}; current P/E {own_pe}. These are not verified historical publication vintages.")
    if result['score'] is None:result['signals'].append('Valuation attractiveness is withheld: no sufficient explicit scenario or reliable relative comparison. Generic yield hurdles do not establish intrinsic value.')
    result['methodology_version']='2.0'
    return result
