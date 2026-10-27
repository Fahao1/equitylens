from .common import result,prerequisites,reject,technical_stop,finalize


def evaluate(snapshot,context,config):
    out=result('breakout',snapshot,context,config)
    if not prerequisites(out,snapshot,context):return out
    if out['regime'] not in ('Strong bullish trend','Weak bullish trend','Sideways consolidation'):
        return reject(out,'Breakouts are not entered in bearish or high-volatility disorder regimes.','avoid')
    close=snapshot['close'];atr=snapshot['atr'];previous=snapshot.get('previous_close')
    zones=[z for z in snapshot.get('support_zones',[])+snapshot.get('resistance_zones',[]) if z.get('touches',0)>=2 and previous is not None and previous<=z.get('upper',z['price'])<close and any(p.get('kind')=='high' for p in z.get('pivots',[]))]
    if not zones:return reject(out,'No completed close above repeatedly confirmed prior resistance.')
    zone=max(zones,key=lambda z:z['price'])
    if snapshot.get('range_atr_20') is None or snapshot['range_atr_20']>8:
        return reject(out,'Prior 20-session consolidation width exceeds eight ATR or cannot be measured.')
    if snapshot.get('relative_volume') is None or snapshot['relative_volume']<1.5:
        return reject(out,'A breakout requires relative volume of at least 1.5; a headline or intrabar high is insufficient.')
    if close-zone['upper']>.75*atr:return reject(out,'Price is extended beyond the 0.75 ATR breakout entry cap; avoid chasing.')
    entry=[zone['upper']+.05*atr,min(close,zone['upper']+.75*atr)]
    stop,buffer=technical_stop(zone,atr,context,config)
    height=(snapshot.get('prior_high_20') or 0)-(snapshot.get('prior_low_20') or 0)
    targets=[z['price'] for z in snapshot.get('resistance_zones',[]) if z.get('touches',0)>=2]
    if height>0:targets.append(zone['price']+height)
    out.update(entry_condition='A completed close and volume breakout must hold; next open must be within the capped breakout zone.',
      invalidation={'price':stop,'kind':'technical','condition':'Loss of the broken resistance zone and its ATR buffer is a failed-breakout invalidation.'},
      evidence=[f"Resistance {zone['price']:.6f}, {zone['touches']} confirmed touches; previous close {previous:.6f}, latest {close:.6f}.",f"Relative volume {snapshot['relative_volume']:.2f}; consolidation width {snapshot['range_atr_20']:.2f} ATR."],
      target_methodology=['Existing resistance plus one measured move equal to the prior 20-bar range; the measured move is a rule assumption, not a forecast.'],
      calculation=[f"Entry starts 0.05 ATR above the zone and is capped at 0.75 ATR; stop = zone low −{buffer} ATR. Measured move height {height:.6f}."])
    return finalize(out,entry,stop,targets,snapshot,context,config)
