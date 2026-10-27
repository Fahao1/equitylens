"""Empirical barrier frequencies with explicit sample and chronological safeguards.

These are historical observations, never LLM probabilities or promised outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import NormalDist, mean, stdev

UTC = timezone.utc
MIN_SAMPLES = 30
STOP_ATR_BINS = (0, 1, 2, 3, 5, math.inf)
TARGET_R_BINS = (0, 1, 2, 3, 5, 10, math.inf)


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _time(value):
    if value is None:
        return None
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(UTC) if stamp.tzinfo else None
    except (TypeError, ValueError):
        return None


def wilson_interval(successes: int, observations: int, confidence: float = .95) -> list[float] | None:
    """Two-sided Wilson score interval, without continuity correction."""
    if isinstance(successes, bool) or isinstance(observations, bool) or not isinstance(successes, int) or not isinstance(observations, int) or not 0 <= successes <= observations or not 0 < confidence < 1:
        raise ValueError("Wilson interval requires integer 0 <= successes <= observations and confidence in (0,1)")
    if observations == 0:
        return None
    z = NormalDist().inv_cdf(.5 + confidence / 2)
    p = successes / observations
    denominator = 1 + z * z / observations
    center = (p + z * z / (2 * observations)) / denominator
    half = z * math.sqrt(p * (1 - p) / observations + z * z / (4 * observations * observations)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def _bin(value, edges):
    number = _finite(value)
    if number is None or number < edges[0]:
        return None
    for left, right in zip(edges[:-1], edges[1:]):
        if left <= number < right:
            return f"[{left},{right})"
    return None


def comparison_signature(item: dict) -> dict | None:
    """Bin boundaries are fixed in code before outcomes are observed."""
    strategy = item.get("strategy_id") or item.get("id")
    regime = item.get("regime")
    if isinstance(regime, dict):
        regime = regime.get("regime")
    horizon = item.get("horizon")
    holding = item.get("max_holding_bars")
    entry = _finite(item.get("entry_reference"))
    stop = _finite(item.get("stop"))
    atr = _finite(item.get("atr"))
    targets = item.get("targets") or []
    stop_atr = _finite(item.get("stop_atr"))
    target_1_r = _finite(item.get("target_1_r"))
    target_2_r = _finite(item.get("target_2_r"))
    if entry is not None and stop is not None and entry > stop:
        risk = entry - stop
        if stop_atr is None and atr is not None and atr > 0:
            stop_atr = risk / atr
        if target_1_r is None and targets and _finite(targets[0]) is not None:
            target_1_r = (targets[0] - entry) / risk
        if target_2_r is None and len(targets) > 1 and _finite(targets[1]) is not None:
            target_2_r = (targets[1] - entry) / risk
    stop_bin, target_bin = _bin(stop_atr, STOP_ATR_BINS), _bin(target_1_r, TARGET_R_BINS)
    if not strategy or not regime or not horizon or not isinstance(holding, int) or isinstance(holding, bool) or holding < 1 or stop_bin is None or target_bin is None:
        return None
    return {"strategy_id": str(strategy), "regime": str(regime), "horizon": str(horizon), "max_holding_bars": holding,
            "stop_atr_bin": stop_bin, "target_1_r_bin": target_bin, "target_2_r_bin": _bin(target_2_r, TARGET_R_BINS),
            "commission_bps": _finite(item.get("commission_bps")), "slippage_bps": _finite(item.get("slippage_bps"))}


def _same_primary(left, right):
    return left is not None and right is not None and all(left[key] == right[key] for key in ("strategy_id", "regime", "horizon", "max_holding_bars", "stop_atr_bin", "target_1_r_bin", "commission_bps", "slippage_bps"))


def _is_heldout(record):
    return record.get("partition") in {"out_of_sample", "walk_forward"} or record.get("out_of_sample") is True


def _observed(record, cutoff, target=1):
    outcome = record.get(f"target_{target}_outcome")
    closed = _time(record.get(f"target_{target}_closed_at") or (record.get("closed_at") if target == 1 else None))
    return outcome in {"target", "stop", "timeout"} and closed is not None and closed < cutoff


def calibration_summary(records: list[dict], cutoff: datetime, min_samples: int = MIN_SAMPLES) -> dict:
    """Walk forward: estimate each held-out label only from already closed samples."""
    heldout = sorted([row for row in records if _is_heldout(row) and _observed(row, cutoff)], key=lambda row: row.get("signal_time") or "")
    forecasts = []
    for row in heldout:
        decision = _time(row.get("signal_time"))
        signature = comparison_signature(row)
        if not decision or signature is None:
            continue
        prior = [past for past in records if _observed(past, decision)]
        comparable = [past for past in prior if _same_primary(comparison_signature(past), signature)]
        baseline = [past for past in prior if (past.get("strategy_id") or past.get("id")) == signature["strategy_id"] and past.get("horizon") == signature["horizon"] and past.get("max_holding_bars") == signature["max_holding_bars"] and _finite(past.get("commission_bps")) == signature["commission_bps"] and _finite(past.get("slippage_bps")) == signature["slippage_bps"]]
        if len(comparable) < min_samples or len(baseline) < min_samples:
            continue
        p = sum(past["target_1_outcome"] == "target" for past in comparable) / len(comparable)
        b = sum(past["target_1_outcome"] == "target" for past in baseline) / len(baseline)
        observed = int(row["target_1_outcome"] == "target")
        forecasts.append({"signal_time": row["signal_time"], "closed_at": row.get("closed_at"), "probability": p, "baseline": b,
                          "observed": observed, "training_samples": len(comparable), "brier_error": (p - observed) ** 2, "baseline_brier_error": (b - observed) ** 2})
    sufficient = len(forecasts) >= min_samples
    return {"status": "available" if sufficient else "Insufficient historical evidence", "prediction_count": len(forecasts), "min_predictions": min_samples,
            "brier_score": mean(row["brier_error"] for row in forecasts) if sufficient else None,
            "history_mean_baseline_brier": mean(row["baseline_brier_error"] for row in forecasts) if sufficient else None,
            "method": "Chronological held-out forecasts from strictly earlier closed comparable outcomes; baseline is expanding prior strategy/horizon mean. No fitted model or holdout parameter selection.",
            "forecasts": forecasts, "limitations": ["A small prediction count cannot establish calibration. Wilson intervals and Brier diagnostics do not correct all temporal dependence or regime shifts."]}



def _unique_records(records):
    unique = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (record.get("strategy_id") or record.get("id"), record.get("entry_time") or record.get("signal_time"))
        if not all(key):
            continue
        if key not in unique:
            unique[key] = record
        elif unique[key] is not None:
            old = unique[key]
            identity = lambda row: (row.get("target_1_outcome"), row.get("target_1_closed_at") or row.get("closed_at"), row.get("stop"), tuple(row.get("targets") or []), row.get("target_2_outcome"), row.get("target_2_closed_at"))
            if identity(old) != identity(record):
                unique[key] = None
            elif _is_heldout(record) and not _is_heldout(old):
                unique[key] = record
    return [row for row in unique.values() if row is not None]


def estimate_probabilities(records: list[dict], candidate: dict, as_of=None, min_samples: int = MIN_SAMPLES) -> dict:
    if not isinstance(min_samples, int) or isinstance(min_samples, bool) or min_samples < 1:
        raise ValueError("min_samples must be a positive integer")
    supplied_count = len(records)
    records = _unique_records(records)
    requested_cutoff = as_of or candidate.get("as_of")
    cutoff = _time(requested_cutoff) if requested_cutoff is not None else datetime.now(UTC)
    if cutoff is None:
        raise ValueError("Probability cutoff must be a valid timezone-aware timestamp")
    signature = comparison_signature(candidate)
    result = {
        "status": "Insufficient historical evidence", "sample_size": 0, "min_samples": min_samples,
        "as_of": cutoff.isoformat(), "validation_period": {"start": None, "end": None},
        "comparison": signature,
        "estimates": {"target_1_before_stop": None, "target_2_before_stop": None, "stop_before_target": None, "unresolved_within_horizon": None, "expected_return": None, "expected_holding_bars": None},
        "confidence_intervals": {"target_1_before_stop": None, "target_2_before_stop": None, "stop_before_target": None, "expected_return": None},
        "counts": {"target": 0, "stop": 0, "timeout": 0},
        "target_2": {"status": "Insufficient historical evidence", "sample_size": 0, "counts": {"target": 0, "stop": 0, "timeout": 0},
                     "conditional_after_target_1": {"status": "Insufficient historical evidence", "sample_size": 0, "estimate": None, "confidence_interval": None}},
        "metadata": {"type": "empirical historical frequency, not a calibrated forecast", "interval": "two-sided Wilson 95%, no continuity correction", "cohort": None, "denominator": "Target + stop + fully observed timeout. End-of-history censored observations are excluded.", "return_basis": "First-target full-exit strategy net return after modeled entry/exit costs; target2 is a separate hypothetical barrier follow-up.", "time_precision": "Outcome cutoff checks use completed-bar availability bounds, not session-start labels or assumed intraday fill times."},
        "limitations": ["Historical similarity does not establish future odds. Fixed bins can still contain materially different market conditions.", "Non-overlapping observation windows reduce shared-price dependence but do not make market observations independent.", "Daily OHLC ambiguity is resolved conservatively with stop-first intraday labeling; actual sequencing and liquidity may differ."],
    }
    if len(records) < supplied_count:
        result["limitations"].append("Duplicate, conflicting or undated record identities were excluded; repeated observations cannot increase sample size.")
    if signature is None:
        result["limitations"].append("Candidate lacks strategy, regime, horizon, holding limit or comparable risk-distance inputs; no frequency is substituted.")
        return result
    if signature["strategy_id"] == "fundamental_value":
        result["limitations"].append("Fundamental-value historical probabilities require verified point-in-time filings and valuations; current financial snapshots are excluded.")
        return result
    same = [record for record in records if _same_primary(comparison_signature(record), signature)]
    closed = [record for record in same if _observed(record, cutoff)]
    heldout = [record for record in closed if _is_heldout(record)]
    # Do not fill a short held-out sample with favorable in-sample observations.
    cohort = heldout if any(_is_heldout(record) for record in same) else closed
    result["metadata"]["cohort"] = "chronological held-out observations" if any(_is_heldout(record) for record in same) else "historical observations without an independent holdout label"
    if not any(_is_heldout(record) for record in same):
        result["limitations"].append("No independently labeled held-out cohort is supplied; any frequency is descriptive rather than out-of-sample validated.")
    result["sample_size"] = len(cohort)
    result["counts"] = {outcome: sum(record["target_1_outcome"] == outcome for record in cohort) for outcome in ("target", "stop", "timeout")}
    if cohort:
        result["validation_period"] = {"start": min(record.get("entry_time") or record["signal_time"] for record in cohort), "end": max(record.get("target_1_closed_at") or record["closed_at"] for record in cohort)}
    if len(cohort) >= min_samples:
        n, counts = len(cohort), result["counts"]
        result["status"] = "available"
        result["estimates"].update(target_1_before_stop=counts["target"] / n, stop_before_target=counts["stop"] / n, unresolved_within_horizon=counts["timeout"] / n)
        result["confidence_intervals"].update(target_1_before_stop=wilson_interval(counts["target"], n), stop_before_target=wilson_interval(counts["stop"], n))
        returns = [value for record in cohort if (value := _finite(record.get("net_return"))) is not None]
        holding = [value for record in cohort if (value := _finite(record.get("holding_bars"))) is not None]
        if len(returns) >= min_samples:
            average = mean(returns)
            result["estimates"]["expected_return"] = average
            if len(returns) > 1:
                radius = NormalDist().inv_cdf(.975) * stdev(returns) / math.sqrt(len(returns))
                result["confidence_intervals"]["expected_return"] = [average - radius, average + radius]
                result["limitations"].append("Mean net-return interval is a normal-approximation standard-error interval, not Wilson; heavy tails and serial dependence can understate uncertainty.")
        if len(holding) >= min_samples:
            result["estimates"]["expected_holding_bars"] = mean(holding)
    else:
        result["limitations"].append(f"Only {len(cohort)} comparable closed observations; at least {min_samples} are required. No default 50% probability is assigned.")
    second = [record for record in cohort if signature["target_2_r_bin"] is not None and (comparison_signature(record) or {}).get("target_2_r_bin") == signature["target_2_r_bin"] and _observed(record, cutoff, 2)]
    result["target_2"]["sample_size"] = len(second)
    result["target_2"]["counts"] = {outcome: sum(record["target_2_outcome"] == outcome for record in second) for outcome in ("target", "stop", "timeout")}
    if len(second) >= min_samples:
        result["target_2"]["status"] = "available"
        hits = result["target_2"]["counts"]["target"]
        result["estimates"]["target_2_before_stop"] = hits / len(second)
        result["confidence_intervals"]["target_2_before_stop"] = wilson_interval(hits, len(second))
    else:
        result["limitations"].append("Target2 has its own missing/censored/comparability count; a target1 exit is never treated as an observed continued trade.")
    continued = [record for record in second if record["target_1_outcome"] == "target"]
    conditional = result["target_2"]["conditional_after_target_1"]
    conditional["sample_size"] = len(continued)
    if len(continued) >= min_samples:
        hits = sum(record["target_2_outcome"] == "target" for record in continued)
        conditional.update(status="available", estimate=hits / len(continued), confidence_interval=wilson_interval(hits, len(continued)))
    result["calibration"] = calibration_summary(records, cutoff, min_samples)
    return result
