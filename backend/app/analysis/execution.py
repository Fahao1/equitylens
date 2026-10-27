"""Cost-aware long-only execution arithmetic, independent of strategy eligibility."""
from math import floor, isfinite


def calculate_execution(entry_zone, stop, targets, config, existing_price=None):
    result={'valid':False,'risk_qualified':False,'entry_zone':None,'stop':None,'targets':[],
            'net_reward_risk':[],'risk_reward':None,'position_size':0,'calculation':[],'errors':[]}
    try:
        values=[float(v) for v in [*entry_zone,stop,*targets]]
        if len(entry_zone)!=2 or not all(isfinite(v) and v>0 for v in values):
            raise ValueError('Entry, stop and target prices must be finite and positive.')
        precision=2 if values[1]>=1 else 6
        low,high,stop=map(lambda x:round(float(x),precision),[*entry_zone,stop])
        targets=sorted(set(round(float(t),precision) for t in targets))[:3]
        if not 0<stop<low<=high or any(t<=high for t in targets):
            raise ValueError('Require stop < entry low <= entry high < every target after rounding.')
        capital=float(config.get('capital',10000)); risk_fraction=float(config.get('risk_per_trade',.01))
        c=float(config.get('commission_bps',5))/10000; s=float(config.get('slippage_bps',5))/10000
        if not all(isfinite(v) for v in (capital,risk_fraction,c,s)) or capital<=0 or not 0<risk_fraction<=.05 or not 0<=c<=.01 or not 0<=s<=.01:
            raise ValueError('Invalid capital, risk or transaction cost assumptions.')
        outlay=high*(1+s)*(1+c); stop_proceeds=stop*(1-s)*(1-c)
        loss=outlay-stop_proceeds
        gains=[target*(1-s)*(1-c)-outlay for target in targets]
        ratios=[gain/loss for gain in gains]
        budget=capital*risk_fraction
        existing=float(config.get('existing_shares',0))
        market=float(existing_price if existing_price is not None else high)
        if not isfinite(existing) or existing<0 or not isfinite(market) or market<=0:
            raise ValueError('Existing holdings and current price must be valid.')
        consumed=existing*max(0,market-stop_proceeds)
        available_risk=max(0,budget-consumed); available_capital=max(0,capital-existing*market)
        shares=max(0,min(floor(available_risk/loss),floor(available_capital/outlay)))
        result.update(valid=True,entry_zone=[low,high],entry_reference=high,stop=stop,targets=targets,
                      entry_outlay_per_share=outlay,stop_proceeds_per_share=stop_proceeds,risk_per_share=loss,
                      net_reward_risk=ratios,risk_reward=ratios[0] if ratios else None,risk_budget=budget,
                      position_size=shares,position_value=shares*outlay,estimated_capital_risk=consumed+shares*loss,
                      existing_capital_risk=consumed,
                      risk_qualified=bool(ratios and ratios[0]>=float(config.get('min_reward_risk',2)) and shares>0),
                      commission_bps=c*10000,slippage_bps=s*10000,
                      upside_percent=gains[0]/outlay*100 if gains else None,downside_percent=loss/outlay*100)
        result['calculation']=[f'Worst entry {high} × (1 + {s:.6f} slippage) × (1 + {c:.6f} commission) = {outlay:.6f} outlay/share.',
          f'Stop proceeds {stop} × (1 − slippage) × (1 − commission) = {stop_proceeds:.6f}; modeled risk/share {loss:.6f}.',
          'Each net reward/risk = (target net proceeds − entry outlay) / modeled risk; levels are not moved to satisfy the threshold.',
          f'Additional whole shares = min(floor({available_risk:.2f} / {loss:.6f}), floor({available_capital:.2f} / {outlay:.6f})) = {shares}. Gap losses may be larger.']
    except (ValueError,TypeError,OverflowError,ZeroDivisionError) as exc:
        result['errors'].append(str(exc))
    return result
