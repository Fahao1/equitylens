"""Opt-in synthetic preview cannot be confused with retrieved company data."""
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.providers.demo import DemoProvider, SOURCE
from app.providers.yahoo import DataUnavailable, records_frame
from app.service import ResearchService
from app.storage import Store

NOW = datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc)


def test_demo_is_deterministic_fictional_and_has_no_fake_news_or_events():
    left = DemoProvider(NOW).bundle("AAPL")
    right = DemoProvider(NOW).bundle("AAPL")
    assert left == right
    assert left["info"]["longName"].startswith("Synthetic Research Company")
    assert "Apple" not in json.dumps(left)
    assert "Microsoft" not in json.dumps(left)
    assert left["articles"] == []
    assert left["company_calendar"] == {}
    assert left["history"]["source"] == SOURCE
    assert left["synthetic"] is True
    assert left["analyst_targets"] == {}
    assert DemoProvider(NOW).history("MSFT")["prices"] != left["history"]["prices"]


def test_demo_ohlc_are_positive_consistent_and_never_future():
    provider = DemoProvider(NOW)
    for interval in ("1d", "1wk"):
        history = provider.history("NVDA", period="5y", interval=interval)
        frame = records_frame(history["prices"])
        assert not frame.empty
        assert (frame[["Open", "High", "Low", "Close"]] > 0).all().all()
        assert (frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1)).all()
        assert (frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1)).all()
        assert frame.index.max() < NOW
        assert frame.index.min() >= pd.Timestamp(NOW.date(), tz="UTC") - pd.DateOffset(years=5, days=1)
        assert np.isfinite(frame[["Open", "High", "Low", "Close"]].to_numpy()).all()


def test_demo_statement_math_periods_and_dates():
    provider = DemoProvider(NOW)
    bundle = provider.bundle("MSFT")
    for frequency, count in (("annual", 4), ("quarterly", 5)):
        for kind in ("income", "balance", "cashflow"):
            rows = bundle["statements"][f"{frequency}_{kind}"]
            assert len(rows) == count
            assert all(pd.Timestamp(row["date"], tz="UTC") < NOW for row in rows)
        for income, cashflow in zip(bundle["statements"][f"{frequency}_income"], bundle["statements"][f"{frequency}_cashflow"]):
            assert income["date"] == cashflow["date"]
            values = cashflow["values"]
            assert values["Free Cash Flow"] == pytest.approx(values["Operating Cash Flow"] - abs(values["Capital Expenditure"]))
    assert bundle["info"]["marketCap"] == pytest.approx(bundle["info"]["sharesOutstanding"] * bundle["info"]["regularMarketPrice"])


def test_invalid_ticker_period_and_interval_rejected():
    provider = DemoProvider(NOW)
    for ticker, period, interval in (("bad/<ticker>", "1y", "1d"), ("AAPL", "20y", "1d"), ("AAPL", "1y", "1h")):
        with pytest.raises(DataUnavailable):
            provider.history(ticker, period, interval)


def test_research_service_runs_offline_with_explicit_synthetic_disclosure(tmp_path):
    settings = Settings(demo=True, database_url="sqlite:///:memory:", data_dir=tmp_path)
    store = Store(settings.database_url)
    service = ResearchService(DemoProvider(), store, settings)
    research = service.research("AAPL", period="3mo")
    assert research["data_quality"]["mode"] == "synthetic demo"
    assert any("SYNTHETIC" in limitation for limitation in research["data_quality"]["limitations"])
    assert "Synthetic" in research["overview"]["name"]
    assert research["fundamentals"]["score"] is not None
    assert research["technical"]["score"] is not None
    assert research["valuation"]["score"] is None
    assert research["valuation"]["score_basis"] is None
    assert research["news"]["score"] is None
    assert research["macro"]["score"] is None
    assert "synthetic demo" in research["report"]["markdown"]
    assert len(research["history"]["prices"]) < 100
    json.dumps(research, allow_nan=False)
    store.engine.dispose()
