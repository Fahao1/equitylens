"""One causal indicator table reused by live strategies and point-in-time validation."""
import numpy as np
import pandas as pd
from app.analysis.technical import calculate_indicators, prepare_prices, finite
from app.analysis.structure import confirmed_structure
from app.providers.bar_times import bar_availability


def _percentile(series, window=252):
    return series.rolling(window,min_periods=63).apply(lambda a:100*float(np.sum(a<a[-1])+.5*np.sum(a==a[-1]))/len(a),raw=True)


def build_features(history, benchmark=None):
    prices,_=prepare_prices(history)
    if prices.empty:
        return prices
    indicators=calculate_indicators(prices)
    frame=prices.join(indicators)
    frame['previous_bollinger_lower']=frame.bollinger_lower.shift()
    frame['slope_50']=frame.sma_50/frame.sma_50.shift(10)-1
    frame['slope_200']=frame.sma_200/frame.sma_200.shift(20)-1
    frame['atr_percentile']=_percentile(frame.atr/frame.Close)
    frame['hv_percentile']=_percentile(frame.historical_volatility)
    frame['prior_high_20']=frame.High.shift().rolling(20).max()
    frame['prior_low_20']=frame.Low.shift().rolling(20).min()
    frame['range_atr_20']=(frame.prior_high_20-frame.prior_low_20)/frame.atr.replace(0,np.nan)
    frame['relative_strength_63']=np.nan
    frame['benchmark_trend']=None
    if benchmark is not None and not benchmark.empty and 'Close' in benchmark:
        b,_=prepare_prices(benchmark)
        if not b.empty:
            # Match session dates, never fill a missing benchmark from a future session.
            target_dates=frame.index.tz_convert('UTC').normalize() if frame.index.tz else frame.index.normalize()
            b_dates=b.index.tz_convert('UTC').normalize() if b.index.tz else b.index.normalize()
            series=pd.Series(b.Close.to_numpy(),index=b_dates).groupby(level=0).last()
            aligned=series.reindex(target_dates)
            aligned.index=frame.index
            frame['relative_strength_63']=frame.Close.pct_change(63,fill_method=None)-aligned.pct_change(63,fill_method=None)
            ma=aligned.rolling(50).mean()
            frame['benchmark_trend']=np.where(aligned>ma,'bullish',np.where(aligned<ma,'bearish',None))
    return frame


def snapshot_at(features,index=-1):
    if features.empty:
        return {'bars':0,'as_of':None}
    i=index if index>=0 else len(features)+index
    if not 0<=i<len(features):
        raise IndexError('Snapshot position out of range')
    row=features.iloc[i]
    snapshot={key:finite(value) for key,value in row.items() if key not in {'benchmark_trend','Bar End'}}
    snapshot.update(as_of=bar_availability(features)[i].isoformat(),session_label=features.index[i].isoformat(),bars=i+1,close=finite(row.get('Close')),open=finite(row.get('Open')),
                    high=finite(row.get('High')),low=finite(row.get('Low')),benchmark_trend=row.get('benchmark_trend'))
    if i:
        previous=features.iloc[i-1]
        snapshot.update(previous_close=finite(previous.Close),previous_low=finite(previous.Low),rsi_previous=finite(previous.get('rsi')))
    structure=confirmed_structure(features.iloc[max(0,i-125):i+1],snapshot.get('atr'))
    snapshot.update(support_zones=structure['support_zones'],resistance_zones=structure['resistance_zones'],
                    support=structure['support'][0] if structure['support'] else None,
                    resistance=structure['resistance'][0] if structure['resistance'] else None,
                    swing_high=structure['swing_high'],swing_low=structure['swing_low'])
    # The sequence of confirmed pivots is a separate price-structure group.
    data=features.iloc[max(0,i-125):i+1]
    highs,lows=[],[]
    high_values=data.High.to_numpy();low_values=data.Low.to_numpy()
    for n in range(2,len(data)-2):
        if high_values[n]>max(high_values[n-2],high_values[n-1],high_values[n+1],high_values[n+2]):highs.append(high_values[n])
        if low_values[n]<min(low_values[n-2],low_values[n-1],low_values[n+1],low_values[n+2]):lows.append(low_values[n])
    snapshot['structure']='higher_highs_higher_lows' if len(highs)>1 and len(lows)>1 and highs[-1]>highs[-2] and lows[-1]>lows[-2] else 'lower_highs_lower_lows' if len(highs)>1 and len(lows)>1 and highs[-1]<highs[-2] and lows[-1]<lows[-2] else 'mixed'
    return snapshot
