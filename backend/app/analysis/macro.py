"""Context-aware calendar research without claiming causality or forecasting prices."""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

from app.providers.calendar import parse_quantity

UTC = timezone.utc


def _dt(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def economic_surprise(event: dict, history: list[dict] | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    result = {"value": None, "unit": None, "normalized": None, "interpretation": "uncertain", "explanation": "Actual and comparable forecast are not both available."}
    scheduled = _dt(event.get("scheduled_at"))
    available = _dt(event.get("available_at"))
    updated = _dt(event.get("last_updated"))
    if not scheduled or scheduled > now or (available and available > now) or (updated and updated > now) or event.get("status") in {"canceled", "delayed", "scheduled"}:
        result["explanation"] = "Release is not known to have occurred; no economic surprise is calculated."
        return result
    quantities = event.get("quantities") or {}
    actual = quantities.get("actual") or parse_quantity(event.get("actual"))
    forecast = quantities.get("forecast") or parse_quantity(event.get("forecast"))
    if actual.get("value") is None or forecast.get("value") is None or actual.get("unit") != forecast.get("unit"):
        return result
    surprise = actual["value"] - forecast["value"]
    if not math.isfinite(surprise):
        return result
    title = event.get("title", "").lower()
    interpretation = "uncertain"
    explanation = "The numeric surprise has no stable directional implication for this stock."
    if abs(surprise) < 1e-12:
        interpretation, explanation = "mixed", "The release matched consensus; details, revisions and policy context can still matter."
    elif any(word in title for word in ("cpi", "ppi", "pce", "inflation", "price index")):
        interpretation = "bearish" if surprise > 0 else "bullish"
        explanation = ("Inflation exceeded consensus, which may pressure rate-sensitive valuations if policy expectations tighten."
                       if surprise > 0 else "Inflation undershot consensus, which may support rate-sensitive valuations if growth remains resilient.")
    elif any(word in title for word in ("federal funds", "cash rate", "refinancing rate", "bank rate", "overnight rate")):
        interpretation = "bearish" if surprise > 0 else "mixed"
        explanation = "A policy-rate surprise can change discount rates and funding costs; growth and central-bank guidance determine its implications."
    elif any(word in title for word in ("employment", "payroll", "hourly earnings", "jobless", "unemployment", "adp")):
        interpretation = "mixed"
        explanation = "Labor surprises affect both demand and monetary-policy expectations; stronger employment is not automatically positive for equities."
    elif any(word in title for word in ("gdp", "retail sales", "pmi", "ism", "confidence")):
        interpretation = "mixed" if surprise > 0 else "bearish"
        explanation = "Growth below consensus can increase demand concerns; stronger growth may support sales while also changing rate expectations."
    result.update(value=surprise, unit="percentage points" if actual["unit"] == "percent" else "source units", interpretation=interpretation, explanation=explanation)
    # Normalize only against prior comparable forecast errors, not unrelated releases.
    errors = []
    for previous in history or []:
        if previous.get("id") == event.get("id") or previous.get("title") != event.get("title") or previous.get("currency") != event.get("currency"):
            continue
        previous_time = _dt(previous.get("scheduled_at"))
        known_time = _dt(previous.get("available_at"))
        revised_time = _dt(previous.get("last_updated"))
        if not previous_time or previous_time >= scheduled or not known_time or known_time >= scheduled or (revised_time and revised_time >= scheduled):
            continue
        old = economic_surprise(previous, now=scheduled)
        if old["value"] is not None and old["unit"] == result["unit"]:
            errors.append(old["value"])
    if len(errors) >= 10:
        scale = statistics.stdev(errors)
        if scale > 0:
            result["normalized"] = surprise / scale
            result["normalization"] = f"Surprise / sample SD of {len(errors)} prior comparable, timestamp-verified forecast errors."
    return result


def analyze_macro(events: list[dict], info: dict, horizon: str = "swing", now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    sector = str(info.get("sector") or "").lower()
    industry = str(info.get("industry") or "").lower()
    currency = str(info.get("currency") or "USD").upper()
    relevant_currencies = {currency, "USD"}
    relevant = [event for event in events if event.get("currency") in relevant_currencies and event.get("status") != "canceled"]
    upcoming, recent = [], []
    for event in relevant:
        stamp = _dt(event.get("scheduled_at"))
        if not stamp:
            continue
        copy = dict(event)
        copy["surprise"] = economic_surprise(event, relevant, now)
        if ("bank" in industry or "insurance" in industry or "financial" in sector) and copy["surprise"]["value"] is not None and any(word in event.get("title", "").lower() for word in ("cpi", "pce", "ppi", "inflation", "funds rate", "cash rate")):
            copy["surprise"]["interpretation"] = "mixed"
            copy["surprise"]["explanation"] = "For financial firms, inflation and policy surprises can change margins, funding costs and credit losses in opposing directions; a directional stock implication is not established."
        if now <= stamp <= now + timedelta(days=30):
            copy["seconds_until"] = int((stamp - now).total_seconds())
            upcoming.append(copy)
        elif now - timedelta(days=14) <= stamp < now:
            recent.append(copy)
    upcoming.sort(key=lambda event: event["scheduled_at"])
    recent.sort(key=lambda event: event["scheduled_at"], reverse=True)
    high = [event for event in upcoming if event.get("impact", "").lower() == "high"]
    risk_window = {"short": 1, "swing": 3, "long": 7}.get(horizon, 3)
    imminent = [event for event in high if event["seconds_until"] <= risk_window * 86400]
    impacts = []
    for event in high[:8]:
        title = event["title"].lower()
        if any(word in title for word in ("cpi", "pce", "fomc", "funds rate", "ppi", "inflation")):
            if "bank" in industry or "financial" in sector:
                mechanism = "Policy expectations can change funding costs, lending margins and credit demand; direction depends on the yield curve and deposit pricing."
            elif "technology" in sector or "software" in industry or "semiconductor" in industry:
                mechanism = "Discount-rate expectations can change growth-stock valuations; demand and earnings outcomes remain separate considerations."
            else:
                mechanism = "Rate expectations can affect financing costs, customer borrowing and valuation discount rates."
        elif any(word in title for word in ("employment", "payroll", "retail", "confidence", "gdp", "ism", "pmi")):
            mechanism = "Demand and credit conditions may change expected revenue or credit losses; stronger activity can also shift policy expectations."
        elif "oil" in title or "inventory" in title:
            mechanism = "Commodity supply signals may affect input costs or energy revenue; company-specific commodity exposure has not been verified."
        else:
            mechanism = "Broader risk sentiment or exchange rates may change; company-specific revenue exposure has not been verified."
        impacts.append({"event_id": event["id"], "title": event["title"], "scheduled_at": event["scheduled_at"], "source_url": event.get("source_url"), "evidence_type": "hypothesis", "explanation": mechanism, "company_evidence": f"Yahoo sector: {info.get('sector') or 'unavailable'}; industry: {info.get('industry') or 'unavailable'}. Geographic revenue breakdown unavailable."})
    measured = [event for event in recent if event["surprise"]["value"] is not None]
    directions = [event["surprise"]["interpretation"] for event in measured if event["surprise"]["interpretation"] in {"bullish", "bearish"}]
    directional = {"bullish": 1, "bearish": -1}
    score = None
    outlook = "Insufficient Data"
    confidence = 0.0
    if measured:
        # One grouped release component avoids counting CPI/core-CPI as independent votes.
        grouped = {}
        for event in measured:
            title = event["title"].lower()
            family = "inflation" if any(word in title for word in ("cpi", "ppi", "pce", "inflation", "price index")) else "policy" if "rate" in title else "activity"
            grouped.setdefault(family, []).append(directional.get(event["surprise"]["interpretation"], 0))
        averages = [sum(values) / len(values) for values in grouped.values()]
        score = round(5 + 2 * sum(averages) / len(averages), 2)
        confidence = min(0.55, 0.2 + 0.1 * len(grouped))
        outlook = "Bullish" if score >= 6 else "Bearish" if score <= 4 else "Mixed" if directions or any(event["surprise"]["interpretation"] == "mixed" for event in measured) else "Neutral"
    limitations = [
        "Imported calendar coverage is limited to supplied files; absence of an event is not evidence that none is scheduled.",
        "Actuals, revision history and release availability timestamps may not be included in weekly exports.",
        "Stock exposure links are sector-based hypotheses; geographic revenue, policy futures pricing and observed event-price reactions are not modeled.",
        "Upcoming event risk does not measure realized volatility or establish a cause of price moves.",
    ]
    if not measured:
        limitations.append("No comparable recent actual-versus-forecast releases: macro score withheld rather than assigning a favorable value.")
    return {
        "score": score, "confidence": confidence, "outlook": outlook,
        "signals": [f"{len(high)} imported high-impact events in the next 30 days; {len(imminent)} within the {risk_window}-day strategy window."] if events else ["No authorized economic calendar has been imported."],
        "limitations": limitations, "upcoming_events": upcoming, "recent_events": recent,
        "event_risk": {"level": "elevated" if imminent else "unknown" if not events else "no imported imminent high-impact event", "window_days": risk_window, "events": imminent, "warnings": [f"{event['title']} at {event['scheduled_at']}: entry and stop levels may be less reliable around the release; gaps can exceed modeled losses." for event in imminent]},
        "stock_impacts": impacts,
        "windows": {str(days): [event["id"] for event in upcoming if event["seconds_until"] <= days * 86400] for days in (1, 3, 7, 30)},
        "coverage": {"completeness_verified": False, "events_imported": len(events), "relevant_events": len(relevant), "recent_comparable_releases": len(measured), "first_scheduled_at": min((event["scheduled_at"] for event in relevant if event.get("scheduled_at")), default=None), "last_scheduled_at": max((event["scheduled_at"] for event in relevant if event.get("scheduled_at")), default=None)},
    }
