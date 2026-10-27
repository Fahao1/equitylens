# Published-ranking portfolio replay

`backend/app/analysis/screener_backtest.py` replays actual archived ranking vintages. It never rebuilds a historical top5/top10 from today's universe, financial statements, prices, revised events or current screener scores. A newly launched screener therefore has **insufficient historical evidence** until genuine ranking publications and subsequent completed price history accumulate.

## Required evidence

Each replayed snapshot needs an archived ID, timezone-bearing `published_at`, `membership_as_of` no later than publication, the selected `short_term` or `long_term` horizon, `point_in_time:true`, and ranked rows with ticker, positive integer rank, finite score and known currency. A row's supplied score/retrieval timestamp cannot be after publication; stale source evidence cannot certify a valid rank. Metadata provenance is trusted as an archive assertion, not an independent forensic audit of the upstream dataset.

Selected companies need finite positive historical daily Open/Close bars with timezone-aware session labels. Explicit `Bar End` is preferred. Availability is computed before converting the source index to UTC, preserving source-local midnight and daylight-saving changes. An unavailable session is not forward-filled, and a missing or delisted selected company is not dropped or replaced by a surviving company.

Mixed or unknown portfolio currencies fail closed; no FX path is assumed. Supplied benchmark frames likewise require a currency matching the portfolio. Missing/misaligned benchmark prices or currency withhold that comparison without inventing a zero return or invalidating otherwise supported portfolio arithmetic.

## Fixed replay rules

- Top5 or top10 follows published rank order; it is not reranked by subsequent returns.
- The first source-session label strictly after publication is the earliest modeled next-open entry. This is conservative and may skip a same-day pre-open opportunity when only a midnight session label is available. It is not an observed brokerage fill timestamp.
- Rebalance every selected number of archived snapshots. Multiple publications before the same execution session coalesce to the latest publication known before that session. Optional `start`/`end` dates limit the replay period; the latest prior published ranking can initialize the requested start period.
- Fractional-share equal weighting is an explicit research assumption. The engine solves for post-cost equal target values using net trades rather than needlessly liquidating/rebuying unchanged positions.
- A buy uses reference open ×(1+slippage) and commission on the executed amount; a sell uses reference price ×(1−slippage) and its commission. Cash is self-financing. Cost assumptions are user supplied and bounded.
- Final holdings liquidate at the last supported close with selling costs. Historical equity is measured at daily closes. It does not include unknown intraday portfolio ordering or cash dividends.

For an initial all-cash purchase at unchanged prices, terminal capital is exactly:

`initial × (1−slippage) × (1−commission) / ((1+slippage) × (1+commission))`

The test suite independently checks this reference, a 30% cost-free top5/top10 gain, unchanged-membership zero-turnover rebalancing, and publication-gated changes of constituents.

## Outputs and limits

The engine reports portfolio equity, trades, rebalances, transaction costs, total/annualized return, maximum daily-close drawdown, Sharpe ratio and profit factor where defined. Profit factor uses realized sell transactions, including partial rebalances; these are not independent complete strategy bets. A missing denominator returns null.

QQQ and XLK comparisons use supplied matching historical bars only. No provider requests occur inside the replay engine. The API can use existing cached source histories, avoiding unbounded downloads for every archive member. The actual replay start/end and observed session count remain visible; a dated cache is not proof of present-day coverage.

Chronological last30% and fixed walk-forward slices summarize already published replay performance. No parameters are fitted or selected from holdout outcomes. These descriptive slices do not certify a predictive model or remove all temporal dependence. Annualized figures on a short observed period are mathematical extrapolations, not expected future returns.

This experiment is restricted to the discovered/ranked coverage actually archived. It cannot establish a survivorship-free entire-technology-sector history, reconstruct companies omitted by the original discovery provider, or certify backdated membership from a current listing directory. The application returns `Insufficient historical evidence` when required vintages or selected prices are unavailable. No portfolio performance before the archive exists is fabricated.
