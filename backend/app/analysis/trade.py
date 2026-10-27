"""Conditional, long-only research plans; never places orders."""
from math import floor
from app.utils import number


def build_trade_plan(overview, technical, valuation, macro, score, config):
    price = number(overview.get("price"))
    capital, risk_fraction = config.get("capital", 10000), config.get("risk_per_trade", .01)
    horizon = str(config.get("horizon", "swing"))
    tolerance = config.get("risk_tolerance", "medium")
    budget = capital * risk_fraction
    event_risk = macro.get("event_risk", {})
    warnings = list(macro.get("limitations", []))
    if isinstance(event_risk, dict):
        warnings.extend(event_risk.get("warnings", []))
    elif event_risk:
        warnings.append(str(event_risk))
    result = {"recommendation": "Insufficient Data", "status": "No favorable setup", "entry_zone": None, "breakout_entry": None,
              "targets": [], "stop": None, "risk_reward": None, "upside_percent": None, "downside_percent": None,
              "position_size": 0, "risk_budget": round(budget,2), "holding_horizon": {"short": "1–5 sessions", "swing": "2–8 weeks", "long": "1–3 years"}.get(horizon, horizon),
              "calculation": [], "invalidation": ["Reassess after new earnings, a material news development, or a change in market structure."],
              "event_warnings": warnings, "quoted_price": price, "quote_at": overview.get("quote_at"),
              "limitations": ["Stops can gap through; sizing excludes commissions and taxes. Price levels are conditional research estimates."]}
    atr = number(technical.get("indicators", {}).get("atr"))
    if price is None or price <= 0 or atr is None or atr <= 0:
        result["calculation"].append("A positive dated price and ATR(14) are required before computing levels.")
        return result
    if overview.get("stale"):
        result["calculation"].append("Quote is stale or undated. Refresh the source before generating actionable levels.")
        return result
    structure = technical.get("structure", {})
    supports = sorted([v for x in structure.get("support", []) if (v := number(x)) is not None and 0 < v <= price])
    resistances = sorted([v for x in structure.get("resistance", []) if (v := number(x)) is not None and v > price])
    if not supports:
        result["recommendation"] = "Wait"
        result["calculation"].append("No objectively identified support below the current price; no justified entry zone.")
        return result
    support = supports[-1]
    width = {"short": .15, "swing": .25, "long": .5}.get(horizon, .25) * atr
    entry_low, entry_high = max(.01, support-width), min(price, support+width)
    entry = entry_high  # size and reward/risk use the least favorable fill in the zone
    multiplier = {"low": 2.5, "medium": 2, "high": 1.5}[tolerance]
    if horizon == "long":
        multiplier += 1
    stop = max(.01, min(support-.5*atr, entry-multiplier*atr))
    precision = 2 if price >= 1 else 6
    entry_low, entry_high, stop = (round(v, precision) for v in (entry_low, entry_high, stop))
    entry = entry_high
    if not 0 < stop < entry_low <= entry_high:
        result["recommendation"] = "Wait"
        result["calculation"].append("No valid positive-risk zone at the supported price precision; no position is sized.")
        return result
    unit_risk = entry-stop
    targets = [v for v in resistances if v > entry]
    # Never invent a target by adding the minimum R multiple to entry.
    if horizon == "long":
        scenarios = valuation.get("scenarios", {})
        if isinstance(scenarios, dict):
            for name in ("conservative", "base"):
                scenario = scenarios.get(name)
                candidate = number(scenario.get("value_per_share") or scenario.get("fair_value") if isinstance(scenario, dict) else scenario)
                if candidate and candidate > entry:
                    targets.append(candidate)
    targets = sorted({round(v, precision) for v in targets if round(v, precision) > entry})
    target = targets[0] if targets else None
    ratio = (target-entry)/unit_risk if target is not None and unit_risk > 0 else None
    shares = max(0, min(floor(budget/unit_risk), floor(capital/entry))) if unit_risk > 0 else 0
    # Existing holdings consume the same risk and capital budget; displayed shares are additional.
    existing = config.get("existing_shares", 0)
    at_risk = existing * max(0, price-stop)
    shares = min(shares, max(0, floor((budget-at_risk)/unit_risk)), max(0, floor((capital-existing*price)/entry)))
    result.update(entry_zone=[entry_low, entry_high], targets=targets[:2], stop=stop,
                  risk_reward=round(ratio,2) if ratio is not None else None,
                  upside_percent=round((target/entry-1)*100,2) if target else None, downside_percent=round((1-stop/entry)*100,2),
                  position_size=shares, entry_reference=round(entry,2), risk_per_share=round(unit_risk,4),
                  position_value=round(shares*entry,2), estimated_capital_risk=round(shares*unit_risk+at_risk,2))
    result["calculation"] = [f"Nearest detected support {support:.4f}; ATR(14) {atr:.4f}.",
        f"Entry zone = support ± {width/atr:.2f} × ATR, capped at quoted price: {entry_low:.4f}–{entry_high:.4f}.",
        f"Stop = min(support − 0.5 × ATR, entry-high − {multiplier:.1f} × ATR), floored at 0.01: {stop:.4f}.",
        f"Targets are the next detected resistance levels above price{' plus available DCF scenarios for a long horizon' if horizon=='long' else ''}: {', '.join(f'{t:.4f}' for t in targets[:2]) or 'none'}.",
        f"Reward/risk uses the entry-zone high and first target: (target − {entry:.4f}) / ({entry:.4f} − {stop:.4f}).",
        f"Risk budget = {capital:.2f} × {risk_fraction:.2%} = {budget:.2f}. Additional whole shares = min(risk-budget / unit-risk, available-capital / entry), after existing holdings."]
    result["invalidation"].insert(0, f"Price closing below {stop:.2f} invalidates this technical setup; gap losses may be larger.")
    if len(targets) > 1:
        result["calculation"].append("Second target is a separate resistance/scenario; the candidate threshold is tested against the first target.")
    high_events = [e for e in macro.get("upcoming_events", []) if str(e.get("impact", "")).lower() == "high"]
    event_soon = False
    from datetime import datetime, timezone
    for event in high_events:
        try:
            delta = (datetime.fromisoformat(event["scheduled_at"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
            if 0 <= delta <= (72 if tolerance=="low" else 24)*3600:
                event_soon = True
                result["event_warnings"].append(f"High-impact {event.get('title','event')} approaches. Entry levels have greater event uncertainty; waiting for the release is part of this strategy.")
        except (ValueError, KeyError, TypeError):
            pass
    overall = number(score.get("overall"))
    trend = str(technical.get("trend", technical.get("regime", ""))).lower()
    if len(resistances) >= 2 and overall is not None and overall >= 6 and score.get("confidence",0) >= .4 and not event_soon and "up" in trend and resistances[0]-price <= 2*atr:
        trigger = round(resistances[0]+.1*atr, precision)
        breakout_stop = round(max(.01, resistances[0]-atr), precision)
        breakout_target = round(resistances[1], precision)
        breakout_risk = trigger-breakout_stop
        breakout_rr = (breakout_target-trigger)/breakout_risk if breakout_risk>0 else 0
        if breakout_rr >= config.get("min_reward_risk",2):
            result["breakout_entry"] = trigger
            result["breakout_alternative"] = {"trigger": trigger, "stop": breakout_stop, "target": breakout_target, "risk_reward": round(breakout_rr,2),
                "confirmation": "A completed daily close above the trigger and relative volume at least 1.2; recompute risk sizing after confirmation."}
            result["calculation"].append(f"Conditional breakout trigger = first resistance + 0.1 ATR ({trigger}); stop = first resistance − ATR ({breakout_stop}); target = next resistance ({breakout_target}); reward/risk {breakout_rr:.2f}. This alternative has no allocated shares until confirmation and a new size calculation.")
    if overall is None or score.get("confidence",0) < .4:
        result["recommendation"] = "Hold/Manage" if existing else "Insufficient Data"
        result["position_size"] = 0
    elif overall < 3.5:
        result["recommendation"] = "Reduce/Sell candidate" if existing else "Avoid"
        result["position_size"] = 0
    elif event_soon or ratio is None or ratio < config.get("min_reward_risk",2) or shares <= 0 or overall < 6 or "bear" in trend or "down" in trend:
        result["recommendation"] = "Hold/Manage" if existing else "Wait"
        result["position_size"] = 0
        result["calculation"].append("Candidate requires score ≥6, confidence ≥40%, supportive trend, positive affordable size, no imminent strategy-blocking high-impact event, and first-target reward/risk above the requested minimum.")
    else:
        result["recommendation"] = "Hold/Manage" if existing else "Buy candidate"
        result["status"] = "Conditional setup; wait for entry confirmation"
    if result["position_size"] == 0:
        result["position_value"] = 0
        result["estimated_capital_risk"] = round(at_risk,2)
    if config.get("cost_basis") and existing:
        result["unrealized_pnl"] = round(existing*(price-config["cost_basis"]),2)
    return result
