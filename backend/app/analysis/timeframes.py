"""Completed-candle summaries with hierarchical context, not five independent votes."""
from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np
import pandas as pd

from app.analysis.structure import confirmed_structure
from app.analysis.technical import rsi, wilder
from app.providers.bar_times import completed_bars

TIMEFRAMES = ('weekly', 'daily', '4h', '1h', '15m')
INTERVALS = {'weekly': '1wk', 'daily': '1d', '4h': '4h', '1h': '1h', '15m': '15m'}


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _empty(name, metadata, status='missing'):
    return {'timeframe': name, 'status': status, 'trend': 'Unavailable', 'momentum': 'Unavailable',
            'volatility': 'Unavailable', 'support': None, 'resistance': None, 'bars': 0,
            'last_bar_at': None, 'last_bar_end': None, 'source': metadata.get('source'),
            'confidence': 0., 'indicators': {}, 'limitations': []}


def _percentile(series):
    values = series.replace([np.inf, -np.inf], np.nan).dropna().tail(252)
    if len(values) < 63:
        return None
    if values.nunique() == 1:
        return 50.
    return 100*float((values <= values.iloc[-1]).mean())


def _completed(frame, name, metadata, when):
    limits = []
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError('A DatetimeIndex is required; arbitrary row numbers are not timestamps.')
    data = frame.copy().sort_index()
    if data.index.has_duplicates:
        data = data[~data.index.duplicated(keep='last')]
        limits.append('Duplicate source timestamps were reduced to the latest supplied observation.')
    zone = metadata.get('exchange_timezone') or metadata.get('source_timezone') or metadata.get('timezone') or str(data.index.tz or 'UTC')
    if data.index.tz is None:
        if not any(metadata.get(key) for key in ('exchange_timezone', 'source_timezone', 'timezone')):
            limits.append('Source timezone is unavailable; UTC boundaries are assumed and completion confidence is reduced.')
        data.index = data.index.tz_localize(zone, ambiguous='raise', nonexistent='raise')
    opened = data.index.tz_convert('UTC')
    data = data.loc[opened < when].copy()
    explicit = 'Bar End' in data
    if explicit:
        # The contract requires timezone-bearing end timestamps, rather than guessed local times.
        aware = []
        for value in data['Bar End']:
            try:
                aware.append(pd.notna(value) and pd.Timestamp(value).tzinfo is not None)
            except (ValueError, TypeError):
                aware.append(False)
        ends = pd.to_datetime(data['Bar End'], utc=True, errors='coerce')
        valid = np.asarray(aware, dtype=bool) & ends.notna().to_numpy() & (ends.to_numpy() > data.index.tz_convert('UTC').to_numpy())
        if not valid.all():
            limits.append(f'{int((~valid).sum())} invalid, undated or nonpositive-duration Bar End values were excluded.')
        data = data.loc[valid].copy()
        data['Bar End'] = pd.to_datetime(data['Bar End'], utc=True, errors='coerce')
    else:
        limits.append('Bar End was not provided: daily/current source-local day and weekly/current week are conservatively excluded; intraday completion uses the nominal interval and may omit truncated session bars.')
    original = len(data)
    data = data.loc[data['Bar End'] <= when].copy() if explicit else completed_bars(data, INTERVALS[name], zone, when)
    excluded = original-len(data)
    if excluded:
        limits.append(f'{excluded} not-yet-completed candles were excluded at the decision timestamp.')
    if metadata.get('completion_verified') is False:
        limits.append('Exchange/session completion metadata is not independently verified; historical holidays and half-day closes may be absent. No missing bars are invented.')
    required = ['Open', 'High', 'Low', 'Close']
    if not set(required).issubset(data.columns):
        raise ValueError('Open, High, Low and Close are required for a timeframe summary.')
    for key in required:
        data[key] = pd.to_numeric(data[key], errors='coerce').astype(float)
    valid = (np.isfinite(data[required].to_numpy()).all(axis=1)
             & (data[required] > 0).all(axis=1)
             & (data.High >= data[['Open', 'Close', 'Low']].max(axis=1))
             & (data.Low <= data[['Open', 'Close', 'High']].min(axis=1)))
    if not valid.all():
        limits.append(f'{int((~valid).sum())} invalid OHLC candles were excluded without interpolation.')
    data = data.loc[valid].copy()
    completion_quality = 1. if explicit and metadata.get('completion_verified') is not False else .8 if explicit else .65
    if frame.index.tz is None and not any(metadata.get(key) for key in ('exchange_timezone', 'source_timezone', 'timezone')):
        completion_quality *= .8
    return data, limits, completion_quality


def _summarize(frame, name, metadata, when):
    result = _empty(name, metadata, 'unavailable')
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        result['limitations'].append('No source bars were supplied; no substitute timeframe is fabricated.')
        return result
    try:
        data, limits, quality = _completed(frame, name, metadata, when)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result['limitations'].append(f'Timeframe unavailable: {exc}')
        return result
    result['limitations'].extend(limits)
    result['bars'] = len(data)
    if data.empty:
        result['limitations'].append('No valid completed candles remain at the decision timestamp.')
        return result
    result['last_bar_at'] = data.index[-1].isoformat()
    result['last_bar_end'] = pd.Timestamp(data['Bar End'].iloc[-1]).isoformat()
    result['timestamp_basis'] = 'last_bar_at is the source bar start/session label; last_bar_end is the completion cutoff'
    if len(data) < 50:
        result['status'] = 'insufficient_data'
        result['limitations'].append('At least 50 completed candles are required for this timeframe trend summary.')
        return result
    close, high, low = data.Close, data.High, data.Low
    sma50 = close.rolling(50).mean()
    ema21 = close.ewm(span=21, adjust=False, min_periods=21).mean()
    momentum = rsi(close, 14)
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr, 14)
    bar_volatility = np.log(close/close.shift()).rolling(20).std(ddof=1)
    atr_pct, hv_pct = _percentile(atr/close), _percentile(bar_volatility)
    level, ma, ema, prior_ema = close.iloc[-1], sma50.iloc[-1], ema21.iloc[-1], ema21.iloc[-6]
    result['trend'] = ('Bullish' if level > ema > ma and ema > prior_ema else
                       'Bearish' if level < ema < ma and ema < prior_ema else 'Mixed')
    rsi_value = _number(momentum.iloc[-1])
    result['momentum'] = 'Positive' if rsi_value is not None and rsi_value >= 55 else 'Negative' if rsi_value is not None and rsi_value <= 45 else 'Neutral' if rsi_value is not None else 'Unavailable'
    if atr_pct is not None and hv_pct is not None:
        result['volatility'] = 'High' if atr_pct >= 80 and hv_pct >= 80 else 'Low' if atr_pct <= 20 and hv_pct <= 20 else 'Normal'
    else:
        result['limitations'].append('At least 63 valid historical ATR/return-volatility observations are needed for relative volatility context.')
    structure = confirmed_structure(data, _number(atr.iloc[-1]))
    result['support'] = structure['support'][0] if structure['support'] else None
    result['resistance'] = structure['resistance'][0] if structure['resistance'] else None
    result['support_zones'], result['resistance_zones'] = structure['support_zones'], structure['resistance_zones']
    if result['support'] is None or result['resistance'] is None:
        result['limitations'].append('Confirmed local pivots do not establish both support and resistance; missing levels remain unavailable.')
    result['indicators'] = {'close': _number(level), 'sma_50': _number(ma), 'ema_21': _number(ema),
                            'rsi': rsi_value, 'atr': _number(atr.iloc[-1]),
                            'atr_percent': _number(100*atr.iloc[-1]/level),
                            'realized_bar_volatility': _number(bar_volatility.iloc[-1]),
                            'atr_percentile': atr_pct, 'hv_percentile': hv_pct}
    coverage = sum(value is not None for value in result['indicators'].values())/len(result['indicators'])
    result['confidence'] = round(min(1., len(data)/200)*quality*coverage, 3)
    result['status'] = 'available'
    result['limitations'].append('A moving-average period means candles of this timeframe, not calendar days. Realized volatility is per bar; no unsupported annualization is applied.')
    return result


def _alignment(rows):
    by_name = {row['timeframe']: row for row in rows}
    usable = {name: row for name, row in by_name.items() if row['status'] == 'available'}
    weekly, daily = usable.get('weekly'), usable.get('daily')
    confirmation_name = next((name for name in ('1h', '4h', '15m') if name in usable), None)
    confirmation = usable.get(confirmation_name)
    confidence = round(.35*(weekly['confidence'] if weekly else 0)+.45*(daily['confidence'] if daily else 0)+.20*(confirmation['confidence'] if confirmation else 0), 3)
    result = {'status': 'insufficient_data', 'label': 'Insufficient completed higher-timeframe evidence',
              'direction': None, 'aligned': False, 'conflicting': False,
              'weekly_context': weekly['trend'] if weekly else None,
              'daily_setup': daily['trend'] if daily else None,
              'confirmation_timeframe': confirmation_name,
              'confirmation': confirmation['trend'] if confirmation else None,
              'contradictions': [], 'score': None, 'confidence': confidence,
              'evidence': ['Weekly establishes context, daily establishes setup, and only one lower timeframe confirms timing (1h, otherwise 4h, otherwise 15m). Nested candles are not independent votes.']}
    if not weekly or not daily:
        result['evidence'].append('Weekly and daily completed-bar summaries are both required for a combined alignment classification.')
        return result
    if weekly['trend'] in {'Bullish', 'Bearish'} and daily['trend'] in {'Bullish', 'Bearish'} and weekly['trend'] != daily['trend']:
        result.update(status='conflicting', label='Weekly context and daily setup disagree', conflicting=True)
        result['contradictions'].append(f"Weekly {weekly['trend'].lower()} versus daily {daily['trend'].lower()}.")
        result['confidence'] = round(confidence*.8, 3)
        return result
    if weekly['trend'] != daily['trend'] or weekly['trend'] == 'Mixed':
        result.update(status='mixed', label='Higher-timeframe direction is mixed')
        return result
    direction = weekly['trend']
    result['direction'] = direction.lower()
    if confirmation and confirmation['trend'] in {'Bullish', 'Bearish'} and confirmation['trend'] != direction:
        result.update(status='mixed', label=f'{direction} higher-timeframe context; timing confirmation disagrees', conflicting=True)
        result['contradictions'].append(f"{confirmation_name} {confirmation['trend'].lower()} versus {direction.lower()} weekly/daily context.")
        result['confidence'] = round(confidence*.9, 3)
    elif confirmation and confirmation['trend'] == 'Mixed':
        result.update(status='mixed', label=f'{direction} higher-timeframe context; timing is unconfirmed')
    else:
        result.update(status=f'aligned_{direction.lower()}', label=f'{direction} higher-timeframe alignment', aligned=True,
                      score=8. if direction == 'Bullish' else 2.)
        if not confirmation:
            result['evidence'].append('Lower-timeframe confirmation is unavailable; the confidence calculation retains that missing evidence.')
    return result


def analyze_timeframes(frames: dict[str, pd.DataFrame], metadata=None, as_of=None) -> dict:
    metadata = metadata if isinstance(metadata, dict) else {}
    frames = frames if isinstance(frames, dict) else {}
    when = pd.Timestamp(as_of or datetime.now(timezone.utc))
    when = when.tz_localize('UTC') if when.tzinfo is None else when.tz_convert('UTC')
    rows = []
    for name in TIMEFRAMES:
        meta = metadata.get(name) if isinstance(metadata.get(name), dict) else {}
        if name not in frames:
            row = _empty(name, meta)
            row['limitations'].append('This timeframe was not supplied by the provider.')
        else:
            row = _summarize(frames[name], name, meta, when)
        if meta.get('cache_stale'):
            row['source_status'] = row['status']
            row['status'] = 'stale'
            row['confidence'] = 0.
            row['limitations'].append('Source refresh failed: these dated cached candles are stale and excluded from alignment and timing confirmation.')
        row['cache_stale'] = bool(meta.get('cache_stale', False))
        row['fetched_at'] = meta.get('fetched_at')
        source_limits = meta.get('limitations')
        if isinstance(source_limits, list):
            row['limitations'].extend(str(limit) for limit in source_limits)
        if isinstance(meta.get('error'), dict):
            row['limitations'].append(f"Source error: {meta['error'].get('message') or meta['error'].get('code') or 'unavailable'}")
        rows.append(row)
    alignment = _alignment(rows)
    return {'as_of': when.isoformat(), 'timeframes': rows, 'alignment': alignment,
            'confidence': alignment['confidence'], 'limitations': [
                'Timeframe evidence overlaps. The combined view uses a fixed context/setup/confirmation hierarchy, not five independent votes.',
                'Confidence reports evidence coverage and completion quality; it is not a probability of profit.',
                'Missing timeframes and bars remain missing. No synthetic intraday candles or unseen historical sessions are created.',
            ]}
