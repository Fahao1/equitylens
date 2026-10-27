# Technology discovery, source rights and coverage

`backend/app/providers/universe.py` separates discovery from individual-company research. It contains no list of popular stocks. Source-supported query taxonomy, listing regions and exchange codes come from yfinance's `EquityQuery.valid_values`; actual tickers come from source responses or an explicitly selected authorized import.

## Live discovery

The adapter uses a custom equity query with:

- Technology-sector membership, plus explicitly declared adjacent Internet Content & Information and Internet Retail queries by default.
- U.S. major listing exchanges by default. International source listing regions/exchanges can be selected explicitly.
- Configurable capitalization, average three-month share volume and industry filters. Defaults are capitalization at least one billion in source-reported units and average volume at least 100,000 shares.
- At most 250 results per page and a default maximum 20 pages per query. Requested offsets, repeated ticker pages, changing totals, early exhaustion, source failures and page limits are checked and disclosed.

The [yfinance screen documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.screen.html) documents custom queries, offsets and the 250-result maximum. Its [EquityQuery reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.EquityQuery.html) lists the source fields and permitted taxonomy. These are library-supported interfaces, not a guarantee of a complete, stable or unrestricted official Yahoo discovery API.

The adapter always reports `comprehensive:false`. `pagination_complete:true` means the requested source pages were exhausted, not that every real technology company was found. Source totals from separate queries may overlap; they are not a unique sector census. Counts of discovered, eligible, excluded and duplicate rows remain separate. A page cap or partial response makes the eligible count a lower bound. No source failure substitutes a fixed list of famous stocks.

Default internet-adjacent scope is deliberately broader than the Technology sector. An internet retailer can be a platform business, but the adapter does not assert that every member is a pure technology company. `technology_scope`, source taxonomy and classification rationale preserve that distinction. Disable `include_tech_adjacent` at the provider level for a strict source Technology-sector view.

Yahoo screener payloads can omit sector, industry and issuer country. The live response verified for this implementation did so. A classification may therefore be established by the exact screening predicate, with `classification_basis` recording both supplied fields and query provenance. An unspecified Technology industry's name stays null; it is not guessed from the company name or an AI theme. Selecting an explicit supported industry submits that industry predicate. Broad AI/cloud/cybersecurity themes are not claimed as separately verified revenue exposures.

Only source-reported EQUITY instruments are accepted. Funds, ETFs, unknown instrument types and explicitly named warrant/preferred/unit/right securities are excluded. Full research verifies instrument identity again. This is a documented instrument-type/name filter, not an assertion of a perfect exchange-level common-stock master.

Country selection means **listing region**, established by source query/exchange mapping. It does not identify issuer domicile. A U.S.-listed ADR can have a non-U.S. issuer country. Missing issuer country remains null. International market capitalization and share volume remain in source units; no FX-normalized capitalization, turnover or return is invented.

## Caching and failures

The filter-specific persistent cache defaults to six hours. Incomplete results have a shorter maximum five-minute freshness window. Requests are serial and use the existing bounded Yahoo retry/error classifier; rate limits stop additional discovery queries. A failed or incomplete refresh can preserve the prior successful membership with its original retrieval timestamp, explicit `cache_stale` warning and new upstream error. It does not become a newly observed current universe.

The library's screen transport controls its own request timeout; the adapter bounds page/attempt counts and does not monkeypatch the shared Yahoo transport. No authentication challenge, denied access or rate limit is bypassed.

## Source rights and alternatives

The [yfinance project notice](https://github.com/ranaroussi/yfinance#readme) describes research/personal-use access and refers users to Yahoo's applicable terms. Library availability does not grant broader redistribution or commercial data rights. This local personal research implementation does not claim a public-data license.

The [official Nasdaq Trader directory definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs) document listing, ETF and test-issue fields. They do not supply technology-sector classifications, and the [Nasdaq Trader copyright notice](https://www.nasdaqtrader.com/Trader.aspx?id=CopyDisclaimMain) does not establish unrestricted parsing, storage or redistribution rights. Consequently this implementation does not silently turn that directory into a redistributed sector master. A separately licensed/authorized listing directory can be integrated through the replaceable discovery interface.

`TechnologyUniverseProvider.import_file(content, format='json'|'csv', source=..., source_as_of=...)` supports an explicitly authorized source export. It persists an import ID. `discover({'universe_source':'import','import_id':...})` applies the same classification, instrument, size, volume and exchange/region filters without a Yahoo discovery call. This is a provider/programmatic import pathway; it is not an undocumented UI upload capability. Required source columns include ticker/symbol, EQUITY quote type, source sector or supported industry, Yahoo-compatible exchange code, capitalization and average volume when those filters are enabled. Unknown values do not pass thresholds. Duplicate tickers are reported and collapsed. Importing a file does not grant rights to redistribute it or certify historical score vintages.

## Recorded live verification

SCREENER_UNIVERSE_LIVE_VERIFICATION.json (`SCREENER_UNIVERSE_LIVE_VERIFICATION.json`, retained locally) records a read of the running application's existing source cache, without another full discovery request. That observed default run discovered 428 unique EQUITY symbols over four pages: 381 Technology-sector matches, 28 Internet Content & Information matches and 19 Internet Retail matches. Its source timestamp is preserved in UTC. Those are current source/filter-specific observations and can change.

Discovery count is separate from deep-analysis count. The screener's serialized worker reports how many members received full financial/technical/valuation research, how many remain broad-only, and which were eligible for ranking. This document does not claim that all 428 companies were deeply analyzed or that the resulting ranks represent the entire sector.
