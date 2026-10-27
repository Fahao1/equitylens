"""Replay archived published rankings; never rebuild historical scores from today's data."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import mean

import numpy as np
import pandas as pd

from app.providers.bar_times import bar_availability
from app.providers.yahoo import validate_ticker, DataUnavailable
from app.utils import clean, number

STATUS = 'Insufficient historical evidence'


def _empty(reason):
    return {'status':STATUS,'metrics':{},'equity_curve':[],'trades':[],'rebalances':[],
            'benchmarks':{},'validation':{},'coverage':{},'limitations':[reason,
              'Current universe membership and current financial scores are never substituted for archived point-in-time rankings.']}


def _timestamp(value):
    stamp=pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:raise ValueError('Ranking publication and membership timestamps need an explicit timezone.')
    return stamp.tz_convert('UTC')


def _prices(frame,as_of):
    if not isinstance(frame,pd.DataFrame) or frame.empty or not {'Open','Close'}.issubset(frame):
        raise ValueError('A selected company is missing historical Open/Close prices.')
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError('Historical daily session labels need a timezone-aware DatetimeIndex.')
    data=frame.copy().sort_index()
    available=bar_availability(data)
    if data.index.has_duplicates:raise ValueError('Duplicate historical session timestamps cannot be resolved with a future correction.')
    data.index=data.index.tz_convert('UTC')
    if data.index.normalize().has_duplicates:raise ValueError('The ranked portfolio replay requires daily bars, not intraday rows.')
    for key in ('Open','Close'):
        data[key]=pd.to_numeric(data[key],errors='coerce')
    if not np.isfinite(data[['Open','Close']].to_numpy(dtype=float)).all() or (data[['Open','Close']]<=0).any().any():
        raise ValueError('Selected historical prices must be finite and positive; missing prices are not forward-filled.')
    data=data.loc[available.notna() & (available<=as_of)].copy()
    return data


def _metrics(curve,initial,trades):
    values=np.asarray([row['equity'] for row in curve],dtype=float)
    if not len(values):return {}
    all_values=np.r_[initial,values]
    returns=all_values[1:]/all_values[:-1]-1
    total=values[-1]/initial-1
    std=float(np.std(returns,ddof=1)) if len(returns)>1 else 0.
    gains=[row['realized_pnl'] for row in trades if row.get('realized_pnl') is not None and row['realized_pnl']>0]
    losses=[row['realized_pnl'] for row in trades if row.get('realized_pnl') is not None and row['realized_pnl']<0]
    return {'starting_capital':initial,'ending_equity':float(values[-1]),'total_return':float(total),
            'annualized_return':float((1+total)**(252/len(values))-1) if total>-1 else -1.,
            'maximum_drawdown':float(np.min(all_values/np.maximum.accumulate(all_values)-1)),
            'sharpe_ratio':float(np.mean(returns)/std*np.sqrt(252)) if std>0 else None,
            'profit_factor':sum(gains)/abs(sum(losses)) if losses else None,
            'profit_factor_basis':'Realized sell transactions, including partial rebalances; not independent full-round-trip bets.',
            'sell_transactions':sum(row['side']=='sell' for row in trades),
            'commissions':sum(row['commission'] for row in trades),
            'slippage_cost':sum(row['slippage_cost'] for row in trades)}


def replay_ranked_portfolio(snapshots, histories, config=None, benchmarks=None):
    """Equal-weight top5/top10; publication precedes a conservative next-session open."""
    config=dict(config or {})
    top_n=config.get('top_n',5);horizon=config.get('horizon','short_term')
    capital=number(config.get('starting_capital',10000));commission=number(config.get('commission_bps',5));slippage=number(config.get('slippage_bps',5))
    every=config.get('rebalance_every',1)
    if top_n not in (5,10) or isinstance(top_n,bool) or horizon not in ('short_term','long_term'):
        raise ValueError('Ranked replay supports top_n 5 or 10 and short_term/long_term horizon.')
    if capital is None or not 0<capital<=1e12 or commission is None or slippage is None or not 0<=commission<=100 or not 0<=slippage<=100:
        raise ValueError('Capital must be positive; commission and slippage must be in 0–100 basis points.')
    if not isinstance(every,int) or isinstance(every,bool) or not 1<=every<=100:
        raise ValueError('rebalance_every must be a positive number of archived snapshots, at most100.')
    now=_timestamp(config.get('as_of') or datetime.now(timezone.utc))
    if not isinstance(snapshots,list) or not snapshots or not isinstance(histories,dict) or not histories:
        return _empty('Published point-in-time ranking snapshots and matching historical prices are required. No history has been manufactured.')
    try:
        requested_start=config.get('start_date') or config.get('start')
        requested_end=config.get('end_date') or config.get('end')
        start_date=pd.Timestamp(requested_start).date() if requested_start else None
        end_date=pd.Timestamp(requested_end).date() if requested_end else None
        if start_date and end_date and start_date>end_date:raise ValueError('Replay start must not be after its end.')
        archived=[];identities=set()
        for snapshot in snapshots:
            if not isinstance(snapshot,dict) or snapshot.get('horizon')!=horizon:continue
            published=_timestamp(snapshot.get('published_at'))
            if published>now:continue
            if snapshot.get('point_in_time') is not True or not snapshot.get('id'):
                raise ValueError('Every replayed ranking needs an archived id and point_in_time=true provenance.')
            membership=_timestamp(snapshot.get('membership_as_of'))
            if membership>published:raise ValueError('Universe membership became available after ranking publication.')
            if end_date and published.date()>end_date:continue
            if snapshot['id'] in identities:raise ValueError('Duplicate ranking archive ids are ambiguous.')
            identities.add(snapshot['id'])
            rows=snapshot.get('rankings')
            if not isinstance(rows,list):raise ValueError('Archived ranked members are unavailable.')
            ranked=[];seen=set();ranks=set()
            for row in rows:
                if not isinstance(row,dict):raise ValueError('Archived ranking rows must be objects.')
                rank=row.get('rank');score=number(row.get('score'))
                if rank is None or score is None:continue
                if isinstance(rank,bool) or not isinstance(rank,int) or rank<1 or not 0<=score<=10:
                    raise ValueError('Archived ranks/scores must be valid published values.')
                if row.get('cache_stale'):raise ValueError('Archived stale source evidence cannot certify an eligible published rank.')
                ticker=validate_ticker(row.get('ticker',''))
                if ticker in seen or rank in ranks:raise ValueError('Duplicate ticker/rank in an archived ranking cannot be silently repaired.')
                seen.add(ticker);ranks.add(rank)
                for key in ('score_as_of','as_of','fetched_at'):
                    if row.get(key) and _timestamp(row[key])>published:raise ValueError('A score input became available after the ranking was published.')
                ranked.append({**row,'ticker':ticker})
            ranked.sort(key=lambda row:row['rank'])
            if len(ranked)<top_n:raise ValueError(f'An archived ranking contains fewer than {top_n} eligible ranked companies; missing slots are not backfilled.')
            selected=ranked[:top_n]
            currencies=set()
            for row in selected:
                history=histories.get(row['ticker'])
                source_currency=history.attrs.get('currency') if isinstance(history,pd.DataFrame) else None
                currencies.add(str(row.get('currency') or snapshot.get('currency') or source_currency or '').upper())
            if '' in currencies or len(currencies)!=1:raise ValueError('Selected currency metadata is missing or mixed; a verified FX history is required before combining currencies.')
            archived.append({**snapshot,'published':published,'selected':selected,'currency':next(iter(currencies))})
        if not archived:return _empty('No point-in-time ranking archives are available for this horizon and decision date.')
        if len({row['currency'] for row in archived})!=1:raise ValueError('Base currency changes between ranking vintages; no currency conversion is invented.')
        archived.sort(key=lambda row:(row['published'],str(row['id'])))
        archived=archived[::every]
        if start_date:
            previous=[row for row in archived if row['published'].date()<start_date]
            archived=previous[-1:]+[row for row in archived if row['published'].date()>=start_date]
        needed={row['ticker'] for snapshot in archived for row in snapshot['selected']}
        prices={ticker:_prices(histories.get(ticker),now) for ticker in needed}
        if any(frame.empty for frame in prices.values()):raise ValueError('No completed historical prices remain for a selected member at the decision date.')
        calendar=sorted(set().union(*(set(frame.index) for frame in prices.values())))
        calendar=[stamp for stamp in calendar if (not start_date or stamp.date()>=start_date) and (not end_date or stamp.date()<=end_date)]
        schedule={}
        for snapshot in archived:
            eligible=[stamp for stamp in calendar if stamp>snapshot['published']]
            if eligible:schedule[eligible[0]]=snapshot
        if not schedule:return _empty('No completed historical session follows an archived publication. Save current rankings and accumulate genuine forward history first.')
        start=min(schedule)
        dates=[stamp for stamp in calendar if stamp>=start]
        if len(dates)<2:return _empty('At least two completed replay sessions after a ranking publication are required; a current snapshot is not a historical universe.')
        fee,slip=commission/10000,slippage/10000
        cash=capital;holdings={};basis={};trades=[];curve=[];rebalances=[]
        current_snapshot=None

        def trade(ticker,quantity,reference,stamp,snapshot,reason):
            nonlocal cash
            if abs(quantity)<1e-12:return
            buy=quantity>0;amount=abs(quantity);fill=reference*(1+slip if buy else 1-slip)
            fees=amount*fill*fee;value=amount*fill
            pnl=None
            if buy:
                cash-=value+fees
                basis[ticker]=basis.get(ticker,0)+value+fees
                holdings[ticker]=holdings.get(ticker,0)+amount
            else:
                original=holdings[ticker]
                allocation=basis[ticker]*amount/original
                pnl=value-fees-allocation
                cash+=value-fees
                holdings[ticker]=max(0,original-amount)
                basis[ticker]=max(0,basis[ticker]-allocation)
                if holdings[ticker]<1e-10:holdings.pop(ticker,None);basis.pop(ticker,None)
            trades.append({'ticker':ticker,'side':'buy' if buy else 'sell','shares':amount,'reference_price':reference,
                           'fill_price':fill,'commission':fees,'slippage_cost':amount*reference*slip,'realized_pnl':pnl,
                           'execution_time':stamp.isoformat(),'timestamp_precision':'daily session label; next-open/closing-price model, not an observed fill timestamp',
                           'snapshot_id':snapshot['id'],'published_at':snapshot['published_at'],'reason':reason})

        for day_index,stamp in enumerate(dates):
            snapshot=schedule.get(stamp)
            required=set(holdings)|({row['ticker'] for row in snapshot['selected']} if snapshot else set())
            for ticker in required:
                if stamp not in prices[ticker].index:raise ValueError(f'Missing historical session for held/selected member {ticker}; no survivorship or forward-fill substitute is allowed.')
            if snapshot:
                current_snapshot=snapshot
                chosen=[row['ticker'] for row in snapshot['selected']]
                opening={ticker:float(prices[ticker].loc[stamp,'Open']) for ticker in required}
                current={ticker:holdings.get(ticker,0)*opening[ticker] for ticker in required}
                equity=cash+sum(current.values())
                def residual(target_equity):
                    cash_after=cash
                    for ticker in required:
                        wanted=target_equity/top_n if ticker in chosen else 0.
                        difference=wanted-current[ticker]
                        cash_after-=difference*(1+slip)*(1+fee) if difference>=0 else difference*(1-slip)*(1-fee)
                    return cash_after
                low,high=0.,equity
                for _ in range(80):
                    middle=(low+high)/2
                    if residual(middle)>0:low=middle
                    else:high=middle
                target_equity=(low+high)/2
                targets={ticker:target_equity/top_n/opening[ticker] if ticker in chosen else 0. for ticker in required}
                changes={ticker:targets[ticker]-holdings.get(ticker,0) for ticker in required}
                first_trade=len(trades)
                for ticker in sorted(required,key=lambda name:(changes[name]>=0,name)):
                    trade(ticker,changes[ticker],opening[ticker],stamp,snapshot,'published ranking rebalance')
                if abs(cash)<1e-8*capital:cash=0.
                rebalances.append({'date':stamp.isoformat(),'snapshot_id':snapshot['id'],'published_at':snapshot['published_at'],
                    'membership_as_of':snapshot['membership_as_of'],'tickers':chosen,'target_weight':1/top_n,
                    'opening_equity_before_costs':equity,'invested_equity_after_costs':sum(holdings.get(t,0)*opening[t] for t in chosen),
                    'transaction_cost':sum(t['commission']+t['slippage_cost'] for t in trades[first_trade:]),
                    'gross_turnover':sum(abs(changes[t])*opening[t] for t in required)/equity if equity else None})
            for ticker in holdings:
                if stamp not in prices[ticker].index:raise ValueError(f'Missing closing price for held member {ticker}.')
            if day_index==len(dates)-1:
                for ticker in sorted(list(holdings)):
                    trade(ticker,-holdings[ticker],float(prices[ticker].loc[stamp,'Close']),stamp,current_snapshot,'final closing-price liquidation')
            equity=cash+sum(q*float(prices[t].loc[stamp,'Close']) for t,q in holdings.items())
            curve.append({'date':stamp.isoformat(),'equity':equity,'snapshot_id':current_snapshot['id'] if current_snapshot else None})

        results={}
        for name,source in (benchmarks or {}).items():
            try:
                if not isinstance(source,pd.DataFrame) or str(source.attrs.get('currency') or '').upper()!=archived[0]['currency']:
                    raise ValueError('Benchmark currency is unknown or differs from the portfolio; verified FX history is required.')
                data=_prices(source,now).reindex(pd.DatetimeIndex(dates))
                if data[['Open','Close']].isna().any().any():raise ValueError('Benchmark sessions are not exactly aligned.')
                opening=float(data.Open.iloc[0]);quantity=capital/(opening*(1+slip)*(1+fee))
                rows=[{'date':stamp.isoformat(),'equity':quantity*float(data.loc[stamp,'Close'])} for stamp in dates]
                rows[-1]['equity']*=((1-slip)*(1-fee))
                results[name]={'status':'available','metrics':_metrics(rows,capital,[]),'equity_curve':rows}
            except (ValueError,TypeError,KeyError) as exc:results[name]={'status':STATUS,'metrics':{},'equity_curve':[],'limitations':[str(exc),'No benchmark return or currency conversion was invented.']}
        for name in ('QQQ','XLK'):
            results.setdefault(name,{'status':STATUS,'metrics':{},'equity_curve':[],'limitations':['No matching historical benchmark was supplied.']})
        split=max(1,int(len(curve)*.7))
        holdout=curve[split:]
        validation={'method':'Fixed published top-N replay, no parameter fitting or holdout selection.',
                    'out_of_sample':{'start':holdout[0]['date'],'end':holdout[-1]['date'],'metrics':_metrics(holdout,curve[split-1]['equity'],[]) if holdout else {},
                                     'basis':'Last30% of already published replay sessions; existing holdings continue, no model is refitted.'} if holdout else None,
                    'walk_forward':[]}
        edges=np.linspace(max(1,len(curve)//2),len(curve),4,dtype=int)
        for left,right in zip(edges[:-1],edges[1:]):
            if right-left<5:continue
            rows=curve[left:right]
            validation['walk_forward'].append({'start':rows[0]['date'],'end':rows[-1]['date'],
                'metrics':_metrics(rows,curve[left-1]['equity'],[]),'method':'Fixed chronological replay slice; no parameters selected from its outcomes.'})
        return clean({'status':'historical published-ranking replay','horizon':horizon,'top_n':top_n,'currency':archived[0]['currency'],
            'metrics':_metrics(curve,capital,trades),'equity_curve':curve,'trades':trades,'rebalances':rebalances,
            'benchmarks':results,'validation':validation,
            'coverage':{'archived_snapshots_used':len(rebalances),'first_publication':archived[0]['published_at'],
                        'replay_start':curve[0]['date'],'replay_end':curve[-1]['date'],'sessions':len(curve),
                        'point_in_time':True,'coverage_scope':'Only archived, source-covered membership/ranking vintages; no full-sector or prearchive history is implied.'},
            'methodology':{'weighting':'Fractional-share equal weighting; net trades solve a self-financing target after commissions/slippage.',
                           'execution':'First source-session label strictly after publication, next-open model; final close liquidation. No same-session hindsight entries.',
                           'rebalance_every_snapshots':every,'commission_bps':commission,'slippage_bps':slippage,
                           'price_basis':'Split-adjusted price return; cash dividends are not reinvested.'},
            'limitations':['Archived point_in_time metadata is trusted provenance, not an independent audit of every upstream vintage. Rankings are never reconstructed from current financial data.',
                          'This does not establish a survivorship-free entire-sector history. Companies absent from the originally discovered/published coverage remain outside this experiment.',
                          'Fractional shares model equal weighting. Taxes, liquidity, market impact, distributions and corporate delisting proceeds are not fabricated.',
                          'Missing selected/held prices fail the replay; delisted companies are not silently dropped or replaced by survivors.',
                          'Historical results and chronological slices do not guarantee future ranking or portfolio performance.']})
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,DataUnavailable) as exc:
        return _empty(str(exc))
