# Completed-bar regimes and timeframe context

Methodology version 2 adds descriptive regimes and a hierarchical timeframe view. Neither module estimates trade outcome probabilities. They do not use an LLM. All thresholds below are explicit research assumptions requiring historical evaluation; a descriptive label does not establish forecast skill.

## Shared causal features

`analysis/features.py` builds indicators from past/current completed bars once. `snapshot_at()` exposes the values known at a specific row, including confirmed pivot zones and their confirmation times. `analysis/regime.py` consumes this snapshot through `classify_regime(features)`. It does not calculate a second set of competing indicators. Snapshot `as_of` is the candle knowledge/completion time, with the original timestamp retained separately as `session_label`; `Bar End` is not converted into a numeric indicator.

Required fields use these units:

- `bars`: completed observations through the decision row.
- `sma_50`, `sma_200`, `close`, `atr`, open/high/low and prior close: the same split-adjusted price basis.
- `slope_50`: fractional change in SMA50 over 10 bars; `slope_200`: fractional change in SMA200 over 20 bars.
- `adx`: Wilder ADX14 in 0–100, describing strength rather than direction.
- `atr_percentile`, `hv_percentile`: 0–100 percentile ranks of normalized ATR and historical volatility within the available trailing window. A minimum 63 observations is required by the feature builder.
- `relative_strength_63`: the selected instrument's 63-bar price return minus the same-date aligned benchmark return, expressed as a fraction. Missing benchmark observations are not filled from future data.
- `benchmark_trend`: bullish, bearish, sideways/mixed, or unavailable.
- `structure`: higher highs/higher lows, lower highs/lower lows, or mixed, based on confirmed pivots. A five-bar pivot is known only after the next two bars have completed.

A minimum 200 completed bars and finite positive close/SMA50/SMA200 are required. A full 252-session context increases evidence maturity, rather than making an unavailable measurement favorable. SMA200's 20-bar slope can remain unavailable until 220 observations; that prevents a strong directional label. At least three feature groups must be present. Inconclusive evidence returns `Insufficient Data`, including cases where available features conflict without establishing any modeled regime.

The optional `analyze_regime(history, benchmark, as_of)` wrapper builds the same shared features after excluding later timestamps and any `Bar End` later than the decision time. Callers must provide completed daily bars or explicit completion ends; a daily session label alone does not prove the candle was closed. The provider completion layer supplies that guarantee.

## Six descriptive states

The rules are evaluated in this priority order:

1. **High-volatility regime.** Both normalized-ATR and historical-volatility percentiles are at least 80, and measured historical close-return volatility is positive. Independent price-action evidence must also be present: a bar high–low range at least 1.5 ATR, an opening gap at least 1 ATR, close displaced at least 3 ATR from SMA50, or a mixed-structure 20-bar range at least 8 ATR. High volatility takes precedence over directional states. Mixed/unknown pivot structure by itself is not a price-action confirmation.
2. **Strong bullish trend.** Close > SMA50 > SMA200; both MA slopes are positive; ADX is at least 25; confirmed structure is higher highs/higher lows. An observed negative relative return or bearish benchmark prevents this strong label. Missing benchmark evidence does not add a positive vote and lowers confidence; otherwise confirmed technical evidence can still describe a strong price trend.
3. **Strong bearish trend.** Close < SMA50 < SMA200; both slopes are negative; ADX is at least 25; confirmed structure is lower highs/lower lows. An observed positive relative return or bullish benchmark prevents this strong label.
4. **Sideways consolidation.** ADX is below 20; structure is mixed; SMA50 and SMA200 differ by no more than 3%; the absolute 10-bar SMA50 change is no more than 1%; an available 20-bar range must be no more than 8 ATR. No directional assumption fills a missing field.
5. **Weak bullish trend.** Either close > SMA50 > SMA200 with nonnegative SMA50 slope, or close > SMA50 with a positive SMA50 slope and higher-high/higher-low structure. It lacks one or more strong-trend confirmations or has opposing benchmark evidence.
6. **Weak bearish trend.** The corresponding inverse of weak bullish conditions.

The returned `trend_strength` is the string Strong, Moderate, Weak or Unavailable. Strong requires ADX at least 25 and both slopes aligned; Moderate covers remaining ADX at least 20; lower ADX is Weak. This field describes strength independently from the directional state. `volatility_regime` is High when measured return volatility is positive and both percentiles are at least 80, Low when both are no more than 20, Normal otherwise when the full volatility group is available, and Unavailable when it is incomplete.

### Evidence confidence

Confidence measures completeness, history maturity and rule consistency; it is not a probability. Feature-group coverage weights are moving-average alignment 25%, slopes 20%, ADX strength 15%, volatility context 15%, confirmed structure 15%, and relative benchmark context 10%. The two slopes share one group; correlated volatility measures share one group. Missing benchmark evidence contributes zero of its 10%, never an invented positive relative return.

Multiply available weighted coverage by `min(1,bars/252)`. Opposing MA direction versus confirmed structure multiplies confidence by .8; relative return opposing MA direction multiplies it by .9. Conflicting evidence that fails every regime rule returns Insufficient Data with confidence capped at .4. Returned evidence and limitations disclose the inputs and missing groups.

## Timeframe inputs and candle completion

`analyze_timeframes(frames, metadata, as_of)` accepts only actual provider frames keyed weekly, daily, 4h, 1h and 15m. No missing interval is reconstructed from invented candles. Source metadata and errors remain visible. A provider snapshot marked `cache_stale` remains visible as dated data but has zero completion confidence and is excluded from context/setup/timing alignment. Derived intervals must inherit that staleness from their source candles. Each row returns status, trend, momentum, volatility state, nearest confirmed support/resistance, bar count, source, latest bar start/session label, latest completion end, indicators and limitations.

An explicit timezone-bearing UTC `Bar End` is preferred. A candle is eligible only when its start is earlier than the decision time, its completion end is after its start, and its completion end is no later than the decision time. Invalid/undated/nonpositive-duration ends, future observations and incomplete candles are excluded before every calculation. An explicit short final-session end is honored even if the nominal timeframe lasts longer. Completion metadata marked unverified reduces confidence and discloses that historical holidays/half-day schedules may be absent.

Without `Bar End`, the shared conservative provider helper excludes the current source-local day and current source-local week. Daily completion uses the next local midnight; weekly completion uses the next local Monday, with UTC conversion preserving daylight-saving changes. This intentionally can omit an already closed market day/week until the conservative boundary passes. Intraday fallback uses open plus nominal interval, which can omit a truncated final session bar; it does not assume an exchange calendar. A naive source index needs a named source timezone; otherwise UTC is disclosed as an assumption with reduced confidence. No missing session or holiday is interpolated.

Finite positive, internally consistent OHLC is required. Invalid bars are excluded with an explicit count. Duplicate timestamps keep the latest supplied observation. This is a source snapshot policy, not evidence that corrected bars were available earlier; historical evaluation requires a point-in-time dataset.

## Per-timeframe summaries

At least 50 completed candles are needed. Periods count candles of that timeframe, not calendar days:

- Bullish: close > EMA21 > SMA50 and EMA21 has risen over the preceding five candles. Bearish is the inverse; otherwise Mixed.
- Momentum: RSI14 at least 55 is Positive, no more than 45 is Negative, otherwise Neutral. Unavailable RSI stays unavailable. Oversold does not establish a reversal.
- Volatility: normalized Wilder ATR14 and 20-bar log-return standard deviation each need at least 63 available observations for trailing relative percentile context. Both percentiles at least 80 mean High; both no more than 20 mean Low; otherwise Normal. An exactly constant trailing measurement is ranked at 50 because its within-sample relative position is uninformative; a zero-volatility series cannot become high solely from inclusive percentile ties. Raw realized volatility is **per bar**, with no unsupported annualization.
- Support/resistance reuse shared strictly confirmed five-bar pivots, with 0.5 ATR clustering and explicit knowledge times. Unconfirmed final-sample extrema are not substituted when a pivot level is absent.

Per-row confidence is `min(1,bars/200) × available-indicator fraction × completion quality`. Completion quality is 1 for explicit ends unless session metadata is marked unverified, .8 for unverified explicit ends, and .65 for inferred ends. An unzoned index assumed UTC receives an additional .8 factor. These are disclosed evidence-quality heuristics.

## Hierarchical alignment without vote inflation

Weekly sets context; daily sets setup direction. One lower interval supplies timing confirmation: 1h is preferred when available, otherwise 4h, otherwise 15m. The remaining nested frames remain visible as ancillary context and cannot add votes or increase combined confidence.

Both weekly and daily summaries are required for a combined alignment classification. Opposing bullish/bearish higher frames return Conflicting. Mixed higher context or an opposing/mixed selected timing frame returns Mixed with explicit contradictions. Matching weekly/daily directions return aligned bullish/bearish when timing agrees or is unavailable; missing timing retains its confidence penalty. The descriptive alignment score is 8 for aligned bullish, 2 for aligned bearish, and null for conflicting, mixed or insufficient evidence; it is not expected return or probability.

Combined confidence weights are weekly 35%, daily 45%, selected timing frame 20%. Missing inputs contribute no confidence. Weekly-versus-daily opposition applies a .8 consistency factor; opposing lower timing applies .9. Adding more overlapping fast intervals cannot raise this confidence.

## Provider inputs and timestamp meanings

The Yahoo adapter requests native 1h and 15m candles only. It uses a UTC calendar start date 59 dates before the request, regular sessions (`prepost=False`), explicit unadjusted/dividend-separate OHLC (`auto_adjust=False`) and a 12-second request timeout. This calendar-date policy can include the current partial day's additional hours while remaining inside a 60-day intraday window. Four-hour candles are derived separately with disclosed anchoring/completion rules; an unsupported native interval is not silently substituted.

Intraday source caching lasts 900 seconds for 1h and 300 seconds for 15m. Company metadata shares the normal configurable financial-data cache (default six hours). Vendor historical valuation tables cache for 86400 seconds. An unchanged fresh snapshot is reused. Failed refreshes preserve the original `fetched_at`, source values and observation dates, while setting `cache_stale` and attaching a structured upstream error. A cached retrieval timestamp is not a new quote timestamp or a new fiscal reporting date. A stale intraday interval and every interval derived from it must remain excluded from timing confirmation.

The historical valuation adapter requests quarterly measures with at most eight period columns, skips the `Current` column and unparseable/undated/NaT date labels, and preserves missing metrics as null. Vendor historical rows are not verified publication-time vintages and must not enter point-in-time financial backtests. A missing metadata/table response remains empty rather than producing a company identity, multiple or price. Fund source identity remains metadata-driven; querying company metadata does not enable corporate-statement or earnings calls for an ETF.

Source `fetched_at` records retrieval time. The source index is a bar start/session label, retained as `session_label`; it does not imply that a candle's high, low and close were known then. Snapshot `as_of` uses explicit `Bar End` or the shared conservative daily availability boundary. Prior-bar reversal evidence compares each close against its own period's band: the prior close must be below `previous_bollinger_lower`, and the completed current close must recover above the current lower band. Today's moving band cannot establish yesterday's breach.

## Verification

Offline tests cover all six reference states, insufficient/missing inputs, single-ADX and single-volatility safeguards, partial 252-session confidence, benchmark contradictions, finite JSON, exact decision-time boundaries, incomplete final candles, explicit short session closes, future-prefix invariance, conservative daily/weekly exclusion, daylight-saving cutoffs, missing timeframes, contradictory directions and invariance to additional nested confirmation frames. Tests use explicit synthetic fixtures and do not establish strategy profitability or vendor accuracy.
