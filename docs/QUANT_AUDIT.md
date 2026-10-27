# Quantitative upgrade: audit and implementation

The existing application and visual design are retained. Methodology version 2 is a deterministic research system, not an established improvement in forecast accuracy. No LLM supplies market prices, trading levels or numerical probabilities.

## Findings before changes

The indicator module already contained independently tested Wilder RSI/ATR/ADX, moving averages, volatility and volume calculations. Its technical score grouped related indicators instead of counting every indicator as an independent vote. However, the old regime label depended mainly on ADX, current-session daily candles could affect decisions, and support/resistance mixed pivots with final-window extrema without recording confirmation strength or knowledge times.

The old single trade plan used fixed ATR offsets and broad heuristic targets. It did not include transaction costs in reward/risk, did not validate distinct trading strategies, and could mix a long-term DCF sensitivity with a short-term technical target. Its SMA crossover backtest was useful for that rule only; it did not establish the performance of the displayed trade plan. Data confidence was a heuristic, not a probability.

Fundamental calculations already handled missing fields, reporting dates, negative earnings, currencies, financial-sector exclusions and ETF non-applicability. Generic yield hurdles were not sufficient evidence of intrinsic value, reliable peer pricing or historical valuation. The upgrade keeps financial mathematics while withholding valuation attractiveness when defensible scenario/comparison inputs are missing.

## Implemented changes

1. **Price and risk corrections.** Finite OHLC validation, strictly confirmed five-bar pivots, explicit completion/confirmation times, displayed-price rounding before sizing, adverse costs and worst-zone risk sizing. Levels are never moved to manufacture a qualifying ratio.
2. **Regimes and timeframes.** Six states use moving-average alignment/slopes, ADX, normalized ATR/history-volatility ranks, confirmed structure and relative benchmark context. Weekly/daily and native hourly/15-minute candles are analyzed; four-hour candles are explicitly derived. Current/incomplete candles and stale timing confirmations are excluded. See [regime rules](REGIME_METHODS.md).
3. **Four shared strategies.** Trend following, breakout, mean reversion and long-horizon fundamental value each have separate eligibility, entry, invalidation, target and avoid rules. Missing confirmation returns Wait/Insufficient Data. Bearish/high-volatility conditions are not forced into a long entry.
4. **Execution.** Up to three justified targets, structural stops with preselected volatility buffers, costs, risk/capital limits and existing holdings. Fundamental thesis invalidation is separate from the capital-risk price stop.
5. **Validation.** The actual daily strategy evaluators drive historical signals. Next-open zone restrictions, stop-first ambiguous candles, adverse opening gaps, cost-aware sizing, holdout/purging, chronological fixed-rule slices, training-only sensitivity and buy-and-hold/index comparisons are implemented.
6. **Probabilities.** Comparable, non-overlapping mature outcome cohorts, independent target2 follow-up, Wilson intervals, a minimum 30 observations, past-only prospective frequency diagnostics and explicit abstention. These are empirical frequencies, not calibrated forecasts. See [statistical methods](STATISTICAL_VALIDATION.md).
7. **Valuation and scoring.** Explicit DCF, earnings-multiple and FCF-yield scenarios, user-selected same-industry/currency peers and available vendor historical multiples. Separate company quality, valuation, technical, setup, macro and composite ratings; confidence/freshness/model uncertainty/sample reliability remain separate.
8. **Existing dashboard.** The Quantitative research tab adds regime, timeframe, strategy, valuation and historical evidence without changing the design. Ordinary research avoids costly intraday/validation requests; full research is requested explicitly. Main ratings/plans and saved reports use version2. Full setup information never implies statistical success when samples are sparse.

## Deterministic strategy reference thresholds

All thresholds are research assumptions, not parameters optimized on the evaluation sample. Each technical strategy needs at least200 completed daily bars and positive ATR; an imminent known earnings/high-impact event, stale price source or contradictory higher-timeframe context blocks entry.

- **Trend:** bullish regime, support with at least2 confirmed touches within1.5ATR, rising RSI40–65 and higher close, relative volume≥1.1. Entry uses support−.25ATR to support+.5ATR, capped by the decision close. Targets use confirmed resistance/latest confirmed swing high.
- **Breakout:** bullish/sideways regime, a completed close crossing repeated prior high-pivot resistance, prior20-bar range≤8ATR, relative volume≥1.5, no chase beyond.75ATR. Entry starts.05ATR above resistance. Targets use resistance and a disclosed measured move equal to the prior20-bar range.
- **Mean reversion:** sideways regime, ADX<20, repeated support within1ATR, rising RSI after a prior reading<35, prior close below its own prior Bollinger lower band and current close back above the current band. Targets use SMA20/SMA50/confirmed resistance.
- **Value:** long horizon, company quality≥7, positive FCF, nonnegative comparable EPS growth, fresh financial evidence, explicit bear/base scenarios and default20% margin of safety. No corporate model is applied to ETFs. A technical support stop manages capital; business deterioration invalidates the investment thesis.

The structural stop buffer is1.25ATR/1ATR/.75ATR for low/medium/high risk tolerance, plus.5ATR in high volatility, chosen before targets. First-target net reward/risk must reach the configured minimum (default2). No justified target means no favorable setup.

## Version2 scoring

Company quality =70% financial performance +30% financial resilience, requiring both. Existing sector exclusions remain. Technical strength preserves the grouped daily indicator score, computed on completed bars. Setup quality =min(10,5+1.5×max(0, first-target net R−minimum R)) for eligible setups; missing setups do not earn points. Macro uses the existing release-family grouping, which prevents related inflation releases becoming independent votes.

Editable financial/valuation/technical/risk/macro weights map respectively to quality/valuation/technical/setup/macro. The risk control now represents setup quality; measured price risk remains a separate section. Horizon multipliers, in that order, are short[.5,.5,1.25,1.5,1], swing[1,.75,1.25,1.25,1], long[1.5,1.5,.5,.5,.75]. Normalize adjusted weights. Sum known weighted scores and divide by known weight only when coverage≥70%, company quality and technical evidence exist, and the instrument is an operating company. Otherwise the composite is unavailable. News adds at most±.25 points using `(news_score−5)×min(news_weight,.1)×.5`; it cannot rescue missing categories.

Explicit valuation scenarios use the median bear/base/bull across supplied correlated models, with dispersion disclosed. EPS×multiple and FCF/share÷yield require verified matching currencies. Margin of safety=(base−price)/base. Scenario attractiveness interpolates base/price−1 across[-.5,−.2,0,.2,.5] to[0,2,5,7,10]. Without scenarios, at least3 comparable peers or4 dated historical multiple observations are needed; relative score=clip(5+5×(referencePE/currentPE−1),0,10). Lower multiples do not prove undervaluation. Stale failed-refresh comparison inputs are excluded.

Evidence confidence uses source financial/valuation/macro confidence and completed technical/regime coverage, with staleness reductions. It is neither included in category scores nor described as outcome probability. The frontend separately displays source freshness, model uncertainty and historical sample reliability.

## Availability and operating limits

Daily labels identify sessions, not precise release times. Explicit Bar End governs knowledge time; otherwise daily results become available at the next local midnight (UTC assumed only for unzoned input). Pivot confirmation requires two later completed bars. Outcomes must have resolved strictly before a probability cutoff. Intraday and weekly completion is conservative because no independent holiday/half-day calendar is installed. Stale lower-timeframe rows remain visible but cannot confirm an entry.

Yahoo native1h/15m history is requested for up to59 calendar days; provider restrictions/outages may shorten or remove it. A missing timeframe/benchmark is disclosed. SPY is the default configurable benchmark; automatic currency matching is not claimed. The USD default is withheld for non-USD listings until a suitable benchmark is chosen.

Forex Factory remains an authorized export-import source. First/last imported event timestamps establish observed span, not completeness. Current imports explicitly do not certify full event coverage, so the final recommendation remains Wait for calendar review even if a price setup is eligible. No upcoming event outcome is predicted. Recent actuals must have passed their scheduled/known publication timestamps; current revised macro/financial/news information never enters historical strategy tests.

A single-stock historical dataset cannot eliminate survivorship bias or establish cross-market generalization. Current vendor history may contain corrections. Fundamental-value backtesting and historical full live-context gates are withheld without point-in-time inputs. Tests validate implementation behavior, not profitable forecasting.

The ordinary full review uses five years of history. A fixed maximum-holding embargo and30% holdout can make30 comparable outcomes unattainable for longer horizons; no minimum is silently relaxed. The separate backtest API supports maximum available history. Quotes more than five minutes in the future, or with invalid epoch values, fall back to dated history instead of becoming current valuation evidence.

## Changed areas and final checks

Backend additions are `analysis/structure.py`, `execution.py`, `features.py`, `regime.py`, `timeframes.py`, `strategies/`, `validation.py`, `probability.py`, `valuation_models.py`, `quant_scoring.py`, `quantitative.py` and `providers/bar_times.py`. Integration changes are in `technical.py`, `macro.py`, `providers/yahoo.py`, `service.py`, `schemas.py` and `main.py`. New unit/integration suites cover these interfaces; existing dynamic ticker/demo assertions now expect honest version2 valuation/composite abstention where their fixtures lack defensible valuation inputs.

Frontend additions are `QuantResearch.tsx` and its tests; existing `App.tsx`, `ResearchSections.tsx`, `types.ts`, styles and application tests integrate results without rebuilding the design. `scripts/verify_quantitative.py` preserves actual HTTP evidence and an example report. Documentation links distinguish retained legacy formulas from current methodology.

Final verification:317 backend tests passed, one PostgreSQL test skipped;81 frontend tests passed; production build, compileall, dependency consistency and Compose configuration passed. Actual research/quantitative HTTP responses passed for MSFT/AAPL/NVDA/ORCL/QQQ/SPY, and full report saving/reopening was browser-verified. See [the full verification record](VERIFICATION.md) for observed boundaries.
