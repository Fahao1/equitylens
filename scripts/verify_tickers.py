"""Opt-in fresh Yahoo checks. Network calls are deliberately excluded from CI.

Run from any working directory with the repository Python environment. Each run
uses a new temporary database and yfinance cache, never the app's saved snapshots.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.providers.yahoo import DataUnavailable, YahooFinanceProvider, validate_ticker
from app.service import ResearchService
from app.storage import Store
from app.utils import clean, iso_now

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "ORCL", "TSLA", "AMD", "AMZN", "GOOGL", "META", "PLTR", "SOFI", "TSM", "JPM", "BRK-B"]


class ObservedProvider(YahooFinanceProvider):
    """Retain only the latest source bundle for the verification evidence."""
    def bundle(self, ticker, period="1y"):
        self.last_bundle = super().bundle(ticker, period)
        return self.last_bundle


def verify(tickers: list[str], output: Path, delay: float = .5) -> dict:
    canonical = list(dict.fromkeys(validate_ticker(ticker) for ticker in tickers))
    report = {
        "started_at": iso_now(), "finished_at": None,
        "mode": "intentional live verification; no synthetic fallback",
        "cache_policy": "New temporary SQLite database and yfinance cache for this run; no pre-existing application snapshot can satisfy a request.",
        "execution": "Sequential tickers with at least 0.5 seconds between symbols; provider performs only its own bounded retries.",
        "requested_tickers": canonical, "results": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="equitylens-live-check-") as folder:
        work = Path(folder)
        settings = Settings(_env_file=None, database_url=f"sqlite:///{work / 'verification.db'}", data_dir=work / "provider-cache", demo=False,
                            background_refresh=False, llm_api_key=None, api_token=None)
        store = Store(settings.database_url)
        provider = ObservedProvider(store, settings)
        service = ResearchService(provider, store, settings)
        try:
            for index, ticker in enumerate(canonical):
                started = time.monotonic()
                try:
                    data = service.research(ticker, period="1y")
                    source = provider.last_bundle
                    prices = source["history"]["prices"]
                    overview, score, plan = data["overview"], data["score"], data["trade_plan"]
                    selection_matches = data["ticker"] == overview["ticker"] == ticker and score.get("ticker") == ticker and plan.get("ticker") == ticker and plan.get("quoted_price") == overview["price"]
                    record = {
                        "ticker": ticker, "verified_at": iso_now(), "status": "retrieved",
                        "elapsed_seconds": round(time.monotonic() - started, 2), "company": overview.get("name"),
                        "source": overview.get("source"), "quote_price": overview.get("price"), "currency": overview.get("currency"),
                        "quote_at": overview.get("quote_at"), "quote_type": overview.get("quote_type"), "quote_stale": overview.get("stale"),
                        "bars_retrieved": len(prices), "bars_displayed_1y": len(data["history"]["prices"]),
                        "history_fetched_at": source["history"].get("fetched_at"), "history_cache_stale": source["history"].get("cache_stale", False),
                        "latest_bar": prices[-1] if prices else None,
                        "statement_periods": {key: len(rows) for key, rows in source.get("statements", {}).items()},
                        "fundamentals_available": bool(data["fundamentals"].get("periods")),
                        "company_metadata_available": bool(source.get("info", {}).get("longName") or source.get("info", {}).get("shortName")),
                        "articles_returned": len(source.get("articles", [])),
                        "technical_score": data["technical"].get("score"), "financial_score": data["fundamentals"].get("score"),
                        "investment_score": score.get("overall"), "company_quality": score.get("company_quality"),
                        "recommendation": plan.get("recommendation"), "trade_quoted_price": plan.get("quoted_price"),
                        "selected_ticker_matches": selection_matches,
                        "sections": source.get("sections", {}),
                        "source_limitations": source.get("limitations", []),
                    }
                    if not selection_matches:
                        record.update(status="failed", error_code="ticker_selection_mismatch", error="Research identity or trade quote did not match the requested ticker.")
                    elif source["history"].get("cache_stale"):
                        record.update(status="failed", error_code="fresh_history_unverified", error="A stale history snapshot cannot establish fresh retrieval.")
                    elif not record["company_metadata_available"] or not record["fundamentals_available"]:
                        record["status"] = "partial"
                except Exception as exc:
                    record = {"ticker": ticker, "verified_at": iso_now(), "status": "failed", "elapsed_seconds": round(time.monotonic() - started, 2),
                              "error_type": type(exc).__name__, "error_code": exc.code if isinstance(exc, DataUnavailable) else "unexpected_error", "error": str(exc)}
                report["results"].append(clean(record))
                report["finished_at"] = iso_now()
                report["summary"] = {state: sum(row["status"] == state for row in report["results"]) for state in ("retrieved", "partial", "failed")}
                output.write_text(json.dumps(clean(report), indent=2, allow_nan=False) + "\n")
                print(json.dumps({key: record.get(key) for key in ("ticker", "status", "company", "bars_retrieved", "technical_score", "error_code", "elapsed_seconds")}), flush=True)
                if index < len(canonical) - 1:
                    time.sleep(max(.5, delay))
        finally:
            store.engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS, help="Yahoo symbols, sequentially; defaults to 14 diverse US-listed symbols.")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "SEARCH_LIVE_VERIFICATION.json")
    parser.add_argument("--delay", type=float, default=.5, help="Seconds between tickers (minimum 0.5).")
    args = parser.parse_args()
    report = verify(args.tickers, args.output.resolve(), args.delay)
    print(json.dumps({"output": str(args.output.resolve()), "summary": report["summary"]}), flush=True)
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
