import math

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest


def prices(close, opens=None):
    close = np.asarray(close, dtype=float)
    opens = close if opens is None else np.asarray(opens, dtype=float)
    return pd.DataFrame({"Open": opens, "High": np.maximum(close, opens) + .25, "Low": np.minimum(close, opens) - .25, "Close": close, "Adj Close": close, "Volume": 1000}, index=pd.bdate_range("2024-01-02", periods=len(close), tz="UTC"))


def settings(**overrides):
    return {"fast_period": 3, "slow_period": 8, "starting_capital": 10000, "commission_bps": 5, "slippage_bps": 5, **overrides}


def wave():
    return prices(np.r_[np.linspace(100, 90, 30), np.linspace(90, 120, 40), np.linspace(120, 80, 40), np.linspace(80, 140, 50)])


def test_flat_series_no_trades_no_nan_and_zero_drawdown():
    result = run_backtest(prices(np.ones(60) * 100), settings(commission_bps=0, slippage_bps=0))
    assert result["metrics"]["number_of_trades"] == 0
    assert result["metrics"]["total_return"] == 0
    assert result["metrics"]["maximum_drawdown"] == 0
    assert result["metrics"]["sharpe_ratio"] is None
    assert result["metrics"]["profit_factor"] is None
    assert result["metrics"]["buy_and_hold_return"] == 0


def test_signals_execute_at_next_open_and_costs_reconcile():
    result = run_backtest(wave(), settings())
    assert result["trades"]
    trade = result["trades"][0]
    frame = wave()
    i = frame.index.get_loc(pd.Timestamp(trade["entry_date"]))
    fast = frame["Close"].rolling(3).mean()
    slow = frame["Close"].rolling(8).mean()
    assert fast.iloc[i - 1] > slow.iloc[i - 1]
    assert fast.iloc[i - 2] <= slow.iloc[i - 2]
    assert trade["entry"] == pytest.approx(frame.iloc[i]["Open"] * 1.0005)
    assert result["metrics"]["ending_equity"] == pytest.approx(10000 + sum(t["pnl"] for t in result["trades"]), abs=1e-5)
    assert trade["commissions"] > 0
    assert result["metrics"]["maximum_drawdown"] <= 0


def test_risk_budget_and_capital_cap():
    result = run_backtest(wave(), settings())
    trade = result["trades"][0]
    risk_at_stop = trade["shares"] * (trade["entry"] - trade["stop"] * .9995 + .0005 * (trade["entry"] + trade["stop"] * .9995))
    assert risk_at_stop <= 100 + 1e-5
    assert trade["shares"] * trade["entry"] * 1.0005 <= 10000


def test_future_bars_do_not_change_earlier_signals_or_equity():
    original = wave()
    changed = original.copy()
    changed.loc[changed.index[100]:, ["Open", "High", "Low", "Close", "Adj Close"]] *= 2
    left = run_backtest(original, settings())
    right = run_backtest(changed, settings())
    prior = original.index[100].isoformat()
    assert [row for row in left["equity_curve"] if row["date"] < prior] == [row for row in right["equity_curve"] if row["date"] < prior]
    # Even if supplied, present-day news and calendar data cannot enter this price strategy.
    result = run_backtest(original, settings(macro_events=[{"actual": "1000", "scheduled_at": "2099-01-01T00:00:00Z"}]))
    assert result["equity_curve"] == left["equity_curve"]
    assert result["validation"]["macro_used"] is False


def test_gap_stop_executes_at_open_not_at_unavailable_stop_price():
    frame = wave()
    baseline = run_backtest(frame, settings())
    first = pd.Timestamp(baseline["trades"][0]["entry_date"])
    i = frame.index.get_loc(first) + 2
    gap = baseline["trades"][0]["stop"] - 8
    frame.loc[frame.index[i], ["Open", "Close", "Adj Close"]] = gap
    frame.loc[frame.index[i], "High"] = gap + .25
    frame.loc[frame.index[i], "Low"] = gap - .25
    result = run_backtest(frame, settings())
    trade = result["trades"][0]
    assert trade["reason"] == "ATR stop (gap-aware)"
    assert trade["exit"] == pytest.approx(gap * .9995)
    assert trade["pnl"] < -100  # Gap losses can exceed a 1% target risk budget.


def test_benchmark_comparison_and_chronological_holdouts():
    frame = wave()
    result = run_backtest(frame, settings(), benchmark=prices(np.linspace(100, 120, len(frame))))
    assert result["metrics"]["benchmark_return"] > 0
    assert result["validation"]["out_of_sample"] is not None
    assert result["validation"]["walk_forward"] == []  # Each fold needs >=30 bars.
    long = prices(np.r_[np.linspace(100, 80, 100), np.linspace(80, 150, 400)])
    assert len(run_backtest(long, settings())["validation"]["walk_forward"]) == 3
    missing = prices(np.linspace(100, 120, len(frame))).iloc[1:]
    assert run_backtest(frame, settings(), missing)["metrics"]["benchmark_return"] is not None  # only evaluation dates required


def test_nontrading_days_are_not_invented():
    frame = wave().drop(wave().index[[50, 51]])
    result = run_backtest(frame, settings())
    dates = {row["date"] for row in result["equity_curve"]}
    assert wave().index[50].isoformat() not in dates
    assert len(result["equity_curve"]) == len(frame) - 8


def test_split_adjusted_series_has_no_fake_split_loss():
    frame = prices(np.ones(60) * 50)
    frame["Stock Splits"] = 0.0
    frame.loc[frame.index[30], "Stock Splits"] = 2.0
    result = run_backtest(frame, settings(commission_bps=0, slippage_bps=0))
    assert result["metrics"]["buy_and_hold_return"] == 0
    with pytest.raises(ValueError, match="Split"):
        run_backtest(frame.drop(columns="Adj Close"), settings())


@pytest.mark.parametrize("change", [{"risk_per_trade": 0}, {"fast_period": 10, "slow_period": 8}, {"commission_bps": -1}, {"slippage_bps": math.inf}, {"fast_period": 2.5}])
def test_invalid_config_is_rejected(change):
    with pytest.raises(ValueError):
        run_backtest(wave(), settings(**change))


def test_insufficient_history_missing_and_inconsistent_prices():
    with pytest.raises(ValueError, match="at least"):
        run_backtest(wave().iloc[:10], settings())
    frame = wave()
    frame.loc[frame.index[0], "Close"] = np.nan
    with pytest.raises(ValueError, match="finite"):
        run_backtest(frame, settings())
    frame = wave()
    frame.loc[frame.index[0], "High"] = 1
    with pytest.raises(ValueError, match="Inconsistent"):
        run_backtest(frame, settings())
