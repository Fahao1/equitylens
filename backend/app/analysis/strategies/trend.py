from .common import result,prerequisites,reject,support_zone,technical_stop,finalize


def evaluate(snapshot,context,config):
    out=result('trend_following',snapshot,context,config)
    if not prerequisites(out,snapshot,context):return out
    if out['regime'] not in ('Strong bullish trend','Weak bullish trend'):
        return reject(out,'Trend following requires an established multi-signal bullish regime.','avoid')
    zone=support_zone(snapshot);atr=snapshot['atr'];close=snapshot['close']
    if not zone or close-zone['price']>1.5*atr:
        return reject(out,'No repeatedly confirmed support within 1.5 ATR of the pullback.')
    if snapshot.get('rsi') is None or snapshot.get('rsi_previous') is None or not (40<=snapshot['rsi']<=65 and snapshot['rsi']>snapshot['rsi_previous'] and close>snapshot.get('previous_close',close)):
        return reject(out,'Daily momentum recovery is unconfirmed (rising RSI 40–65 and a higher close required).')
    if snapshot.get('relative_volume') is None or snapshot['relative_volume']<1.1:
        return reject(out,'Relative volume must confirm at least 1.1 times the preceding 20-bar average.')
    entry=[max(zone['lower'],zone['price']-.25*atr),min(close,zone['price']+.5*atr)]
    stop,buffer=technical_stop(zone,atr,context,config)
    targets=[z['price'] for z in snapshot.get('resistance_zones',[]) if z.get('touches',0)>=2]
    if snapshot.get('swing_high'):targets.append(snapshot['swing_high'])
    out.update(entry_condition='Next open must fall inside the support pullback zone after the completed daily momentum/volume confirmation.',
      invalidation={'price':stop,'kind':'technical','condition':'A trade below structural support minus the preselected ATR buffer invalidates this setup.'},
      evidence=[f"Confirmed support {zone['price']:.6f} with {zone['touches']} pivots, known by {zone['confirmed_at']}.",f"RSI recovered to {snapshot['rsi']:.2f}; relative volume {snapshot['relative_volume']:.2f}."],
      target_methodology=['Targets are repeatedly confirmed historical resistance and the latest confirmed swing high; no synthetic R-multiple target.'],
      calculation=[f"Entry uses support −0.25 ATR to support +0.5 ATR, capped at close; stop = structural zone low −{buffer} ATR."])
    return finalize(out,entry,stop,targets,snapshot,context,config)
