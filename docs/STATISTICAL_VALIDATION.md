# Shared-strategy validation and empirical probabilities

The version 2 validation engine calls the same `evaluate_strategies(snapshot, context, config)` functions that produce current technical setups. It does not backtest an unrelated indicator vote. Causal daily features are calculated once, snapshots read only through their decision bar, and confirmed pivots are unavailable until their confirmation bars have completed. Input must contain completed, split-adjusted OHLC bars. Current fundamentals, valuation snapshots, company news and revised macro records are absent from historical strategy contexts. Historical intraday/weekly alignment and event-risk gates are not reconstructed; the result validates the shared daily price rules, not every live contextual filter.

Fundamental-value validation returns **Insufficient historical evidence** until verified historical publication times and contemporaneous valuation inputs exist. Supplying today's financial statements does not make them historical evidence.

## Execution assumptions

Each strategy holds at most one long position at a time. A completed-bar eligible setup can enter only at the following bar's opening price **inside the previously defined entry zone**. A later intraday touch cannot create an entry after an opening gap outside the zone. The original stop and first target are fixed before entry. The executed validation strategy exits the whole position at target1, at the original stop, or at its maximum holding close. No stop or target is moved to manufacture a favorable reward/risk ratio.

A stop opening gap exits at the worse opening price. A known opening gap above a target fills conservatively at the target price. When the opening price lies between barriers and the daily high and low touch both, the stop is assumed first. Daily bars cannot establish the actual sequence, order-book liquidity or fill certainty.

Entry outlay/share = `open × (1 + slippage) × (1 + commission)`.
Stop proceeds/share = `stop × (1 − slippage) × (1 − commission)`.
Modeled risk/share = entry outlay − stop proceeds.
Whole shares are capped by the risk budget, cash affordability and the shared setup's conservative worst-zone position size. Exit proceeds apply both adverse slippage and commissions. Gaps can exceed the modeled risk budget. No borrowing, live orders, taxes, market impact, partial fills or spread model is supplied.

Yahoo Close is already split-adjusted in the expected input. This validator deliberately does not apply today's Adj-Close dividend factors retroactively. It is a **price-return** simulation, excludes cash dividends, and does not claim that vendor-restated bars are verified historical vintages. Clear raw split discontinuities are rejected. Buy-and-hold and a supplied index use the same evaluation dates, capital and cost assumptions; missing exact-date index coverage remains unavailable.

## Trades, metrics and excursion limits

The ledger preserves the decision availability timestamp, next-open entry session label, exit availability bound, strategy, regime, stop, target levels, share count, costs, net return, holding bars and outcome reason. Separate `signal_session`, `entry_session` and `exit_session` fields preserve daily session labels. `time_precision` distinguishes labels and completed-bar availability bounds from exact intraday execution timestamps, which are not available. Signal/outcome availability uses explicit `Bar End` when supplied; otherwise it uses the conservative next daily boundary in the source index time zone (naive indices are treated as UTC). A daily high/low outcome is never known merely because its session-start label is earlier than an intraday query cutoff. A fold/end-of-history liquidation is explicitly censored if the strategy's original horizon has not finished. Raw descriptive performance includes the liquidation because portfolio value must reconcile, while unresolved censored barrier labels are excluded from probability denominators.

Return, annualization (252 sessions), daily-close maximum drawdown, zero-risk-free Sharpe, win rate, average positive/negative currency P&L and profit factor share the legacy documented formulas. New metrics include mean net trade return, mean currency P&L expectancy, mean realized R multiple, average holding bars, and average MAE/MFE. Profit factor remains unavailable without losing trades. A profitable timeout is a winning trade but is **not** counted as a target hit.

MAE is the lowest observed held price / executed entry −1, capped at 0; MFE is the highest / entry −1, floored at 0. Full completed holding bars are observed, but unsequenced extremes on a stop/target exit bar might have occurred after exit. Those extremes are excluded; only the execution point is added. A holding-horizon close can use its complete bar. These are **known-path bounds**, not exact realized or tick-level excursions: signed MAE is an upper bound (adverse magnitude is a lower bound), and MFE is a lower bound. They must not be interpreted as conservative upper estimates of adverse risk. Each trade provides `excursion_bounds`; each strategy supplies `excursion_method` metadata beside these raw metric values.

## Chronological validation and sensitivity

The dataset is split 70/30 in time order. The final 30% uses fixed original rules and fresh capital; preceding bars provide only causal feature warmup. Training statistical observation windows that cross the split are purged. Three additional chronological held-out slices use fixed parameters and fresh capital when each has at least 30 bars. These checks are not a claim of fitted machine learning or optimized walk-forward training.

Sensitivity is restricted to training bars: baseline costs, zero modeled costs, doubled modeled costs (within supported bounds), and reward/risk hurdles 0.5 below/above baseline. The engine reports each scenario without choosing a favorable variant and applying it to the holdout. Zero-cost sensitivity is a comparison assumption, not a realistic execution promise. The temporal separation follows the principle that time-ordered evaluation cannot train on future observations; see the official [scikit-learn TimeSeriesSplit documentation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).

## Probability definition and denominator

The reported quantity is the **empirical frequency that a specified target was reached before the original stop within the strategy's maximum holding horizon**. It is not a guaranteed probability for the current stock and is not generated by an LLM.

For target1:

`n = target-first + stop-first + fully observed timeout`.

`target1 frequency = target-first / n`.

`stop frequency = stop-first / n`.

`unresolved-within-horizon frequency = timeout / n`.

A timeout counts in the denominator and is not silently discarded. An end-of-history/fold censored observation is excluded because its complete horizon is unknown. A target hit can still be unprofitable after costs; net-return expectancy is a separate statistic.

Target2 is labeled independently through the remaining original horizon against the **same original stop**. The trade ledger includes `target_2_hypothetical` and its separate `target_2_closed_at` availability bound, so a later virtual result is not misrepresented as known at the first-target exit. It describes a hypothetical continuation; the actual first-target strategy already exited. Target2 has its own count, censoring, comparability check and minimum-sample status. A separately labeled conditional-after-target1 frequency uses only target1 hits with mature target2 observations and has its own minimum count; it still describes a hypothetical continuation. Missing target2 is unavailable, never copied from target1 or filled with 50%.

Actual trading positions do not overlap per strategy. Statistical observations additionally use a predetermined maximum-holding-bar embargo between selected entry samples. This prevents a hypothetical target2 follow-up from sharing future bars with the next statistical observation, even when actual target1 trades exit sooner. Repeated or conflicting record identities cannot inflate sample size.

## Comparability and uncertainty

The default inferential display minimum is **30 comparable, mature observations**. This is a pragmatic minimum, not proof that 30 market observations are statistically sufficient. Without enough observations the estimate and its interval are null and the status is **Insufficient historical evidence**.

Comparability requires identical strategy, regime, horizon, maximum holding bars and supplied cost assumptions. Risk geometry uses fixed, outcome-independent bins:

- Stop distance / decision ATR: `[0,1)`, `[1,2)`, `[2,3)`, `[3,5)`, `[5,infinity)`.
- Gross target distance / decision risk: `[0,1)`, `[1,2)`, `[2,3)`, `[3,5)`, `[5,10)`, `[10,infinity)`.

Target2 must also match its own target-R bin. Regime, ATR and target geometry come from the decision snapshot; future outcomes never choose bins. A supplied held-out cohort is preferred exclusively: a short holdout is not filled with in-sample observations to make the minimum count. If no independent holdout is supplied, any available frequency is explicitly described as historical and descriptive.

Binary frequency intervals use the two-sided 95% Wilson score interval without continuity correction:

`center = (p + z²/(2n)) / (1 + z²/n)`

`half-width = z × sqrt(p(1−p)/n + z²/(4n²)) / (1 + z²/n)`, with `z = inverse_normal(0.975)`.

Endpoints are clipped to [0,1]. The implementation is tested against known reference calculations, including zero/all-success samples. Wilson is documented in the official [SciPy proportion_ci reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html), which also identifies Wilson's 1927 paper. SciPy is not required at runtime. A mean-return interval, when available, is separately labeled a normal-approximation standard-error interval; heavy tails and serial dependence can make it too narrow.

## Prospective frequency diagnostics

Only outcomes with resolution times **strictly earlier than the candidate's decision cutoff** may enter an estimate. Target2's later resolution has its own cutoff check. Each held-out forecast is reconstructed from already closed comparable samples, rather than from its own or later outcomes. The expanding prior strategy/horizon mean is a simple baseline. Brier loss = `(forecast − observed target1 hit)²`. Aggregate Brier and baseline scores are withheld until the minimum number of prospective predictions exists; small counts remain visible without claiming calibration.

These diagnostics describe an expanding historical-frequency rule. They do not prove current probabilities are calibrated, independent or stationary. Non-overlapping windows reduce one source of dependence but do not remove market cycles, selection bias, survivorship bias, changing liquidity or vendor data revisions. Sparse same-regime observations will often require abstention even when the application has years of price bars.

## Verification

`backend/tests/test_strategy_validation.py` uses clearly synthetic observations to test next-open zone restrictions, prior-bar signals, cost/risk reconciliation, gap losses, stop-first ambiguity, timeouts versus censoring, independent target2 labels, statistical non-overlap, chronological purging, training-only sensitivity, future-price prefix invariance, Wilson references, missing/short cohorts, duplicate exclusion and past-only Brier forecasts. Current financial/news/macro inputs never enter the historical context.
