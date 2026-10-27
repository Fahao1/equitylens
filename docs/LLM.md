# Optional AI news synthesis

EquityLens calculations and its deterministic research report work without an AI key. The optional adapter in `backend/app/analysis/llm.py` adds a source-linked narrative to saved reports; it has no access to scoring, indicators, financial formulas, trade levels, sizing or brokerage actions.

Configure server-side environment variables:

```dotenv
EQUITYLENS_LLM_API_KEY=your-private-api-key
EQUITYLENS_LLM_MODEL=gpt-4.1-mini
EQUITYLENS_LLM_BASE_URL=https://api.openai.com/v1
```

Keep keys out of source control and the browser. A custom endpoint must use HTTPS without URL credentials or query parameters. Configuring an endpoint authorizes sending the selected headlines/summaries to that provider. Keys are sent only in the authorization header. Adapter failures never return or log response bodies, request headers, key values or exception strings.

The adapter uses the [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) and [strict Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), with `store:false`, no tools, a maximum of 1800 output tokens, a 20-second HTTP timeout (5-second connection timeout), and no automatic retries. `store:false` disables stored Responses; it is not a blanket claim about all provider retention policies. Consult the provider's applicable account settings and terms. No live paid request is part of the automated tests.

Only up to eight source-linked articles are sent. Each has a headline limited to 300 characters and summary limited to 1800 characters, plus publisher/date/source URL. Full articles are neither fetched nor claimed to have been read. Source text is transmitted as untrusted JSON data separately from instructions. Publisher instructions embedded in source text are not trusted. Output Markdown/HTML and arbitrary links from the model are escaped; clickable citations are constructed locally from validated input URLs.

Every generated claim must reference known source IDs and contain an exact supporting excerpt from the bounded text actually sent. Each cited source needs its own excerpt. Excerpts across all claims have an aggregate 25-word limit per source. Shared four-word runs copied into claim text also consume this budget; this conservative check can reject otherwise usable wording. Unknown sources, missing/altered excerpts, unexpected fields, oversized replies, empty/unusable output, tool requests, refusals, incomplete responses and HTTP failures all fail closed to the deterministic report. Business implications are labeled **Hypothesis**; direct reported statements are labeled **Reported evidence**. Model narrative cannot update calculations.

Exact excerpt validation verifies provenance, not logical entailment. A model can still misinterpret a real passage, overlook context or attach an irrelevant excerpt to a claim. The saved narrative carries that limitation and invites inspection of the original sources. Headline sentiment, causal relationships and future returns remain uncertain.

The report route is responsible for caching a validated synthesis by article content/model so saving an unchanged report does not repeatedly purchase identical summaries. The adapter itself makes at most one request per invocation and never calls a provider when no key or usable source-linked news exists.

Tests use `httpx.MockTransport` and cover payload/timeout/storage flags, valid citations and scope labels, hypothetical language, output escaping, unknown source IDs, fabricated excerpts, per-source quotation budgets, missing credentials/news, input bounds, refusal/incomplete output, outages and credential non-disclosure.
