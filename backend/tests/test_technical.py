from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest
from app.analysis.technical import calculate_indicators, analyze_technical, rsi, wilder, prepare_prices


def bars(count=300, close=None):
    c = np.asarray(close if close is not None else np.arange(count)+100.,dtype=float)
    return pd.DataFrame({'Open':c,'High':c+1,'Low':c-1,'Close':c,'Adj Close':c,'Volume':np.full(len(c),1000.)},
                        index=pd.date_range('2024-01-01',periods=len(c),freq='B',tz='America/New_York'))


def test_wilder_seed_and_recursion_reference():
    result = wilder(pd.Series([np.nan,1.,2.,3.,4.,5.]),3)
    assert result.iloc[3] == 2
    assert result.iloc[4] == pytest.approx(8/3)
    assert result.iloc[5] == pytest.approx(31/9)


def test_rsi_wilder_published_example():
    # Wilder's standard 14-period example, arithmetic gain/loss seed.
    close = pd.Series([44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.00,46.03,46.41,46.22,45.64,46.21])
    result = rsi(close)
    assert result.iloc[14] == pytest.approx(70.464135,abs=.00001)
    assert result.iloc[15] == pytest.approx(66.249619,abs=.00001)
    assert np.isnan(result.iloc[13])


def test_trend_and_volatility_known_calculations():
    df = bars()
    out = calculate_indicators(df)
    latest = out.iloc[-1]
    assert latest.sma_20 == pytest.approx(np.mean(df.Close.iloc[-20:]))
    assert latest.ema_12 == pytest.approx(df.Close.ewm(span=12,adjust=False).mean().iloc[-1])
    assert latest.macd == pytest.approx(latest.ema_12-latest.ema_26)
    assert latest.macd_histogram == pytest.approx(latest.macd-latest.macd_signal)
    assert latest.atr == pytest.approx(2)
    assert latest.bollinger_upper == pytest.approx(df.Close.iloc[-20:].mean()+2*np.std(df.Close.iloc[-20:]))
    assert latest.roc == pytest.approx((df.Close.iloc[-1]/df.Close.iloc[-13]-1)*100)
    assert latest.stochastic_k == pytest.approx(100*14/15)
    assert latest.williams_r == pytest.approx(-100/15)
    assert latest.obv == 299000
    assert latest.relative_volume == 1
    assert latest.mfi == 100
    assert latest.cmf == 0
    assert latest.adx == pytest.approx(100)
    assert latest.ichimoku_span_b == pytest.approx((df.High.iloc[-78:-26].max()+df.Low.iloc[-78:-26].min())/2)
    assert latest.cci == pytest.approx(9.5/(.015*5))
    assert latest.vwap is None or np.isnan(latest.vwap)


def test_flat_prices_zero_volume_no_infinity():
    df = bars(close=[100.]*300)
    df['Volume'] = 0
    result = analyze_technical(df)
    assert result['indicators']['rsi'] == 50
    assert result['indicators']['historical_volatility'] == 0
    assert result['indicators']['relative_volume'] is None
    assert result['indicators']['stochastic_rsi'] is None
    assert result['indicators']['mfi'] == 50
    import json
    json.dumps(result,allow_nan=False)


def test_short_history_and_empty_abstain():
    assert analyze_technical(bars(10))['score'] is None
    assert analyze_technical(pd.DataFrame())['score'] is None
    assert analyze_technical(bars(60))['indicators']['sma_200'] is None
    assert any('52-week' in text for text in analyze_technical(bars(60))['limitations'])


def test_missing_bars_not_filled_and_bad_ohlc_dropped():
    df = bars(60)
    df.iloc[2,df.columns.get_loc('Close')] = np.nan
    df.iloc[3,df.columns.get_loc('High')] = 0
    prices,warnings = prepare_prices(df)
    assert len(prices) == 58
    assert any('2 invalid' in x for x in warnings)


def test_raw_split_repaired_but_adjusted_split_not_doubled():
    raw = bars(close=[400.]*40+[100.]*40)
    raw['Stock Splits'] = 0
    raw.iloc[40,raw.columns.get_loc('Stock Splits')] = 4
    adjusted,warning = prepare_prices(raw)
    assert adjusted.Close.iloc[0] == 100
    assert adjusted.Volume.iloc[0] == 4000
    adjusted_again,_ = prepare_prices(adjusted)
    assert adjusted_again.Close.iloc[0] == 100
    assert warning


def test_no_lookahead_for_rolling_indicators():
    df = bars()
    original = calculate_indicators(df.iloc[:180])
    changed = df.copy()
    changed.iloc[180:,changed.columns.get_loc('Close')] += 1000
    changed.iloc[180:,changed.columns.get_loc('High')] += 1000
    changed.iloc[180:,changed.columns.get_loc('Open')] += 1000
    changed.iloc[180:,changed.columns.get_loc('Low')] += 1000
    pd.testing.assert_frame_equal(original,calculate_indicators(changed).iloc[:180])
