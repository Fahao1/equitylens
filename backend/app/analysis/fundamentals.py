"""Financial ratios from date-matched Yahoo statements, with explicit abstention."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from app.instruments import is_fund, instrument_type
from .technical import finite


def ratio(numerator, denominator, positive=True):
    a, b = finite(numerator), finite(denominator)
    if a is None or b is None or b == 0 or (positive and b <= 0):
        return None
    return a/b


def growth(current, previous):
    value = ratio(current, previous)
    return value-1 if value is not None else None


def value(record, *names):
    values = (record or {}).get('values', {})
    for name in names:
        result = finite(values.get(name))
        if result is not None:
            return result
    return None


def _date(record):
    try:
        return datetime.fromisoformat(record['date'].replace('Z','+00:00')).replace(tzinfo=timezone.utc)
    except (ValueError, KeyError, TypeError):
        return None


def _records(statements, key, now):
    records = [r for r in statements.get(key, []) if isinstance(r, dict) and _date(r) and _date(r) <= now]
    return sorted(records, key=lambda r: r['date'], reverse=True)


def _matched(records, when, tolerance=10):
    if when is None:
        return None
    return next((r for r in records if abs((_date(r)-when).days) <= tolerance), None)


def _prior(records, current, days):
    when = _date(current)
    if when is None:
        return None
    return next((r for r in records if r is not current and abs((when-_date(r)).days-days) <= (45 if days == 365 else 20)), None)


def _fcf(record):
    reported = value(record, 'Free Cash Flow')
    if reported is not None:
        return reported
    ocf, capex = value(record, 'Operating Cash Flow', 'Total Cash From Operating Activities'), value(record, 'Capital Expenditure', 'Capital Expenditures')
    return ocf-abs(capex) if ocf is not None and capex is not None else None


def _debt(record):
    reported = value(record, 'Total Debt')
    if reported is not None:
        return reported
    long, short = value(record,'Long Term Debt'), value(record,'Current Debt')
    return long+short if long is not None and short is not None else None


def _cash(record):
    return value(record, 'Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments')


def _equity(record):
    return value(record, 'Stockholders Equity', 'Common Stock Equity', 'Total Stockholder Equity')


def _investment(record):
    debt, cash, equity = _debt(record), _cash(record), _equity(record)
    return debt+equity-cash if all(x is not None for x in (debt,cash,equity)) else None


def _period(record, cashflows):
    cashflow = _matched(cashflows, _date(record))
    revenue = value(record, 'Total Revenue', 'Operating Revenue')
    income = value(record, 'Net Income', 'Net Income Common Stockholders')
    operating = value(record, 'Operating Income')
    fcf = _fcf(cashflow)
    return {'date': record['date'], 'revenue': revenue, 'net_income': income,
            'operating_income': operating, 'gross_profit': value(record, 'Gross Profit'),
            'eps': value(record,'Diluted EPS','Basic EPS'),
            'operating_cash_flow': value(cashflow,'Operating Cash Flow'),
            'capital_expenditure': value(cashflow,'Capital Expenditure'),
            'free_cash_flow': fcf, 'net_margin': ratio(income,revenue),
            'operating_margin': ratio(operating,revenue), 'fcf_margin': ratio(fcf,revenue)}


def _score(x, points):
    """Linear interpolation between conservative operating-company reference points."""
    if x is None:
        return None
    if x <= points[0][0]:
        return points[0][1]
    for (left, a), (right, b) in zip(points, points[1:]):
        if x <= right:
            return a+(b-a)*(x-left)/(right-left)
    return points[-1][1]


def _average(scores):
    available = [x for x in scores if x is not None]
    return mean(available) if available else None


def analyze_fundamentals(statements: dict, info: dict, now: datetime | None = None) -> dict:
    if is_fund(info):
        return {
            'applicable': False, 'instrument_type': instrument_type(info),
            'score': None, 'risk_score': None, 'confidence': 0.,
            'signals': ['Corporate financial health and company-quality ratios do not apply to a fund; its underlying holdings require a separate portfolio analysis.'],
            'limitations': ['Operating-company statements, profitability, leverage and cash-flow scores are not evaluated for ETF or mutual-fund shares. No fund quality score is inferred from missing or accidental corporate fields.'],
            'metrics': {}, 'periods': [], 'quarterly_periods': [],
            'reporting_date': None, 'quarterly_reporting_date': None,
            'statement_currency': None, 'statement_age_days': None,
        }
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    annual = _records(statements,'annual_income', now)
    quarterly = _records(statements,'quarterly_income', now)
    balance = _records(statements,'annual_balance', now)
    qbalance = _records(statements,'quarterly_balance', now)
    cashflows = _records(statements,'annual_cashflow', now)
    qcashflows = _records(statements,'quarterly_cashflow', now)
    limitations = ['Statement dates are fiscal period ends, not verified filing/publication times. These snapshots are not suitable for point-in-time backtests.']
    result = {'score':None,'confidence':0.,'risk_score':None,'signals':[], 'limitations':limitations,
              'metrics':{},'periods':[_period(r,cashflows) for r in annual],
              'quarterly_periods':[_period(r,qcashflows) for r in quarterly],
              'reporting_date':annual[0]['date'] if annual else None,
              'quarterly_reporting_date':quarterly[0]['date'] if quarterly else None,
              'statement_currency':info.get('financialCurrency'), 'statement_age_days':None}
    if not annual:
        limitations.append('Annual income statement unavailable; no annual financial score is produced.')
        return result
    latest = annual[0]
    when = _date(latest)
    b = _matched(balance,when)
    cf = _matched(cashflows,when)
    previous = _prior(annual,latest,365)
    prior_b = _matched(balance,_date(previous)) if previous else None
    prior_cf = _matched(cashflows,_date(previous)) if previous else None
    if b is None or cf is None:
        limitations.append('Balance-sheet or cash-flow periods do not match the income statement; affected ratios are unavailable.')
    revenue, income = value(latest,'Total Revenue','Operating Revenue'), value(latest,'Net Income','Net Income Common Stockholders')
    operating, gross = value(latest,'Operating Income'), value(latest,'Gross Profit')
    ocf, fcf = value(cf,'Operating Cash Flow'), _fcf(cf)
    debt, cash, equity, assets = _debt(b), _cash(b), _equity(b), value(b,'Total Assets')
    interest = value(latest,'Interest Expense','Interest Expense Non Operating')
    current_assets, current_liabilities = value(b,'Current Assets'), value(b,'Current Liabilities')
    avg_equity = (equity+_equity(prior_b))/2 if equity is not None and equity > 0 and _equity(prior_b) is not None and _equity(prior_b) > 0 else None
    avg_assets = (assets+value(prior_b,'Total Assets'))/2 if assets is not None and value(prior_b,'Total Assets') is not None else None
    average_capital = (_investment(b)+_investment(prior_b))/2 if _investment(b) is not None and _investment(b) > 0 and _investment(prior_b) is not None and _investment(prior_b) > 0 else None
    pretax, tax = value(latest,'Pretax Income'), value(latest,'Tax Provision')
    effective_tax = ratio(tax,pretax)
    nopat = operating*(1-effective_tax) if operating is not None and effective_tax is not None and 0 <= effective_tax <= .5 else None
    inventory = value(b,'Inventory')
    shares, prior_shares = value(latest,'Diluted Average Shares','Basic Average Shares'), value(previous,'Diluted Average Shares','Basic Average Shares')
    metrics = {'revenue':revenue,'net_income':income,'gross_margin':ratio(gross,revenue),
        'operating_margin':ratio(operating,revenue),'net_margin':ratio(income,revenue),
        'revenue_growth_yoy':growth(revenue,value(previous,'Total Revenue','Operating Revenue')),
        'net_income_growth_yoy':growth(income,value(previous,'Net Income','Net Income Common Stockholders')),
        'eps':value(latest,'Diluted EPS','Basic EPS'),
        'eps_growth_yoy':growth(value(latest,'Diluted EPS','Basic EPS'),value(previous,'Diluted EPS','Basic EPS')),
        'roe':ratio(income,avg_equity),'roa':ratio(income,avg_assets),'roic':ratio(nopat,average_capital),
        'effective_tax_rate':effective_tax,'total_debt':debt,'cash':cash,
        'net_debt':debt-cash if debt is not None and cash is not None else None,
        'debt_to_equity':ratio(debt,equity),'current_ratio':ratio(current_assets,current_liabilities),
        'quick_ratio':ratio(current_assets-inventory,current_liabilities) if current_assets is not None and inventory is not None else None,
        'interest_coverage':ratio(operating,abs(interest)) if interest is not None else None,
        'operating_cash_flow':ocf,'free_cash_flow':fcf,'fcf_margin':ratio(fcf,revenue),
        'free_cash_flow_growth':growth(fcf,_fcf(prior_cf)),
        'capital_expenditure':value(cf,'Capital Expenditure'), 'cash_conversion':ratio(ocf,income),
        'share_dilution':growth(shares,prior_shares),
        'research_and_development':value(latest,'Research And Development'),
        'rd_to_revenue':ratio(value(latest,'Research And Development'),revenue),
        'dividends_paid':value(cf,'Cash Dividends Paid','Common Stock Dividend Paid'),
        'share_repurchases':value(cf,'Repurchase Of Capital Stock'),
        'revenue_growth_qoq':None, 'quarterly_revenue_growth_yoy':None,
        'quarterly_eps_growth_yoy':None, 'revenue_consistency':None}
    payout = metrics['dividends_paid']
    metrics['dividend_fcf_payout'] = ratio(abs(payout),fcf) if payout is not None else None
    year_growth = [growth(value(a,'Total Revenue','Operating Revenue'),value(_prior(annual,a,365),'Total Revenue','Operating Revenue')) for a in annual]
    valid_growth = [x for x in year_growth if x is not None]
    metrics['revenue_consistency'] = sum(x>=0 for x in valid_growth)/len(valid_growth) if len(valid_growth)>=2 else None
    if quarterly:
        q = quarterly[0]
        previous_q, previous_y = _prior(quarterly,q,91), _prior(quarterly,q,365)
        metrics['revenue_growth_qoq'] = growth(value(q,'Total Revenue','Operating Revenue'),value(previous_q,'Total Revenue','Operating Revenue'))
        metrics['quarterly_revenue_growth_yoy'] = growth(value(q,'Total Revenue','Operating Revenue'),value(previous_y,'Total Revenue','Operating Revenue'))
        metrics['quarterly_eps_growth_yoy'] = growth(value(q,'Diluted EPS','Basic EPS'),value(previous_y,'Diluted EPS','Basic EPS'))
        if (now-_date(q)).days > 180:
            limitations.append('Latest quarterly statement is more than 180 days old.')
    result['metrics'] = metrics
    age = (now-when).days
    result['statement_age_days'] = age
    if age > 550:
        limitations.append('Latest annual statement is more than 550 days old; financial confidence is reduced.')
    if equity is not None and equity <= 0:
        limitations.append('Nonpositive equity makes ROE and debt-to-equity unsuitable; these ratios are unavailable.')
    if previous and value(previous,'Net Income','Net Income Common Stockholders') is not None and value(previous,'Net Income','Net Income Common Stockholders') <= 0:
        limitations.append('Earnings percentage growth is unavailable when prior earnings are nonpositive; inspect absolute earnings history.')
    industry_text = f"{info.get('industry','')} {info.get('sector','')}".lower()
    specialized = any(term in industry_text for term in ('bank','insurance','reit','real estate investment trust','financial services'))
    if specialized:
        for key in ('roic','current_ratio','quick_ratio','interest_coverage','debt_to_equity'):
            metrics[key] = None
        limitations.append('Banks, insurers, REITs and financial services need regulatory capital, asset quality or FFO baselines unavailable here; generic operating-company financial and resilience scores abstain.')
        result['confidence'] = .25
        return result
    revenue_score = _score(metrics['revenue_growth_yoy'],[(-.2,0),(0,4),(.1,7),(.25,10)])
    growth_score = _average([revenue_score,_score(metrics['eps_growth_yoy'],[(-.3,0),(0,4),(.1,7),(.3,10)])])
    profit_score = _score(metrics['operating_margin'],[(-.1,0),(0,3),(.1,6),(.25,10)])
    cash_score = _average([_score(metrics['fcf_margin'],[(-.1,0),(0,3),(.1,7),(.25,10)]),_score(metrics['cash_conversion'],[(0,0),(.5,3),(1,7),(1.5,10)])])
    efficiency_score = _score(metrics['roic'],[(0,1),(.08,5),(.15,8),(.25,10)])
    groups = {'growth':growth_score,'profitability':profit_score,'cash_generation':cash_score,'capital_efficiency':efficiency_score}
    available = [s for s in groups.values() if s is not None]
    result['score'] = round(mean(available),2) if len(available)>=2 else None
    risk_groups = {'leverage':_score(metrics['debt_to_equity'],[(0,10),(.5,8),(1,6),(2,3),(4,0)]),
                   'liquidity':_score(metrics['current_ratio'],[(0,0),(1,4),(1.5,7),(2.5,10)]),
                   'interest_coverage':_score(metrics['interest_coverage'],[(0,0),(2,3),(5,7),(10,10)])}
    risk_available = [x for x in risk_groups.values() if x is not None]
    # Negative equity is evidence of fragility, even though its ratio is undefined.
    if equity is not None and equity <= 0:
        risk_available.append(1.)
    result['risk_score'] = round(mean(risk_available),2) if len(risk_available)>=2 else None
    result['group_scores'], result['resilience_components'] = groups, risk_groups
    tracked = ('revenue_growth_yoy','operating_margin','fcf_margin','cash_conversion','roic','debt_to_equity','current_ratio','interest_coverage')
    completeness = sum(metrics[k] is not None for k in tracked)/len(tracked)
    freshness = 1 if age <= 550 else max(.15,550/max(age,1))
    result['confidence'] = round(completeness*freshness,3)
    result['signals'] = [f"Annual financial period ended {latest['date']}; amounts use the financial-statement currency reported by Yahoo."]
    if metrics['revenue_growth_yoy'] is not None:
        result['signals'].append(f"Annual revenue changed {metrics['revenue_growth_yoy']:+.1%} against the comparable prior fiscal year.")
    if metrics['operating_margin'] is not None:
        result['signals'].append(f"Operating margin is {metrics['operating_margin']:.1%}.")
    if fcf is not None:
        result['signals'].append(f"Reported/derived annual free cash flow is {fcf:,.0f}; {'positive cash generation supports flexibility' if fcf > 0 else 'cash burn weakens financial flexibility'}.")
    limitations.append('Scores use disclosed generic operating-company reference thresholds, not claimed industry peer percentiles. Stability ratios are scored only in resilience, not counted again in the financial score.')
    return result
