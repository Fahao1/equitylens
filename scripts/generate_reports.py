"""Generate dated examples only from actual Yahoo observations (or clearly dated cache)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import get_settings
from app.storage import Store
from app.providers.yahoo import YahooFinanceProvider
from app.service import ResearchService

settings=get_settings()
if settings.demo:
    raise SystemExit('Disable EQUITYLENS_DEMO before generating actual-data sample reports.')
store=Store(settings.database_url)
service=ResearchService(YahooFinanceProvider(store,settings),store,settings)
out=Path(__file__).resolve().parents[1]/'docs'/'reports'
out.mkdir(exist_ok=True,parents=True)
for ticker in ('AAPL','MSFT','NVDA'):
    report=service.research(ticker)
    path=out/f'{ticker}.md'
    path.write_text(report['report']['markdown'])
    print(f'{ticker}: saved actual-source report; quote as of {report["overview"]["quote_at"]}')
