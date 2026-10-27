"""Deterministic fictional data for explicitly enabled, offline UI demonstrations.

This provider never contacts Yahoo, supplies real company metadata, or creates news
or economic events. The requested symbol is only a reproducible scenario seed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.providers.yahoo import DataUnavailable, PERIODS, frame_records, validate_ticker

UTC = timezone.utc
SOURCE = "SYNTHETIC demonstration fixture — not market data"
LIMITATIONS = [
    "SYNTHETIC DEMONSTRATION DATA: prices, company metadata and statements are fictional and cannot support an investment decision.",
    "Ticker labels select deterministic fictional scenarios; they do not identify the actual company's financial results.",
    "Synthetic business-day bars do not follow a real exchange holiday calendar; maximum history is five calendar years.",
    "No company news, analyst estimates, earnings calendar or economic events are fabricated for preview.",
]


class DemoProvider:
    def __init__(self, now: datetime | None = None):
        self.now = now or datetime.now(UTC)
        self.now = self.now.replace(tzinfo=UTC) if self.now.tzinfo is None else self.now.astimezone(UTC)
        self.fetched_at = self.now.isoformat()
        self._history = {}

    def _frame(self, ticker: str) -> pd.DataFrame:
        if ticker in self._history:
            return self._history[ticker].copy()
        end = pd.Timestamp((self.now - timedelta(days=1)).date(), tz="UTC")
        index = pd.bdate_range(start=end - pd.DateOffset(years=5), end=end, tz="UTC")
        seed = int.from_bytes(hashlib.sha256(ticker.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        n = len(index)
        t = np.arange(n)
        log_returns = .00035 + rng.normal(0, .010, n) + .002 * np.sin(t / 23)
        close = (70 + seed % 50) * np.exp(np.cumsum(log_returns))
        opens = np.r_[close[0] * .999, close[:-1]] * np.exp(rng.normal(0, .002, n))
        width = rng.uniform(.003, .012, n)
        high = np.maximum(opens, close) * (1 + width)
        low = np.minimum(opens, close) * (1 - width)
        volume = rng.integers(900_000, 4_500_000, n)
        frame = pd.DataFrame({"Open": opens, "High": high, "Low": low, "Close": close,
                              "Adj Close": close, "Volume": volume, "Dividends": 0.0, "Stock Splits": 0.0}, index=index)
        self._history[ticker] = frame
        return frame.copy()

    def history(self, ticker: str, period: str = "1y", interval: str = "1d") -> dict:
        ticker = validate_ticker(ticker)
        if period not in PERIODS or interval not in ("1d", "1wk"):
            raise DataUnavailable("Supported windows: 3mo, 6mo, 1y, 5y, max; intervals: 1d, 1wk.", "invalid_history_window", 422)
        frame = self._frame(ticker)
        if interval == "1wk":
            last_session = frame.index[-1]
            frame = frame.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Adj Close": "last", "Volume": "sum", "Dividends": "sum", "Stock Splits": "max"}).dropna()
            frame = frame.loc[frame.index <= last_session]
        # Match Yahoo adapter: retain warmup; application crops requested display window.
        return {"prices": frame_records(frame), "fetched_at": self.fetched_at, "source": SOURCE,
                "interval": interval, "period": period, "cache_age_seconds": 0, "cache_stale": False,
                "synthetic": True, "adjustment": "Fictional split-free and dividend-free OHLC; adjusted close equals close."}

    def _statements(self) -> dict:
        # Forty-five days of publication lag prevents future/unpublished fixture periods.
        known = pd.Timestamp(self.now.date() - timedelta(days=45))
        latest_annual_year = known.year if known.month == 12 and known.day == 31 else known.year - 1
        annual_dates = [pd.Timestamp(year=latest_annual_year - i, month=12, day=31) for i in range(4)]
        quarter_dates = pd.date_range(end=known, periods=5, freq="QE-DEC")[::-1]
        statements = {key: [] for key in ("annual_income", "quarterly_income", "annual_balance", "quarterly_balance", "annual_cashflow", "quarterly_cashflow")}
        for frequency, dates in (("annual", annual_dates), ("quarterly", quarter_dates)):
            for i, date in enumerate(dates):
                divisor = 1 if frequency == "annual" else 4
                growth = (1.14 ** (-i)) if frequency == "annual" else (1.14 ** (-i / 4))
                revenue = 6_000_000_000 * growth / divisor
                shares = 100_000_000 * (1.005 ** i)
                net_income = revenue * .18
                income = {"Total Revenue": revenue, "Operating Revenue": revenue, "Gross Profit": revenue * .62,
                          "Operating Income": revenue * .24, "Net Income": net_income,
                          "Pretax Income": revenue * .23, "Tax Provision": revenue * .05,
                          "Interest Expense": revenue * .01, "Diluted EPS": net_income / shares,
                          "Basic EPS": net_income / shares, "Diluted Average Shares": shares,
                          "Basic Average Shares": shares, "Research And Development": revenue * .12}
                balance_growth = growth if frequency == "annual" else growth * 1.07
                balance = {"Total Assets": 8_500_000_000 * balance_growth, "Stockholders Equity": 5_000_000_000 * balance_growth,
                           "Total Debt": 1_600_000_000 * balance_growth, "Long Term Debt": 1_200_000_000 * balance_growth,
                           "Current Debt": 400_000_000 * balance_growth, "Cash And Cash Equivalents": 1_100_000_000 * balance_growth,
                           "Current Assets": 3_000_000_000 * balance_growth, "Current Liabilities": 1_500_000_000 * balance_growth,
                           "Inventory": 200_000_000 * balance_growth}
                cashflow = {"Operating Cash Flow": revenue * .28, "Capital Expenditure": -revenue * .06,
                            "Free Cash Flow": revenue * .22, "Cash Dividends Paid": -revenue * .02,
                            "Repurchase Of Capital Stock": -revenue * .03}
                for kind, values in (("income", income), ("balance", balance), ("cashflow", cashflow)):
                    statements[f"{frequency}_{kind}"].append({"date": date.date().isoformat(), "values": values})
        return statements

    def bundle(self, ticker: str, period: str = "1y") -> dict:
        ticker = validate_ticker(ticker)
        history = self.history(ticker, period)
        latest, previous = history["prices"][-1], history["prices"][-2]
        statements = self._statements()
        income = statements["annual_income"][0]["values"]
        cashflow = statements["annual_cashflow"][0]["values"]
        shares = 100_000_000
        price = latest["close"]
        market_cap = price * shares
        fcf = cashflow["Free Cash Flow"]
        info = {
            "symbol": ticker, "longName": f"Synthetic Research Company · {ticker} scenario",
            "shortName": "Synthetic Research Company", "currency": "USD", "financialCurrency": "USD",
            "sector": "Technology (synthetic fixture)", "industry": "Illustrative enterprise software (fictional)",
            "longBusinessSummary": "A fictional company used to demonstrate EquityLens. All prices, financial statements and metadata in this scenario are synthetic. This is not the real business associated with the ticker label.",
            "exchange": "SYNTHETIC", "fullExchangeName": "Synthetic business-day sequence", "exchangeTimezoneName": "UTC",
            "regularMarketPrice": price, "currentPrice": price, "regularMarketPreviousClose": previous["close"],
            "regularMarketTime": int(pd.Timestamp(latest["date"]).timestamp()),
            "marketCap": market_cap, "sharesOutstanding": shares, "trailingEps": income["Diluted EPS"],
            "trailingPE": price / income["Diluted EPS"], "freeCashflow": fcf,
            "priceToSalesTrailing12Months": market_cap / income["Total Revenue"],
            "priceToBook": market_cap / statements["annual_balance"][0]["values"]["Stockholders Equity"],
            "enterpriseValue": market_cap + 500_000_000,
            "enterpriseToEbitda": (market_cap + 500_000_000) / (income["Operating Income"] + 300_000_000),
            "dividendRate": abs(cashflow["Cash Dividends Paid"]) / shares,
        }
        return {"ticker": ticker, "history": history, "info": info, "statements": statements,
                "articles": [], "company_calendar": {}, "analyst_targets": {}, "earnings_history": [], "earnings_estimates": [],
                "fetched_at": self.fetched_at, "cache_age_seconds": 0, "cache_stale": False,
                "synthetic": True, "source": SOURCE, "limitations": list(LIMITATIONS)}
