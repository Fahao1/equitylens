"""Confirmed five-bar pivots with explicit knowledge times; no final-sample extrema."""
from math import isfinite
import numpy as np
import pandas as pd
from app.providers.bar_times import bar_availability


def confirmed_structure(history: pd.DataFrame, atr=None, lookback=126):
    empty = {'support': [], 'resistance': [], 'support_zones': [], 'resistance_zones': [],
             'swing_high': None, 'swing_low': None, 'fibonacci': {}, 'as_of': None}
    if len(history) < 5:
        return empty
    data = history.sort_index().tail(lookback)
    if not {'Low','High','Close'}.issubset(data.columns):
        return empty
    close = float(data.Close.iloc[-1])
    if not isfinite(close) or close <= 0:
        return empty
    tolerance = float(atr)*.5 if atr is not None and isfinite(float(atr)) and atr>0 else close*.005
    pivots, highs, lows = [], [], []
    available=bar_availability(data)
    for i in range(2,len(data)-2):
        for column, kind, direction in [('Low','low',-1),('High','high',1)]:
            level = float(data[column].iloc[i])
            peers = data[column].iloc[[i-2,i-1,i+1,i+2]].to_numpy(dtype=float)
            if np.isfinite(peers).all() and isfinite(level) and (level < peers.min() if direction<0 else level > peers.max()):
                event = {'price':level,'pivot_at':data.index[i].isoformat(),'confirmed_at':available[i+2].isoformat(),'kind':kind}
                pivots.append(event)
                (highs if kind=='high' else lows).append(event)
    groups = []
    for event in sorted(pivots,key=lambda p:p['price']):
        if groups and abs(event['price']-np.mean([p['price'] for p in groups[-1]]))<=tolerance:
            groups[-1].append(event)
        else:
            groups.append([event])
    zones = [{'price':round(float(np.mean([p['price'] for p in group])),6),
              'lower':min(p['price'] for p in group),'upper':max(p['price'] for p in group),
              'touches':len({p['pivot_at'] for p in group}),
              'confirmed_at':max(p['confirmed_at'] for p in group),'pivots':group} for group in groups]
    supports = sorted((z for z in zones if z['price']<=close),key=lambda z:z['price'],reverse=True)[:6]
    resistances = sorted((z for z in zones if z['price']>close),key=lambda z:z['price'])[:6]
    high = highs[-1]['price'] if highs else None
    low = lows[-1]['price'] if lows else None
    fib = {str(r):round(high-(high-low)*r,6) for r in (.236,.382,.5,.618,.786)} if high is not None and low is not None and high>low else {}
    return {**empty,'support':[z['price'] for z in supports],'resistance':[z['price'] for z in resistances],
            'support_zones':supports,'resistance_zones':resistances,'swing_high':high,'swing_low':low,
            'fibonacci':fib,'as_of':available[-1].isoformat(),
            'method':'Strict five-bar pivot, known after two subsequent completed bars; cluster tolerance 0.5 ATR; no unconfirmed extrema.'}
