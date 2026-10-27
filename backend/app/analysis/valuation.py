"""Valuation describes prices paid for cash flows; assumptions remain visible."""
from __future__ import annotations

from .technical import finite
from .fundamentals import ratio, _score
from app.instruments import is_fund, instrument_type


def discounted_cash_flow(base_fcf: float, shares: float, growth: float, discount_rate: float,
                         terminal_growth: float, years: int = 5) -> dict:
    """Equity cash-flow proxy DCF. No enterprise-value debt deduction is appropriate."""
    values = [finite(v) for v in (base_fcf,shares,growth,discount_rate,terminal_growth)]
    if any(v is None for v in values) or base_fcf <= 0 or shares <= 0:
        raise ValueError('DCF requires finite, positive free cash flow and share count.')
    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 20 or not -0.9 <= growth <= .5 or not 0 < discount_rate < 1 or not -0.1 <= terminal_growth <= .1 or discount_rate <= terminal_growth:
        raise ValueError('DCF requires 1–20 years, bounded growth and a discount rate above terminal growth.')
    projected = [base_fcf*(1+growth)**year for year in range(1,years+1)]
    present = sum(cash/(1+discount_rate)**year for year,cash in enumerate(projected,1))
    terminal = projected[-1]*(1+terminal_growth)/(discount_rate-terminal_growth)
    terminal_pv = terminal/(1+discount_rate)**years
    equity_value = present+terminal_pv
    return {'value_per_share':round(equity_value/shares,2),'equity_value':equity_value,
            'projected_cash_flows':projected,'present_value_explicit':present,
            'present_value_terminal':terminal_pv,'terminal_value_share':terminal_pv/equity_value,
            'assumptions':{'base_fcf':base_fcf,'shares':shares,'growth':growth,'discount_rate':discount_rate,
                           'terminal_growth':terminal_growth,'years':years,
                           'cash_flow_basis':'Yahoo operating cash flow minus capital expenditure: levered equity cash-flow proxy; debt is not deducted again'}}


def analyze_valuation(info: dict, fundamentals: dict, assumptions: dict | None = None) -> dict:
    if is_fund(info):
        def source_metric(name):
            raw = info.get(name)
            result = finite(raw) if not isinstance(raw, bool) else None
            return result if result is not None and result > 0 else None
        metrics = {'portfolio_pe': source_metric('trailingPE'),
                   'nav_price': source_metric('navPrice'),
                   'total_assets': source_metric('totalAssets')}
        signals = ['Fund valuation describes a portfolio of holdings. Source-reported portfolio P/E is not the earnings multiple of an operating company; Yahoo aggregation methodology has not been independently verified.']
        limitations = ['Corporate EPS, free-cash-flow yields and equity cash-flow DCF do not apply to ETF or mutual-fund shares. Corporate valuation scoring is withheld even when custom cash-flow assumptions are supplied.',
                       'Only available positive finite Yahoo fund metadata is shown. Holdings, expense ratios, tracking difference and portfolio fair value are not inferred.']
        if assumptions is not None:
            limitations.append('The requested corporate DCF was not run for this fund.')
        return {'applicable': False, 'instrument_type': instrument_type(info),
                'score': None, 'confidence': 0., 'metrics': metrics,
                'signals': signals, 'limitations': limitations,
                'scenarios': {}, 'assumptions': None, 'comparisons': [], 'score_basis': None}
    price = finite(info.get('currentPrice')) or finite(info.get('regularMarketPrice'))
    market_cap = finite(info.get('marketCap'))
    eps = finite(info.get('trailingEps'))
    trailing_pe = finite(info.get('trailingPE'))
    forward_pe = finite(info.get('forwardPE'))
    fcf = finite(info.get('freeCashflow'))
    financial_currency, quote_currency = info.get('financialCurrency'), info.get('currency')
    currency_mismatch = financial_currency and quote_currency and financial_currency != quote_currency
    limitations = ['Historical valuation and industry-peer comparisons are unavailable unless reliable comparable snapshots are separately supplied. No peer discount is inferred.',
                   'Yield reference thresholds are generic assumptions, not an interest-rate forecast or sector-adjusted fair value.']
    if currency_mismatch:
        fcf = None
        limitations.append('Statement and quote currencies differ; cash-flow yield and DCF are unavailable without a verified exchange-rate conversion.')
    metrics = {
        'trailing_pe':trailing_pe if trailing_pe is not None and trailing_pe>0 and (eps is None or eps>0) else None,
        'forward_pe':forward_pe if forward_pe is not None and forward_pe>0 else None,
        'peg':finite(info.get('trailingPegRatio')) if finite(info.get('trailingPegRatio')) is not None else finite(info.get('pegRatio')),
        'price_to_sales':finite(info.get('priceToSalesTrailing12Months')),
        'price_to_book':finite(info.get('priceToBook')),
        'ev_to_ebitda':finite(info.get('enterpriseToEbitda')),
        'fcf_yield':ratio(fcf,market_cap), 'earnings_yield':ratio(eps,price) if not currency_mismatch else None,
        'dividend_yield':ratio(finite(info.get('dividendRate')),price),
        'market_cap':market_cap,'enterprise_value':finite(info.get('enterpriseValue')),
        'fcf_basis':'Yahoo freeCashflow snapshot (vendor trailing basis; fiscal coverage may be unspecified)' if fcf is not None else None,
    }
    for key in ('peg','price_to_sales','price_to_book','ev_to_ebitda'):
        if metrics[key] is not None and metrics[key] <= 0:
            metrics[key] = None
    if eps is not None and eps <= 0:
        limitations.append('Nonpositive earnings make trailing P/E unsuitable; a negative earnings yield is retained as evidence of losses.')
    if metrics['dividend_yield'] is None:
        dividend_yield = finite(info.get('trailingAnnualDividendYield'))
        metrics['dividend_yield'] = dividend_yield if dividend_yield is not None and 0 <= dividend_yield <= 1 else None
    basis, score = None,None
    yield_value = metrics['fcf_yield'] if metrics['fcf_yield'] is not None else metrics['earnings_yield']
    if yield_value is not None:
        basis = 'free_cash_flow_yield' if metrics['fcf_yield'] is not None else 'earnings_yield'
        score = _score(yield_value,[(0,0),(.02,3),(.05,6),(.08,8),(.12,10)])
    signals = []
    if basis:
        signals.append(f"{basis.replace('_',' ').capitalize()} is {yield_value:.1%}. The score maps this yield to disclosed reference hurdles; growth and business risk can justify different multiples.")
    if metrics['forward_pe'] is not None:
        signals.append(f"Forward P/E is {metrics['forward_pe']:.1f}× based on analyst estimates, which may change.")
    scenarios = {}
    used_assumptions = None
    if assumptions is not None:
        if currency_mismatch:
            limitations.append('DCF request cannot be evaluated across mismatched currencies.')
        else:
            base_fcf = finite(assumptions.get('base_fcf')) if 'base_fcf' in assumptions else fcf
            shares = finite(assumptions.get('shares')) if 'shares' in assumptions else finite(info.get('sharesOutstanding'))
            g = finite(assumptions.get('growth',.05))
            discount = finite(assumptions.get('discount_rate',.1))
            terminal = finite(assumptions.get('terminal_growth',.02))
            years = assumptions.get('years',5)
            used_assumptions = {'growth':g,'discount_rate':discount,'terminal_growth':terminal,'years':years,
                                'base_fcf':base_fcf,'shares':shares}
            try:
                if g is None or discount is None or terminal is None:
                    raise ValueError('DCF assumptions must be finite numbers.')
                for name, growth_delta, discount_delta in [('conservative',-.03,.02),('base',0,0),('optimistic',.03,-.01)]:
                    scenarios[name] = discounted_cash_flow(base_fcf,shares,g+growth_delta,discount+discount_delta,terminal,years)
                if price and price > 0:
                    score = max(0,min(10,5+10*(scenarios['base']['value_per_share']/price-1)))
                    basis = 'explicit_dcf_assumptions'
                signals.append('DCF scenarios are sensitive equity cash-flow estimates, not guaranteed future prices. Inspect the terminal-value concentration and assumptions.')
            except (ValueError,TypeError) as exc:
                scenarios = {}
                limitations.append(str(exc))
    else:
        limitations.append('DCF is disabled until explicit assumptions are supplied. No intrinsic-value target is invented.')
    confidence = .45 if basis else 0.
    if scenarios:
        confidence = .55
    if fcf is None and yield_value is not None:
        limitations.append('Cash-flow yield is unavailable; the yield score uses earnings yield with reduced confidence.')
        confidence = min(confidence,.3)
    return {'score':round(score,2) if score is not None else None,'confidence':confidence,
            'metrics':metrics,'signals':signals,'limitations':limitations,
            'scenarios':scenarios,'assumptions':used_assumptions,'score_basis':basis,
            'comparisons':[], 'reference_hurdles':{'yield':[[0,0],[.02,3],[.05,6],[.08,8],[.12,10]]}}
