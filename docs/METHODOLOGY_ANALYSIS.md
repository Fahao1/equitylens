# Analysis methodology

## Version2 update

Current strategy, completion, valuation and risk methods are documented in [the quantitative audit and formulas](QUANT_AUDIT.md), [regime methods](REGIME_METHODS.md) and [shared-strategy validation](STATISTICAL_VALIDATION.md). The indicator and financial mathematics below remain relevant. Former single-plan formulas are retained as audit history; the main dashboard uses the four version2 strategies.

All scores are research heuristics on a 0–10 scale. A score is not a probability of profit. Calculations return null when data is insufficient or a denominator is zero, nonfinite, or economically inappropriate. No metric or event is fabricated to fill a gap. Source freshness and coverage constrain confidence. The implementation and offline tests are in `backend/app/analysis/` and `backend/tests/`.

## Technical calculations

Technical analysis uses daily, split-adjusted OHLC and volume. Invalid bars are excluded without interpolating holidays, missing sessions or closed markets. Yahoo normally supplies split-adjusted prices even with dividend adjustment disabled. A raw split is repaired only when a recorded split ratio closely matches an obvious price discontinuity (within 12% and a greater than 30% gap); already adjusted input is not adjusted twice. This is a conservative repair heuristic and should be checked for unusual corporate actions.

Implemented values:

- SMA 20/50/100/200: complete-window arithmetic average.
- EMA 9/12/21/26/50/200: recursive EMA with alpha `2/(N+1)`, first observed close seed, hidden until N observations. EMA seed conventions differ across vendors.
- MACD: EMA12 minus EMA26; signal EMA9 of available MACD, histogram difference.
- Wilder ATR14: true range max(high−low, abs(high−prior close), abs(low−prior close)); first complete arithmetic mean seed, then `(previous*13 + new)/14`.
- ADX14: Wilder averages of directional movement divided by ATR, then Wilder mean of directional-index difference. ADX measures strength, not direction.
- Ichimoku: 9-session conversion, 26-session baseline; span A average of those lines and span B 52-session high/low midpoint, each shifted 26 bars to its displayed date. No future price is used.
- Parabolic SAR: acceleration starts at .02, increases by .02 up to .2 at new extremes; constrained by prior two highs/lows and reverses at penetration. First value is unavailable.
- RSI14: Wilder mean gains/losses; all-gain RSI100, flat RSI50, hidden during warmup.
- Stochastic 14 %K with 3-bar %D; Stochastic RSI over 14 RSI observations; ROC12; CCI20 with mean absolute deviation and .015 constant; Williams %R14.
- Bollinger20 ±2 population standard deviations; annualized 20-session log-return historical volatility with sample deviation and 252 sessions/year.
- Keltner: EMA20 ±2 ATR14; Donchian20 high/low extrema.
- OBV begins at zero, adds/subtracts volume with close direction. MFI14 uses typical-price direction and volume, flat flows50. CMF20 uses close location within daily range; zero-range bars contribute no signed flow. Volume SMA20/SMA50; relative volume divides latest bar by the previous 20 completed sessions.
- Daily OHLC cannot recover intraday session VWAP. The VWAP field is null, with this limitation disclosed.
- 52-week extrema use up to 252 available sessions, with incomplete coverage identified.

Support and resistance combine five-bar confirmed local pivots and recent 126-session extremes. Pivots require two subsequent completed bars, so the final two bars are not pivot candidates. Nearby levels within 0.5 ATR are clustered. Values below/above the current close are support/resistance respectively. Fibonacci values are 23.6%, 38.2%, 50%, 61.8%, 78.6% retracements of this recent range; these descriptive levels are not predictive evidence. A breakout/breakdown compares the latest close with the preceding 20 completed sessions, excluding the latest bar. A moving-average crossover is reported only when the SMA50−SMA200 sign changes between the two latest bars.

### Technical score

A minimum 50 valid daily bars is required. Correlated indicators are grouped, not treated as independent votes:

1. Trend (50%): mean of price above/below SMA50 (8/2), SMA200 (8/2 when available), five-session EMA50 slope positive/negative (8/2), MACD histogram positive/negative (7/3).
2. Momentum (35%): RSI50–70 gives7; RSI>70 or40–50 gives5; RSI<40 gives3. Oversold does not imply a buy.
3. Participation (15%): CMF>.05 gives7; CMF<−.05 gives3; otherwise5. Missing CMF abstains.

Unavailable groups are excluded with explicit reduced coverage. Technical confidence is `min(1,valid_bars/252) * fraction_of_available_indicator_fields`. ADX≥25 labels a trending regime; lower ADX means a weak trend/range. Volatility affects risk management separately, not a bullish directional vote.

## Financial statements and ratios

Annual and quarterly series retain fiscal period ends. These are not verified publication/filing timestamps and must not enter historical simulation as if known on period-end day. Annual balance/cash-flow records must match income-statement periods within10 days. Annual YoY comparisons require a prior period within45 days of365 days; quarterly QoQ requires a prior period within20 days of91 days; quarterly YoY within45 days of365 days. Missing comparable periods remain unavailable. Percentage growth requires a positive prior denominator, so transitions from losses are described through absolute history instead of misleading percentages.

- Margin = named profit / revenue.
- ROE/ROA = annual net income / average current and prior annual equity/assets. Nonpositive average denominator is unavailable.
- ROIC = operating income ×(1−effective tax rate) / average invested capital. Invested capital = debt+equity−cash. Both annual balances and tax provision / pretax income in0–50% are required.
- Net debt = total debt−cash. Debt-to-equity requires positive equity.
- Current ratio = current assets/current liabilities. Quick ratio = (current assets−inventory)/current liabilities; absent inventory is not assumed zero.
- Interest coverage = operating income / absolute interest expense, with nonzero interest required.
- FCF uses reported Free Cash Flow when available, otherwise OCF−absolute capex. FCF margin=FCF/revenue. Cash conversion=OCF/positive net income.
- Share dilution uses comparable annual diluted/basic average share counts. These are not asserted to equal point-in-time shares outstanding.
- Dividend FCF payout = absolute dividends paid / positive FCF. Missing dividends are not assumed zero.

More than550 days since the latest annual period or180 days since the latest quarter is flagged stale. Financial confidence is the available fraction of eight tracked ratios multiplied by `min(1,550/annual_age_days)` after550 days, floored at.15 for the freshness factor.

### Financial score and resilience

Only ordinary operating companies receive the generic reference scores. Banks, insurers, financial services companies and REITs abstain because regulatory capital, asset quality or FFO baselines are unavailable. Available raw statement history remains visible. These are generic reference assumptions, not claimed peer percentiles.

Each metric linearly interpolates between the points below and is capped at the extreme scores. The financial score equally averages available growth, profitability, cash generation and capital efficiency groups; at least two groups are required.

- Revenue growth: −20%=0;0%=4;10%=7;25%=10.
- EPS growth: −30%=0;0%=4;10%=7;30%=10. The growth group averages available revenue/EPS scores.
- Operating margin: −10%=0;0%=3;10%=6;25%=10.
- FCF margin: −10%=0;0%=3;10%=7;25%=10.
- Cash conversion:0=0;.5=3;1=7;1.5=10. The cash-generation group averages available FCF-margin/cash-conversion scores.
- ROIC:0%=1;8%=5;15%=8;25%=10.

Financial resilience is separate from those groups and equally averages available leverage/liquidity/coverage scores, requiring at least two components:

- Debt/equity:0=10;.5=8;1=6;2=3;4=0.
- Current ratio:0=0;1=4;1.5=7;2.5=10.
- Interest coverage:0=0;2=3;5=7;10=10.
- Nonpositive reported equity contributes a fragility score1, while the undefined debt/equity ratio remains null.

## Valuation

Trailing/forward P/E, PEG, price/sales, price/book and EV/EBITDA are displayed only when available and positive. P/E is unsuitable for nonpositive trailing earnings. Earnings yield may remain negative to disclose losses. FCF yield prefers the vendor freeCashflow snapshot divided by market capitalization, with its potentially unspecified trailing coverage disclosed. Earnings yield is trailing EPS / current quote. Currency mismatch suppresses cross-currency yields and DCF unless a verified conversion is supplied. Dividend yield is annual dividend rate / quote, with vendor trailing annual yield as a fallback; arbitrary field unit assumptions are avoided.

Default valuation scoring uses one yield reference group, preferring FCF yield and falling back to earnings yield, so the two correlated measures do not count as separate votes. Reference yields0%,2%,5%,8%,12% map to scores0,3,6,8,10 by linear interpolation. These absolute hurdle assumptions do not establish that a company is cheap or expensive relative to its industry. Confidence is capped at.45 (.30 for earnings-yield fallback). Historical valuations and peer comparisons are explicitly unavailable without a reliable comparable dataset.

### Optional DCF

DCF is disabled until explicit assumptions are supplied. Inputs are base free cash flow, share count, growth, discount rate, terminal growth and years. Default values within an explicit request are growth5%, discount10%, terminal2%, five years, with base FCF/share count from available source fields. Forecast years1..N use `FCF0*(1+g)^t`; discount each at `(1+r)^t`; terminal value is `FCFN*(1+terminal_growth)/(r−terminal_growth)` at the end of yearN. Discount rate must exceed terminal growth, growth and rates are bounded, and positive FCF/shares are mandatory.

Yahoo OCF less capex is a **levered equity cash-flow proxy**, not verified unlevered FCFF. Therefore this DCF estimates equity value directly and does **not deduct net debt again**. It is unsuitable where financing flows, working capital distortions or nonrepresentative FCF dominate. Terminal-value concentration is exposed.

Conservative scenario reduces growth by3 percentage points and increases discount rate by2; optimistic increases growth by3 and reduces discount rate by1. Terminal growth is unchanged. Base assumptions are shown. If valid, the explicitly assumption-driven valuation score is `clamp(5+10*(base_value/quote−1),0,10)` with confidence capped at.55. Outputs are scenarios, never guaranteed future quotes.

## News

News is analyzed only at the retrieved headline/summary scope. Original publisher, URL, timestamp and supplied summary remain visible. Canonical URLs (tracking query removed) and normalized titles deduplicate exact syndication; rewritten syndication can remain.

The deterministic classifier exposes matched positive/negative phrases. Mixed matches or detected negation become uncertain; no matches becomes neutral. Linked, dated, nonfuture stories within30 days contribute only. Sentiment scores positive7.5, neutral5, negative2.5 are weighted by `exp(−age_days/7)`, provider relevance (default.6 when unverified), and significance1.3 for earnings/guidance/revenue/regulatory/lawsuit/bankruptcy/acquisition phrases. Uncertain stories abstain. Confidence is capped at.65 and depends on total weighted evidence (`min(.65,total_weight/8)`). Scores are not stock-return forecasts, and unknown company relevance is disclosed. No full article has been read; no event date is inferred from an undated headline. LLM use is optional and this deterministic engine reports `llm_used=false`.

## Verification

Offline tests independently check Wilder seed arithmetic and known RSI reference values; expected ATR, ADX, MACD, CCI, Bollinger and Ichimoku calculations; no look-ahead in rolling prefixes; flat/zero-volume data; insufficient history; invalid OHLC; raw versus already adjusted stock splits; date-matched statement ratios; negative/zero denominators; specialized-sector abstention; stale statements; DCF formula and rate constraints; news scope, syndication, recency, negation and future timestamps. These establish calculation behavior, not forecast efficacy or vendor correctness.
