from .common import result,prerequisites,reject,support_zone,technical_stop,finalize


def evaluate(snapshot,context,config):
    out=result('mean_reversion',snapshot,context,config)
    if not prerequisites(out,snapshot,context):return out
    if out['regime']!='Sideways consolidation' or snapshot.get('adx') is None or snapshot['adx']>=20:
        return reject(out,'Mean reversion is restricted to low-strength sideways conditions; no falling-knife trade in strong trends.','avoid')
    zone=support_zone(snapshot);atr=snapshot['atr'];close=snapshot['close']
    if not zone or close-zone['price']>atr:return reject(out,'No repeatedly confirmed range support within one ATR.')
    if any(snapshot.get(k) is None for k in ('rsi','rsi_previous','bollinger_lower','previous_bollinger_lower','previous_close')):
        return reject(out,'Reversal inputs are incomplete.','insufficient_data')
    if not (snapshot['rsi_previous']<35 and snapshot['rsi']>snapshot['rsi_previous'] and snapshot['previous_close']<snapshot['previous_bollinger_lower'] and close>snapshot['bollinger_lower']):
        return reject(out,'A prior close below its own lower Bollinger band, a completed close back above the current lower band, and rising RSI from below 35 are required.')
    entry=[max(zone['lower'],close-.25*atr),close]
    stop,buffer=technical_stop(zone,atr,context,config)
    targets=[snapshot[k] for k in ('sma_20','sma_50') if snapshot.get(k)]
    targets.extend(z['price'] for z in snapshot.get('resistance_zones',[]) if z.get('touches',0)>=2)
    out.update(entry_condition='Next open inside the reversal zone after a completed lower-band recovery; no entry on oversold RSI alone.',
      invalidation={'price':stop,'kind':'technical','condition':'Range support fails beyond its ATR buffer or a strong directional trend emerges.'},
      evidence=[f"ADX {snapshot['adx']:.2f}; RSI {snapshot['rsi_previous']:.2f} → {snapshot['rsi']:.2f}; prior close {snapshot['previous_close']:.4f} was below its prior band {snapshot['previous_bollinger_lower']:.4f}, and current close {close:.4f} recovered above the current band {snapshot['bollinger_lower']:.4f}."],
      target_methodology=['Mean reversion targets the observed SMA20/SMA50 and confirmed range resistance above entry.'],
      calculation=[f"Entry = reversal close −0.25 ATR through close; stop = confirmed range support low −{buffer} ATR."])
    return finalize(out,entry,stop,targets,snapshot,context,config)
