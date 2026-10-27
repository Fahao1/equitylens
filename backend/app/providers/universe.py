"""Bounded dynamic company discovery with explicit source coverage and import provenance."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
from threading import Lock

import yfinance as yf

from app.providers.yahoo import DataUnavailable, classify_provider_error, retry_call, validate_ticker
from app.utils import clean, iso_now, number

SOURCE = 'Yahoo Finance custom equity screener via yfinance; source-covered universe, not an authoritative sector census'
ADJACENT = ('Internet Content & Information', 'Internet Retail')
MAJOR_US = ('NMS', 'NGM', 'NCM', 'NYQ', 'ASE', 'PCX', 'BTS')
COUNTRIES = {'united states':'us','united states of america':'us','usa':'us','united kingdom':'gb','uk':'gb',
             'canada':'ca','germany':'de','france':'fr','japan':'jp','hong kong':'hk','taiwan':'tw','india':'in',
             'australia':'au','israel':'il','netherlands':'nl','sweden':'se','singapore':'sg','south korea':'kr',
             'china':'cn','switzerland':'ch'}
EXCHANGES = {'NASDAQ':('NMS','NGM','NCM'),'NYSE':('NYQ',),'NYSE AMERICAN':('ASE',),'NYSE ARCA':('PCX',),'CBOE':('BTS',)}
NONCOMPANY = ('warrant','preferred','depositary preference','units,',' - units','rights to',' - rights')


def _positive(value):
    result = number(value)
    return result if result is not None and result >= 0 else None


def _text(value):
    return value.strip() if isinstance(value,str) and value.strip() else None


def _invalid(message):
    return DataUnavailable(message,'invalid_universe_filter',422,False)


class TechnologyUniverseProvider:
    def __init__(self, store, settings, screen_fetcher=None, query_factory=None):
        self.store, self.settings = store, settings
        self.screen_fetcher = screen_fetcher or yf.screen
        self.query_factory = query_factory or yf.EquityQuery
        self.lock = Lock()
        # This is supported library taxonomy, not a hardcoded stock list.
        reference = yf.EquityQuery('eq',['sector','Technology'])
        self.valid = reference.valid_values
        self.industries = {name:sector for sector,names in self.valid['industry'].items() for name in names}
        self.exchange_regions = {}
        for region,codes in self.valid['exchange'].items():
            for code in codes:
                self.exchange_regions.setdefault(code,set()).add(region)

    def _config(self, config):
        given = dict(config or {})
        include = bool(given.get('include_international',False))
        regions = []
        for country in given.get('countries') or ([] if include else ['us']):
            value = COUNTRIES.get(str(country).strip().casefold(),str(country).strip().lower())
            if value not in self.valid['region']:
                raise _invalid('Use source-supported two-letter listing-region codes for country filters.')
            if not include and value != 'us':
                raise _invalid('Enable international listings before selecting a non-US listing region.')
            regions.append(value)
        regions = sorted(set(regions or (self.valid['region'] if include else ['us'])))
        exchange_codes = []
        for exchange in given.get('exchanges') or []:
            code = str(exchange).strip().upper()
            expanded = EXCHANGES.get(code,(code,))
            if any(item not in self.exchange_regions for item in expanded):
                raise _invalid('Exchange filters must be Yahoo exchange codes or supported Nasdaq/NYSE aliases.')
            exchange_codes.extend(expanded)
        if not exchange_codes:
            exchange_codes = [code for region in regions for code in self.valid['exchange'].get(region,[]) if region!='us' or code in MAJOR_US]
        exchange_codes = sorted(set(exchange_codes))
        if not exchange_codes or not any(self.exchange_regions[code].intersection(regions) for code in exchange_codes):
            raise _invalid('No supported exchange matches the selected listing regions.')
        allowed_industries = {name for name,sector in self.industries.items() if sector=='Technology'} | set(ADJACENT)
        canonical = {name.casefold():name for name in allowed_industries}
        industries=[]
        for value in given.get('industries') or []:
            name=canonical.get(str(value).strip().casefold())
            if not name:raise _invalid('Industry is outside the declared Technology / internet-platform-adjacent source taxonomy.')
            industries.append(name)
        cap_min = _positive(given.get('market_cap_min',1e9))
        cap_max = _positive(given.get('market_cap_max')) if given.get('market_cap_max') is not None else None
        volume = _positive(given.get('average_volume_min',100000))
        if cap_min is None or volume is None or (cap_max is not None and cap_max<cap_min):
            raise _invalid('Market-cap and average-volume filters must be finite, nonnegative and correctly ordered.')
        if given.get('market_cap_max') is not None and cap_max is None:
            raise _invalid('Maximum market capitalization must be a finite nonnegative number.')
        page_size,max_pages=given.get('page_size',250),given.get('max_pages',20)
        if isinstance(page_size,bool) or not isinstance(page_size,int) or not 1<=page_size<=250 or isinstance(max_pages,bool) or not isinstance(max_pages,int) or not 1<=max_pages<=40:
            raise _invalid('Page size must be 1–250 and page limit 1–40.')
        source=given.get('universe_source','yahoo')
        if source not in ('yahoo','import'):raise _invalid('Universe source must be yahoo or import.')
        return {'regions':regions,'exchanges':exchange_codes,'industries':sorted(set(industries)),
                'include_international':include,'market_cap_min':cap_min,'market_cap_max':cap_max,
                'average_volume_min':volume,'page_size':page_size,'max_pages':max_pages,
                'universe_source':source,'import_id':given.get('import_id'),
                'include_tech_adjacent':bool(given.get('include_tech_adjacent',True))}

    def _queries(self, config):
        scopes = ([{'industry':name,'sector':self.industries.get(name)} for name in config['industries']]
                  if config['industries'] else [{'sector':'Technology','industry':None}]
                  +([{'industry':name,'sector':self.industries.get(name)} for name in ADJACENT] if config['include_tech_adjacent'] else []))
        queries=[]
        for scope in scopes:
            parts=[self.query_factory('eq',['industry',scope['industry']]) if scope['industry'] else self.query_factory('eq',['sector','Technology']),
                   self.query_factory('is-in',['region',*config['regions']]),
                   self.query_factory('is-in',['exchange',*config['exchanges']]),
                   self.query_factory('gte',['intradaymarketcap',config['market_cap_min']]),
                   self.query_factory('gte',['avgdailyvol3m',config['average_volume_min']])]
            if config['market_cap_max'] is not None:parts.append(self.query_factory('lte',['intradaymarketcap',config['market_cap_max']]))
            queries.append((scope,self.query_factory('and',parts)))
        return queries

    def _member(self, quote, scope, config):
        if not isinstance(quote,dict):return None,'malformed_quote'
        raw_symbol=quote.get('symbol') or quote.get('ticker')
        if not isinstance(raw_symbol,str):return None,'missing_ticker'
        try:ticker=validate_ticker(raw_symbol)
        except DataUnavailable:return None,'invalid_ticker'
        kind=_text(quote.get('quoteType') or quote.get('asset_type'))
        if not kind or kind.upper()!='EQUITY':return None,'non_company_or_unknown_instrument'
        name=_text(quote.get('longName') or quote.get('shortName') or quote.get('name'))
        if name and any(word in name.lower() for word in NONCOMPANY):return None,'non_common_security'
        actual_sector=_text(quote.get('sector') or quote.get('sectorDisp'))
        actual_industry=_text(quote.get('industry') or quote.get('industryDisp'))
        industry=actual_industry or scope.get('industry')
        sector=actual_sector or scope.get('sector')
        known_industry_sector=self.industries.get(actual_industry)
        if known_industry_sector and known_industry_sector!='Technology' and actual_industry not in ADJACENT:
            return None,'classification_mismatch'
        valid_scope=sector=='Technology' or industry in ADJACENT
        if not valid_scope:return None,'unverified_technology_classification'
        if scope.get('industry') and actual_industry and actual_industry!=scope['industry']:return None,'classification_mismatch'
        if config['industries'] and industry not in config['industries']:return None,'industry_filter'
        if not config['include_tech_adjacent'] and (sector!='Technology' or industry in ADJACENT):return None,'adjacent_scope_disabled'
        exchange=_text(quote.get('exchange'))
        if not exchange or exchange not in config['exchanges']:return None,'exchange_filter_or_missing_exchange'
        regions=self.exchange_regions.get(exchange,set())
        if not regions.intersection(config['regions']):return None,'listing_region_filter'
        cap=_positive(quote.get('marketCap',quote.get('market_cap')))
        volume=_positive(quote.get('averageDailyVolume3Month',quote.get('average_volume')))
        if cap is None:return None,'missing_market_cap'
        if volume is None:return None,'missing_average_volume'
        if cap<config['market_cap_min'] or (config['market_cap_max'] is not None and cap>config['market_cap_max']):return None,'market_cap_filter'
        if volume<config['average_volume_min']:return None,'average_volume_filter'
        listing=next(iter(regions)).upper() if len(regions)==1 else None
        adjacent=sector!='Technology' or industry in ADJACENT
        rationale=(f'Source classification industry={industry}; declared internet-platform-adjacent scope, not a claim that every constituent is a pure technology business.'
                   if adjacent else 'Yahoo Technology classification, supplied in the quote or established by the source screening predicate.')
        result={**clean(quote),'ticker':ticker,'symbol':ticker,'quoteType':'EQUITY','name':name,'sector':sector,'industry':industry,
                'exchange':exchange,'country':_text(quote.get('country')),'listing_country':listing,
                'market_cap':cap,'average_volume':volume,'source':SOURCE,
                'technology_scope':'internet_platform_adjacent' if adjacent else 'technology_sector',
                'classification_rationale':rationale,'classification_basis':{'source_sector':actual_sector,'source_industry':actual_industry,'query_sector':scope.get('sector'),'query_industry':scope.get('industry')},
                'raw_quote':clean(quote)}
        return result,None

    def _fetch(self, config):
        members={};excluded=Counter();errors=[];reports=[];duplicates=0;pages=0
        for scope,query in self._queries(config):
            offset=0;complete=False;seen_pages=set();totals=[];query_pages=0
            for _ in range(config['max_pages']):
                try:
                    response=retry_call(lambda:self.screen_fetcher(query,offset=offset,size=config['page_size'],sortField='ticker',sortAsc=True))
                    if not isinstance(response,dict) or not isinstance(response.get('quotes'),list):
                        raise DataUnavailable('Yahoo universe discovery returned an unreadable page.','provider_response_error',502,False)
                    quotes=response['quotes'];total=number(response.get('total'))
                    total=int(total) if total is not None and total>=0 and total==int(total) else None
                    if total is not None:totals.append(total)
                    start=number(response.get('start'))
                    if start is not None and start!=offset:
                        raise DataUnavailable('Yahoo ignored the requested discovery offset; coverage is incomplete.','universe_pagination_error',502,False)
                    fingerprint=sha256(json.dumps([q.get('symbol') if isinstance(q,dict) else None for q in quotes],sort_keys=True).encode()).hexdigest()
                    if quotes and fingerprint in seen_pages:
                        raise DataUnavailable('Yahoo repeated a discovery page; coverage is incomplete.','universe_pagination_error',502,False)
                    seen_pages.add(fingerprint);pages+=1;query_pages+=1
                    for quote in quotes:
                        member,reason=self._member(quote,scope,config)
                        if member:
                            if member['ticker'] in members:duplicates+=1
                            else:members[member['ticker']]=member
                        else:excluded[reason]+=1
                    if not quotes:
                        complete=total in (None,0) or offset>=total
                        if not complete:errors.append({'scope':scope,'code':'premature_empty_page','message':'Source page ended before its reported total.'})
                        break
                    offset+=len(quotes)
                    if (total is not None and offset>=total) or (total is None and len(quotes)<config['page_size']):
                        complete=True;break
                except Exception as exc:
                    error=classify_provider_error(exc)
                    errors.append({'scope':scope,**error.payload(),'http_status':error.status})
                    break
            if len(set(totals))>1:
                complete=False
                errors.append({'scope':scope,'code':'changing_source_total','message':'Source result totals changed during pagination; the discovery is not atomic.'})
            reports.append({'scope':scope,'source_reported_total':totals[-1] if totals else None,'pages_fetched':query_pages,'pagination_complete':complete,'rows_received':offset})
            if errors and errors[-1].get('code') in ('upstream_rate_limit','network_error','request_timeout','provider_unavailable'):break
        if errors and not members:
            last=errors[-1]
            raise DataUnavailable(last.get('message','Dynamic universe source unavailable.'),last.get('code','provider_unavailable'),last.get('http_status',503),bool(last.get('retryable',False)))
        complete=len(reports)==len(self._queries(config)) and all(row['pagination_complete'] for row in reports)
        return {'members':sorted(members.values(),key=lambda row:row['ticker']),'source':SOURCE,'fetched_at':iso_now(),
                'coverage':{'eligible_count':len(members),'unique_discovered_count':len(members),'excluded_count':sum(excluded.values()),
                            'exclusions':dict(excluded),'duplicates_removed':duplicates,'pages_fetched':pages,'queries':reports,
                            'source_reported_total':sum(r['source_reported_total'] for r in reports) if reports and all(r['source_reported_total'] is not None for r in reports) else None,
                            'source_total_basis':'Sum of source query totals; may overlap and is not a unique sector census.',
                            'pagination_complete':complete,'truncated':not complete,'comprehensive':False,
                            'eligible_count_is_lower_bound':not complete,'errors':errors,'scope':config},
                'limitations':[
                    'This is the source-covered, filtered discovery set, not a complete or authoritative technology-sector census. Query pagination completeness does not prove sector completeness.',
                    'Classification can be established by a source predicate when quote payloads omit sector/industry. Missing industry is not invented.',
                    'Country filters identify listing regions using source exchange mappings; issuer domicile remains unavailable unless explicitly supplied.',
                    'Internet-platform-adjacent industries include internet retail as an explicit expanded scope; not every retailer is a pure technology company.',
                    'Yahoo access is intended for personal research and is subject to its terms. No authentication, rate-limit or access protection is bypassed.',
                    'International market-cap thresholds apply source-reported units; no cross-currency market-cap normalization or foreign-exchange return is invented.',
                    'Current discovery cannot establish historical universe membership or remove survivorship bias in a historical screen.',
                ]}

    def discover(self, config=None):
        given=dict(config or {});cfg=self._config(given)
        key='tech:universe:v1:'+sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
        with self.lock:
            cached=self.store.cache_get(key)
            ttl=getattr(self.settings,'universe_cache_seconds',21600)
            if cached and not given.get('force_refresh'):
                lifetime=ttl if cached['value']['coverage'].get('pagination_complete') else min(ttl,300)
                if cached['age']<=lifetime:return {**cached['value'],'cache_stale':False,'cache_age_seconds':round(cached['age'])}
            try:
                if cfg['universe_source']=='import':
                    imported=self.store.cache_get('tech:universe:import:'+str(cfg.get('import_id')))
                    if not imported:raise _invalid('Authorized universe import not found; import the source file first.')
                    original=imported['value'];members=[];excluded=Counter()
                    for row in original['rows']:
                        member,reason=self._member(row,{},cfg)
                        if member:member['source']=original['source'];members.append(member)
                        else:excluded[reason]+=1
                    value={'members':members,'source':original['source'],'fetched_at':original['imported_at'],
                           'coverage':{'eligible_count':len(members),'excluded_count':sum(excluded.values()),'exclusions':dict(excluded),'comprehensive':False,
                                       'pagination_complete':True,'truncated':False,'scope':cfg,'source_as_of':original.get('source_as_of'),'import_id':cfg['import_id']},
                           'limitations':['Authorized user-imported coverage only; a file does not establish whole-sector completeness or verified historical membership.','Listing-region and instrument/metric filters are enforced; missing fields do not pass the configured filters.']}
                else:value=self._fetch(cfg)
                if cached and value['coverage'].get('errors'):
                    return {**cached['value'],'cache_stale':True,'cache_age_seconds':round(cached['age']),
                            'cache_warning':'Discovery refresh was incomplete. Showing the original dated cached universe, with the new source errors.','upstream_errors':value['coverage']['errors']}
                value=clean(value);self.store.cache_set(key,value)
                return {**value,'cache_stale':False,'cache_age_seconds':0}
            except Exception as exc:
                if cached and (not isinstance(exc,DataUnavailable) or exc.status!=422):
                    error=classify_provider_error(exc)
                    return {**cached['value'],'cache_stale':True,'cache_age_seconds':round(cached['age']),
                            'cache_warning':'Universe source refresh failed; original membership and source timestamp are retained.','upstream_errors':[error.payload()]}
                raise

    def import_file(self, content, format='json', source='Authorized user universe import', source_as_of=None):
        if not isinstance(content,str) or not content.strip() or len(content)>5_000_000:
            raise _invalid('Universe import must contain 1–5,000,000 characters of authorized JSON or CSV.')
        if format=='json':
            try:data=json.loads(content)
            except ValueError as exc:raise _invalid('Universe import is not valid JSON.') from exc
            rows=data.get('members') if isinstance(data,dict) else data
        elif format=='csv':rows=list(csv.DictReader(StringIO(content)))
        else:raise _invalid('Universe import supports JSON and CSV.')
        if not isinstance(rows,list) or len(rows)>10000 or any(not isinstance(row,dict) for row in rows):
            raise _invalid('Universe import must contain at most 10,000 object rows.')
        normalized={}
        for row in rows:
            symbol=row.get('ticker') or row.get('symbol')
            if not isinstance(symbol,str):raise _invalid('Every imported member needs a ticker/symbol.')
            ticker=validate_ticker(symbol)
            normalized[ticker]={**row,'symbol':ticker}
        if source_as_of:
            try:
                stamp=datetime.fromisoformat(str(source_as_of).replace('Z','+00:00'))
                if stamp.tzinfo is None or stamp>datetime.now(timezone.utc):raise ValueError
            except (ValueError,TypeError):raise _invalid('Import source_as_of must be a past/present timestamp with a UTC offset.')
        payload={'rows':clean(list(normalized.values())),'source':str(source)[:500],'source_as_of':source_as_of,'imported_at':iso_now()}
        identity=sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        self.store.cache_set('tech:universe:import:'+identity,payload)
        return {'import_id':identity,'members_imported':len(normalized),'duplicates_removed':len(rows)-len(normalized),'source':payload['source'],'fetched_at':payload['imported_at'],
                'limitations':['Import only files you are authorized to use. Import does not grant redistribution rights or establish past score vintages.']}
