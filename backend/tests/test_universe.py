"""Universe discovery fixtures are explicitly synthetic; no Yahoo requests are made."""
from datetime import datetime,timedelta,timezone
import json
from types import SimpleNamespace

import pytest

from app.providers.universe import TechnologyUniverseProvider
from app.providers.yahoo import DataUnavailable
from app.storage import Store,Cache


def quote(ticker,**values):
    return {'symbol':ticker,'quoteType':'EQUITY','longName':f'SYNTHETIC {ticker} company',
            'exchange':'NMS','marketCap':2e9,'averageDailyVolume3Month':200000,
            'regularMarketPrice':100,'currency':'USD','trailingPE':20,'epsTrailingTwelveMonths':5,**values}


def scope(query):
    def visit(value):
        if not isinstance(value,dict):return None
        args=value.get('operands',[])
        if args and args[0] in ('sector','industry'):return (args[0],args[1])
        for item in args:
            result=visit(item)
            if result:return result
        return None
    return visit(query.to_dict())


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr('app.providers.yahoo.time.sleep',lambda _:None)
    store=Store('sqlite:///:memory:')
    yield store,SimpleNamespace(universe_cache_seconds=21600)
    store.engine.dispose()


def provider(setup,fetch):
    return TechnologyUniverseProvider(*setup,screen_fetcher=fetch)


def expire(store):
    with store.session.begin() as session:
        for row in session.query(Cache).all():
            row.updated_at=datetime.now(timezone.utc)-timedelta(days=2)


def test_dynamic_pagination_dedup_and_fund_exclusion_without_ticker_whitelist(setup):
    calls=[];rows=[quote('NEWTECH1'),quote('NEWTECH2'),quote('NEWTECH3'),quote('ETF999',quoteType='ETF'),quote('NEWTECH1')]
    def fetch(query,**kwargs):
        calls.append(kwargs)
        start=kwargs['offset'];return {'start':start,'total':len(rows),'quotes':rows[start:start+kwargs['size']]}
    result=provider(setup,fetch).discover({'include_tech_adjacent':False,'page_size':2})
    assert [row['ticker'] for row in result['members']]==['NEWTECH1','NEWTECH2','NEWTECH3']
    assert [row['offset'] for row in calls]==[0,2,4]
    assert result['coverage']['pagination_complete'] is True
    assert result['coverage']['comprehensive'] is False
    assert result['coverage']['duplicates_removed']==1
    assert result['coverage']['exclusions']['non_company_or_unknown_instrument']==1
    member=result['members'][0]
    assert member['sector']=='Technology' and member['industry'] is None
    assert member['classification_basis']['source_sector'] is None
    assert member['classification_basis']['query_sector']=='Technology'
    assert member['country'] is None and member['listing_country']=='US'
    assert member['raw_quote']['regularMarketPrice']==100


def test_default_expanded_scope_is_explicit_not_a_blanket_retailer_technology_claim(setup):
    seen=[]
    def fetch(query,**kwargs):
        field,name=scope(query);seen.append(name)
        return {'start':0,'total':1,'quotes':[quote({'Technology':'TECHX','Internet Content & Information':'PLATFORMX','Internet Retail':'RETAILX'}[name])]}
    result=provider(setup,fetch).discover()
    assert set(seen)=={'Technology','Internet Content & Information','Internet Retail'}
    retail=next(row for row in result['members'] if row['ticker']=='RETAILX')
    assert retail['sector']=='Consumer Cyclical'
    assert retail['industry']=='Internet Retail'
    assert retail['technology_scope']=='internet_platform_adjacent'
    assert 'not a claim' in retail['classification_rationale']


def test_industry_filter_uses_source_predicate_when_quote_omits_industry(setup):
    seen=[]
    def fetch(query,**kwargs):
        seen.append(scope(query));return {'start':0,'total':1,'quotes':[quote('INFRA9')]}
    result=provider(setup,fetch).discover({'industries':['Software—Infrastructure']})
    assert seen==[('industry','Software—Infrastructure')]
    row=result['members'][0]
    assert row['industry']=='Software—Infrastructure'
    assert row['classification_basis']['source_industry'] is None
    assert row['classification_basis']['query_industry']=='Software—Infrastructure'


def test_market_cap_volume_exchange_filters_and_missing_fields_are_explicit(setup):
    rows=[quote('GOOD',exchange='NYQ'),quote('SMALL',marketCap=1e8,exchange='NYQ'),quote('LARGE',marketCap=1e12,exchange='NYQ'),
          quote('THIN',averageDailyVolume3Month=5,exchange='NYQ'),quote('UNKNOWN',marketCap=None,exchange='NYQ'),
          quote('NASDAQX'),quote('PREF',exchange='NYQ',longName='SYNTHETIC Company Preferred Stock')]
    result=provider(setup,lambda *a,**kw:{'start':0,'total':len(rows),'quotes':rows}).discover({
        'include_tech_adjacent':False,'exchanges':['NYSE'],'market_cap_min':1e9,'market_cap_max':1e10,'average_volume_min':100000})
    assert [row['ticker'] for row in result['members']]==['GOOD']
    assert result['coverage']['excluded_count']==6
    assert result['coverage']['exclusions']['missing_market_cap']==1
    assert result['coverage']['exclusions']['non_common_security']==1


def test_international_listing_region_is_not_source_locale_or_issuer_domicile(setup):
    result=provider(setup,lambda *a,**kw:{'start':0,'total':1,'quotes':[quote('CAN.TO',exchange='TOR',region='US',country='Canada',currency='CAD')]}).discover({
        'include_international':True,'countries':['Canada'],'include_tech_adjacent':False})
    assert result['members'][0]['ticker']=='CAN.TO'
    assert result['members'][0]['listing_country']=='CA'
    assert result['members'][0]['country']=='Canada'
    assert result['coverage']['scope']['regions']==['ca']


@pytest.mark.parametrize('config',[
    {'countries':['CA']},{'include_international':True,'countries':['not-a-country']},
    {'industries':['Airlines']},{'exchanges':['NOTEXCHANGE']},{'market_cap_min':-1},
    {'market_cap_max':1},{'market_cap_max':float('nan')},{'average_volume_min':True},
    {'page_size':251},{'max_pages':0},
])
def test_invalid_filters_fail_before_network(setup,config):
    def forbidden(*args,**kwargs):pytest.fail('No provider request is authorized for invalid filters')
    with pytest.raises(DataUnavailable) as caught:provider(setup,forbidden).discover(config)
    assert caught.value.status==422


def test_bounded_page_cap_reports_lower_bound_not_entire_sector(setup):
    def fetch(query,**kwargs):return {'start':kwargs['offset'],'total':100,'quotes':[quote('CAP1'),quote('CAP2')]}
    result=provider(setup,fetch).discover({'include_tech_adjacent':False,'max_pages':1,'page_size':2})
    assert len(result['members'])==2
    assert result['coverage']['truncated'] is True
    assert result['coverage']['eligible_count_is_lower_bound'] is True
    assert result['coverage']['pagination_complete'] is False
    assert result['coverage']['source_reported_total']==100


def test_repeated_page_symbols_detected_even_when_prices_change(setup):
    calls=[]
    def fetch(query,**kwargs):
        calls.append(kwargs['offset'])
        return {'start':kwargs['offset'],'total':8,'quotes':[quote('REPEAT1',regularMarketPrice=100+len(calls)),quote('REPEAT2')]}
    result=provider(setup,fetch).discover({'include_tech_adjacent':False,'page_size':2})
    assert calls==[0,2]
    assert result['coverage']['pagination_complete'] is False
    assert result['coverage']['errors'][0]['code']=='universe_pagination_error'


def test_fresh_cache_reused_and_failed_refresh_preserves_membership_timestamp(setup):
    calls=[];failed=False
    def fetch(query,**kwargs):
        calls.append(1)
        if failed:raise ConnectionError('Synthetic DNS outage')
        return {'start':0,'total':1,'quotes':[quote('CACHEDX')]}
    p=provider(setup,fetch);config={'include_tech_adjacent':False}
    first=p.discover(config);second=p.discover(config)
    assert len(calls)==1 and second['fetched_at']==first['fetched_at']
    expire(setup[0]);failed=True
    stale=p.discover(config)
    assert stale['cache_stale'] is True
    assert stale['members']==first['members']
    assert stale['fetched_at']==first['fetched_at']
    assert stale['upstream_errors'][0]['code']=='network_error'
    assert len(calls)==3


def test_uncached_outage_or_rate_limit_never_substitutes_popular_tickers(setup):
    calls=[]
    def fail(*args,**kwargs):calls.append(1);raise DataUnavailable('Synthetic rate limit','upstream_rate_limit',429,True)
    with pytest.raises(DataUnavailable) as caught:provider(setup,fail).discover()
    assert caught.value.status==429
    assert len(calls)==1


def test_empty_discovery_is_valid_and_does_not_create_companies(setup):
    result=provider(setup,lambda *a,**kw:{'start':0,'total':0,'quotes':[]}).discover({'include_tech_adjacent':False})
    assert result['members']==[]
    assert result['coverage']['eligible_count']==0
    assert result['coverage']['comprehensive'] is False


def test_authorized_import_json_csv_filters_and_duplicates_without_network(setup):
    def forbidden(*args,**kwargs):pytest.fail('Imported discovery must not call Yahoo')
    p=provider(setup,forbidden)
    rows=[{**quote('IMPORTEDX'),'sector':'Technology'},{**quote('IMPORTEDX'),'sector':'Technology'},
          {**quote('FUNDX',quoteType='ETF'),'sector':'Technology'}]
    imported=p.import_file(json.dumps(rows),source='Authorized synthetic fixture')
    assert imported['members_imported']==2 and imported['duplicates_removed']==1
    result=p.discover({'universe_source':'import','import_id':imported['import_id']})
    assert [row['ticker'] for row in result['members']]==['IMPORTEDX']
    assert result['source']=='Authorized synthetic fixture'
    csv='ticker,quoteType,sector,exchange,market_cap,average_volume,currency\nCSVX,EQUITY,Technology,NMS,2000000000,200000,USD\n'
    imported=p.import_file(csv,format='csv',source='Authorized CSV fixture')
    assert p.discover({'universe_source':'import','import_id':imported['import_id']})['members'][0]['ticker']=='CSVX'


def test_import_requires_real_source_fields_and_valid_timestamp(setup):
    p=provider(setup,lambda *a,**kw:None)
    with pytest.raises(DataUnavailable):p.import_file('not-json')
    with pytest.raises(DataUnavailable):p.import_file('[{"name":"missing symbol"}]')
    with pytest.raises(DataUnavailable):p.import_file('[]',source_as_of='2099-01-01T00:00:00Z')
    imported=p.import_file(json.dumps([{'ticker':'UNKNOWNX','sector':'Technology'}]))
    result=p.discover({'universe_source':'import','import_id':imported['import_id']})
    assert result['members']==[]
    assert result['coverage']['excluded_count']==1


def test_explicit_nontech_industry_cannot_be_overridden_by_a_technology_query(setup):
    result=provider(setup,lambda *a,**kw:{'start':0,'total':1,'quotes':[quote('AIRLINEX',industry='Airlines')]}).discover({'include_tech_adjacent':False})
    assert result['members']==[]
    assert result['coverage']['exclusions']['classification_mismatch']==1
