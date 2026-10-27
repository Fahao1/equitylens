"""Transparent scoring with explicit missing-weight coverage."""
from math import isfinite
import numpy as np
from app.utils import number

DEFAULT_WEIGHTS = {"financial": .25, "valuation": .20, "technical": .20, "news": .10, "macro": .10, "risk": .15}
LABELS = {"financial": "Financial health & growth", "valuation": "Valuation", "technical": "Technical analysis", "news": "Company news & earnings", "macro": "Macroeconomic outlook", "risk": "Risk & resilience"}


def risk_assessment(history, fundamentals):
    components, signals = [], []
    stability = number(fundamentals.get("risk_score"))
    if stability is not None:
        components.append((stability, .5, fundamentals.get("confidence", 0)))
        signals.append(f"Statement resilience subscore: {stability:.1f}/10; distinct from profitability/growth scoring.")
    closes = history["Close"].dropna() if "Close" in history else []
    if len(closes) >= 63:
        returns = closes.pct_change().dropna()
        vol = float(returns.tail(252).std(ddof=1) * np.sqrt(252))
        drawdown = float((closes.tail(252) / closes.tail(252).cummax() - 1).min())
        vol_score = float(np.interp(vol, [.10, .20, .35, .60, 1], [10, 8, 5, 2, 0]))
        dd_score = float(np.interp(abs(drawdown), [.05, .15, .30, .50, .8], [10, 8, 5, 2, 0]))
        components.append(((vol_score + dd_score) / 2, .5, min(1, len(closes) / 252)))
        signals.append(f"Annualized daily volatility {vol:.1%}; trailing available-window drawdown {drawdown:.1%}. These are historical measurements.")
    coverage = sum(w for _, w, _ in components)
    return {"score": round(sum(s*w for s,w,_ in components)/coverage, 2) if coverage else None,
            "confidence": round(sum(w*c for _,w,c in components), 3), "signals": signals,
            "limitations": ["Does not measure future gap, liquidity, concentration or tail risk."] + (["A resilience component is missing."] if coverage < 1 else [])}


def score_stock(categories, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    if set(weights) != set(DEFAULT_WEIGHTS) or any(not isfinite(v) or v < 0 for v in weights.values()) or abs(sum(weights.values())-1)>1e-6:
        raise ValueError("Weights must contain all six categories, be nonnegative and total 1.")
    rows, coverage = [], 0.
    for key, weight in weights.items():
        category = categories.get(key, {})
        score = number(category.get("score"))
        if score is not None and not 0 <= score <= 10:
            raise ValueError("Category scores must be between 0 and 10.")
        conf = min(1, max(0, number(category.get("confidence")) or 0))
        if score is not None:
            coverage += weight
        rows.append({"key": key, "label": LABELS[key], "score": score, "weight": weight,
                     "contribution": score * weight if score is not None else None, "confidence": conf})
    known = [row for row in rows if row["score"] is not None and row["weight"] > 0]
    overall = sum(row["contribution"] for row in known)/coverage if coverage else None
    # At least 60% of requested evidence and financial/technical evidence are required.
    enough = coverage >= .6 and categories.get("financial", {}).get("score") is not None and categories.get("technical", {}).get("score") is not None
    values = [r["score"] for r in known]
    agreement = max(.5, 1 - (float(np.std(values))/10 if values else 1))
    confidence = sum(r["confidence"]*r["weight"] for r in known)*agreement
    financial = categories.get("financial", {})
    stability = number(financial.get("risk_score"))
    quality_parts = [(number(financial.get("score")), .7), (stability, .3)]
    quality_coverage = sum(w for v,w in quality_parts if v is not None)
    quality = sum(v*w for v,w in quality_parts if v is not None)/quality_coverage if quality_coverage >= .7 else None
    return {"overall": round(overall, 2) if enough else None, "company_quality": round(quality, 2) if quality is not None else None,
            "confidence": round(confidence, 3), "coverage": round(coverage, 3), "agreement": round(agreement, 3), "categories": rows,
            "observed_weight_score": round(overall, 2) if overall is not None else None,
            "quality_confidence": round(financial.get("confidence", 0)*quality_coverage, 3),
            "formula": "Observed weighted sum / available weight. Original weighted contributions are shown; unavailable categories reduce coverage and confidence. Overall withheld below 60% coverage or absent financial/technical evidence.",
            "limitations": [f"Missing evidence: {', '.join(r['label'] for r in rows if r['score'] is None)}."] if coverage < 1 else []}
