"""Deterministic market regimes from grouped, causal features; no outcome probabilities."""
from __future__ import annotations

from datetime import datetime, timezone
import math

LABELS = (
    'Strong bullish trend', 'Weak bullish trend', 'Sideways consolidation',
    'Weak bearish trend', 'Strong bearish trend', 'High-volatility regime',
)
FEATURE_KEYS = (
    'bars', 'as_of', 'close', 'open', 'high', 'low', 'previous_close', 'atr',
    'sma_50', 'sma_200', 'slope_50', 'slope_200', 'adx', 'atr_percentile',
    'hv_percentile', 'historical_volatility', 'relative_strength_63',
    'benchmark_trend', 'structure', 'range_atr_20',
)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value):
    number = _number(value)
    return number if number is not None and number > 0 else None


def _percentile(value):
    number = _number(value)
    return number if number is not None and 0 <= number <= 100 else None


def _benchmark_direction(value):
    text = str(value or '').strip().lower()
    if text in {'bullish', 'uptrend', 'up'}:
        return 1
    if text in {'bearish', 'downtrend', 'down'}:
        return -1
    if text in {'sideways', 'mixed', 'neutral', 'range'}:
        return 0
    return None


def classify_regime(features: dict) -> dict:
    """Consume a completed-bar snapshot; slopes are fractional changes, percentiles 0..100."""
    features = features if isinstance(features, dict) else {}
    values = {key: _number(features.get(key)) for key in FEATURE_KEYS if key not in {'as_of', 'structure', 'benchmark_trend'}}
    for key in ('structure', 'benchmark_trend'):
        values[key] = features.get(key) if isinstance(features.get(key), str) else None
    stamp = features.get('as_of')
    values['as_of'] = stamp.isoformat() if hasattr(stamp, 'isoformat') else stamp if isinstance(stamp, str) else None
    result = {'regime': 'Insufficient Data', 'trend_strength': 'Unavailable',
              'volatility_regime': 'Unavailable', 'confidence': 0., 'evidence': [],
              'features': values, 'limitations': [
                  'Regimes are descriptive rules, not predictions. Confidence measures feature completeness and rule consistency, not a calibrated probability.',
                  'Classification requires completed bars and features computed only through the decision timestamp.',
              ]}
    bars = _number(features.get('bars'))
    close, sma50, sma200 = (_positive(features.get(key)) for key in ('close', 'sma_50', 'sma_200'))
    slope50, slope200 = (_number(features.get(key)) for key in ('slope_50', 'slope_200'))
    adx = _number(features.get('adx'))
    adx = adx if adx is not None and 0 <= adx <= 100 else None
    atr = _positive(features.get('atr'))
    atr_pct, hv_pct = (_percentile(features.get(key)) for key in ('atr_percentile', 'hv_percentile'))
    hv = _number(features.get('historical_volatility'))
    hv = hv if hv is not None and hv >= 0 else None
    relative = _number(features.get('relative_strength_63'))
    benchmark = _benchmark_direction(features.get('benchmark_trend'))
    structure = features.get('structure')
    structure = structure if isinstance(structure, str) and structure in {'higher_highs_higher_lows', 'lower_highs_lower_lows', 'mixed'} else None
    range_atr = _number(features.get('range_atr_20'))
    if bars is None or bars < 200 or bars != int(bars) or None in (close, sma50, sma200):
        result['limitations'].append('At least 200 completed bars and finite positive close/SMA50/SMA200 are required; unavailable long-term trend is not assigned a favorable state.')
        return result
    if bars < 252:
        result['limitations'].append(f'Only {int(bars)} completed bars are available; a full 252-session context is not present and confidence is reduced.')
    if slope50 is None or slope200 is None:
        result['limitations'].append('One or both moving-average slopes are unavailable; a strong directional regime cannot be established from slopes alone.')
    if atr_pct is None or hv_pct is None or atr is None or hv is None:
        result['limitations'].append('ATR/historical-volatility context is incomplete; no volatility state is inferred from a single available measure.')
    if relative is None or benchmark is None:
        result['limitations'].append('Aligned benchmark return/trend evidence is incomplete; relative strength contributes no favorable default and confidence is reduced.')
    if structure is None:
        result['limitations'].append('Confirmed price-structure evidence is unavailable.')

    ma_up, ma_down = close > sma50 > sma200, close < sma50 < sma200
    slopes_up = slope50 is not None and slope200 is not None and slope50 > 0 and slope200 > 0
    slopes_down = slope50 is not None and slope200 is not None and slope50 < 0 and slope200 < 0
    structure_up, structure_down = structure == 'higher_highs_higher_lows', structure == 'lower_highs_lower_lows'
    vol_complete = atr_pct is not None and hv_pct is not None and atr is not None and hv is not None
    relative_complete = relative is not None and benchmark is not None
    groups = {
        'moving_average_alignment': 1.,
        'slopes': (int(slope50 is not None) + int(slope200 is not None))/2,
        'trend_strength': float(adx is not None),
        'volatility': float(vol_complete),
        'price_structure': float(structure is not None),
        'relative_context': float(relative_complete),
    }
    weights = {'moving_average_alignment': .25, 'slopes': .20, 'trend_strength': .15,
               'volatility': .15, 'price_structure': .15, 'relative_context': .10}
    completeness = sum(groups[key]*weights[key] for key in groups)
    if sum(value > 0 for value in groups.values()) < 3:
        result['limitations'].append('Fewer than three feature groups are available; moving averages alone cannot establish a model regime.')
        return result
    agreement = 1.
    if (ma_up and structure_down) or (ma_down and structure_up):
        agreement *= .8
        result['limitations'].append('Moving-average direction and confirmed price structure disagree.')
    if (ma_up and relative is not None and relative < 0) or (ma_down and relative is not None and relative > 0):
        agreement *= .9
        result['limitations'].append('Relative performance opposes the moving-average direction.')
    result['confidence'] = round(completeness*min(1., bars/252)*agreement, 3)
    if adx is not None:
        result['trend_strength'] = ('Strong' if adx >= 25 and (slopes_up or slopes_down)
                                    else 'Moderate' if adx >= 20 else 'Weak')
    if hv == 0:
        result['limitations'].append('Measured close-return volatility is zero; an inclusive percentile rank alone cannot establish elevated volatility.')
    if vol_complete:
        result['volatility_regime'] = 'High' if hv > 0 and atr_pct >= 80 and hv_pct >= 80 else 'Low' if atr_pct <= 20 and hv_pct <= 20 else 'Normal'
    high, low, opened, previous = (_number(features.get(key)) for key in ('high', 'low', 'open', 'previous_close'))
    wide_bar = bool(atr and high is not None and low is not None and high >= low and (high-low)/atr >= 1.5)
    gap = bool(atr and opened is not None and previous is not None and abs(opened-previous)/atr >= 1.)
    dislocated = bool(atr and abs(close-sma50)/atr >= 3.)
    mixed_wide_range = structure == 'mixed' and range_atr is not None and range_atr >= 8
    price_disorder = mixed_wide_range or wide_bar or gap or dislocated
    high_volatility = vol_complete and hv > 0 and atr_pct >= 80 and hv_pct >= 80 and price_disorder
    # Relative evidence may contradict a strong technical trend. Missing data adds no vote.
    opposing_bull = (relative is not None and relative < 0) or benchmark == -1
    opposing_bear = (relative is not None and relative > 0) or benchmark == 1
    strong_bull = ma_up and slopes_up and adx is not None and adx >= 25 and structure_up and not opposing_bull
    strong_bear = ma_down and slopes_down and adx is not None and adx >= 25 and structure_down and not opposing_bear
    weak_bull = (ma_up and slope50 is not None and slope50 >= 0) or (close > sma50 and slope50 is not None and slope50 > 0 and structure_up)
    weak_bear = (ma_down and slope50 is not None and slope50 <= 0) or (close < sma50 and slope50 is not None and slope50 < 0 and structure_down)
    compact = abs(sma50/sma200-1) <= .03 and (range_atr is None or 0 <= range_atr <= 8)
    sideways = (adx is not None and adx < 20 and structure == 'mixed' and compact
                and slope50 is not None and abs(slope50) <= .01)
    if high_volatility:
        result['regime'] = 'High-volatility regime'
    elif strong_bull:
        result['regime'] = 'Strong bullish trend'
    elif strong_bear:
        result['regime'] = 'Strong bearish trend'
    elif sideways:
        result['regime'] = 'Sideways consolidation'
    elif weak_bull:
        result['regime'] = 'Weak bullish trend'
    elif weak_bear:
        result['regime'] = 'Weak bearish trend'
    else:
        result['confidence'] = min(result['confidence'], .4)
        result['limitations'].append('Available signals conflict or lack the confirmations required by any directional/consolidation rule; no regime is forced.')

    result['evidence'] = [
        f'Completed bars: {int(bars)}. Close {close:.4f}; SMA50 {sma50:.4f}; SMA200 {sma200:.4f}.',
        f'Grouped moving-average alignment is {"bullish" if ma_up else "bearish" if ma_down else "mixed"}; slope50={slope50 if slope50 is not None else "unavailable"}, slope200={slope200 if slope200 is not None else "unavailable"}.',
        f'ADX={adx if adx is not None else "unavailable"} describes strength; confirmed price structure is {structure or "unavailable"}.',
        f'ATR percentile={atr_pct if atr_pct is not None else "unavailable"}; historical-volatility percentile={hv_pct if hv_pct is not None else "unavailable"}; volatility state {result["volatility_regime"]}.',
        f'63-bar stock return minus aligned benchmark return={relative if relative is not None else "unavailable"}; benchmark trend={features.get("benchmark_trend") or "unavailable"}.',
    ]
    if high_volatility:
        result['evidence'].append('Both volatility percentiles are at least 80 and independent price-action evidence shows a wide mixed-structure range, a wide bar, a gap or a large moving-average displacement. This state takes precedence over direction.')
    result['feature_coverage'] = groups
    return result


def analyze_regime(history, benchmark=None, as_of: datetime | None = None) -> dict:
    """Convenience wrapper; callers must provide completed daily bars (or explicit Bar End)."""
    import pandas as pd
    from app.analysis.features import build_features, snapshot_at
    from app.providers.bar_times import bar_availability
    when = as_of or datetime.now(timezone.utc)
    when = pd.Timestamp(when)
    when = when.tz_localize('UTC') if when.tzinfo is None else when.tz_convert('UTC')
    def past(frame):
        if frame is None:
            return None
        result = frame.copy()
        index = pd.to_datetime(result.index, utc=True)
        available = bar_availability(result)
        mask = (index <= when) & available.notna() & (available <= when)
        return result.loc[mask]
    causal = build_features(past(history), past(benchmark))
    if causal.empty:
        return classify_regime({})
    return classify_regime(snapshot_at(causal))
