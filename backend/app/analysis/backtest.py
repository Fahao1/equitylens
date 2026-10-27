"""Daily moving-average research backtest with explicit execution and cost rules.

No fundamentals, current news or revised macro data are read by this module.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _number(value):
    result = float(value)
    return round(result, 8) if math.isfinite(result) else None


def _performance(curve: list[dict], trades: list[dict], initial: float) -> dict:
    equity = pd.Series([row["equity"] for row in curve], dtype=float)
    returns = pd.concat([pd.Series([initial]), equity], ignore_index=True).pct_change().dropna()
    if len(equity):
        # Include initial capital so the first trading day's costs/drawdown count.
        all_equity = pd.concat([pd.Series([initial]), equity], ignore_index=True)
        maximum_drawdown = float((all_equity / all_equity.cummax() - 1).min())
        total = equity.iloc[-1] / initial - 1
        years = len(equity) / 252
        annual = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    else:
        maximum_drawdown, total, annual = 0.0, 0.0, 0.0
    wins = [trade["pnl"] for trade in trades if trade["pnl"] > 0]
    losses = [trade["pnl"] for trade in trades if trade["pnl"] < 0]
    deviation = returns.std(ddof=1) if len(returns) > 1 else 0
    return {
        "starting_capital": initial, "ending_equity": _number(equity.iloc[-1] if len(equity) else initial),
        "total_return": _number(total), "annualized_return": _number(annual),
        "maximum_drawdown": _number(maximum_drawdown), "sharpe_ratio": _number(returns.mean() / deviation * math.sqrt(252)) if deviation and math.isfinite(deviation) else None,
        "number_of_trades": len(trades), "win_rate": len(wins) / len(trades) if trades else None,
        "average_gain": _number(np.mean(wins)) if wins else None, "average_loss": _number(np.mean(losses)) if losses else None,
        "profit_factor": _number(sum(wins) / abs(sum(losses))) if losses else None,
        "profit_factor_note": "Undefined with no losing trades" if not losses else None,
    }


def _prepare(history: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(history.columns):
        raise ValueError("Backtest requires Open, High, Low and Close")
    frame = history.copy().sort_index()
    if frame.index.has_duplicates:
        raise ValueError("Duplicate price timestamps are not allowed")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True)
    columns = list(required)
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[columns].isna().any().any() or not np.isfinite(frame[columns].to_numpy()).all() or (frame[columns] <= 0).any().any():
        raise ValueError("Prices must be finite and positive; missing rows must be resolved before backtesting")
    if ((frame["High"] < frame[["Open", "Close", "Low"]].max(axis=1)) | (frame["Low"] > frame[["Open", "Close", "High"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC prices")
    if "Adj Close" in frame.columns:
        adjusted = pd.to_numeric(frame["Adj Close"], errors="coerce")
        if adjusted.isna().any() or not np.isfinite(adjusted).all() or (adjusted <= 0).any():
            raise ValueError("Adjusted close must be finite and positive when supplied")
        # Yahoo's Close is split-adjusted. Ratio also incorporates distributions.
        factor = adjusted / frame["Close"]
        frame[columns] = frame[columns].mul(factor, axis=0)
    elif "Stock Splits" in frame.columns and (pd.to_numeric(frame["Stock Splits"], errors="coerce").fillna(0) != 0).any():
        raise ValueError("Split events require Yahoo adjusted OHLC with Adj Close; unadjusted split series cannot be backtested safely")
    return frame


def _simulate(frame: pd.DataFrame, config: dict, start: int, end: int, benchmark: pd.DataFrame | None = None) -> dict:
    initial = config["starting_capital"]
    fee = config["commission_bps"] / 10000
    slip = config["slippage_bps"] / 10000
    cash, shares, entry, stop, entry_fee = initial, 0, 0.0, 0.0, 0.0
    entry_date = None
    curve, trades = [], []

    def liquidate(price, date, reason):
        nonlocal cash, shares, entry, stop, entry_fee, entry_date
        execution = price * (1 - slip)
        exit_fee = shares * execution * fee
        pnl = shares * (execution - entry) - entry_fee - exit_fee
        trades.append({"entry_date": entry_date, "exit_date": date, "entry": _number(entry), "exit": _number(execution), "shares": shares, "stop": _number(stop), "pnl": _number(pnl), "return": _number(pnl / (shares * entry + entry_fee)), "reason": reason, "commissions": _number(entry_fee + exit_fee)})
        cash += shares * execution - exit_fee
        shares, entry, stop, entry_fee, entry_date = 0, 0.0, 0.0, 0.0, None

    start_open = float(frame.iloc[start]["Open"])
    buyhold_shares = math.floor(initial / (start_open * (1 + slip) * (1 + fee)))
    buyhold_cash = initial - buyhold_shares * start_open * (1 + slip) * (1 + fee)
    bench_aligned = None
    index_shares, index_cash = 0, initial
    if benchmark is not None and not benchmark.empty:
        benchmark_frame = _prepare(benchmark)
        target_dates = frame.index[start:end]
        # Exact trading-date alignment only; no fill from future observations.
        bench_aligned = benchmark_frame.reindex(target_dates)
        if not bench_aligned[["Open", "Close"]].isna().any().any():
            index_open = float(bench_aligned.iloc[0]["Open"])
            index_shares = math.floor(initial / (index_open * (1 + slip) * (1 + fee)))
            index_cash = initial - index_shares * index_open * (1 + slip) * (1 + fee)
        else:
            bench_aligned = None
    for i in range(start, end):
        row, previous = frame.iloc[i], frame.iloc[i - 1]
        date = frame.index[i].isoformat()
        trend = previous["fast"] > previous["slow"]
        crossed_up = trend and (i < 2 or not (frame.iloc[i - 2]["fast"] > frame.iloc[i - 2]["slow"]))
        if shares and not trend:
            liquidate(float(row["Open"]), date, "moving-average exit at next open")
        if not shares and crossed_up and pd.notna(previous["atr"]):
            candidate_entry = float(row["Open"]) * (1 + slip)
            candidate_stop = float(previous["Close"] - 2 * previous["atr"])
            # A gap below the stop invalidates the setup before entry.
            if 0 < candidate_stop < float(row["Open"]):
                unit_risk = candidate_entry - candidate_stop * (1 - slip) + fee * (candidate_entry + candidate_stop * (1 - slip))
                quantity = min(math.floor(cash * config["risk_per_trade"] / unit_risk), math.floor(cash / (candidate_entry * (1 + fee))))
                if quantity > 0:
                    shares, entry, stop, entry_date = quantity, candidate_entry, candidate_stop, date
                    entry_fee = shares * entry * fee
                    cash -= shares * entry + entry_fee
        if shares and row["Low"] <= stop:
            liquidate(min(float(row["Open"]), stop), date, "ATR stop (gap-aware)")
        if i == end - 1 and shares:
            liquidate(float(row["Close"]), date, "end-of-test liquidation")
        buyhold_value = buyhold_cash + buyhold_shares * float(row["Close"])
        if i == end - 1:
            buyhold_value = buyhold_cash + buyhold_shares * float(row["Close"]) * (1 - slip) * (1 - fee)
        benchmark_value = None
        if bench_aligned is not None:
            benchmark_value = index_cash + index_shares * float(bench_aligned.iloc[i - start]["Close"])
            if i == end - 1:
                benchmark_value = index_cash + index_shares * float(bench_aligned.iloc[i - start]["Close"]) * (1 - slip) * (1 - fee)
        curve.append({"date": date, "equity": _number(cash + shares * float(row["Close"])), "buy_and_hold": _number(buyhold_value), "benchmark": _number(benchmark_value) if benchmark_value is not None else None})
    metrics = _performance(curve, trades, initial)
    metrics["buy_and_hold_return"] = _number(curve[-1]["buy_and_hold"] / initial - 1) if curve else None
    metrics["benchmark_return"] = _number(curve[-1]["benchmark"] / initial - 1) if curve and curve[-1]["benchmark"] is not None else None
    return {"metrics": metrics, "equity_curve": curve, "trades": trades}


def run_backtest(history: pd.DataFrame, config: dict, benchmark: pd.DataFrame | None = None) -> dict:
    settings = {"starting_capital": 10000, "commission_bps": 5, "slippage_bps": 5, "risk_per_trade": 0.01, "fast_period": 20, "slow_period": 50, **config}
    for key in ("starting_capital", "commission_bps", "slippage_bps", "risk_per_trade", "fast_period", "slow_period"):
        if not isinstance(settings[key], (int, float)) or not math.isfinite(settings[key]):
            raise ValueError(f"{key} must be a finite number")
    if not (0 < settings["starting_capital"] <= 1e12 and 0 <= settings["commission_bps"] <= 1000 and 0 <= settings["slippage_bps"] <= 1000 and 0 < settings["risk_per_trade"] <= 0.1):
        raise ValueError("Invalid capital, trading costs or risk (must be >0 and <=10%)")
    fast, slow = settings["fast_period"], settings["slow_period"]
    if int(fast) != fast or int(slow) != slow or not (2 <= fast < slow <= 500):
        raise ValueError("Moving-average periods must be integers, 2 <= fast < slow <= 500")
    fast, slow = int(fast), int(slow)
    frame = _prepare(history)
    if len(frame) < max(slow + 2, 16):
        raise ValueError(f"Need at least {max(slow + 2, 16)} valid price bars")
    frame["fast"] = frame["Close"].rolling(fast).mean()
    frame["slow"] = frame["Close"].rolling(slow).mean()
    true_range = pd.concat([frame["High"] - frame["Low"], (frame["High"] - frame["Close"].shift()).abs(), (frame["Low"] - frame["Close"].shift()).abs()], axis=1).max(axis=1)
    # Simple ATR here is deliberately stated; indicators elsewhere may use Wilder.
    frame["atr"] = true_range.rolling(14).mean()
    result = _simulate(frame, settings, slow, len(frame), benchmark)
    validation = {"signal_timing": "Previous completed close only; entry/MA exit at next open.", "stop_timing": "Fixed prior-close minus 2 x 14-bar simple ATR; stop executed intraday with open-gap handling.", "macro_used": False, "fundamentals_used": False, "news_used": False, "point_in_time": "Only past price bars drive signals. Current/revised financial, news and calendar records excluded.", "out_of_sample": None, "walk_forward": []}
    split = max(slow + 1, int(len(frame) * 0.7))
    if len(frame) - split >= 30:
        oos = _simulate(frame, settings, split, len(frame), benchmark)
        validation["out_of_sample"] = {"start": frame.index[split].isoformat(), "metrics": oos["metrics"], "method": "Last 30%, fixed parameters, fresh capital; preceding prices used only for indicator warmup. No optimization."}
    # Anchored, fixed-parameter held-out slices, not a claim of parameter tuning.
    first = max(slow + 1, len(frame) // 2)
    edges = np.linspace(first, len(frame), 4, dtype=int)
    for start, end in zip(edges[:-1], edges[1:]):
        if end - start >= 30:
            fold = _simulate(frame, settings, int(start), int(end), benchmark)
            validation["walk_forward"].append({"start": frame.index[start].isoformat(), "end": frame.index[end - 1].isoformat(), "metrics": fold["metrics"], "method": "Chronological holdout with fixed settings and fresh capital; no fit or parameter search."})
    result.update(config=settings, strategy="Long-only SMA crossover with fixed 2 ATR stop", validation=validation,
        limitations=["Historical performance is not expected future performance; no execution guarantees.", "Only price signals are backtested. Fundamentals, news and macro require verified point-in-time datasets and are excluded.", "Daily bars cannot reveal intraday path or true stop liquidity; gaps may exceed the initial risk budget.", "Yahoo adjusted-price ratios are used when available; this is an adjusted-unit total-return proxy, not historical literal share quantities.", "No taxes, borrow costs, liquidity/market impact or parameter optimization. Sharpe uses daily returns, 252 sessions and a zero risk-free rate.", "Win rate and gain/loss use completed trades including final liquidation; profit factor is undefined if there are no losing trades.", "Benchmarks start after identical indicator warmup and include the same cost assumptions; missing index data is reported as unavailable."])
    return result
