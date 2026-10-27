"""Daily technical evidence. All rolling calculations use current/past bars only."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from .structure import confirmed_structure


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder average seeded with the first complete arithmetic mean."""
    values = series.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        if i == 0 or not np.isfinite(output[i - 1]):
            window = values[i - period + 1:i + 1]
            if np.isfinite(window).all():
                output[i] = window.mean()
        elif np.isfinite(values[i]):
            output[i] = ((period - 1) * output[i - 1] + values[i]) / period
    return pd.Series(output, index=series.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), period)
    loss = wilder(-delta.clip(upper=0), period)
    result = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    result = result.mask((loss == 0) & (gain > 0), 100)
    return result.mask((loss == 0) & (gain == 0), 50)


def parabolic_sar(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    result = np.full(len(close), np.nan)
    if len(close) < 2:
        return pd.Series(result, index=close.index)
    rising = close.iloc[1] >= close.iloc[0]
    extreme = high.iloc[0] if rising else low.iloc[0]
    sar = low.iloc[0] if rising else high.iloc[0]
    acceleration = 0.02
    for i in range(1, len(close)):
        sar = sar + acceleration * (extreme - sar)
        if rising:
            sar = min(sar, low.iloc[i - 1], low.iloc[max(0, i - 2)])
            if low.iloc[i] < sar:
                rising, sar, extreme, acceleration = False, extreme, low.iloc[i], 0.02
            elif high.iloc[i] > extreme:
                extreme, acceleration = high.iloc[i], min(acceleration + 0.02, 0.2)
        else:
            sar = max(sar, high.iloc[i - 1], high.iloc[max(0, i - 2)])
            if high.iloc[i] > sar:
                rising, sar, extreme, acceleration = True, extreme, high.iloc[i], 0.02
            elif low.iloc[i] < extreme:
                extreme, acceleration = low.iloc[i], min(acceleration + 0.02, 0.2)
        result[i] = sar
    return pd.Series(result, index=close.index)


def prepare_prices(history: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    data = history.copy().sort_index()
    limitations = []
    data = data[~data.index.duplicated(keep='last')]
    for column in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if column not in data:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors='coerce').astype(float)
    valid = (np.isfinite(data[['Open', 'High', 'Low', 'Close']]).all(axis=1)
             & (data[['Open', 'High', 'Low', 'Close']] > 0).all(axis=1)
             & (data.High >= data[['Open', 'Close', 'Low']].max(axis=1))
             & (data.Low <= data[['Open', 'Close', 'High']].min(axis=1)))
    if not valid.all():
        limitations.append(f'{int((~valid).sum())} invalid OHLC bars excluded; missing sessions are not interpolated.')
    data = data.loc[valid].copy()
    # Yahoo normally supplies split-adjusted OHLC. Repair only a clear raw split discontinuity.
    if 'Stock Splits' in data:
        for i in range(1, len(data)):
            split = finite(data['Stock Splits'].iloc[i])
            if split and split != 1:
                ratio = data.Close.iloc[i - 1] / data.Open.iloc[i]
                if abs(ratio / split - 1) < 0.12 and abs(ratio - 1) > 0.3:
                    data.loc[data.index[:i], ['Open', 'High', 'Low', 'Close']] /= split
                    data.loc[data.index[:i], 'Volume'] *= split
                    limitations.append('A clear raw stock split discontinuity was adjusted; vendor-adjusted bars were not adjusted twice.')
    return data, limitations


def calculate_indicators(history: pd.DataFrame) -> pd.DataFrame:
    """Reference-friendly indicators; daily session VWAP deliberately unavailable."""
    data, _ = prepare_prices(history)
    if data.empty:
        return data
    c, h, l, v = data.Close, data.High, data.Low, data.Volume.clip(lower=0)
    out = pd.DataFrame(index=data.index)
    for n in (20, 50, 100, 200):
        out[f'sma_{n}'] = c.rolling(n, min_periods=n).mean()
    for n in (9, 12, 21, 26, 50, 200):
        out[f'ema_{n}'] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    out['macd'] = out.ema_12 - out.ema_26
    out['macd_signal'] = out.macd.ewm(span=9, adjust=False, min_periods=9).mean()
    out['macd_histogram'] = out.macd - out.macd_signal
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    out['atr'] = wilder(tr, 14)
    up, down = h.diff(), -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0).mask(up.isna())
    minus_dm = down.where((down > up) & (down > 0), 0).mask(down.isna())
    out['plus_di'] = 100 * wilder(plus_dm, 14) / out.atr.replace(0, np.nan)
    out['minus_di'] = 100 * wilder(minus_dm, 14) / out.atr.replace(0, np.nan)
    denominator = out.plus_di + out.minus_di
    dx = 100 * (out.plus_di - out.minus_di).abs() / denominator.replace(0, np.nan)
    dx = dx.mask(denominator == 0, 0)
    out['adx'] = wilder(dx, 14)
    out['ichimoku_conversion'] = (h.rolling(9).max() + l.rolling(9).min()) / 2
    out['ichimoku_base'] = (h.rolling(26).max() + l.rolling(26).min()) / 2
    out['ichimoku_span_a'] = ((out.ichimoku_conversion + out.ichimoku_base) / 2).shift(26)
    out['ichimoku_span_b'] = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    out['parabolic_sar'] = parabolic_sar(h, l, c)
    out['rsi'] = rsi(c)
    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    spread = (hi14-lo14).replace(0, np.nan)
    out['stochastic_k'] = 100 * (c-lo14) / spread
    out['stochastic_d'] = out.stochastic_k.rolling(3).mean()
    rsi_low, rsi_high = out.rsi.rolling(14).min(), out.rsi.rolling(14).max()
    out['stochastic_rsi'] = 100 * (out.rsi-rsi_low) / (rsi_high-rsi_low).replace(0, np.nan)
    out['roc'] = 100 * (c / c.shift(12) - 1)
    typical = (h+l+c)/3
    deviation = typical.rolling(20).apply(lambda a: np.mean(np.abs(a-a.mean())), raw=True)
    out['cci'] = (typical-typical.rolling(20).mean()) / (0.015*deviation.replace(0, np.nan))
    out['williams_r'] = -100 * (hi14-c) / spread
    std = c.rolling(20).std(ddof=0)
    out['bollinger_mid'] = out.sma_20
    out['bollinger_upper'], out['bollinger_lower'] = out.sma_20+2*std, out.sma_20-2*std
    out['historical_volatility'] = np.log(c/c.shift()).rolling(20).std(ddof=1)*np.sqrt(252)
    ema20 = c.ewm(span=20, adjust=False, min_periods=20).mean()
    out['keltner_mid'] = ema20
    out['keltner_upper'], out['keltner_lower'] = ema20+2*out.atr, ema20-2*out.atr
    out['donchian_upper'], out['donchian_lower'] = h.rolling(20).max(), l.rolling(20).min()
    out['obv'] = (np.sign(c.diff()).fillna(0)*v).cumsum()
    money = typical*v
    positive = money.where(typical.diff() > 0, 0).rolling(14).sum()
    negative = money.where(typical.diff() < 0, 0).rolling(14).sum()
    out['mfi'] = 100-100/(1+positive/negative.replace(0, np.nan))
    out['mfi'] = out.mfi.mask((negative == 0) & (positive > 0), 100)
    out['mfi'] = out.mfi.mask((negative == 0) & (positive == 0), 50)
    multiplier = ((c-l)-(h-c))/(h-l).replace(0, np.nan)
    out['cmf'] = (multiplier.fillna(0)*v).rolling(20).sum()/v.rolling(20).sum().replace(0, np.nan)
    out['volume_sma_20'], out['volume_sma_50'] = v.rolling(20).mean(), v.rolling(50).mean()
    # Compare a completed bar with the preceding 20 bars, excluding itself.
    out['relative_volume'] = v/v.shift().rolling(20).mean().replace(0, np.nan)
    out['high_52_week'], out['low_52_week'] = h.rolling(252, min_periods=1).max(), l.rolling(252, min_periods=1).min()
    out['vwap'] = np.nan
    return out


def _zones(prices: list[float], tolerance: float) -> list[float]:
    groups = []
    for price in sorted(prices):
        if groups and abs(price - float(np.mean(groups[-1]))) <= tolerance:
            groups[-1].append(price)
        else:
            groups.append([price])
    return [round(float(np.mean(group)), 4) for group in groups]


def analyze_technical(history: pd.DataFrame) -> dict:
    data, limitations = prepare_prices(history)
    base = {'score': None, 'confidence': 0, 'signals': [], 'limitations': limitations,
            'indicators': {}, 'series': [], 'structure': {'support': [], 'resistance': [],
            'swing_high': None, 'swing_low': None, 'fibonacci': {}},
            'regime': 'Insufficient Data', 'trend': 'Unknown', 'volatility': None}
    if data.empty:
        base['limitations'].append('No valid price history available.')
        return base
    indicators = calculate_indicators(data)
    latest = {k: finite(v) for k, v in indicators.iloc[-1].items()}
    c = float(data.Close.iloc[-1])
    base['indicators'] = latest
    base['series'] = [{'date': index.isoformat(), **{k: finite(v) for k, v in row.items()}}
                      for index, row in indicators.iterrows()]
    atr = latest.get('atr')
    base['volatility'] = latest.get('historical_volatility')
    base['limitations'].append('Daily OHLC bars cannot reconstruct intraday session VWAP; VWAP is unavailable.')
    if len(data) < 252:
        base['limitations'].append(f'52-week extrema cover only {len(data)} available sessions.')
    base['structure'] = confirmed_structure(data, atr)
    if len(data) < 50:
        base['limitations'].append('At least 50 valid daily sessions are required for a technical score.')
        return base
    trend_components = []
    for name in ('sma_50', 'sma_200'):
        if latest.get(name) is not None:
            trend_components.append(8 if c > latest[name] else 2)
    if latest.get('ema_50') is not None and len(indicators) > 6:
        old = finite(indicators.ema_50.iloc[-6])
        if old:
            trend_components.append(8 if latest['ema_50'] > old else 2)
    if latest.get('macd_histogram') is not None:
        trend_components.append(7 if latest['macd_histogram'] > 0 else 3)
    trend_score = float(np.mean(trend_components)) if trend_components else None
    momentum = latest.get('rsi')
    momentum_score = None
    if momentum is not None:
        # Extremes identify stretched moves; do not interpret oversold as an automatic buy.
        momentum_score = 7 if 50 <= momentum <= 70 else (5 if momentum > 70 or 40 <= momentum < 50 else 3)
    cmf = latest.get('cmf')
    volume_score = 7 if cmf is not None and cmf > .05 else 3 if cmf is not None and cmf < -.05 else 5 if cmf is not None else None
    groups = [(trend_score,.5), (momentum_score,.35), (volume_score,.15)]
    valid_groups = [(s,w) for s,w in groups if s is not None]
    base['score'] = round(sum(s*w for s,w in valid_groups)/sum(w for _,w in valid_groups), 2)
    coverage = sum(v is not None for k,v in latest.items() if k != 'vwap')/(len(latest)-1)
    base['confidence'] = round(min(1,len(data)/252)*coverage, 3)
    base['trend'] = 'Uptrend' if trend_score and trend_score >= 6 else 'Downtrend' if trend_score and trend_score <= 4 else 'Mixed'
    adx = latest.get('adx')
    base['regime'] = 'Trending' if adx is not None and adx >= 25 else 'Range / weak trend' if adx is not None else 'Uncertain'
    base['signals'] = [f"{base['trend']}: price is {'above' if c > latest['sma_50'] else 'below'} its 50-session average ({latest['sma_50']:.2f})."]
    if momentum is not None:
        base['signals'].append(f"RSI(14) is {momentum:.1f}; {'momentum is stretched and pullback risk is elevated' if momentum > 70 else 'weak momentum is not evidence of a reversal' if momentum < 30 else 'momentum is positive' if momentum >= 50 else 'momentum is subdued'}.")
    if adx is not None:
        base['signals'].append(f'ADX(14) is {adx:.1f}; this measures trend strength, not direction.')
    if atr is not None:
        base['signals'].append(f'ATR(14) is {atr:.2f} per session ({atr/c:.1%} of the latest close).')
    if len(data) > 21:
        prior_high, prior_low = data.High.iloc[-21:-1].max(), data.Low.iloc[-21:-1].min()
        if c > prior_high:
            base['signals'].append('The latest close broke above the preceding 20-session high; confirmation is uncertain.')
        if c < prior_low:
            base['signals'].append('The latest close broke below the preceding 20-session low.')
    if len(indicators) > 201:
        now_spread = indicators.sma_50.iloc[-1]-indicators.sma_200.iloc[-1]
        previous_spread = indicators.sma_50.iloc[-2]-indicators.sma_200.iloc[-2]
        if now_spread*previous_spread < 0:
            base['signals'].append('A 50/200-session moving-average crossover occurred on the latest completed session.')
    base['group_scores'] = {'trend': trend_score, 'momentum': momentum_score, 'participation': volume_score}
    base['limitations'].append('Trend 50%, momentum 35%, participation 15%; correlated indicators are not independent votes. Prices are split-adjusted, not guaranteed total-return adjusted.')
    return base
