"""Known synthetic arithmetic and cross-stock isolation; no market/network requests."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.providers.yahoo import DataUnavailable
from app.screener.schemas import LONG_WEIGHTS, SHORT_WEIGHTS, ScreenRequest
from app.screener.scenarios import conditional_scenarios
from app.screener.scoring import calculate_scores, rank_rows
from app.screener.service import TechnologyScreenerService, evaluate_row


@pytest.fixture
def evidence():
    metrics = {"revenue_growth_yoy": .15, "eps_growth_yoy": .1, "operating_margin": .2, "free_cash_flow": 200,
               "fcf_margin": .15, "roic": .15, "debt_to_equity": .5, "current_ratio": 2,
               "revenue_consistency": 1, "net_income": 100}
    financial = {"score": 8, "risk_score": 8, "confidence": .9, "statement_age_days": 120, "reporting_date": "2025-12-31",
                 "metrics": metrics, "group_scores": {"profitability": 8, "cash_generation": 6, "capital_efficiency": 7, "growth": 9}, "limitations": []}
    base = {"overview": {"ticker": "FIXTURE", "name": "Synthetic fixture business", "price": 100, "currency": "USD",
                         "stale": False, "is_fund": False, "quote_at": "2026-06-01T20:00:00Z", "fetched_at": "2026-06-01T20:01:00Z"},
            "fundamentals": financial, "news": {"score": 6, "confidence": .9}, "data_quality": {"sections": {}}}
    indicators = {"rsi": 50, "relative_volume": 1, "atr": 2, "sma_50": 100, "sma_200": 90, "adx": 25}
    strategy = {"id": "trend_following", "status": "eligible", "eligible": True, "risk_reward": 3, "entry_zone": [99, 101],
                "stop": 95, "targets": [120, 140], "position_size": 15, "entry_condition": "Completed synthetic confirmation",
                "evidence": [], "calculation": [], "invalidation": {"kind": "technical", "price": 95, "condition": "Lose confirmed support"}}
    quant = {"technical_assessment": {"group_scores": {"trend": 8}, "indicators": indicators, "confidence": .9, "structure": {}},
             "regime": {"regime": "Strong bullish trend", "confidence": .8}, "strategies": [strategy],
             "valuation": {"score": 8, "confidence": .8, "valuation_range": {"bear": 110, "base": 150, "bull": 180},
                           "margin_of_safety": 1 / 3, "metrics": {"forward_pe": 20}, "limitations": []},
             "recommendation": {"recommendation": "Buy candidate", "best_strategy": "trend_following", "position_size": 15,
                                "entry_zone": [99, 101], "stop": 95, "targets": [120, 140], "risk_reward": 3,
                                "status": "Conditions confirmed", "entry_condition": "Wait for zone", "event_warnings": []},
             "probabilities": {"status": "available", "sample_size": 40, "estimates": {"expected_return": .02}},
             "evidence": {"sample_reliability": {"status": "available", "sample_size": 40}}, "validation": {}}
    return base, quant


def test_horizon_scores_match_independent_known_weighted_calculations(evidence):
    base, quant = evidence
    short = calculate_scores(base, quant, "short_term")
    long = calculate_scores(base, quant, "long_term")
    # Short: trend8, geometry6.5, mean(RSI6, participation5)=5.5,
    # news6, mean(operating-quality7, resilience8)=7.5.
    assert short["overall_score"] == pytest.approx(6.88)
    assert short["scores"]["momentum_volume"] == 5.5
    assert short["scores"]["fundamentals_risk"] == 7.5
    assert short["confidence"] == pytest.approx(.875)
    # Long: operating quality7; valuation8; mean(growth9, consistency10)=9.5;
    # resilience8 and trend8. 2.1 +2 +1.9 +1.2 +0.8 =8.
    assert long["overall_score"] == 8
    assert long["scores"]["growth_outlook"] == 9.5
    assert short["weights"] == SHORT_WEIGHTS
    assert long["weights"] == LONG_WEIGHTS
    assert short["data_completeness"] == long["data_completeness"] == 1


def test_user_weights_apply_to_selected_categories_without_overriding_required_evidence(evidence):
    base, quant = evidence
    weights = {key: float(key == "technical_strength") for key in SHORT_WEIGHTS}
    assert calculate_scores(base, quant, "short_term", weights)["overall_score"] == 8
    quant["technical_assessment"]["indicators"].pop("rsi")
    result = calculate_scores(base, quant, "short_term", weights)
    assert result["overall_score"] is None
    assert "momentum_volume" in result["missing_information"]


def test_missing_category_is_not_assigned_favorable_points_and_reduces_confidence(evidence):
    base, quant = evidence
    base["fundamentals"] = {}
    result = calculate_scores(base, quant, "short_term")
    assert result["scores"]["fundamentals_risk"] is None
    assert result["contributions"]["fundamentals_risk"] is None
    assert result["data_completeness"] == pytest.approx(.85)
    assert result["confidence"] == pytest.approx(.74)
    assert result["overall_score"] == pytest.approx(6.76)
    assert "fundamentals_risk" in result["missing_information"]


@pytest.mark.parametrize("missing", ["financial", "valuation", "growth"])
def test_long_term_requires_business_valuation_and_growth_evidence(evidence, missing):
    base, quant = evidence
    if missing == "financial":
        base["fundamentals"]["group_scores"].pop("profitability")
        base["fundamentals"]["group_scores"].pop("cash_generation")
    elif missing == "valuation":
        quant["valuation"]["score"] = None
    else:
        base["fundamentals"]["group_scores"]["growth"] = None
        base["fundamentals"]["metrics"]["revenue_consistency"] = None
    assert calculate_scores(base, quant, "long_term")["overall_score"] is None


def test_observed_no_setup_is_distinct_from_missing_strategy_inputs(evidence):
    base, quant = evidence
    quant["strategies"][0].update(eligible=False, status="wait")
    observed = calculate_scores(base, quant, "short_term")
    assert observed["setup_score"] == 2
    quant["strategies"][0]["status"] = "insufficient_data"
    missing = calculate_scores(base, quant, "short_term")
    assert missing["setup_score"] is None
    assert "trade_setup_quality" in missing["missing_information"]


def test_etf_company_rankings_abstain_for_both_horizons(evidence):
    base, quant = evidence
    base["overview"]["is_fund"] = True
    for horizon in ("short_term", "long_term"):
        assert calculate_scores(base, quant, horizon)["overall_score"] is None
        row = evaluate_row(base, quant, horizon, ScreenRequest(horizon=horizon).model_dump(mode="json"))
        assert row["eligible_buy"] is False
        assert row["recommendation"] == "Insufficient Evidence"


@pytest.mark.parametrize("stale_kind", ["quote", "history", "statements", "annual_age"])
def test_stale_evidence_blocks_current_buy_and_ranking(evidence, stale_kind):
    base, quant = evidence
    if stale_kind == "quote": base["overview"]["stale"] = True
    elif stale_kind == "annual_age": base["fundamentals"]["statement_age_days"] = 551
    else: base["data_quality"]["sections"][stale_kind] = {"cache_stale": True}
    row = evaluate_row(base, quant, "short_term", ScreenRequest().model_dump(mode="json"))
    assert row["eligible_buy"] is False
    assert row["recommendation"] == "Insufficient Evidence"
    assert row["plan"]["position_size"] == 0
    ranked, excluded = rank_rows([row])
    assert not ranked and excluded[0]["cache_stale"] is True


def strong_short(base, quant):
    base = deepcopy(base)
    quant = deepcopy(quant)
    quant["technical_assessment"]["group_scores"]["trend"] = 10
    quant["technical_assessment"]["indicators"].update(rsi=65, relative_volume=2.5)
    quant["strategies"][0]["risk_reward"] = 4
    base["news"]["score"] = 8
    return base, quant


def test_rank_score_does_not_override_current_plan_calendar_or_historical_gates(evidence):
    base, quant = strong_short(*evidence)
    settings = ScreenRequest().model_dump(mode="json")
    assert evaluate_row(base, quant, "short_term", settings)["eligible_buy"] is True
    quant["recommendation"].update(recommendation="Wait", position_size=0, status="Calendar completeness is unknown")
    blocked = evaluate_row(base, quant, "short_term", settings)
    assert blocked["overall_score"] >= 7
    assert blocked["eligible_buy"] is False
    assert blocked["plan"]["position_size"] == 0
    quant["recommendation"]["recommendation"] = "Buy candidate"
    quant["evidence"]["sample_reliability"]["sample_size"] = 29
    assert evaluate_row(base, quant, "short_term", settings)["eligible_buy"] is False
    quant["evidence"]["sample_reliability"]["sample_size"] = 40
    quant["probabilities"]["estimates"]["expected_return"] = -.01
    assert evaluate_row(base, quant, "short_term", settings)["eligible_buy"] is False


def test_currency_mismatch_never_allocates_shares(evidence):
    base, quant = strong_short(*evidence)
    base["overview"]["currency"] = "HKD"
    row = evaluate_row(base, quant, "short_term", ScreenRequest(capital_currency="USD").model_dump(mode="json"))
    assert row["eligible_buy"] is False
    assert row["plan"]["position_size"] == 0
    assert "currencies differ" in " ".join(row["ranking_explanation"])


def test_long_term_buy_must_use_fundamental_value_plan_not_unrelated_technical_plan(evidence):
    base, quant = evidence
    value = deepcopy(quant["strategies"][0])
    value.update(id="fundamental_value", risk_reward=2.5)
    quant["strategies"].append(value)
    settings = ScreenRequest(horizon="long_term").model_dump(mode="json")
    # A value setup can exist while the current recommendation selected a different strategy.
    # A long-term purchase must not inherit the unrelated technical plan's levels.
    row = evaluate_row(base, quant, "long_term", settings)
    assert row["plan"].get("best_strategy") == "fundamental_value" or row["eligible_buy"] is False


def test_rank_ties_use_confidence_then_ticker_and_do_not_rank_missing_or_stale():
    rows = [{"ticker": "ZZZ", "overall_score": 8, "confidence": .8}, {"ticker": "BBB", "overall_score": 8, "confidence": .9},
            {"ticker": "AAA", "overall_score": 8, "confidence": .9}, {"ticker": "MISSING", "overall_score": None},
            {"ticker": "STALE", "overall_score": 10, "cache_stale": True}, {"ticker": "ZERO", "overall_score": 0,"confidence":.8}]
    ranked, excluded = rank_rows(rows)
    assert [row["ticker"] for row in ranked] == ["AAA", "BBB", "ZZZ", "ZERO"]
    assert [row["rank"] for row in ranked] == [1, 2, 3, 4]
    assert {row["ticker"] for row in excluded} == {"MISSING", "STALE"}
    assert all("rank" not in row for row in rows)


def test_threshold_filters_exclude_missing_numeric_fields_instead_of_assuming_zero():
    rows = [{"ticker": "NOPE", "overall_score": 9, "forward_pe": None, "net_income": None},
            {"ticker": "GOOD", "overall_score": 7, "forward_pe": 20, "net_income": 10,"confidence":.8}]
    ranked, excluded = rank_rows(rows, {"max_forward_pe": 25, "profitable_only": True})
    assert [row["ticker"] for row in ranked] == ["GOOD"]
    assert excluded[0]["ticker"] == "NOPE"


def test_cached_rankings_still_honor_market_industry_and_country_filters():
    rows = [{"ticker": "US_SOFT", "overall_score": 8,"confidence":.8, "industry": "Software", "listing_country": "United States", "country": "United States", "market_cap": 2e9, "average_volume": 2e5},
            {"ticker": "JP_CHIP", "overall_score": 9, "industry": "Semiconductors", "listing_country": "Japan", "country": "Japan", "market_cap": 5e8, "average_volume": 1e4}]
    ranked, _ = rank_rows(rows, {"industries": ["Software"], "countries": ["United States"], "market_cap_min": 1e9, "average_volume_min": 1e5})
    assert [row["ticker"] for row in ranked] == ["US_SOFT"]


def scenario_quant():
    return {"technical_assessment": {"indicators": {"atr": 2}, "structure": {
                "support_zones": [{"price": 100, "lower": 99, "upper": 101, "touches": 3}],
                "resistance_zones": [{"price": 120, "lower": 119, "upper": 121, "touches": 3}, {"price": 140, "lower": 139, "upper": 141, "touches": 3}]}},
            "strategies": [], "regime": {"volatility_regime": "Normal"}, "recommendation": {"recommendation": "Wait"},
            "valuation": {"valuation_range": {"bear": 80, "base": 140, "bull": 180}}}


def test_inactive_scenarios_preserve_structural_levels_and_cost_adjusted_math():
    config = ScreenRequest().model_dump(mode="json")
    scenario = next(row for row in conditional_scenarios(scenario_quant(), config, "short_term") if row["id"] == "support_bounce")
    assert scenario["entry_zone"] == [99.5, 101]
    assert scenario["stop"] == 97
    assert scenario["targets"] == [120, 140]
    outlay = 101 * 1.0005 * 1.0005
    stop = 97 * .9995 * .9995
    target = 120 * .9995 * .9995
    assert scenario["risk_reward"] == pytest.approx((target - outlay) / (outlay - stop))
    assert scenario["position_size"] == 0
    assert scenario["status"] == "Waiting for confirmation"
    rejected = next(row for row in conditional_scenarios(scenario_quant(), {**config, "min_reward_risk": 10}, "short_term") if row["id"] == "support_bounce")
    assert rejected["status"] == "Invalidated"
    assert rejected["entry_zone"] == scenario["entry_zone"] and rejected["stop"] == scenario["stop"] and rejected["targets"] == scenario["targets"]


def test_fundamental_scenario_never_labels_multiyear_valuation_as_short_term_target():
    scenario = next(row for row in conditional_scenarios(scenario_quant(), ScreenRequest().model_dump(mode="json"), "short_term") if row["id"] == "fundamental_accumulation")
    assert scenario["status"] in ("Not applicable", "Insufficient evidence") or "years" in scenario["holding_horizon"]
    assert scenario["position_size"] == 0


@pytest.mark.parametrize("changes", [{"weights": {"technical_strength": 1}}, {"weights": {**SHORT_WEIGHTS, "news_catalysts": .1}}, {"weights": {**SHORT_WEIGHTS, "news_catalysts": float('nan')}}, {"existing_shares": 5}, {"capital": -1}])
def test_invalid_weight_money_and_unscoped_position_inputs_rejected(changes):
    with pytest.raises(ValidationError): ScreenRequest(**changes)


def test_custom_weights_and_existing_position_ticker_normalize():
    request = ScreenRequest(weights={key: float(key == "technical_strength") for key in SHORT_WEIGHTS}, existing_shares=5, position_ticker="orcl")
    assert request.position_ticker == "ORCL"
    assert sum(request.weights.values()) == 1


def test_custom_horizon_weights_do_not_leak_into_other_horizon(evidence):
    base, quant = evidence
    selected = {key: float(key == "technical_strength") for key in SHORT_WEIGHTS}
    request = ScreenRequest(weights=selected).model_dump(mode="json")
    short = evaluate_row(base, quant, "short_term", request)
    long = evaluate_row(base, quant, "long_term", request)
    assert short["weights"] == selected
    assert long["weights"] == LONG_WEIGHTS
    assert long["overall_score"] == 8


def test_existing_position_is_applied_only_to_its_stock_in_both_worker_horizons(evidence, monkeypatch):
    import app.screener.service as module
    base_fixture, quant_fixture = evidence
    calls = []
    class Store:
        published = None
        def screening_runs(self, **kwargs): return []
        def cache_set(self, *args): pass
        def save_screening(self, run_id, payload, status, **kwargs):
            if kwargs.get("published"): self.published = deepcopy(payload)
    class Provider:
        def bundle(self, ticker, *args):
            return {"ticker": ticker, "info": {"quoteType": "EQUITY", "country": "United States", "exchangeTimezoneName": "UTC"}, "history": {"prices": []}}
        def history(self, *args): raise DataUnavailable("Synthetic benchmark unavailable")
    class Base:
        def research(self, ticker, **kwargs):
            result = deepcopy(base_fixture)
            result["overview"].update(ticker=ticker, name=f"Synthetic {ticker}", market_cap=2e9)
            return result
    class Quant:
        def analyze(self, ticker, config):
            calls.append((ticker, "short", config["existing_shares"]))
            result = deepcopy(quant_fixture)
            result["event_risk"] = {"blocked": False, "coverage_status": "incomplete", "warnings": []}
            return result
    def long_core(bundle, base, config, *args):
        calls.append((bundle["ticker"], "long", config["existing_shares"]))
        result = deepcopy(quant_fixture)
        result["event_risk"] = {"blocked": False, "coverage_status": "incomplete", "warnings": []}
        result["evidence"]["limitations"] = []
        return result
    monkeypatch.setattr(module, "build_quant_core", long_core)
    members = [{"ticker": ticker, "name": f"Synthetic {ticker}", "market_cap": 2e9, "average_volume": 1e6,
                "industry": "Software", "listing_country": "United States"} for ticker in ("AAA", "BBB")]
    universe = SimpleNamespace(discover=lambda filters: {"members": members, "source": "Synthetic fixture", "coverage": {}})
    store = Store()
    controller = TechnologyScreenerService(Provider(), universe, Base(), Quant(), store, SimpleNamespace(screener_request_delay=0))
    try:
        payload = {"job": {"id": "fixture-run", "status": "queued", "deep_processed": 0},
                   "configuration": ScreenRequest(existing_shares=5, position_ticker="aaa", max_deep_analysis=2).model_dump(mode="json"),
                   "provider_errors": [], "results": {}}
        controller._run(payload)
        assert payload["job"]["status"] == "completed", payload["provider_errors"]
        assert calls == [("AAA", "short", 5), ("AAA", "long", 5), ("BBB", "short", 0), ("BBB", "long", 0)]
        assert store.published is not None
    finally:
        controller.close()
