from datetime import datetime, timezone, timedelta
import pytest
from app.analysis.scoring import score_stock, DEFAULT_WEIGHTS
from app.analysis.trade import build_trade_plan
from app.schemas import TradeRequest, Weights


def test_scoring_coverage_contributions_and_quality():
    inputs={k:{'score':8,'confidence':1,'risk_score':8} for k in DEFAULT_WEIGHTS}
    inputs['valuation']={'score':2,'confidence':1}
    r=score_stock(inputs)
    assert r['overall']==6.8 and r['company_quality']==8
    assert sum(x['contribution'] for x in r['categories'])==pytest.approx(6.8)
    inputs['macro']={'score':None,'confidence':0}
    r=score_stock(inputs)
    assert r['coverage']==.9 and r['confidence']<=.9 and r['company_quality']==8
    inputs['financial']={'score':None,'confidence':0}
    assert score_stock(inputs)['overall'] is None
    with pytest.raises(ValueError): Weights(financial=.5)
    with pytest.raises(ValueError): TradeRequest(capital=float('inf'))
    with pytest.raises(ValueError): TradeRequest(risk_per_trade=.2)


def plan(technical=None,macro=None,**config):
    return build_trade_plan({'price':100,'quote_at':'2026-01-01T00:00:00+00:00'},technical or {'indicators':{'atr':2},'structure':{'support':[97,99],'resistance':[112,120]},'trend':'uptrend'}, {},macro or {'upcoming_events':[]},{'overall':8,'confidence':.8},{**TradeRequest().model_dump(mode='json'),**config})


def test_sizing_uses_displayed_worst_fill_and_first_target():
    r=plan()
    assert r['recommendation']=='Buy candidate'
    assert r['entry_zone']==[98.5,99.5] and r['stop']==95.5
    assert r['risk_reward']==3.12 and r['position_size']==25
    assert r['estimated_capital_risk']==100 and r['position_value']<=10000


def test_targets_not_manufactured_existing_positions_and_events():
    r=plan({'indicators':{'atr':2},'structure':{'support':[99],'resistance':[]}})
    assert r['recommendation']=='Wait' and r['targets']==[] and r['position_size']==0
    r=plan(existing_shares=20,cost_basis=90)
    assert r['position_size']<=2 and r['unrealized_pnl']==200 and r['estimated_capital_risk']<=100
    event={'title':'Synthetic test event','impact':'High','scheduled_at':(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat()}
    r=plan(macro={'upcoming_events':[event]})
    assert r['recommendation']=='Wait' and r['position_size']==0 and r['event_warnings']
    assert plan({'indicators':{},'structure':{}})['entry_zone'] is None


@pytest.mark.parametrize('price, support, atr',[(.01,.00975,.001),(.012,.011,.001),(10,9.999,.0001)])
def test_low_price_and_rounding_cannot_create_zero_risk(price,support,atr):
    r=build_trade_plan({'price':price},{'indicators':{'atr':atr},'structure':{'support':[support],'resistance':[price*2]},'trend':'uptrend'}, {},{}, {'overall':8,'confidence':.8},TradeRequest().model_dump(mode='json'))
    if r['position_size']:
        assert r['stop']<r['entry_zone'][0]<=r['entry_zone'][1]
        assert r['position_size']*(r['entry_zone'][1]-r['stop'])<=r['risk_budget']+1e-6


def test_breakout_alternative_requires_independent_target():
    r=plan({'indicators':{'atr':2},'structure':{'support':[97,99],'resistance':[101,112]},'trend':'uptrend'})
    assert r['breakout_entry']==101.2
    assert r['breakout_alternative']['target']==112
    assert r['breakout_alternative']['risk_reward']>=2
    assert 'completed daily close' in r['breakout_alternative']['confirmation']
