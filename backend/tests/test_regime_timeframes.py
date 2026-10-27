"""Reference rule and causal-completion tests; no market data is invented for assertions."""
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
import pytest

from app.analysis.regime import classify_regime, analyze_regime, LABELS
from app.analysis.timeframes import analyze_timeframes
from app.analysis.features import build_features, snapshot_at


def snapshot(**changes):
    return {'bars':300,'as_of':'2026-01-01T00:00:00+00:00','close':120.,'open':119.,'high':121.,'low':118.5,
            'previous_close':119.,'sma_50':110.,'sma_200':100.,'slope_50':.02,'slope_200':.01,
            'adx':32.,'atr':2.,'atr_percentile':45.,'hv_percentile':40.,'historical_volatility':.2,
            'relative_strength_63':.05,'benchmark_trend':'bullish','structure':'higher_highs_higher_lows',
            'range_atr_20':7.,**changes}


@pytest.mark.parametrize('changes,expected',[
    ({},'Strong bullish trend'),
    ({'adx':18,'slope_200':-.005,'structure':'mixed','relative_strength_63':-.02,'benchmark_trend':'bearish'},'Weak bullish trend'),
    ({'close':100,'sma_50':100,'sma_200':100,'slope_50':0,'slope_200':0,'adx':12,'structure':'mixed','range_atr_20':4},'Sideways consolidation'),
    ({'close':90,'sma_50':95,'sma_200':100,'slope_50':-.01,'slope_200':.005,'adx':18,'structure':'mixed'},'Weak bearish trend'),
    ({'close':80,'sma_50':90,'sma_200':100,'slope_50':-.02,'slope_200':-.01,'structure':'lower_highs_lower_lows','relative_strength_63':-.05,'benchmark_trend':'bearish'},'Strong bearish trend'),
    ({'atr_percentile':95,'hv_percentile':92,'structure':'mixed'},'High-volatility regime'),
])
def test_six_exact_regime_reference_cases(changes,expected):
    result = classify_regime(snapshot(**changes))
    assert result['regime'] == expected
    assert result['regime'] in LABELS
    assert 0 < result['confidence'] <= 1
    assert isinstance(result['trend_strength'],str)
    assert isinstance(result['volatility_regime'],str)
    assert len(result['evidence']) >= 4
    assert any('not a calibrated probability' in item for item in result['limitations'])


def test_adx_alone_does_not_determine_regime_or_direction():
    low_adx = classify_regime(snapshot(adx=12))
    assert low_adx['regime'] == 'Weak bullish trend'
    contradictory = classify_regime(snapshot(close=100,sma_50=100,sma_200=100,slope_50=0,slope_200=0,adx=50,structure='mixed'))
    assert contradictory['regime'] == 'Insufficient Data'
    assert classify_regime({'bars':300,'close':100,'sma_50':100,'sma_200':100,'adx':50})['regime'] == 'Insufficient Data'


def test_high_volatility_requires_two_percentiles_and_price_action_confirmation():
    one = classify_regime(snapshot(atr_percentile=99,hv_percentile=20))
    assert one['regime'] != 'High-volatility regime'
    calm_structure = classify_regime(snapshot(close=112,sma_50=110,atr_percentile=99,hv_percentile=99,open=112,high=112.4,low=111.6,previous_close=112))
    assert calm_structure['regime'] != 'High-volatility regime'
    mixed_without_range = classify_regime(snapshot(close=112,sma_50=110,atr_percentile=99,hv_percentile=99,open=112,high=112.4,low=111.6,previous_close=112,structure='mixed',range_atr_20=4))
    assert mixed_without_range['regime'] != 'High-volatility regime'
    missing = classify_regime(snapshot(atr_percentile=99,hv_percentile=None))
    assert missing['volatility_regime'] == 'Unavailable'
    assert missing['regime'] != 'High-volatility regime'


def test_missing_benchmark_reduces_confidence_without_a_favorable_vote():
    complete = classify_regime(snapshot())
    missing = classify_regime(snapshot(relative_strength_63=None,benchmark_trend=None))
    assert missing['confidence'] < complete['confidence']
    assert missing['feature_coverage']['relative_context'] == 0
    assert any('no favorable default' in item for item in missing['limitations'])
    opposed = classify_regime(snapshot(relative_strength_63=-.05,benchmark_trend='bearish'))
    assert opposed['regime'] == 'Weak bullish trend'


def test_warmup_and_partial_252_context_are_explicit():
    assert classify_regime(snapshot(bars=199))['regime'] == 'Insufficient Data'
    mature = classify_regime(snapshot())
    partial = classify_regime(snapshot(bars=220))
    assert partial['confidence'] < mature['confidence']
    assert any('252' in item for item in partial['limitations'])
    missing_slope = classify_regime(snapshot(bars=200,slope_200=None))
    assert missing_slope['regime'] == 'Weak bullish trend'


def test_invalid_regime_features_are_json_safe_and_do_not_force_state():
    result = classify_regime(snapshot(close=float('inf'),structure=['invalid']))
    assert result['regime'] == 'Insufficient Data'
    json.dumps(result,allow_nan=False)


def frame(count=300,frequency='D',up=True,end='2025-12-01T00:00:00Z',duration='1D'):
    index = pd.date_range(end=end,periods=count,freq=frequency)
    close = np.linspace(100,180,count) if up else np.linspace(180,100,count)
    data = pd.DataFrame({'Open':close,'High':close+.5,'Low':close-.5,'Close':close,'Volume':1000.},index=index)
    data['Bar End'] = index+pd.Timedelta(duration)
    return data


def by_timeframe(result,name):
    return next(row for row in result['timeframes'] if row['timeframe'] == name)


def test_explicit_latest_partial_bar_is_dropped_before_every_indicator():
    prices = frame(count=100,frequency='1h',end='2026-01-01T12:00:00Z',duration='1h')
    when = '2026-01-01T12:30:00Z'
    expected = analyze_timeframes({'1h':prices.iloc[:-1]},as_of=when)
    changed = prices.copy()
    changed.loc[changed.index[-1],['Open','High','Low','Close']] *= 4
    actual = analyze_timeframes({'1h':changed},as_of=when)
    row = by_timeframe(actual,'1h')
    baseline = by_timeframe(expected,'1h')
    assert row['bars'] == 99
    assert row['indicators'] == baseline['indicators']
    assert row['trend'] == baseline['trend']
    assert pd.Timestamp(row['last_bar_end']) <= pd.Timestamp(when)
    assert any('not-yet-completed' in text for text in row['limitations'])


def test_future_candles_cannot_change_an_earlier_timeframe_summary():
    prices = frame(count=300,frequency='1h',end='2026-01-02T00:00:00Z',duration='1h')
    when = prices['Bar End'].iloc[199]
    baseline = analyze_timeframes({'1h':prices.iloc[:200]},as_of=when)
    changed = prices.copy()
    changed.iloc[200:,changed.columns.get_indexer(['Open','High','Low','Close'])] *= 8
    actual = analyze_timeframes({'1h':changed},as_of=when)
    assert actual == baseline


def test_missing_timeframes_are_explicit_and_never_fabricated():
    result = analyze_timeframes({'daily':frame()},as_of='2026-01-10T00:00:00Z')
    assert [row['timeframe'] for row in result['timeframes']] == ['weekly','daily','4h','1h','15m']
    assert by_timeframe(result,'weekly')['status'] == 'missing'
    assert by_timeframe(result,'15m')['bars'] == 0
    assert result['alignment']['status'] == 'insufficient_data'
    assert result['alignment']['score'] is None
    assert result['confidence'] < 1


def test_nested_fast_frames_do_not_inflate_votes_or_confidence():
    frames = {'weekly':frame(frequency='7D',duration='7D'),'daily':frame(),
              '1h':frame(frequency='1h',duration='1h')}
    when = '2026-01-10T00:00:00Z'
    base = analyze_timeframes(frames,as_of=when)
    enriched = analyze_timeframes({**frames,'4h':frame(frequency='4h',duration='4h'),
                                   '15m':frame(frequency='15min',duration='15min')},as_of=when)
    assert base['alignment'] == enriched['alignment']
    assert base['confidence'] == enriched['confidence']
    assert enriched['alignment']['confirmation_timeframe'] == '1h'
    assert enriched['alignment']['status'] == 'aligned_bullish'


def test_weekly_daily_and_timing_contradictions_are_explained():
    when = '2026-01-10T00:00:00Z'
    weekly_daily = analyze_timeframes({'weekly':frame(frequency='7D',duration='7D'),
                                      'daily':frame(up=False)},as_of=when)
    assert weekly_daily['alignment']['status'] == 'conflicting'
    assert weekly_daily['alignment']['score'] is None
    assert weekly_daily['alignment']['contradictions']
    lower = analyze_timeframes({'weekly':frame(frequency='7D',duration='7D'),'daily':frame(),
                                '1h':frame(frequency='1h',duration='1h',up=False)},as_of=when)
    assert lower['alignment']['status'] == 'mixed'
    assert lower['alignment']['conflicting'] is True
    assert lower['alignment']['score'] is None


def test_daily_and_weekly_fallbacks_conservatively_drop_current_period():
    daily = frame(count=100,end='2026-01-05T00:00:00Z').drop(columns='Bar End')
    weekly = frame(count=100,frequency='7D',end='2026-01-05T00:00:00Z').drop(columns='Bar End')
    result = analyze_timeframes({'daily':daily,'weekly':weekly},as_of='2026-01-05T20:00:00Z')
    assert by_timeframe(result,'daily')['bars'] == 99
    assert by_timeframe(result,'weekly')['bars'] == 99
    assert any('conservatively excluded' in item for item in by_timeframe(result,'daily')['limitations'])


def test_timezone_daylight_saving_completion_and_unverified_metadata():
    local = pd.date_range('2026-03-05',periods=100,freq='D',tz='America/New_York')
    data = frame(count=100).drop(columns='Bar End')
    data.index = local
    when = pd.Timestamp('2026-03-09T03:30:00Z')  # March8 local23:30 after DST starts.
    result = analyze_timeframes({'daily':data},metadata={'daily':{'exchange_timezone':'America/New_York','completion_verified':False}},as_of=when)
    row = by_timeframe(result,'daily')
    assert row['bars'] == 3  # March5,6,7; March8 is not complete at local23:30.
    assert pd.Timestamp(row['last_bar_end']) == pd.Timestamp('2026-03-08T05:00:00Z')
    assert any('not independently verified' in item for item in row['limitations'])


def test_invalid_end_order_and_nonfinite_prices_are_excluded():
    data = frame(count=100,frequency='1h',duration='1h')
    data.loc[data.index[-1],'Bar End'] = data.index[-1]-pd.Timedelta(hours=1)
    data.loc[data.index[-2],['Open','High','Low','Close']] = np.inf
    result = analyze_timeframes({'1h':data},as_of='2026-01-10T00:00:00Z')
    row = by_timeframe(result,'1h')
    assert row['bars'] == 98
    json.dumps(result,allow_nan=False)


def test_explicit_short_final_session_bar_uses_actual_provided_end():
    data = frame(count=100,frequency='4h',end='2026-01-05T13:30:00-05:00',duration='4h')
    data.loc[data.index[-1],'Bar End'] = pd.Timestamp('2026-01-05T16:00:00-05:00')
    result = analyze_timeframes({'4h':data},as_of='2026-01-05T21:01:00Z')
    assert by_timeframe(result,'4h')['bars'] == 100
    assert pd.Timestamp(by_timeframe(result,'4h')['last_bar_end']) == pd.Timestamp('2026-01-05T21:00:00Z')


def test_all_future_bars_produce_unavailable_without_crash():
    result = analyze_timeframes({'1h':frame(count=100,frequency='1h',end='2026-01-01T12:00:00Z',duration='1h')},as_of='2020-01-01T00:00:00Z')
    assert by_timeframe(result,'1h')['status'] == 'unavailable'
    assert by_timeframe(result,'1h')['bars'] == 0


def test_regime_wrapper_and_snapshot_prefix_do_not_read_future_observations():
    data = frame(count=320).drop(columns='Bar End')
    cutoff = data.index[250]
    left = analyze_regime(data.iloc[:251],as_of=cutoff)
    altered = data.copy()
    altered.iloc[251:,altered.columns.get_indexer(['Open','High','Low','Close'])] *= 3
    right = analyze_regime(altered,as_of=cutoff)
    assert left == right
    full = build_features(altered)
    prefix = build_features(data.iloc[:251])
    assert classify_regime(snapshot_at(full,250)) == classify_regime(snapshot_at(prefix))


def test_constant_zero_volatility_cannot_be_called_high_volatility():
    result = classify_regime(snapshot(historical_volatility=0,atr_percentile=100,hv_percentile=100))
    assert result['regime'] != 'High-volatility regime'
    assert result['volatility_regime'] != 'High'
    data = frame(count=300,frequency='1h',duration='1h')
    data[['Open','Close']] = 100.
    data['High'],data['Low'] = 100.5,99.5
    summaries = analyze_timeframes({'1h':data},as_of='2026-01-10T00:00:00Z')
    row = by_timeframe(summaries,'1h')
    assert row['indicators']['hv_percentile'] == 50
    assert row['volatility'] == 'Normal'


def test_stale_intraday_candles_are_visible_but_cannot_confirm_a_setup():
    frames = {'weekly':frame(frequency='7D',duration='7D'),'daily':frame(),
              '1h':frame(frequency='1h',duration='1h')}
    when = '2026-01-10T00:00:00Z'
    fresh = analyze_timeframes(frames,as_of=when)
    stale = analyze_timeframes(frames,metadata={'1h':{'cache_stale':True,'fetched_at':'2025-01-01T00:00:00Z'}},as_of=when)
    hourly = by_timeframe(stale,'1h')
    assert hourly['status'] == 'stale'
    assert hourly['confidence'] == 0
    assert hourly['bars'] == by_timeframe(fresh,'1h')['bars']
    assert hourly['indicators']
    assert stale['alignment']['confirmation_timeframe'] is None
    assert stale['confidence'] < fresh['confidence']
    assert hourly['fetched_at'] == '2025-01-01T00:00:00Z'
    assert any('excluded from alignment' in text for text in hourly['limitations'])


def test_stale_derived_and_native_frames_cannot_replace_one_another_as_confirmation():
    frames = {'weekly':frame(frequency='7D',duration='7D'),'daily':frame(),
              '1h':frame(frequency='1h',duration='1h'),'4h':frame(frequency='4h',duration='4h'),
              '15m':frame(frequency='15min',duration='15min')}
    metadata = {'1h':{'cache_stale':True},'4h':{'cache_stale':True}}
    result = analyze_timeframes(frames,metadata=metadata,as_of='2026-01-10T00:00:00Z')
    assert by_timeframe(result,'1h')['status'] == 'stale'
    assert by_timeframe(result,'4h')['status'] == 'stale'
    assert result['alignment']['confirmation_timeframe'] == '15m'


def test_snapshot_as_of_is_candle_availability_not_its_session_label():
    data = frame(count=300,frequency='D',duration='1D')
    features = build_features(data)
    result = snapshot_at(features,200)
    assert result['as_of'] == pd.Timestamp(data['Bar End'].iloc[200]).isoformat()
    assert result['session_label'] == data.index[200].isoformat()
    assert pd.Timestamp(result['as_of']) > pd.Timestamp(result['session_label'])
    assert 'Bar End' not in result
    assert result['previous_bollinger_lower'] == pytest.approx(features.bollinger_lower.iloc[199])
    prefix = build_features(data.iloc[:201])
    assert snapshot_at(features,200) == snapshot_at(prefix)


def test_regime_wrapper_without_bar_end_still_respects_daily_availability():
    data = frame(count=300).drop(columns='Bar End')
    cutoff = data.index[-1]+pd.Timedelta(hours=12)
    result = analyze_regime(data,as_of=cutoff)
    assert pd.Timestamp(result['features']['as_of']) <= cutoff
    assert result['features']['bars'] == 299
