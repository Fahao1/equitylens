import pytest
from app.analysis.valuation_models import enhance_valuation
from app.analysis.quant_scoring import quantitative_scores


def test_earnings_and_fcf_scenarios_exact_math_and_mos():
    info={'currentPrice':80,'trailingEps':5,'freeCashflow':100,'sharesOutstanding':10,'currency':'USD','financialCurrency':'USD'}
    r=enhance_valuation(info,{}, {'score':5,'confidence':.45,'limitations':[]},{'earnings_multiples':[10,20,30],'fcf_yields':[.1,.08,.05]})
    assert r['models']['earnings_multiple']=={'bear':50,'base':100,'bull':150}
    assert r['models']['fcf_yield']=={'bear':100,'base':125,'bull':200}
    assert r['valuation_range']=={'bear':75,'base':112.5,'bull':175}
    assert r['margin_of_safety']==pytest.approx(1-80/112.5)


def test_comparable_peer_and_historical_data_are_required():
    info={'currentPrice':100,'trailingPE':20,'industry':'Software','currency':'USD'}
    old={'score':9,'confidence':.5,'limitations':[]}
    assert enhance_valuation(info,{},old)['score'] is None
    peers=[{'ticker':str(i),'info':{'trailingPE':30,'trailingEps':2,'industry':'Software','currency':'USD'}} for i in range(3)]
    assert enhance_valuation(info,{},old,peers=peers)['score']>5
    peers[0]['info']['industry']='Banks'
    assert enhance_valuation(info,{},old,peers=peers)['score'] is None


def test_unverified_currency_cannot_create_intrinsic_price_scenarios():
    info={'currentPrice':80,'trailingEps':5,'freeCashflow':100,'sharesOutstanding':10,'currency':'USD'}
    result=enhance_valuation(info,{}, {'confidence':1,'limitations':[]},{'earnings_multiples':[10,20,30],'fcf_yields':[.1,.08,.05]})
    assert result['models']=={} and result['valuation_range'] is None and result['score'] is None


def test_new_scores_do_not_relabel_missing_quality_or_disagreement_as_probability():
    base={'fundamentals':{'score':8,'risk_score':8},'technical':{'score':7},'macro':{'score':None},'news':{'score':10},'overview':{}}
    r=quantitative_scores(base,[],{'horizon':'long'},{'score':4})
    assert r['company_quality']==8 and r['trade_setup_quality'] is None
    assert r['news_modifier']==.25 and 'confidence' not in r
    base['fundamentals']={}
    assert quantitative_scores(base,[],{'horizon':'long'},{'score':10})['overall_investment_attractiveness'] is None
