from datetime import datetime,timezone,timedelta
import pytest
from app.analysis.valuation import discounted_cash_flow,analyze_valuation
from app.analysis.news import analyze_news


def test_dcf_independent_reference_and_no_debt_double_deduction():
    result = discounted_cash_flow(100,10,.05,.1,.02,5)
    explicit = sum(100*1.05**i/1.1**i for i in range(1,6))
    terminal = 100*1.05**5*1.02/(.1-.02)/1.1**5
    assert result['value_per_share'] == round((explicit+terminal)/10,2)
    assert result['terminal_value_share'] == pytest.approx(terminal/(explicit+terminal))


@pytest.mark.parametrize('kwargs',[{'base_fcf':-1},{'shares':0},{'discount_rate':.02},{'years':0},{'years':2.2},{'growth':float('nan')}])
def test_invalid_dcf_assumptions(kwargs):
    assumptions = dict(base_fcf=100,shares=10,growth=.05,discount_rate=.1,terminal_growth=.02,years=5)
    assumptions.update(kwargs)
    with pytest.raises(ValueError):
        discounted_cash_flow(**assumptions)


def test_valuation_yield_reference_missing_and_negative_earnings():
    info = {'currentPrice':100,'marketCap':1000,'freeCashflow':50,'trailingEps':5,'trailingPE':20,'dividendRate':1}
    result = analyze_valuation(info,{})
    assert result['score'] == 6
    assert result['score_basis'] == 'free_cash_flow_yield'
    assert result['metrics']['dividend_yield'] == .01
    assert result['scenarios'] == {}
    assert analyze_valuation({}, {})['score'] is None
    info.update(trailingEps=-5,trailingPE=-20,freeCashflow=None)
    negative = analyze_valuation(info,{})
    assert negative['metrics']['trailing_pe'] is None
    assert negative['metrics']['earnings_yield'] == -.05
    assert negative['score'] == 0


def test_dcf_scenarios_and_currency_mismatch():
    info = {'currentPrice':100,'marketCap':1000,'freeCashflow':100,'sharesOutstanding':10}
    result = analyze_valuation(info,{}, {'growth':.05,'discount_rate':.1,'terminal_growth':.02})
    scenarios = result['scenarios']
    assert scenarios['conservative']['value_per_share'] < scenarios['base']['value_per_share'] < scenarios['optimistic']['value_per_share']
    mismatch = analyze_valuation({**info,'financialCurrency':'EUR','currency':'USD'}, {}, {})
    assert mismatch['metrics']['fcf_yield'] is None
    assert mismatch['scenarios'] == {}


NOW = datetime(2026,5,1,tzinfo=timezone.utc)


def article(title,**kwargs):
    return {'title':title,'url':'https://example.com/'+title.replace(' ','-'),'publisher':'Test Wire',
            'published_at':(NOW-timedelta(days=1)).isoformat(),**kwargs}


def test_news_deduplication_scope_recency_and_source_grounding():
    a = article('Company raises guidance')
    result = analyze_news([a,{**a,'url':a['url']+'?utm_source=syndicate'},article('Company cuts guidance',published_at=(NOW-timedelta(days=100)).isoformat())],NOW)
    assert len(result['articles']) == 2
    assert result['score'] == 7.5
    assert result['articles'][0]['content_scope'] == 'headline'
    assert result['bullish'][0]['url'] == a['url']
    assert result['llm_used'] is False


def test_news_ambiguous_negation_unreleased_and_unlinked_abstain():
    future = article('Company record revenue',published_at=(NOW+timedelta(hours=1)).isoformat())
    uncertain = article('Company denies fraud')
    unlinked = article('Company raises guidance',url=None)
    result = analyze_news([future,uncertain,unlinked],NOW)
    assert len(result['articles']) == 2
    assert result['score'] is None
    assert next(x for x in result['articles'] if 'denies' in x['title'])['sentiment'] == 'uncertain'
    assert analyze_news([],NOW)['score'] is None
