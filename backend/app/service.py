from datetime import datetime, timedelta, timezone
import logging
import pandas as pd
from app.providers.yahoo import records_frame, validate_ticker, PERIODS
from app.analysis.technical import analyze_technical
from app.analysis.fundamentals import analyze_fundamentals
from app.analysis.valuation import analyze_valuation
from app.analysis.news import analyze_news
from app.analysis.macro import analyze_macro
from app.analysis.scoring import risk_assessment, score_stock
from app.analysis.trade import build_trade_plan
from app.schemas import TradeRequest
from app.utils import number, clean, safe_url, iso_now
from app.instruments import instrument_type, is_fund

log = logging.getLogger(__name__)


def display_history(history, period):
    prices = history["prices"]
    if prices and PERIODS.get(period):
        last = pd.Timestamp(prices[-1]["date"])
        start = last - pd.DateOffset(months=PERIODS[period])
        prices = [p for p in prices if pd.Timestamp(p["date"]) >= start]
    return {**history, "prices": prices, "period": period}


def overview_from(bundle):
    info, prices = bundle["info"], bundle["history"]["prices"]
    last = prices[-1]
    timestamp = number(info.get("regularMarketTime"))
    try:reported_time=datetime.fromtimestamp(timestamp,timezone.utc) if timestamp else None
    except (ValueError,OverflowError,OSError):reported_time=None
    price = number(info.get("regularMarketPrice"))
    last_stamp = datetime.fromisoformat(last["date"])
    company_updated = bundle.get("sections", {}).get("company_info", {}).get("fetched_at") or bundle.get("fetched_at")
    history_updated = bundle["history"].get("fetched_at")
    newer_history = bool(company_updated and history_updated and pd.Timestamp(history_updated) > pd.Timestamp(company_updated))
    now=datetime.now(timezone.utc)
    clock_limit=now+timedelta(minutes=5)
    if reported_time and price and price > 0 and last_stamp <= reported_time <= clock_limit and not newer_history:
        stamp = reported_time
        quote_at = stamp.isoformat()
        precision = "reported trade timestamp"
    else:
        price = last["close"]
        stamp = datetime.fromisoformat(last["date"])
        quote_at = last["date"]
        precision = "daily session label, not exact last-trade time"
    previous = number(info.get("regularMarketPreviousClose")) if precision == "reported trade timestamp" else (prices[-2]["close"] if len(prices)>1 else None)
    change = (price/previous - 1)*100 if price is not None and previous and previous>0 else None
    age_days = (now-stamp.astimezone(timezone.utc)).total_seconds()/86400
    stale = age_days>5 or bundle["history"].get("cache_stale", False) or stamp.astimezone(timezone.utc)>clock_limit
    return {"ticker": bundle["ticker"], "name": info.get("longName") or info.get("shortName") or bundle["ticker"],
            "asset_type": instrument_type(info), "is_fund": is_fund(info),
            "price": price, "change_percent": change, "currency": info.get("currency"), "financial_currency": info.get("financialCurrency"),
            "quote_at": quote_at, "quote_timestamp_precision": "Synthetic fixture timestamp" if bundle.get("synthetic") else precision, "quote_type": "SYNTHETIC demonstration quote" if bundle.get("synthetic") else "Delayed / last reported; not a real-time feed",
            "stale": stale, "quote_age_days": round(age_days,2), "source": bundle["history"]["source"], "fetched_at": company_updated if precision == "reported trade timestamp" else history_updated,
            "sector": info.get("sector"), "industry": info.get("industry"), "market_cap": number(info.get("marketCap")),
            "shares_outstanding": number(info.get("sharesOutstanding")), "exchange": info.get("fullExchangeName") or info.get("exchange"),
            "exchange_timezone": info.get("exchangeTimezoneName") or "Unknown", "description": info.get("longBusinessSummary"),
            "website": safe_url(info.get("website")), "analyst_targets": bundle.get("analyst_targets", {}),
            "company_calendar": bundle.get("company_calendar", {}), "earnings_history": bundle.get("earnings_history", []),
            "earnings_estimates": bundle.get("earnings_estimates", [])}


class ResearchService:
    def __init__(self, provider, store, settings):
        self.provider, self.store, self.settings = provider, store, settings
        self.analysis_cache = {}

    def technical(self, ticker, period="1y"):
        ticker = validate_ticker(ticker)
        history = self.provider.history(ticker, period)
        result = analyze_technical(records_frame(history["prices"]))
        result["ticker"] = ticker
        result["source_metadata"] = {"status": "cached" if history.get("from_cache") else "available", "fetched_at": history.get("fetched_at"), "cache_stale": history.get("cache_stale", False), "error": history.get("upstream_error")}
        if history.get("cache_stale"):
            result["confidence"] *= .25
            result["limitations"].append(history.get("cache_warning", "Cached prices could not be refreshed."))
        if result.get("series"):
            visible = display_history(history, period)["prices"]
            if visible:
                start = pd.Timestamp(visible[0]["date"])
                result["series"] = [row for row in result["series"] if pd.Timestamp(row["date"]) >= start]
        return clean(result)

    def research(self, ticker, period="1y", config=None, assumptions=None, include_core=True):
        ticker = validate_ticker(ticker)
        config = config or TradeRequest().model_dump(mode="json")
        bundle = self.provider.bundle(ticker, period)
        frame = records_frame(bundle["history"]["prices"])
        overview = overview_from(bundle)
        # Reuse unchanged source computations; macro and plans remain time-sensitive.
        cache_key = (ticker, bundle["history"].get("fetched_at"), bundle.get("fetched_at"), str(assumptions))
        if cache_key in self.analysis_cache:
            technical, fundamentals, valuation, news, risk = self.analysis_cache[cache_key]
        else:
            technical = analyze_technical(frame)
            fundamentals = analyze_fundamentals(bundle.get("statements", {}), bundle.get("info", {}))
            valuation_info = {**bundle.get("info", {}), "currentPrice": overview["price"], "regularMarketPrice": overview["price"]}
            valuation = analyze_valuation(valuation_info, fundamentals, assumptions)
            news = analyze_news(bundle.get("articles", []))
            news["upcoming_events"] = bundle.get("company_calendar", {})
            risk = risk_assessment(frame, fundamentals)
            if len(self.analysis_cache)>64:
                self.analysis_cache.clear()
            self.analysis_cache[cache_key] = (technical, fundamentals, valuation, news, risk)
        technical, fundamentals, valuation, news, risk = clean([technical, fundamentals, valuation, news, risk])
        if is_fund(bundle.get("info", {})):
            risk["score_basis"] = "historical_price_risk"
            risk["limitations"] = ["Fund risk here covers historical price volatility and drawdown only; holdings concentration, tracking difference and fund liquidity are not assessed."]
        if str(bundle.get("info", {}).get("marketState", "")).upper() == "REGULAR":
            technical["limitations"].append("Latest daily candle may be incomplete during the active session; its signals are provisional until close.")
            technical["confidence"] *= .8
        macro = analyze_macro(self.store.events(), {**bundle.get("info", {}), "symbol": ticker}, config["horizon"])
        categories = {"financial": fundamentals, "valuation": valuation, "technical": technical, "news": news, "macro": macro, "risk": risk}
        if overview["stale"]:
            for key in ("technical", "valuation", "risk"):
                categories[key]["confidence"] *= .25
                categories[key].setdefault("limitations", []).append("Quote source is stale; interpretation has reduced confidence.")
        sections = bundle.get("sections", {})
        for key, section in (("financial", "statements"), ("valuation", "company_info"), ("news", "news")):
            categories[key]["source_metadata"] = sections.get(section, {})
            if sections.get(section, {}).get("cache_stale"):
                categories[key]["confidence"] *= .5
                categories[key].setdefault("limitations", []).append("This section uses dated cached evidence after a failed refresh.")
        technical["source_metadata"] = sections.get("history", {})
        score = score_stock(categories, config.get("weights"))
        score["ticker"] = ticker
        if is_fund(bundle.get("info", {})):
            score["applicable"] = False
            score["limitations"].append("Company quality and the company-stock attractiveness model are not applicable to this fund. Price-based technical analysis and measured market risk remain available.")
        plan = build_trade_plan(overview, technical, valuation, macro, score, config)
        plan["ticker"] = ticker
        if is_fund(bundle.get("info", {})):
            plan["limitations"].append("Company-score-based trade candidates are unavailable for funds; any technical levels shown are illustrative and have no allocated shares.")
            plan["calculation"].insert(0, "This is a fund: the company-score model does not apply. Technical levels are illustrative; no company-based buy candidate or position size is inferred.")
        history = display_history(bundle["history"], period)
        if technical.get("series") and history["prices"]:
            start = pd.Timestamp(history["prices"][0]["date"])
            technical["series"] = [row for row in technical["series"] if pd.Timestamp(row["date"]) >= start]
        limitations = list(bundle.get("limitations", []))
        for item in categories.values():
            limitations.extend(item.get("limitations", []))
        mode = "synthetic demo" if self.settings.demo else "live provider"
        if self.settings.demo:
            limitations.insert(0, "SYNTHETIC DEMONSTRATION DATA — not a real company or actual market data.")
        response = {"ticker": ticker, "as_of": iso_now(), "overview": overview, "history": history,
                    "technical": technical, "fundamentals": fundamentals, "valuation": valuation, "news": news, "macro": macro, "risk": risk,
                    "score": score, "trade_plan": plan, "data_quality": {"mode": mode, "limitations": list(dict.fromkeys(limitations)), "coverage": score["coverage"], "sections": sections}}
        limitations.extend(score["limitations"])
        response["data_quality"]["limitations"] = list(dict.fromkeys(limitations))
        if include_core:
            from app.analysis.quantitative import build_quant_core,source_zone
            from app.providers.bar_times import completed_bars
            reference=None
            benchmark_ticker=config.get('benchmark_ticker','SPY')
            cached=self.store.cache_get(f'yahoo:history:{benchmark_ticker}:5y:1d')
            if cached and cached['age']<=self.settings.history_cache_seconds and overview.get('currency') in (None,'USD'):
                reference=completed_bars(records_frame(cached['value']['prices']),'1d',source_zone(bundle.get('info',{})))
            core_config={**config,'valuation_assumptions':assumptions} if assumptions else config
            response['quant_core']=build_quant_core(bundle,response,core_config,reference)
            response['score']=response['quant_core']['score_adapter']
            response['trade_plan']=response['quant_core']['recommendation']
            response['valuation']=response['quant_core']['valuation']
            response['data_quality']['coverage']=response['score']['coverage']
            response['data_quality']['limitations']=list(dict.fromkeys(response['data_quality']['limitations']+response['quant_core']['evidence']['limitations']+response['score']['limitations']))
        response["report"] = {"markdown": render_report(response), "generator": "Deterministic evidence synthesis", "llm_used": False}
        return clean(response)


def render_report(data):
    o=data['overview']
    core=data.get('quant_core',{})
    score,plan=core.get('score_adapter',data['score']),core.get('recommendation',data['trade_plan'])
    def n(v):
        return f"{v:.2f}" if isinstance(v, (float, int)) else "Unavailable"
    def pct(v):return f"{v:.2%}" if isinstance(v,(float,int)) else 'Unavailable'
    def levels(v):return ' / '.join(n(x) for x in v) if isinstance(v,(list,tuple)) and v else 'Unavailable'
    def performance(v):
        if not v:return 'Unavailable'
        return f"{v.get('number_of_trades',0)} trades; win rate {pct(v.get('win_rate'))}; net total return {pct(v.get('total_return'))}; maximum drawdown {pct(v.get('maximum_drawdown'))}; profit factor {n(v.get('profit_factor'))}; average holding {n(v.get('average_holding_bars'))} sessions"
    sections = [f"# {o['ticker']} — EquityLens Research", f"Generated {data['as_of']} • {data['data_quality']['mode']}",
        "## Executive summary", f"{o['name']}: {plan['recommendation']}. Investment attractiveness {n(score['overall'])}/10; company quality {n(score['company_quality'])}/10. Confidence {score['confidence']:.0%}, available category weight {score['coverage']:.0%}.",
        f"Quoted price: {n(o['price'])} {o.get('currency') or '(currency unavailable)'}. Source: {o['source']}; timestamp {o['quote_at']} ({o['quote_timestamp_precision']}). {o['quote_type']}."]
    if o.get("is_fund"):
        sections.append(f"Instrument type: {o.get('asset_type')}. Corporate financial statements, company quality and corporate DCF are not applicable; no fund attractiveness model is implied.")
    if core:
        sections.extend(["## Market regime and decision timing",f"{core['regime']['regime']}. Completed decision candle available at {core['source'].get('decision_bar_as_of')}. Chart candles may include a newer provisional session."])
    for key, label in [("fundamentals", "Company fundamentals"), ("valuation", "Valuation"), ("technical", "Technical outlook"), ("news", "News assessment"), ("macro", "Macroeconomic outlook"), ("risk", "Risks")]:
        category = core.get('valuation',data[key]) if key=='valuation' else core.get('technical_assessment',data[key]) if key=='technical' else data[key]
        sections += [f"## {label}", f"Score {n(category.get('score'))}/10, confidence {category.get('confidence',0):.0%}."]
        sections.extend(f"- {signal}" for signal in category.get("signals", []))
        if key=='valuation' and core:
            scenario=category.get('valuation_range') or {}
            sections.append(f"V2 basis: {category.get('score_basis') or 'Insufficient valuation evidence'}. Bear/base/bull scenarios: {levels([scenario.get(k) for k in ('bear','base','bull')])}; margin of safety: {pct(category.get('margin_of_safety'))}.")
        if key == "fundamentals":
            sections.append(f"Latest annual reporting date: {category.get('reporting_date') or 'Unavailable'}. Financial reporting currency: {o.get('financial_currency') or 'unknown'}.")
        if key == "news":
            for article in category.get("articles", [])[:8]:
                url = safe_url(article.get("url"))
                if url:
                    sections.append(f"- [{article.get('title','Source')}]({url}) — {article.get('publisher') or 'publisher unknown'}, {article.get('published_at') or 'time unknown'}; scope {article.get('content_scope','headline')}.")
    sections += ["## Upcoming economic catalysts"]
    for event in data["macro"].get("upcoming_events", [])[:10]:
        sections.append(f"- {event.get('title')}: {event.get('scheduled_at') or 'time not specified'} ({event.get('impact')} expected impact). [Forex Factory](https://www.forexfactory.com/calendar)")
    if not data["macro"].get("upcoming_events"):
        sections.append("No upcoming events in the imported coverage. This is not evidence that no events are scheduled.")
    sections += ["## Conditional investment plan", f"{plan['status']}. Entry zone {levels(plan['entry_zone'])}; targets {levels(plan['targets'])}; invalidation {n(plan['stop'])}; net reward/risk {n(plan['risk_reward'])}; additional whole shares {plan['position_size']}."]
    sections.extend(f"- {s}" for s in plan["calculation"] + plan["invalidation"] + plan["event_warnings"])
    sections += ["## Final ratings and contributions"]
    for c in score["categories"]:
        sections.append(f"- {c['label']}: {n(c['score'])}/10 × {c['weight']:.0%}; raw weighted contribution {n(c['contribution'])}; confidence {c['confidence']:.0%}.")
    if core:
        sections += ['## Strategy eligibility and evidence']
        for strategy in core.get('strategies',[]):
            sections.append(f"### {strategy['name']}: {strategy['status']}")
            sections.append(f"Entry {levels(strategy.get('entry_zone'))}; stop {n(strategy.get('stop'))}; targets {levels(strategy.get('targets'))}; net reward/risk {levels(strategy.get('net_reward_risk'))}. {strategy.get('entry_condition')}")
            sections.extend(f"- {s}" for s in strategy.get('evidence',[])+strategy.get('avoid_reasons',[])+strategy.get('calculation',[]))
        if core.get('probabilities'):
            probability=core['probabilities']
            sections += ['## Historical probability evidence',f"{probability.get('status')}; comparable sample size {probability.get('sample_size')}; minimum {probability.get('min_samples')}."]
            for key,value in probability.get('estimates',{}).items():
                interval=probability.get('confidence_intervals',{}).get(key)
                bounds=[interval.get('lower'),interval.get('upper')] if isinstance(interval,dict) else interval
                ci=' to '.join(pct(x) for x in bounds) if isinstance(bounds,(list,tuple)) else 'Unavailable'
                sections.append(f"- {key.replace('_',' ').capitalize()}: {n(value) if key=='expected_holding_bars' else pct(value)}; 95% interval {ci}.")
            sections.extend(f"- {s}" for s in probability.get('limitations',[]))
        for strategy_id,result in core.get('validation',{}).get('strategies',{}).items():
            sections.append(f"Historical {strategy_id.replace('_',' ')}: {result.get('status')}. Full sample: {performance(result.get('metrics'))}. Holdout: {performance((result.get('out_of_sample') or {}).get('metrics'))}. Descriptive past performance, not expected future returns.")
    sections += ["## Confidence and data limitations"]
    sections.extend(f"- {s}" for s in data["data_quality"]["limitations"])
    if core:sections.extend(f"- {s}" for s in core.get('evidence',{}).get('limitations',[]))
    sections += ["Research and decision support only. No return is guaranteed. Historical measurements and backtests do not establish future performance."]
    return "\n\n".join(sections)
