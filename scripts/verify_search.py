"""Deliberate fresh Yahoo company-name searches, not a source mapping."""
from pathlib import Path
import sys
import json
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.config import Settings
from app.storage import Store
from app.providers.search import YahooFinanceSearchProvider
from app.utils import iso_now

results=[]
with tempfile.TemporaryDirectory(prefix='equitylens-search-') as folder:
    settings=Settings(_env_file=None,data_dir=Path(folder),background_refresh=False)
    store=Store('sqlite:///:memory:')
    provider=YahooFinanceSearchProvider(store,settings)
    for query in ['ORCL','Oracle','Tesla','Taiwan Semiconductor']:
        try:
            r=provider.search(query)
            result={'query':query,'verified_at':iso_now(),'status':'retrieved','matches':r['results'],'source':r['source'],'fetched_at':r['fetched_at']}
        except Exception as exc:
            result={'query':query,'verified_at':iso_now(),'status':'failed','error':str(exc),'code':getattr(exc,'code',None)}
        results.append(result)
        print(json.dumps(result),flush=True)
    store.engine.dispose()
Path('docs/SEARCH_NAME_VERIFICATION.json').write_text(json.dumps(results,indent=2))
