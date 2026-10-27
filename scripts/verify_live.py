"""Deliberate live checks, separate from deterministic CI; preserves source timestamps."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pathlib import Path
from app.config import get_settings
from app.storage import Store
from app.providers.yahoo import YahooFinanceProvider
from app.utils import iso_now

settings = get_settings()
provider = YahooFinanceProvider(Store(settings.database_url), settings)
results = []
for ticker in ("AAPL", "MSFT", "NVDA"):
    try:
        bundle = provider.bundle(ticker)
        prices = bundle["history"]["prices"]
        result = {"ticker": ticker, "verified_at": iso_now(), "status": "retrieved", "bars": len(prices),
                  "last_bar": prices[-1], "company": bundle.get("info", {}).get("longName"),
                  "statement_periods": {k: len(v) for k,v in bundle.get("statements", {}).items()},
                  "articles": len(bundle.get("articles", [])), "limitations": bundle.get("limitations", [])}
    except Exception as exc:
        result = {"ticker": ticker, "verified_at": iso_now(), "status": "failed", "error": str(exc)}
    results.append(result)
    print(json.dumps(result), flush=True)
Path("docs/LIVE_VERIFICATION.json").write_text(json.dumps(results, indent=2))
