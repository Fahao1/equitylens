from copy import deepcopy
from app.analysis.strategies import evaluate_strategies


def snapshot():
    zone={'price':100.,'lower':99.9,'upper':100.1,'touches':3,'confirmed_at':'2026-01-01T00:00:00+00:00','pivots':[{'kind':'high'}]}
    return {'as_of':'2026-01-02T00:00:00+00:00','bars':300,'close':100.4,'atr':1.,'rsi':51,'rsi_previous':47,'previous_close':100.2,'relative_volume':1.5,'adx':27,
      'support_zones':[zone],'resistance_zones':[{'price':110.,'touches':2}],'swing_high':111.,'range_atr_20':5.,'prior_high_20':101.,'prior_low_20':96.,'bollinger_lower':99,'previous_bollinger_lower':99,'sma_20':105,'sma_50':107}


def by_id(data,key):return next(r for r in data if r['id']==key)


def test_trend_confirmation_costs_and_target_provenance():
    r=by_id(evaluate_strategies(snapshot(),{'regime':{'regime':'Strong bullish trend'}},{'min_reward_risk':2}),'trend_following')
    assert r['eligible'] and r['targets']==[110,111]
    assert r['stop']==98.9 and r['risk_reward']>2 and r['position_size']>0
    assert all('guarantee' not in x for x in r['evidence'])


def test_unconfirmed_or_event_blocked_is_never_actionable():
    s=snapshot();s['relative_volume']=None
    assert not by_id(evaluate_strategies(s,{'regime':{'regime':'Strong bullish trend'}},{}),'trend_following')['eligible']
    assert not any(r['eligible'] for r in evaluate_strategies(snapshot(),{'regime':{'regime':'Strong bullish trend'},'event_risk':{'blocked':True}},{}))


def test_breakout_and_mean_reversion_require_different_confirmations():
    s=snapshot();s.update(previous_close=99.8,rsi=60,relative_volume=2)
    r=by_id(evaluate_strategies(s,{'regime':{'regime':'Weak bullish trend'}},{}),'breakout')
    assert r['eligible'] and 105 in r['targets']
    s=snapshot();s.update(previous_close=98.5,bollinger_lower=99.5,rsi_previous=29,rsi=33,adx=15)
    r=by_id(evaluate_strategies(s,{'regime':{'regime':'Sideways consolidation'}},{}),'mean_reversion')
    assert r['eligible'] and r['targets'][0]==105


def test_value_has_thesis_invalidation_and_no_historical_financial_leakage():
    context={'regime':{'regime':'Weak bullish trend'},'company_quality':8,'fundamentals':{'metrics':{'free_cash_flow':100,'eps_growth_yoy':.1}},'valuation':{'valuation_range':{'bear':105,'base':150,'bull':170}}}
    r=by_id(evaluate_strategies(snapshot(),context,{'horizon':'long'}),'fundamental_value')
    assert r['eligible'] and r['invalidation']['kind']=='thesis' and r['targets']==[150,170]
    context['historical']=True
    assert by_id(evaluate_strategies(snapshot(),context,{'horizon':'long'}),'fundamental_value')['status']=='not_applicable'


def test_mean_reversion_cannot_use_current_band_as_the_prior_breach():
    s=snapshot()
    s.update(previous_close=98.5,previous_bollinger_lower=98.,bollinger_lower=99.5,
             rsi_previous=29,rsi=33,adx=15)
    result=by_id(evaluate_strategies(s,{'regime':{'regime':'Sideways consolidation'}},{}),'mean_reversion')
    assert result['eligible'] is False
    assert result['position_size'] == 0
    assert any('prior close below its own' in reason for reason in result['avoid_reasons'])


def test_mean_reversion_abstains_without_the_prior_bar_band():
    s=snapshot()
    s.update(previous_close=98.5,bollinger_lower=99.5,rsi_previous=29,rsi=33,adx=15)
    s.pop('previous_bollinger_lower')
    result=by_id(evaluate_strategies(s,{'regime':{'regime':'Sideways consolidation'}},{}),'mean_reversion')
    assert result['eligible'] is False
    assert result['status'] == 'insufficient_data'
