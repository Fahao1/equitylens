from datetime import datetime
from app.storage import Store


def test_sqlite_timezone_roundtrip_and_revision_order():
    s=Store('sqlite:///:memory:')
    s.add_watch('TEST');s.save_report('TEST','Synthetic fixture')
    assert datetime.fromisoformat(s.watchlist()[0]['created_at']).tzinfo is not None
    assert datetime.fromisoformat(s.reports()[0]['created_at']).tzinfo is not None
    e={'id':'fixture','title':'Synthetic','last_updated':'2026-03-10T12:00:00+00:00','actual':'2'}
    s.import_events([e]);s.import_events([{**e,'last_updated':'2026-03-09T12:00:00+00:00','actual':None}])
    assert s.events()[0]['actual']=='2'
    s.import_events([{'id':'new-fixture','title':'Synthetic replacement'}],replace_existing=True)
    assert len(s.events())==1 and s.events()[0]['id']=='new-fixture'
