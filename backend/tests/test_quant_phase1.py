import numpy as np
import pandas as pd
import pytest
from app.analysis.execution import calculate_execution
from app.analysis.structure import confirmed_structure
from app.analysis.technical import analyze_technical


def test_costs_and_sizing_use_actual_displayed_levels():
    r=calculate_execution([99,100],95,[112,120,125],{'capital':10000,'risk_per_trade':.01,'commission_bps':5,'slippage_bps':5,'min_reward_risk':2})
    outlay=100*1.0005*1.0005; proceeds=95*.9995*.9995
    assert r['valid'] and r['risk_reward']==pytest.approx((112*.9995*.9995-outlay)/(outlay-proceeds))
    assert r['position_size']*(outlay-proceeds)<=100
    assert r['targets']==[112,120,125] and r['stop']==95
    assert r['position_value']<=10000


def test_risk_rejection_never_moves_levels():
    r=calculate_execution([99,100],95,[101],{'min_reward_risk':2})
    assert r['valid'] and not r['risk_qualified'] and r['stop']==95 and r['targets']==[101]
    assert not calculate_execution([1,1],1,[2],{})['valid']


def test_confirmed_pivot_knows_two_later_bars_only():
    idx=pd.date_range('2025-01-01',periods=7,tz='UTC')
    data=pd.DataFrame({'Open':[10]*7,'High':[11,12,15,12,11,12,11],'Low':[9,8,5,8,9,8,9],'Close':[10]*7,'Volume':[100]*7},index=idx)
    assert confirmed_structure(data.iloc[:4],1)['support']==[]
    s=confirmed_structure(data.iloc[:5],1)
    assert s['support']==[5] and s['support_zones'][0]['confirmed_at']==(idx[4]+pd.Timedelta(days=1)).isoformat()
    assert s['resistance']==[15]


def test_infinite_ohlc_cannot_crash_or_create_signals():
    idx=pd.date_range('2025-01-01',periods=70,tz='UTC')
    data=pd.DataFrame({'Open':np.inf,'High':np.inf,'Low':np.inf,'Close':np.inf,'Volume':100},index=idx)
    r=analyze_technical(data)
    assert r['score'] is None and r['indicators']=={}


def test_features_are_prefix_invariant_and_completed_candles_are_gated():
    from app.analysis.features import build_features,snapshot_at
    from app.providers.bar_times import completed_bars,derived_weekly,derived_four_hour
    idx=pd.date_range('2024-01-01',periods=300,tz='America/New_York')
    close=np.arange(300)*.1+100+np.sin(np.arange(300)/4)
    data=pd.DataFrame({'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':1000},index=idx)
    full=build_features(data);prefix=build_features(data.iloc[:250])
    a=snapshot_at(full,249);b=snapshot_at(prefix)
    assert a['sma_50']==b['sma_50'] and a['support_zones']==b['support_zones'] and a['atr_percentile']==b['atr_percentile']
    now=pd.Timestamp('2024-10-26T12:00:00-04:00')
    assert len(completed_bars(data,as_of=now,exchange_timezone='America/New_York'))==299
    weekly=completed_bars(derived_weekly(data,'America/New_York'),'1wk','America/New_York',now)
    assert all(pd.to_datetime(weekly['Bar End'],utc=True)<=now)
    hourly=data.iloc[:8].copy();hourly.index=pd.date_range('2026-10-23T09:30:00-04:00',periods=8,freq='h')
    four=derived_four_hour(hourly,'America/New_York')
    assert len(completed_bars(four,'4h','America/New_York',pd.Timestamp('2026-10-23T14:00:00-04:00')))==1


def test_missing_opening_or_interior_hour_never_shifts_four_hour_anchor():
    from app.providers.bar_times import derived_four_hour
    idx=pd.date_range('2026-10-23T09:30:00',periods=7,freq='h',tz='America/New_York')
    data=pd.DataFrame({'Open':100,'High':101,'Low':99,'Close':100,'Volume':1000},index=idx)
    assert len(derived_four_hour(data.drop(idx[0]),'America/New_York','09:30'))==1
    assert len(derived_four_hour(data.drop(idx[2]),'America/New_York','09:30'))==1
