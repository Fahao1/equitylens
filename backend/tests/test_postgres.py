"""Runs in CI against PostgreSQL; local SQLite tests do not impersonate this check."""
import os
from uuid import uuid4
from datetime import datetime, timezone
import pytest
from app.storage import Store


@pytest.mark.skipif(not os.getenv('EQUITYLENS_TEST_POSTGRES_URL'),reason='PostgreSQL integration URL not configured')
def test_postgres_persistence():
    store=Store(os.environ['EQUITYLENS_TEST_POSTGRES_URL'])
    ticker='T'+uuid4().hex[:31].upper()
    try:
        store.add_watch(ticker)
        assert any(w['ticker']==ticker and datetime.fromisoformat(w['created_at']).tzinfo for w in store.watchlist())
        key='test:'+uuid4().hex
        store.cache_set(key,{'value':1,'missing':None})
        assert store.cache_get(key)['value']=={'value':1,'missing':None}
        report=store.save_report(ticker,'# Synthetic integration test report')
        assert any(r['id']==report['id'] for r in store.reports())
    finally:
        store.remove_watch(ticker)
        store.engine.dispose()
