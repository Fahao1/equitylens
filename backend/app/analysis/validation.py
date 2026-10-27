"""Validate the same shared technical strategies used by current research setups.

Daily long-only execution; current financial/news/macro snapshots never enter past
signals. Statistical barrier cohorts are separate from the actual T1 trade ledger.
"""
from __future__ import annotations

import math
from statistics import mean

import numpy as np
import pandas as pd

from app.analysis.backtest import _performance
from app.analysis.execution import calculate_execution
from app.providers.bar_times import bar_availability

TECHNICAL_STRATEGIES = ("trend_following", "breakout", "mean_reversion")
ALL_STRATEGIES = (*TECHNICAL_STRATEGIES, "fundamental_value")


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _prices(history: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close"]
    if not all(column in history for column in required):
        raise ValueError("Strategy validation requires Open, High, Low and Close")
    frame = history.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True)
    frame["Bar End"] = bar_availability(frame)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    if frame.index.has_duplicates or frame.index.isna().any():
        raise ValueError("Price timestamps must be unique and valid")
    if frame["Bar End"].isna().any() or (pd.DatetimeIndex(frame["Bar End"]) <= frame.index).any():
        raise ValueError("Daily bar availability must be valid and later than its session label")
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("OHLC prices must be finite and positive; missing bars are not interpolated")
    if ((frame.High < frame[["Open", "Low", "Close"]].max(axis=1)) | (frame.Low > frame[["Open", "High", "Close"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC values")
    # Keep Yahoo split-adjusted price units; do not retroactively use dividend factors.
    if "Stock Splits" in frame:
        for index in range(1, len(frame)):
            split = _number(frame["Stock Splits"].iloc[index])
            if split and split != 1:
                discontinuity = frame.Close.iloc[index - 1] / frame.Open.iloc[index]
                if abs(discontinuity / split - 1) < .12 and abs(discontinuity - 1) > .3:
                    raise ValueError("Raw split discontinuity detected; supply verified split-adjusted OHLC")
    return frame


def _settings(config):
    settings = {"capital": 10000, "risk_per_trade": .01, "commission_bps": 5, "slippage_bps": 5,
                "horizon": "swing", "risk_tolerance": "medium", "min_reward_risk": 2, "max_holding_bars": 20,
                "min_samples": 30, "warmup_bars": 200, **config}
    if "starting_capital" in config:
        settings["capital"] = config["starting_capital"]
    bounds = {"capital": (0, 1e12), "risk_per_trade": (0, .05), "commission_bps": (0, 100), "slippage_bps": (0, 100), "min_reward_risk": (1, 10)}
    for key, (low, high) in bounds.items():
        value = _number(settings[key])
        if isinstance(settings[key], bool) or value is None or not low <= value <= high or (key in {"capital", "risk_per_trade"} and value <= 0):
            raise ValueError(f"Invalid {key} for strategy validation")
        settings[key] = value
    for key, low, high in (("max_holding_bars", 1, 252), ("min_samples", 1, 10000), ("warmup_bars", 1, 500)):
        if not isinstance(settings[key], int) or isinstance(settings[key], bool) or not low <= settings[key] <= high:
            raise ValueError(f"{key} must be an integer in [{low},{high}]")
    if settings["horizon"] not in {"short", "swing", "long"}:
        raise ValueError("Unknown investment horizon")
    return settings


def _barrier(frame, entry_index, stop, target, holding, end):
    """Static hypothetical barrier follow-up; it does not keep an exited T1 trade open."""
    if target is None:
        return {"outcome": None, "closed_at": None, "exit_index": None, "exit_price": None, "reason": "target not supplied"}
    limit = min(end, entry_index + holding)
    for index in range(entry_index, limit):
        row = frame.iloc[index]
        opening, low, high = float(row.Open), float(row.Low), float(row.High)
        stamp = bar_availability(frame.iloc[index:index + 1])[0].isoformat()
        if opening <= stop:
            return {"outcome": "stop", "closed_at": stamp, "exit_index": index, "exit_price": opening, "reason": "opening gap through stop"}
        if opening >= target:
            return {"outcome": "target", "closed_at": stamp, "exit_index": index, "exit_price": target, "reason": "opening gap beyond target; target-price fill"}
        # With an opening price between barriers, intraday ordering is unknowable.
        if low <= stop:
            return {"outcome": "stop", "closed_at": stamp, "exit_index": index, "exit_price": stop, "reason": "both barriers touched: stop first" if high >= target else "stop touched"}
        if high >= target:
            return {"outcome": "target", "closed_at": stamp, "exit_index": index, "exit_price": target, "reason": "target touched"}
    full_horizon = entry_index + holding <= end
    final = limit - 1
    return {"outcome": "timeout" if full_horizon else "censored", "closed_at": bar_availability(frame.iloc[final:final + 1])[0].isoformat() if final >= entry_index else None,
            "exit_index": final if final >= entry_index else None, "exit_price": float(frame.iloc[final].Close) if final >= entry_index else None,
            "reason": "maximum holding horizon" if full_horizon else "evaluation boundary; incomplete outcome"}


def _context(snapshot, regime):
    return {"regime": regime, "historical": True, "fundamentals": {}, "valuation": {}, "macro": {}, "earnings": {},
            "timeframes": {}, "timeframe_alignment": None, "stale": False, "incomplete": False}


def _simulate(frame, snapshots, regimes, settings, strategy_id, start, end, benchmark=None, partition="full_sample"):
    from app.analysis.strategies import evaluate_strategies
    initial = settings["capital"]
    fee, slip = settings["commission_bps"] / 10000, settings["slippage_bps"] / 10000
    cash, position = initial, None
    trades, curve, records = [], [], []
    ignored_entries = {"outside_entry_zone": 0, "unaffordable_or_invalid": 0}
    statistical_embargo_until = -1
    bench = _benchmark(frame, settings, start, end, benchmark)

    def close_position(index, outcome):
        nonlocal cash, position
        row = frame.iloc[index]
        raw_exit = outcome["exit_price"]
        execution = raw_exit * (1 - slip)
        proceeds = execution * (1 - fee)
        pnl = position["shares"] * (proceeds - position["entry_outlay"])
        net_return = proceeds / position["entry_outlay"] - 1
        # Exit-bar path is unsequenced unless liquidation occurs at its closing price.
        if outcome["outcome"] in {"timeout", "censored"}:
            position["lowest"] = min(position["lowest"], float(row.Low))
            position["highest"] = max(position["highest"], float(row.High))
        else:
            position["lowest"] = min(position["lowest"], raw_exit)
            position["highest"] = max(position["highest"], raw_exit)
        trade = {"strategy_id": strategy_id, "signal_time": position["signal_time"], "entry_time": position["entry_time"], "exit_time": outcome["closed_at"],
                 "signal_session": frame.index[position["entry_index"] - 1].isoformat(), "entry_session": position["entry_time"], "exit_session": frame.index[index].isoformat(),
                 "time_precision": {"signal_time": "completed-bar availability", "entry_time": "session label; exact opening fill timestamp unavailable", "exit_time": "bar availability bound; exact fill timestamp unavailable"},
                 "regime": position["regime"], "horizon": settings["horizon"], "entry": position["entry"], "entry_reference": position["entry_reference"],
                 "exit": execution, "stop": position["stop"], "targets": position["targets"], "shares": position["shares"],
                 "target_1_outcome": outcome["outcome"], "target_1_closed_at": outcome["closed_at"],
                 "target_2_outcome": position["second"]["outcome"], "target_2_closed_at": position["second"]["closed_at"],
                 "target_2_hypothetical": len(position["targets"]) > 1,
                 "pnl": pnl, "return": net_return, "net_return": net_return,
                 "holding_bars": index - position["entry_index"] + 1,
                 "mae": min(0, position["lowest"] / position["entry"] - 1), "mfe": max(0, position["highest"] / position["entry"] - 1),
                 "exit_reason": outcome["reason"], "commission": position["shares"] * (position["entry"] * fee + execution * fee),
                 "initial_risk": position["shares"] * position["unit_risk"], "r_multiple": pnl / (position["shares"] * position["unit_risk"]),
                 "censored": outcome["outcome"] == "censored",
                 "excursion_bounds": {"mae": "signed upper bound; adverse magnitude lower bound", "mfe": "lower bound",
                                      "method": "Known completed held bars and exit execution point; unsequenced exit-bar extremes are excluded unless exiting at its close."}}
        trades.append(trade)
        if position["statistical_sample"]:
            record = {**{key: trade[key] for key in ("strategy_id", "signal_time", "entry_time", "regime", "horizon", "entry_reference", "stop", "targets", "net_return", "holding_bars")},
                      "atr": position["atr"], "max_holding_bars": position["holding_limit"], "partition": partition,
                      "commission_bps": settings["commission_bps"], "slippage_bps": settings["slippage_bps"],
                      "closed_at": trade["exit_time"], "time_precision": "completed-bar availability; exact intraday resolution unavailable",
                      "signal_session": trade["signal_session"], "entry_session": trade["entry_session"], "exit_session": trade["exit_session"],
                      "target_2_hypothetical": trade["target_2_hypothetical"], "target_1_outcome": outcome["outcome"], "target_1_closed_at": outcome["closed_at"],
                      "target_2_outcome": position["second"]["outcome"], "target_2_closed_at": position["second"]["closed_at"],
                      "observation_end_index": position["entry_index"] + position["holding_limit"] - 1,
                      "observation_start_index": position["entry_index"],
                      "outcome_method": "Static original stop; T1 actual full exit; T2 independent hypothetical follow-up through original holding horizon."}
            records.append(record)
        cash += position["shares"] * proceeds
        position = None

    for index in range(start, end):
        row = frame.iloc[index]
        if position is None:
            snapshot = snapshots[index - 1]
            config = {**settings, "capital": cash, "existing_shares": 0, "cost_basis": None}
            setups = evaluate_strategies(snapshot, _context(snapshot, regimes[index - 1]), config)
            setup = next((item for item in setups if item.get("id") == strategy_id), None)
            if setup and setup.get("eligible") and setup.get("status") == "eligible":
                zone = setup.get("entry_zone") or []
                stop = _number(setup.get("stop"))
                targets = [_number(value) for value in (setup.get("targets") or [])]
                opening = float(row.Open)
                if len(zone) != 2 or any(_number(value) is None for value in zone) or not zone[0] <= opening <= zone[1]:
                    ignored_entries["outside_entry_zone"] += 1
                elif stop is None or stop <= 0 or stop >= opening or not targets or targets[0] is None or targets[0] <= opening:
                    ignored_entries["unaffordable_or_invalid"] += 1
                else:
                    actual = calculate_execution([opening, opening], stop, targets, config)
                    entry = actual.get("entry_reference", opening) * (1 + slip)
                    entry_outlay = actual.get("entry_outlay_per_share", 0)
                    unit_risk = actual.get("risk_per_share", 0)
                    quantity = actual.get("position_size", 0) if actual["valid"] and actual["risk_qualified"] else 0
                    # The shared setup already passed worst-zone cost-adjusted eligibility.
                    # Retain its conservative whole-share cap even on a better opening fill.
                    setup_size = _number(setup.get("position_size"))
                    if setup_size is not None:
                        quantity = min(quantity, int(setup_size))
                    if quantity > 0:
                        holding = int(setup.get("max_holding_bars") or settings["max_holding_bars"])
                        first = _barrier(frame, index, stop, targets[0], holding, end)
                        second = _barrier(frame, index, stop, targets[1] if len(targets) > 1 else None, holding, end)
                        selected = index > statistical_embargo_until
                        if selected:
                            statistical_embargo_until = index + holding - 1
                        position = {"entry_index": index, "entry": entry, "entry_outlay": entry_outlay, "shares": quantity,
                                    "stop": stop, "targets": targets, "unit_risk": unit_risk, "holding_limit": holding,
                                    "signal_time": bar_availability(frame.iloc[index - 1:index])[0].isoformat(), "entry_time": frame.index[index].isoformat(),
                                    "regime": setup.get("regime") or regimes[index - 1].get("regime"), "atr": snapshot.get("atr"),
                                    "entry_reference": setup.get("entry_reference") or zone[1],
                                    "lowest": entry, "highest": entry, "first": first, "second": second, "statistical_sample": selected}
                        cash -= quantity * entry_outlay
                    else:
                        ignored_entries["unaffordable_or_invalid"] += 1
        if position:
            if index == position["first"]["exit_index"]:
                close_position(index, position["first"])
            else:
                position["lowest"] = min(position["lowest"], float(row.Low))
                position["highest"] = max(position["highest"], float(row.High))
        curve.append({"date": frame.index[index].isoformat(), "equity": cash + (position["shares"] * float(row.Close) if position else 0),
                      "buy_and_hold": bench["equity_curve"][index - start]["buy_and_hold"], "benchmark": bench["equity_curve"][index - start]["benchmark"]})
    metrics = _performance(curve, trades, initial)
    metrics.update(expectancy=mean(trade["pnl"] for trade in trades) if trades else None,
                   expectancy_return=mean(trade["net_return"] for trade in trades) if trades else None,
                   expectancy_r=mean(trade["r_multiple"] for trade in trades) if trades else None,
                   average_holding_bars=mean(trade["holding_bars"] for trade in trades) if trades else None,
                   average_mae=mean(trade["mae"] for trade in trades) if trades else None,
                   average_mfe=mean(trade["mfe"] for trade in trades) if trades else None,
                   buy_and_hold_return=bench["buy_and_hold_return"], benchmark_return=bench["benchmark_return"],
                   completed_horizon_trades=sum(not trade["censored"] for trade in trades), censored_trades=sum(trade["censored"] for trade in trades),
                   average_gain_percent=mean(trade["net_return"] for trade in trades if trade["pnl"] > 0) if any(trade["pnl"] > 0 for trade in trades) else None,
                   average_loss_percent=mean(trade["net_return"] for trade in trades if trade["pnl"] < 0) if any(trade["pnl"] < 0 for trade in trades) else None)
    return {"sample_size": len(trades), "metrics": metrics, "equity_curve": curve, "trades": trades, "probability_records": records, "skipped_entries": ignored_entries,
            "excursion_method": {"label": "Known-path excursion bounds, not exact realized excursions", "mae": "signed upper bound; adverse magnitude lower bound", "mfe": "lower bound",
                                 "description": "Completed held bars and execution points only; unsequenced exit-bar extremes are excluded unless liquidation occurs at the close."}}


def _benchmark(frame, settings, start, end, benchmark):
    initial, fee, slip = settings["capital"], settings["commission_bps"] / 10000, settings["slippage_bps"] / 10000
    if end <= start:
        return {"buy_and_hold_return": None, "benchmark_return": None, "equity_curve": []}
    def holding(values):
        opening = float(values.iloc[0].Open)
        opening = round(opening, 2 if opening >= 1 else 6)
        quantity = math.floor(initial / (opening * (1 + slip) * (1 + fee)))
        cash = initial - quantity * opening * (1 + slip) * (1 + fee)
        curve = cash + quantity * values.Close.to_numpy(dtype=float)
        curve[-1] = cash + quantity * float(values.iloc[-1].Close) * (1 - slip) * (1 - fee)
        return curve
    dates = frame.index[start:end]
    buyhold = holding(frame.iloc[start:end])
    index_values = None
    if benchmark is not None and not benchmark.empty:
        aligned = benchmark.reindex(dates)
        if not aligned[["Open", "Close"]].isna().any().any():
            index_values = holding(aligned)
    return {"buy_and_hold_return": float(buyhold[-1] / initial - 1), "benchmark_return": float(index_values[-1] / initial - 1) if index_values is not None else None,
            "equity_curve": [{"date": date.isoformat(), "buy_and_hold": float(buyhold[i]), "benchmark": float(index_values[i]) if index_values is not None else None} for i, date in enumerate(dates)]}


def _empty(reason):
    return {"status": "Insufficient historical evidence", "sample_size": 0, "metrics": {}, "equity_curve": [], "trades": [],
            "out_of_sample": None, "walk_forward": [], "sensitivity": [], "probability_records": [], "limitations": [reason]}


def validate_strategies(history: pd.DataFrame, config: dict, benchmark: pd.DataFrame | None = None) -> dict:
    from app.analysis.features import build_features, snapshot_at
    from app.analysis.regime import classify_regime
    settings = _settings(config)
    frame = _prices(history)
    benchmark_frame = _prices(benchmark) if benchmark is not None and not benchmark.empty else None
    start = settings["warmup_bars"]
    report = {"strategies": {}, "benchmark": {}, "methodology": {"version": "2.0", "historical": True,
        "execution": "Completed previous-bar shared strategy; next open must lie inside its entry zone. Static original stop/T1 full exit; no intraday-touch entry assumption.",
        "costs": {"commission_bps": settings["commission_bps"], "slippage_bps": settings["slippage_bps"]},
        "probability_sampling": "Predetermined max-holding-bar embargo between statistical samples; actual trading ledger separately allows non-overlapping T1 positions.",
        "target_2": "Independent hypothetical original-stop barrier follow-up; actual strategy exits all shares at T1.",
        "split": "70/30 chronological split. Purge training observation windows that cross the split. Fixed-parameter held-out slices; no parameter fitting or best-case selection.",
        "fundamentals_used": False, "news_used": False, "macro_used": False,
        "time_precision": "Signals and outcome availability use explicit Bar End, otherwise the next daily boundary in the source index time zone. Session labels are retained separately; intraday fill times are not inferred."},
        "limitations": ["Historical results and empirical frequencies are not guaranteed future outcomes.",
            "Supplied bars must be completed, split-adjusted daily OHLC. Vendor restatements are not verified historical vintages; Adj Close dividend factors are deliberately not applied.",
            "Cash dividends, taxes, market impact, partial fills and liquidity are not modeled. Benchmark comparison is price-return only and uses exact matching session timestamps.",
            "Daily OHLC cannot identify intraday order between barriers; stop-first applies when the open is between both touched barriers. Known opening gaps execute first.",
            "MAE/MFE are known-path bounds, not exact realized excursions: signed MAE upper bound (adverse magnitude lower bound), MFE lower bound. Unsequenced exit-bar extremes are excluded unless exiting at the close. Maximum drawdown is based on daily-close equity.",
            "No point-in-time financial/news/macro history is supplied: fundamental-value backtests and those historical filters are excluded.",
            "Validation uses shared daily price rules. Historical intraday/weekly alignment and event-risk gates are not reconstructed, so this is not a complete backtest of every live contextual filter."]}
    if len(frame) <= start + 1:
        report["strategies"] = {key: _empty(f"Need more than {start + 1} completed daily bars for warmup and execution.") for key in ALL_STRATEGIES}
        return report
    features = build_features(frame, benchmark_frame)
    snapshots = [snapshot_at(features, index) for index in range(len(features))]
    if len(snapshots) != len(frame) or not features.index.equals(frame.index):
        raise ValueError("Causal feature rows must align exactly with the supplied price history")
    regimes = [classify_regime(snapshot) for snapshot in snapshots]
    split = max(start + 1, int(len(frame) * .7))
    selected = config.get("strategy_ids") or ([config["strategy"]] if config.get("strategy") else list(TECHNICAL_STRATEGIES))
    if isinstance(selected, str):
        selected = [selected]
    if any(key not in ALL_STRATEGIES for key in selected):
        raise ValueError("Unknown shared strategy id")
    report["benchmark"] = _benchmark(frame, settings, start, len(frame), benchmark_frame)
    training_variants = [
        ("zero modeled costs", {"commission_bps": 0, "slippage_bps": 0}),
        ("double modeled costs", {"commission_bps": min(100, settings["commission_bps"] * 2), "slippage_bps": min(100, settings["slippage_bps"] * 2)}),
        ("reward/risk hurdle lower by 0.5", {"min_reward_risk": max(1, settings["min_reward_risk"] - .5)}),
        ("reward/risk hurdle higher by 0.5", {"min_reward_risk": min(10, settings["min_reward_risk"] + .5)}),
    ]
    for strategy_id in selected:
        if strategy_id == "fundamental_value":
            continue
        full = _simulate(frame, snapshots, regimes, settings, strategy_id, start, len(frame), benchmark_frame)
        train = _simulate(frame, snapshots, regimes, settings, strategy_id, start, split, benchmark_frame, "training")
        test = _simulate(frame, snapshots, regimes, settings, strategy_id, split, len(frame), benchmark_frame, "out_of_sample")
        retained_training = [row for row in train["probability_records"] if row["observation_end_index"] < split and row["target_1_outcome"] != "censored"]
        full["probability_records"] = retained_training + test["probability_records"]
        full["status"] = "historical descriptive results" if full["sample_size"] >= settings["min_samples"] else "Insufficient historical evidence"
        full["out_of_sample"] = {"start": frame.index[split].isoformat(), "end": frame.index[-1].isoformat(), "metrics": test["metrics"],
            "sample_size": test["sample_size"], "probability_sample_size": sum(row["target_1_outcome"] != "censored" for row in test["probability_records"]),
            "training_samples_purged": len(train["probability_records"]) - len(retained_training), "method": "Last30%, fixed original rules, fresh capital; no parameter tuning. Prior bars provide warmup only."}
        full["walk_forward"] = []
        edges = np.linspace(max(start + 1, len(frame) // 2), len(frame), 4, dtype=int)
        for fold_start, fold_end in zip(edges[:-1], edges[1:]):
            if fold_end - fold_start < 30:
                continue
            fold = _simulate(frame, snapshots, regimes, settings, strategy_id, int(fold_start), int(fold_end), benchmark_frame, "walk_forward")
            full["walk_forward"].append({"start": frame.index[fold_start].isoformat(), "end": frame.index[fold_end - 1].isoformat(),
                "sample_size": fold["sample_size"], "metrics": fold["metrics"], "method": "Chronological held-out slice with fixed rules and fresh capital; no fitted parameters."})
        full["sensitivity"] = [{"scenario": "base training assumptions", "changes": {}, "scope": "training_only", "metrics": train["metrics"]}]
        for label, changes in training_variants:
            variant = _simulate(frame, snapshots, regimes, {**settings, **changes}, strategy_id, start, split, benchmark_frame)
            full["sensitivity"].append({"scenario": label, "changes": changes, "scope": "training_only", "metrics": variant["metrics"]})
        full["limitations"] = [f"Raw metrics use {full['sample_size']} executed trades, including explicitly labeled boundary liquidations; at least {settings['min_samples']} comparable mature samples are required for probability display.",
            "Sensitivity is descriptive on training bars only. No variant is selected as the best strategy or applied to the held-out period.",
            "Target2 labels describe a separate hypothetical continuation at the original stop, not the executed T1-full-exit strategy.",
            "Excursions are known-path bounds, not exact realized MAE/MFE; see excursion_method and per-trade excursion_bounds."]
        report["strategies"][strategy_id] = full
    report["strategies"]["fundamental_value"] = _empty("Verified point-in-time financial statements and historical valuations are unavailable. Current company data cannot be used in earlier decisions.")
    return report
