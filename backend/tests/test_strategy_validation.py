"""Explicit synthetic observations test execution and inferential safeguards."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import math
import sys

import numpy as np
import pandas as pd
import pytest

from app.analysis.execution import calculate_execution
from app.analysis.probability import comparison_signature, estimate_probabilities, wilson_interval
from app.analysis.validation import _barrier, validate_strategies

UTC = timezone.utc


def prices(n=120, high=102, low=99, close=100):
    return pd.DataFrame({"Open": 100.0, "High": float(high), "Low": float(low), "Close": float(close), "Volume": 1000000}, index=pd.bdate_range("2024-01-02", periods=n, tz="UTC"))


@pytest.fixture
def causal_engine(monkeypatch):
    from app.analysis import features, strategies
    observed = []
    def build(history, benchmark=None):
        return history.copy()
    def snapshot(frame, index=-1):
        return {"as_of": frame.index[index].isoformat(), "bars": index + 1, "close": float(frame.iloc[index].Close), "atr": 2.0}
    def evaluate(snapshot, context, config):
        assert context["historical"] is True
        assert context["fundamentals"] == context["valuation"] == context["macro"] == {}
        observed.append((snapshot["as_of"], snapshot["close"], config["capital"]))
        execution = calculate_execution([99, 101], 95, [115, 125], config)
        permitted = snapshot["bars"] in config.get("signal_bars", [10])
        eligible = permitted and execution["valid"] and execution["risk_qualified"]
        return [{**execution, "id": "trend_following", "status": "eligible" if eligible else "wait", "eligible": eligible,
                 "regime": "Strong bullish trend", "atr": snapshot["atr"], "horizon": config["horizon"], "max_holding_bars": config["max_holding_bars"]}]
    monkeypatch.setattr(features, "build_features", build)
    monkeypatch.setattr(features, "snapshot_at", snapshot)
    monkeypatch.setattr(strategies, "evaluate_strategies", evaluate)
    monkeypatch.setitem(sys.modules, "app.analysis.regime", SimpleNamespace(classify_regime=lambda snapshot: {"regime": "Strong bullish trend"}))
    return observed


def config(**changes):
    return {"strategy_ids": ["trend_following"], "warmup_bars": 10, "max_holding_bars": 5, "min_samples": 30, "commission_bps": 0, "slippage_bps": 0, **changes}


def test_next_open_entry_target_exit_and_cash_reconcile(causal_engine):
    frame = prices()
    frame.iloc[11, frame.columns.get_loc("High")] = 116
    frame.iloc[13, frame.columns.get_loc("High")] = 126
    result = validate_strategies(frame, config())["strategies"]["trend_following"]
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["signal_time"] == (frame.index[9] + pd.Timedelta(days=1)).isoformat()
    assert trade["signal_session"] == frame.index[9].isoformat()
    assert trade["entry_time"] == frame.index[10].isoformat()
    assert trade["exit_time"] == (frame.index[11] + pd.Timedelta(days=1)).isoformat()
    assert trade["exit_session"] == frame.index[11].isoformat()
    assert trade["target_2_hypothetical"] is True
    assert trade["target_2_closed_at"] == (frame.index[13] + pd.Timedelta(days=1)).isoformat()
    assert trade["excursion_bounds"]["mfe"] == "lower bound"
    assert "exact opening fill timestamp unavailable" in trade["time_precision"]["entry_time"]
    assert trade["exit"] == 115
    assert trade["target_1_outcome"] == "target"
    assert trade["target_2_outcome"] == "target"
    assert trade["holding_bars"] == 2
    assert trade["mfe"] == pytest.approx(.15)  # Exit-bar high116 is not assumed before exit.
    assert result["metrics"]["ending_equity"] == pytest.approx(10000 + trade["pnl"])
    assert trade["initial_risk"] <= 100
    worst = calculate_execution([99, 101], 95, [115, 125], {"capital": 10000, "risk_per_trade": .01, "commission_bps": 0, "slippage_bps": 0})
    improved = calculate_execution([100, 100], 95, [115, 125], {"capital": 10000, "risk_per_trade": .01, "commission_bps": 0, "slippage_bps": 0})
    assert improved["position_size"] > worst["position_size"]
    assert trade["shares"] == worst["position_size"]
    assert result["status"] == "Insufficient historical evidence"


def test_no_implicit_later_limit_fill_when_next_open_outside_zone(causal_engine):
    frame = prices()
    frame.iloc[10, frame.columns.get_loc("Open")] = 102
    frame.iloc[10, frame.columns.get_loc("High")] = 103
    result = validate_strategies(frame, config())["strategies"]["trend_following"]
    assert result["trades"] == []
    assert result["skipped_entries"]["outside_entry_zone"] == 1


def test_both_barriers_same_bar_stop_first_and_gap_worse_fill(causal_engine):
    frame = prices()
    frame.iloc[11, frame.columns.get_loc("High")] = 130
    frame.iloc[11, frame.columns.get_loc("Low")] = 90
    first = validate_strategies(frame, config())["strategies"]["trend_following"]["trades"][0]
    assert first["exit"] == 95
    assert first["target_1_outcome"] == first["target_2_outcome"] == "stop"
    assert "stop first" in first["exit_reason"]
    assert first["mfe"] <= .02 + 1e-12  # The later high130 is not booked as a held excursion.
    frame.iloc[11] = [90, 96, 89, 94, 1000000]
    gap = validate_strategies(frame, config())["strategies"]["trend_following"]["trades"][0]
    assert gap["exit"] == 90
    assert gap["pnl"] < -100


def test_timeout_is_observed_but_boundary_liquidation_is_censored(causal_engine):
    frame = prices()
    observed = validate_strategies(frame, config())["strategies"]["trend_following"]
    assert observed["trades"][0]["target_1_outcome"] == "timeout"
    assert observed["trades"][0]["holding_bars"] == 5
    assert observed["trades"][0]["censored"] is False
    short = validate_strategies(frame.iloc[:13], config())["strategies"]["trend_following"]
    assert short["trades"][0]["target_1_outcome"] == "censored"
    assert short["metrics"]["censored_trades"] == 1


def test_t2_virtual_followup_and_statistical_windows_do_not_overlap(causal_engine):
    frame = prices(160, high=116)
    result = validate_strategies(frame, config(signal_bars=list(range(10, 160))))["strategies"]["trend_following"]
    assert all(trade["holding_bars"] == 1 for trade in result["trades"])
    records = result["probability_records"]
    assert len(records) < len(result["trades"])
    for previous, following in zip(records, records[1:]):
        assert following["observation_start_index"] > previous["observation_end_index"]
    assert any(record["target_2_outcome"] == "timeout" for record in records)
    assert all(record["target_1_outcome"] == "target" for record in records)


def test_future_prices_do_not_change_earlier_equity_or_signals(causal_engine):
    frame = prices(180, high=116)
    changed = frame.copy()
    changed.loc[changed.index[100]:, ["Open", "High", "Low", "Close"]] *= 2
    left = validate_strategies(frame, config(signal_bars=list(range(10, 180))))
    right = validate_strategies(changed, config(signal_bars=list(range(10, 180))))
    cutoff = frame.index[100].isoformat()
    def prior(result):
        return [row for row in result["strategies"]["trend_following"]["equity_curve"] if row["date"] < cutoff]
    assert prior(left) == prior(right)
    assert left["methodology"]["fundamentals_used"] is False
    assert left["methodology"]["macro_used"] is False


def test_oos_purges_crossing_windows_sensitivity_training_only_and_benchmark(causal_engine):
    frame = prices(400, high=116)
    result = validate_strategies(frame, config(signal_bars=list(range(10, 400))), benchmark=frame)
    strategy = result["strategies"]["trend_following"]
    assert len(strategy["walk_forward"]) == 3
    assert strategy["out_of_sample"]["training_samples_purged"] >= 0
    split = int(len(frame) * .7)
    training = [row for row in strategy["probability_records"] if row["partition"] == "training"]
    assert all(row["observation_end_index"] < split for row in training)
    assert all(row["scope"] == "training_only" for row in strategy["sensitivity"])
    assert len(strategy["sensitivity"]) == 5
    assert result["benchmark"]["benchmark_return"] == 0
    assert result["strategies"]["fundamental_value"]["status"] == "Insufficient historical evidence"
    json.dumps(result, allow_nan=False)


def test_transaction_costs_reduce_returns_and_hurdle_changes_shared_eligibility(causal_engine):
    frame = prices(120, high=116)
    free = validate_strategies(frame, config())["strategies"]["trend_following"]
    costly = validate_strategies(frame, config(commission_bps=10, slippage_bps=10))["strategies"]["trend_following"]
    assert costly["trades"][0]["net_return"] < free["trades"][0]["net_return"]
    assert costly["trades"][0]["commission"] > 0
    assert costly["trades"][0]["initial_risk"] <= 100
    high_hurdle = validate_strategies(frame, config(min_reward_risk=4))["strategies"]["trend_following"]
    assert high_hurdle["trades"] == []


def test_barrier_opening_gap_known_before_later_intraday_extreme():
    frame = prices(10)
    frame.iloc[1] = [120, 125, 90, 100, 1000]
    result = _barrier(frame, 1, 95, 115, 5, len(frame))
    assert result["outcome"] == "target"
    assert result["exit_price"] == 115


@pytest.mark.parametrize("changes", [{"capital": 0}, {"risk_per_trade": .2}, {"min_samples": 0}, {"commission_bps": math.inf}, {"max_holding_bars": 2.5}])
def test_bad_config_rejected(causal_engine, changes):
    with pytest.raises(ValueError):
        validate_strategies(prices(), config(**changes))


def record(index, outcome="target", partition="out_of_sample", **changes):
    base = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=index * 10)
    return {"strategy_id": "trend_following", "regime": "Strong bullish trend", "horizon": "swing", "max_holding_bars": 5,
            "entry_reference": 101, "stop": 95, "targets": [115, 125], "atr": 2,
            "signal_time": base.isoformat(), "entry_time": (base + timedelta(days=1)).isoformat(),
            "closed_at": (base + timedelta(days=3)).isoformat(), "target_1_closed_at": (base + timedelta(days=3)).isoformat(),
            "target_2_closed_at": (base + timedelta(days=5)).isoformat(), "target_1_outcome": outcome, "target_2_outcome": outcome,
            "partition": partition, "net_return": .1 if outcome == "target" else -.05 if outcome == "stop" else 0,
            "holding_bars": 3, **changes}


def candidate(**changes):
    return {"id": "trend_following", "regime": "Strong bullish trend", "horizon": "swing", "max_holding_bars": 5,
            "entry_reference": 101, "stop": 95, "targets": [115, 125], "atr": 2, **changes}


def test_wilson_known_reference_and_extreme_cases():
    assert wilson_interval(50, 100) == pytest.approx([.4038315303659956, .5961684696340044])
    assert wilson_interval(0, 10) == pytest.approx([0, .2775327998628892])
    assert wilson_interval(10, 10) == pytest.approx([.7224672001371107, 1])
    assert wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_probability_minimum_n_missing_and_no_arbitrary_half():
    small = estimate_probabilities([record(i) for i in range(29)], candidate(), as_of="2030-01-01T00:00:00Z")
    assert small["sample_size"] == 29
    assert small["status"] == "Insufficient historical evidence"
    assert small["estimates"]["target_1_before_stop"] is None
    assert small["confidence_intervals"]["target_1_before_stop"] is None
    missing = estimate_probabilities([], candidate(atr=None), as_of="2030-01-01T00:00:00Z")
    assert missing["comparison"] is None


def test_timeouts_in_denominator_censored_excluded_and_t2_has_own_n():
    rows = [record(i, "target" if i < 10 else "stop" if i < 20 else "timeout", target_2_outcome=None) for i in range(30)]
    rows += [record(31, "censored")]
    result = estimate_probabilities(rows, candidate(), as_of="2030-01-01T00:00:00Z")
    assert result["status"] == "available"
    assert result["sample_size"] == 30
    assert result["estimates"]["target_1_before_stop"] == pytest.approx(1 / 3)
    assert result["estimates"]["stop_before_target"] == pytest.approx(1 / 3)
    assert result["estimates"]["unresolved_within_horizon"] == pytest.approx(1 / 3)
    assert result["estimates"]["expected_return"] == pytest.approx((10 * .1 - 10 * .05) / 30)
    assert result["estimates"]["target_2_before_stop"] is None
    assert result["target_2"]["sample_size"] == 0


def test_future_and_same_cutoff_outcomes_excluded_and_bins_are_fixed():
    rows = [record(i) for i in range(30)]
    cutoff = rows[-1]["closed_at"]
    result = estimate_probabilities(rows, candidate(), as_of=cutoff)
    assert result["sample_size"] == 29
    assert result["estimates"]["target_1_before_stop"] is None
    assert comparison_signature(candidate())["stop_atr_bin"] == "[3,5)"
    assert estimate_probabilities(rows, candidate(atr=10), as_of="2030-01-01T00:00:00Z")["sample_size"] == 0
    assert estimate_probabilities(rows, candidate(regime="Sideways consolidation"), as_of="2030-01-01T00:00:00Z")["sample_size"] == 0


def test_short_holdout_not_filled_with_in_sample_data_and_value_abstains():
    rows = [record(i, partition="training") for i in range(50)] + [record(60)]
    result = estimate_probabilities(rows, candidate(), as_of="2030-01-01T00:00:00Z")
    assert result["sample_size"] == 1
    assert result["status"] == "Insufficient historical evidence"
    value = estimate_probabilities(rows, candidate(id="fundamental_value"), as_of="2030-01-01T00:00:00Z")
    assert value["status"] == "Insufficient historical evidence"
    assert "point-in-time" in " ".join(value["limitations"])


def test_walk_forward_brier_uses_only_earlier_closed_outcomes():
    rows = [record(i, "target" if i % 2 else "stop", partition="training" if i < 40 else "out_of_sample") for i in range(80)]
    result = estimate_probabilities(rows, candidate(), as_of="2030-01-01T00:00:00Z")
    calibration = result["calibration"]
    assert calibration["status"] == "available"
    assert calibration["prediction_count"] == 40
    assert calibration["brier_score"] is not None
    first = calibration["forecasts"][0]
    assert first["training_samples"] == 40
    assert first["probability"] == .5
    changed = [dict(row) for row in rows]
    changed[-1]["target_1_outcome"] = "target"
    after = estimate_probabilities(changed, candidate(), as_of="2030-01-01T00:00:00Z")["calibration"]
    assert after["forecasts"][0] == first
    assert after["forecasts"][-1]["probability"] == calibration["forecasts"][-1]["probability"]


def test_duplicate_observations_cannot_create_artificial_probability_sample():
    rows = [record(i) for i in range(20)]
    result = estimate_probabilities(rows + rows, candidate(), as_of="2030-01-01T00:00:00Z")
    assert result["sample_size"] == 20
    assert result["status"] == "Insufficient historical evidence"
    conflict = [record(0, "stop"), *rows]
    assert estimate_probabilities(conflict, candidate(), as_of="2030-01-01T00:00:00Z")["sample_size"] == 19


def test_invalid_or_naive_cutoff_fails_closed():
    for cutoff in ("not-a-date", "2021-01-01", datetime(2021, 1, 1)):
        with pytest.raises(ValueError, match="timezone-aware"):
            estimate_probabilities([record(0)], candidate(), as_of=cutoff)


def test_cost_assumptions_cannot_silently_mix_probability_cohorts():
    rows = [record(i, commission_bps=5, slippage_bps=5) for i in range(30)]
    result = estimate_probabilities(rows, candidate(commission_bps=10, slippage_bps=5), as_of="2030-01-01T00:00:00Z")
    assert result["sample_size"] == 0


def test_target2_has_separate_unconditional_and_conditional_denominators():
    rows = [record(i, "target" if i < 30 else "stop", target_2_outcome="target" if i < 15 else "timeout" if i < 30 else "stop") for i in range(60)]
    result = estimate_probabilities(rows, candidate(), as_of="2030-01-01T00:00:00Z")
    assert result["estimates"]["target_2_before_stop"] == .25
    conditional = result["target_2"]["conditional_after_target_1"]
    assert conditional["sample_size"] == 30
    assert conditional["estimate"] == .5
    assert conditional["status"] == "available"


def test_daily_outcome_uses_bar_end_and_is_invisible_to_intraday_cutoff():
    frame = prices(1, high=116)
    frame["Bar End"] = [pd.Timestamp("2024-01-02T21:00:00Z")]
    outcome = _barrier(frame, 0, 95, 115, 5, 1)
    assert outcome["closed_at"] == "2024-01-02T21:00:00+00:00"
    observation = record(0, signal_time="2024-01-01T21:00:00Z", entry_time=frame.index[0].isoformat(), target_1_closed_at=outcome["closed_at"], closed_at=outcome["closed_at"], target_2_closed_at="2024-01-04T21:00:00Z")
    before = estimate_probabilities([observation], candidate(), as_of="2024-01-02T12:00:00Z", min_samples=1)
    exact = estimate_probabilities([observation], candidate(), as_of="2024-01-02T21:00:00Z", min_samples=1)
    after = estimate_probabilities([observation], candidate(), as_of="2024-01-02T21:00:01Z", min_samples=1)
    assert before["sample_size"] == exact["sample_size"] == 0
    assert before["estimates"]["target_1_before_stop"] is None
    assert after["sample_size"] == 1
    assert after["estimates"]["target_1_before_stop"] == 1
    assert after["estimates"]["target_2_before_stop"] is None


def test_fallback_next_daily_boundary_and_t2_timeout_censor_availability():
    frame = prices(4)
    first = _barrier(frame, 0, 95, 115, 2, 4)
    second = _barrier(frame, 0, 95, 125, 5, 4)
    assert first["outcome"] == "timeout"
    assert first["closed_at"] == (frame.index[1] + pd.Timedelta(days=1)).isoformat()
    assert second["outcome"] == "censored"
    assert second["closed_at"] == (frame.index[-1] + pd.Timedelta(days=1)).isoformat()


def test_signal_availability_preserves_separate_session_label(causal_engine):
    frame = prices()
    frame["Bar End"] = frame.index + pd.Timedelta(hours=21)
    result = validate_strategies(frame, config())["strategies"]["trend_following"]
    trade = result["trades"][0]
    assert trade["signal_time"] == frame["Bar End"].iloc[9].isoformat()
    assert trade["signal_session"] == frame.index[9].isoformat()
    assert trade["exit_time"] == frame["Bar End"].iloc[14].isoformat()
    assert trade["exit_session"] == frame.index[14].isoformat()
    assert "bounds" in result["excursion_method"]["label"]


def test_daily_completion_must_follow_session_label(causal_engine):
    frame = prices()
    frame["Bar End"] = frame.index - pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="availability"):
        validate_strategies(frame, config())
