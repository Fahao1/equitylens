from datetime import datetime, timezone
import pytest
from app.analysis.fundamentals import analyze_fundamentals, ratio, growth


def record(date,**values):
    return {'date':date,'values':values}


def statements():
    return {
      'annual_income':[
        record('2025-12-31',**{'Total Revenue':1000,'Net Income':100,'Operating Income':150,'Gross Profit':400,'Interest Expense':10,'Diluted EPS':2,'Diluted Average Shares':50,'Pretax Income':125,'Tax Provision':25}),
        record('2024-12-31',**{'Total Revenue':800,'Net Income':80,'Operating Income':120,'Diluted EPS':1.6,'Diluted Average Shares':50})],
      'annual_balance':[
        record('2025-12-31',**{'Total Debt':200,'Cash And Cash Equivalents':100,'Stockholders Equity':500,'Total Assets':900,'Current Assets':300,'Current Liabilities':150,'Inventory':50}),
        record('2024-12-31',**{'Total Debt':180,'Cash And Cash Equivalents':80,'Stockholders Equity':400,'Total Assets':800})],
      'annual_cashflow':[
        record('2025-12-31',**{'Operating Cash Flow':180,'Capital Expenditure':-50,'Cash Dividends Paid':-26}),
        record('2024-12-31',**{'Operating Cash Flow':150,'Capital Expenditure':-50})],
      'quarterly_income':[
        record('2026-03-31',**{'Total Revenue':300,'Diluted EPS':.7}),
        record('2025-12-31',**{'Total Revenue':250,'Diluted EPS':.5}),
        record('2025-03-31',**{'Total Revenue':240,'Diluted EPS':.5})]}


NOW = datetime(2026,5,1,tzinfo=timezone.utc)


def test_ratios_known_reference():
    result = analyze_fundamentals(statements(),{'sector':'Technology'},NOW)
    m = result['metrics']
    assert m['revenue_growth_yoy'] == pytest.approx(.25)
    assert m['gross_margin'] == .4
    assert m['net_margin'] == .1
    assert m['roe'] == pytest.approx(100/450)
    assert m['roa'] == pytest.approx(100/850)
    assert m['roic'] == pytest.approx(120/550)
    assert m['total_debt'] == 200
    assert m['net_debt'] == 100
    assert m['debt_to_equity'] == .4
    assert m['current_ratio'] == 2
    assert m['quick_ratio'] == pytest.approx(250/150)
    assert m['interest_coverage'] == 15
    assert m['free_cash_flow'] == 130
    assert m['free_cash_flow_growth'] == pytest.approx(.3)
    assert m['cash_conversion'] == 1.8
    assert m['dividend_fcf_payout'] == .2
    assert m['revenue_growth_qoq'] == pytest.approx(.2)
    assert m['quarterly_revenue_growth_yoy'] == pytest.approx(.25)
    assert result['score'] is not None
    assert result['risk_score'] is not None


def test_zero_negative_and_missing_denominators():
    assert ratio(10,0) is None
    assert ratio(10,-2) is None
    assert growth(5,-5) is None
    data = statements()
    data['annual_balance'][0]['values']['Stockholders Equity'] = -50
    data['annual_income'][1]['values']['Net Income'] = -80
    data['annual_income'][0]['values']['Interest Expense'] = 0
    result = analyze_fundamentals(data,{},NOW)
    assert result['metrics']['debt_to_equity'] is None
    assert result['metrics']['roe'] is None
    assert result['metrics']['net_income_growth_yoy'] is None
    assert result['metrics']['interest_coverage'] is None
    assert any('Nonpositive equity' in text for text in result['limitations'])
    assert analyze_fundamentals({}, {},NOW)['score'] is None


def test_misaligned_periods_not_mixed():
    data = statements()
    data['annual_cashflow'][0]['date'] = '2025-09-30'
    data['annual_balance'][0]['date'] = '2025-09-30'
    result = analyze_fundamentals(data,{},NOW)
    assert result['metrics']['free_cash_flow'] is None
    assert result['metrics']['current_ratio'] is None


@pytest.mark.parametrize('industry',['Banks - Diversified','Insurance - Life','REIT - Retail'])
def test_special_sectors_abstain_generic_scores(industry):
    result = analyze_fundamentals(statements(),{'industry':industry},NOW)
    assert result['score'] is None
    assert result['risk_score'] is None
    assert result['metrics']['roic'] is None


def test_stale_and_future_statements():
    old = analyze_fundamentals(statements(),{},datetime(2030,1,1,tzinfo=timezone.utc))
    fresh = analyze_fundamentals(statements(),{},NOW)
    assert old['confidence'] < fresh['confidence']
    assert any('550 days' in text for text in old['limitations'])
    past = analyze_fundamentals(statements(),{},datetime(2024,1,1,tzinfo=timezone.utc))
    assert past['score'] is None


def test_financial_score_does_not_double_count_stability():
    original = statements()
    altered = statements()
    altered['annual_balance'][0]['values']['Current Liabilities'] = 10000
    a,b = analyze_fundamentals(original,{},NOW),analyze_fundamentals(altered,{},NOW)
    assert a['score'] == b['score']
    assert a['risk_score'] > b['risk_score']
