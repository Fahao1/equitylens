"""Dynamic search uses explicit synthetic Yahoo mocks; these tests make no requests."""
from copy import deepcopy
from collections import Counter

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.demo import DemoProvider
from app.providers.yahoo import DataUnavailable, YahooFinanceProvider, records_frame, validate_ticker
from app.storage import Store

SYMBOLS = ["AAPL", "MSFT", "NVDA", "ORCL", "TSLA", "AMD", "AMZN", "GOOGL", "META", "PLTR", "SOFI", "TSM", "JPM", "BRK-B"]


def as_statement(records):
    return pd.DataFrame({pd.Timestamp(record["date"]): record["values"] for record in records})


class FixtureTicker:
    calls = Counter()
    fixtures = DemoProvider()

    def __init__(self, symbol):
        self.symbol = symbol
        self.bundle = self.fixtures.bundle(symbol)

    def history(self, **kwargs):
        self.calls[(self.symbol, "history")] += 1
        if self.symbol == "UNKNOWN99":
            return pd.DataFrame()
        if self.symbol == "TIMEOUT99":
            raise TimeoutError("Synthetic connection timeout")
        if self.symbol == "RATELIMIT99":
            class YFRateLimitError(Exception):
                pass
            raise YFRateLimitError("Synthetic Yahoo rate limit")
        return records_frame(self.bundle["history"]["prices"])

    def get_info(self):
        self.calls[(self.symbol, "info")] += 1
        values = deepcopy(self.bundle["info"])
        values["longName"] = f"Fixture company {self.symbol}"
        return values

    def _statements(self, kind, freq):
        if self.symbol == "PARTIAL99" and kind == "income":
            raise ValueError("Synthetic unavailable financial statement")
        return as_statement(self.bundle["statements"][f"{'annual' if freq == 'yearly' else 'quarterly'}_{kind}"])

    def get_income_stmt(self, *, freq, **kwargs):
        return self._statements("income", freq)

    def get_balance_sheet(self, *, freq, **kwargs):
        return self._statements("balance", freq)

    def get_cash_flow(self, *, freq, **kwargs):
        return self._statements("cashflow", freq)

    def get_news(self, **kwargs):
        if self.symbol == "NEWSFAIL99":
            raise TimeoutError("Synthetic optional news timeout")
        return []

    def get_calendar(self):
        return {}

    def get_analyst_price_targets(self):
        return {}

    def get_earnings_history(self):
        return None

    def get_earnings_estimate(self):
        return None


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_url="sqlite:///:memory:", data_dir=tmp_path, demo=False, background_refresh=False, request_limit=1000)
    store = Store(settings.database_url)
    provider = YahooFinanceProvider(store, settings, ticker_factory=FixtureTicker)
    with TestClient(create_app(settings, provider, store)) as http:
        yield http


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_every_requested_symbol_drives_research_price_score_and_plan(client, symbol):
    result = client.get(f"/api/stocks/{symbol}/research")
    assert result.status_code == 200, result.text
    data = result.json()
    expected = FixtureTicker.fixtures.bundle(symbol)
    assert data["ticker"] == data["overview"]["ticker"] == symbol
    assert data["overview"]["name"] == f"Fixture company {symbol}"
    assert data["overview"]["price"] == expected["info"]["regularMarketPrice"]
    assert data["history"]["prices"][-1]["close"] == expected["history"]["prices"][-1]["close"]
    assert data["technical"]["score"] is not None
    assert data["fundamentals"]["score"] is not None
    # V2 withholds a composite when this fixture has no defensible valuation/setup evidence.
    assert data["score"]["overall"] is None
    assert data["score"] == data["quant_core"]["score_adapter"]
    assert data["score"]["company_quality"] is not None
    assert data["trade_plan"]["quoted_price"] == data["overview"]["price"]
    assert data["score"]["ticker"] == symbol
    assert data["trade_plan"]["ticker"] == symbol
    assert data["data_quality"]["mode"] != "synthetic demo"  # Mock adapter, not runtime demo fallback.
    assert symbol in data["report"]["markdown"]


@pytest.mark.parametrize("raw,canonical", [("orcl", "ORCL"), ("brk-b", "BRK-B"), ("0700.hk", "0700.HK"), ("vow3.de", "VOW3.DE"), ("^gspc", "^GSPC")])
def test_case_exchange_suffix_and_hyphen_normalize_without_whitelist(client, raw, canonical):
    assert validate_ticker(raw) == canonical
    response = client.get(f"/api/stocks/{raw}/research")
    assert response.status_code == 200, response.text
    assert response.json()["ticker"] == canonical
    assert response.json()["overview"]["name"] == f"Fixture company {canonical}"


@pytest.mark.parametrize("symbol,expected_code", [("UNKNOWN99", "no_history"), ("TIMEOUT99", "request_timeout"), ("RATELIMIT99", "upstream_rate_limit")])
def test_unknown_timeout_and_rate_limit_remain_distinguishable(client, symbol, expected_code):
    result = client.get(f"/api/stocks/{symbol}/research")
    assert result.status_code in (404, 429, 503, 504), result.text
    assert result.json()["detail"]["code"] == expected_code
    assert "Fixture company AAPL" not in result.text
    assert "synthetic demo" not in result.text.lower()


def test_optional_financial_failure_preserves_available_price_analysis(client):
    result = client.get("/api/stocks/PARTIAL99/research")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["ticker"] == "PARTIAL99"
    assert data["technical"]["score"] is not None
    assert data["fundamentals"]["score"] is None
    assert data["fundamentals"]["periods"] == []
    assert data["overview"]["price"] > 0
    assert any("income" in limitation.lower() or "financial" in limitation.lower() for limitation in data["data_quality"]["limitations"])


def test_switching_symbols_cannot_reuse_previous_company_or_plan(client):
    first = client.get("/api/stocks/AAPL/research").json()
    second = client.get("/api/stocks/ORCL/research").json()
    third = client.get("/api/stocks/AAPL/research").json()
    assert first["overview"]["name"] != second["overview"]["name"]
    assert first["trade_plan"]["quoted_price"] != second["trade_plan"]["quoted_price"]
    assert first["score"]["overall"] == third["score"]["overall"]
    assert first["trade_plan"]["quoted_price"] == third["trade_plan"]["quoted_price"]


def test_optional_news_timeout_does_not_hide_available_price_or_statements(client):
    result = client.get("/api/stocks/NEWSFAIL99/research")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["ticker"] == data["score"]["ticker"] == data["trade_plan"]["ticker"] == "NEWSFAIL99"
    assert data["technical"]["score"] is not None
    assert data["fundamentals"]["score"] is not None
    assert data["news"]["score"] is None
    sections = data["data_quality"]["sections"]
    assert sections["history"]["status"] == "available"
    assert sections["statements"]["status"] == "available"
    assert sections["news"]["status"] == "error"
    assert sections["news"]["error"]["code"] == "request_timeout"
