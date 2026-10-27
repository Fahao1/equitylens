# Tech Stock Screener and ranking methodology

The new sidebar page extends the existing EquityLens design and research services. It is not a broker or an LLM price predictor. Universe members and all live ranking inputs come from retrieved source data; no famous-stock list supplies rankings. The [universe documentation](SCREENER_UNIVERSE.md) explains source taxonomy, rights, pagination, international scope and an authorized provider-import interface.

## Workflow and coverage

A manual screen returns HTTP202 and starts one background worker. Stage1 discovers and checks source-supplied company metadata across the filtered source universe. Stage2 performs full financial, valuation, technical, regime, multi-timeframe and daily-strategy analysis on a disclosed capitalization/liquidity-prioritized subset (default15, configurable1–50). Capitalization/volume prioritize research workload; they are not fabricated investment scores. Broad-only members remain unranked.

The worker reuses Yahoo caches, serializes company requests, pauses between companies and stops further deep requests on an upstream rate limit. Duplicate refresh clicks attach to the current job instead of creating concurrent Yahoo scans. Failures retain older published evidence. An interrupted job is marked failed on restart and can be retried. Results, configuration, source coverage and publication times are persisted in SQLite/PostgreSQL. GET rankings/status/universe do not initiate provider downloads.

Both horizon results are published from the same run. Only the selected horizon receives its supplied custom weights; the other uses its separate defaults. The saved configuration identifies the profile used. Switching the UI horizon reads the corresponding independent ranking, rather than relabeling a single score. Comparisons use the same horizon/snapshot; rows open the existing research dashboard.

After a manual run, `auto_refresh:true` schedules its configuration every six hours while normal background refresh is enabled. The scheduler resumes after application restart, checks due work every five minutes, avoids overlapping jobs and backs off failed runs. Set `auto_refresh:false` in a refresh request to disable that run's schedule. `EQUITYLENS_SCREENER_AUTO_REFRESH=true` additionally permits a default screen before the first manual run. Environment settings in `.env.example` control the interval, default depth and inter-company delay.

Discovery counts describe equity listings, not independently deduplicated issuers. Multiple share classes can appear separately and increase issuer concentration in a hypothetical portfolio. Complete query pagination does not establish complete sector coverage. Source-defined Technology plus explicitly disclosed internet-platform-adjacent industries is broader than pure Technology; domicile is not inferred from listing region. International market capitalization is not FX-normalized.

## Two distinct scores

Short-term defaults are trend/technical30%, setup25%, momentum/volume15%, news/catalysts15%, operating quality/resilience15%. Long-term defaults are operating quality30%, valuation25%, reported growth/consistency20%, financial resilience15%, technical entry timing10%. User weights must contain every category for that horizon, stay in[0,1] and sum to1. These are research reference weights, not empirically optimized portfolio allocations.

The short technical category uses the existing moving-average/MACD trend family only. RSI and relative volume form one separate momentum/participation category; they are not repeated inside the30% trend category. RSI interpolates[0,30,50,65,80,100] to[1,2,6,8,4,1], penalizing stretched extremes. Relative volume interpolates[0,.7,1,1.5,2.5] to[1,3,5,8,10]; both inputs are required and averaged. The setup category uses cost-aware geometry for an actually eligible shared strategy: `min(10,5+1.5*max(0,R-2))`. A completed evaluation with no confirmed setup receives2 when waiting or0 when every strategy avoids; these describe observed ineligibility. Missing strategy inputs remain null. Current event risk is a gate, not a fabricated positive catalyst score.

Long operating quality averages at least two known profitability/cash-generation/capital-efficiency groups. It deliberately excludes separately scored growth and resilience. Growth outlook averages available reported growth and revenue-consistency scales; it does not claim a verified competitive moat, management skill or future growth forecast. Resilience reuses the financial leverage/liquidity/coverage group. Valuation uses explicit scenarios or sufficient source-bound historical/peer comparisons from the existing engine. Technical entry timing uses the trend family without repeating financial evidence.

A horizon score is `sum(known category score * weight) / known category weight`, requiring at least70% category coverage. Short-term trend and momentum/volume are mandatory. Long-term operating quality, valuation and growth are mandatory. ETFs and mutual funds never enter corporate rankings. Current ranking also requires evidence confidence at least35%, fresh critical sources and requested financial/size/liquidity filters. Missing categories receive no favorable value. Scores sort descending, then confidence, then ticker for deterministic ties. Company quality remains the separate underlying business score.

Evidence confidence weights the relevant source completeness/freshness heuristics; it is not part of the score and is not a win probability. Data completeness, metric count, missing information, source timestamps, reporting dates and model uncertainty remain separate. A snapshot older than the refresh interval loses current ranking/buy eligibility instead of preserving a stale Buy label.

## Recommendations and price levels

A current Buy Candidate needs score at least7, evidence confidence at least60%, fresh critical inputs, matching capital/quote currency and an eligible current investment plan. Short-term candidates additionally require at least30 comparable mature historical observations and positive historical net expectancy. Long-term candidates require the selected fundamental-value plan, company quality at least7, explicit bear/base valuation scenarios and the configured margin of safety (default20%). Generic technical plans cannot supply a long-term value purchase's levels. Existing shares require an explicit position ticker and affect only that security.

Observed scores below4 are Avoid. Scores at least6 without a qualified entry are Watchlist Candidate. Other adequate observations are Wait. Missing/stale mandatory evidence is Insufficient Evidence. The top-ranked stock is separate from the highest-ranked eligible buy. If none qualifies, the page states **No qualified buy candidate found**. Unknown calendar completeness and small historical samples can block every buy without preventing transparent research rankings.

Price scenarios reuse confirmed structure and shared execution arithmetic. Support bounce, breakout, trend reversal, trend continuation and fundamental accumulation remain distinct. Inactive scenarios allocate zero new shares. Support-derived ranges, repeated resistance, preselected ATR buffers, strategy confirmations and all original targets are disclosed. Invalid reward/risk retains the original levels and rejects the scenario; targets/stops are never moved to manufacture a ratio. The reversal scenario is a conditional research hypothesis, not a separately validated strategy success claim.

Execution includes adverse commissions/slippage (default5bps each), the worst proposed entry and whole-share risk/cash caps. Maximum planned loss is modeled, not guaranteed: gaps can exceed it. Short scenarios cover1–63 sessions; fundamental accumulation always carries a multiyear thesis label even when shown beside short-term opportunities. Long business invalidation is separate from a technical capital-risk stop.

Default screening DCF sensitivities explicitly use5% growth,10% discount,2% terminal growth and5 projection years, with bear/base/bull perturbations from the existing model. These are editable assumptions, not predictions. Disable DCF to withhold it; verified matching currencies, positive cash flow and share count are still required. Relative valuation does not supply an intrinsic-value range. Sources that cannot support a fair-value range leave it unavailable.

## APIs and historical validation

- `GET /api/screener/tech/universe`: cached discovery, taxonomy filter choices and coverage.
- `GET /api/screener/tech/rankings?horizon=short_term|long_term`: published ranked/unranked rows, scores, configuration, candidates and evidence.
- `GET /api/screener/tech/top-candidate`, `/watchlist-candidates`, `/status` accept the same horizon.
- `POST /api/screener/tech/refresh`: typed horizon, weights, filters, risk/capital, valuation assumptions, depth and scheduling settings.
- `POST /api/screener/tech/backtest`: top5/top10 replay from archived publications; no current-data historical reranking.

Archived-ranking replay uses publication times, known membership and subsequent completed prices. It models self-financing equal weights, net rebalancing, costs and supplied QQQ/XLK benchmarks with currency checks. The HTTP replay uses existing price caches instead of starting an unbounded mass download. Current-only archives cannot establish historical ranking performance, so results remain Insufficient historical evidence. See [portfolio replay methods](SCREENER_BACKTEST.md).

The screen reuses the [quantitative audit/strategy methods](QUANT_AUDIT.md), [timeframe rules](REGIME_METHODS.md) and [daily strategy statistics](STATISTICAL_VALIDATION.md). Daily technical backtests do not establish long-term fundamental performance. Revised financial/news/macro data is not injected into past decisions. No profitability improvement or calibrated forecast is claimed merely because implementation tests pass.

## Verification and operation

The actual live screen evidence (`SCREENER_LIVE_VERIFICATION.json`, retained locally), universe observations (`SCREENER_UNIVERSE_LIVE_VERIFICATION.json`, retained locally) and startup recovery evidence (`STARTUP_LIVE_VERIFICATION.json`, retained locally) are separate from synthetic test fixtures. Run `.venv/bin/python scripts/verify_screener.py --refresh` intentionally against the live backend to repeat the screen and representative ticker checks. It is not part of offline CI.

For normal Mac use, double-click [EquityLens.command](../EquityLens.command) or open the local URL. The installed LaunchAgent runs a private Application Support runtime and preserves data/settings across code updates. See [startup and data ownership](STARTUP.md) before using a separate development instance or moving the source folder.
