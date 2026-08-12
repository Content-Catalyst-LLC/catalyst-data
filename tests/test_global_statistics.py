from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python'))

from catalyst_data.adapters import default_adapter_registry
from catalyst_data.database import connect
from catalyst_data.global_statistics import (
    GlobalStatisticsService,
    WorldBankIndicatorDataAdapter,
    UNSDGIndicatorDataAdapter,
)
from catalyst_data.public_api import CatalystApiServer
from catalyst_data.repository import CatalystRepository


class FakeResponse:
    def __init__(self,payload,headers=None):
        self.body=json.dumps(payload).encode('utf-8'); self.status=200; self.headers=headers or {'Content-Type':'application/json'}
    def read(self,n=-1): return self.body if n<0 else self.body[:n]
    def __enter__(self): return self
    def __exit__(self,*args): return False


def test_global_statistics_provider_adapters_registered():
    ids={item['adapter_id'] for item in default_adapter_registry().list()}
    assert {
        'world-bank-countries','world-bank-indicators','world-bank-indicator-data',
        'un-sdg-geoareas','un-sdg-goals','un-sdg-indicators','un-sdg-indicator-data'
    } <= ids


def test_world_bank_adapter_uses_v2_pagination_and_footnotes():
    adapter=WorldBankIndicatorDataAdapter(); config=adapter.normalize_config({'countries':'KEN;UGA','indicator':'SP.POP.TOTL','date':'2020:2025','per_page':250})
    uri=adapter.request_uri(config,{'cursor':2}); parsed=urlparse(uri); query=parse_qs(parsed.query)
    assert parsed.netloc=='api.worldbank.org'
    assert parsed.path=='/v2/country/KEN;UGA/indicator/SP.POP.TOTL'
    assert query['format']==['json'] and query['page']==['2'] and query['per_page']==['250']
    assert query['date']==['2020:2025'] and query['footnote']==['y']


def test_un_sdg_adapter_preserves_m49_and_pagination():
    adapter=UNSDGIndicatorDataAdapter(); config=adapter.normalize_config({'indicators':['1.1.1'],'area_codes':['404','800'],'time_period_start':2015,'time_period_end':2025,'page_size':50})
    uri=adapter.request_uri(config,{'cursor':3}); parsed=urlparse(uri); query=parse_qs(parsed.query)
    assert parsed.netloc=='unstats.un.org' and parsed.path.endswith('/SDGAPI/v1/sdg/Indicator/Data')
    assert query['indicator']==['1.1.1'] and query['areaCode']==['404','800']
    assert query['page']==['3'] and query['pageSize']==['50']


def test_world_bank_catalog_and_observations_are_cached(tmp_path):
    db=tmp_path/'statistics.sqlite3'
    responses=[
        [{'page':1,'pages':1,'per_page':400,'total':1},[{'id':'KEN','iso2Code':'KE','name':'Kenya','region':{'id':'SSF','value':'Sub-Saharan Africa'},'incomeLevel':{'id':'LMC','value':'Lower middle income'},'lendingType':{'id':'IDX','value':'IDA'},'capitalCity':'Nairobi','longitude':'36.812','latitude':'-1.279'}]],
        [{'page':1,'pages':1,'per_page':1000,'total':1},[{'id':'SP.POP.TOTL','name':'Population, total','unit':'people','source':{'id':'2','value':'World Development Indicators'},'sourceNote':'Total population','sourceOrganization':'World Bank'}]],
        [{'page':1,'pages':1,'per_page':1000,'total':1},[{'indicator':{'id':'SP.POP.TOTL','value':'Population, total'},'country':{'id':'KE','value':'Kenya'},'countryiso3code':'KEN','date':'2025','value':56000000,'unit':'people','obs_status':'','decimal':0,'source':2,'footnote':'fixture'}]],
    ]
    calls=[]
    def opener(req,timeout=0): calls.append(req); return FakeResponse(responses.pop(0))
    svc=GlobalStatisticsService(CatalystRepository(db),opener=opener,sleeper=lambda _:None)
    assert svc.fetch_world_bank_countries()['records']==1
    assert svc.fetch_world_bank_indicators()['records']==1
    assert svc.fetch_world_bank_data('KEN','SP.POP.TOTL',date='2025')['records']==1
    obs=svc.world_bank_observations(country='KEN',indicator='SP.POP.TOTL')
    assert obs[0]['value_numeric']==56000000.0 and obs[0]['period']=='2025'
    status=svc.status(); assert status['world_bank_country_count']==1 and status['world_bank_observation_count']==1
    assert calls[0].headers['User-agent'].startswith('SustainableCatalyst-CatalystData/2.9.0')


def test_un_sdg_catalog_and_observations_are_cached(tmp_path):
    db=tmp_path/'sdg.sqlite3'
    responses=[
        [{'geoAreaCode':404,'geoAreaName':'Kenya','type':'Country'}],
        [{'code':'1','title':'No poverty','description':'End poverty in all its forms everywhere'}],
        [{'code':'1.1.1','description':'Proportion of the population living below the international poverty line','goal':'1','target':'1.1','series':[{'code':'SI_POV_DAY1'}]}],
        {'page':1,'pageSize':100,'totalElements':1,'data':[{'indicator':'1.1.1','seriesCode':'SI_POV_DAY1','seriesDescription':'Population below international poverty line','geoAreaCode':404,'geoAreaName':'Kenya','timePeriod':2022,'value':16.0,'units':'PERCENT','nature':'CA','dimensions':{'sex':'BOTHSEX'}}]},
    ]
    def opener(req,timeout=0): return FakeResponse(responses.pop(0))
    svc=GlobalStatisticsService(CatalystRepository(db),opener=opener,sleeper=lambda _:None)
    catalog=svc.fetch_un_sdg_catalog(); assert catalog['counts']=={'geoareas':1,'goals':1,'indicators':1}
    result=svc.fetch_un_sdg_data('1.1.1',area_codes=[404],time_period_start=2015,time_period_end=2025); assert result['records']==1
    obs=svc.un_sdg_observations(indicator='1.1.1',area_code='404'); assert obs[0]['series_code']=='SI_POV_DAY1' and obs[0]['dimensions']['sex']=='BOTHSEX'
    status=svc.status(); assert status['un_sdg_geoarea_count']==1 and status['un_sdg_observation_count']==1


def test_statistics_refresh_is_idempotent_for_same_observation(tmp_path):
    db=tmp_path/'idempotent.sqlite3'
    payload=[{'page':1,'pages':1},[{'indicator':{'id':'SP.POP.TOTL','value':'Population'},'country':{'id':'KE','value':'Kenya'},'countryiso3code':'KEN','date':'2024','value':55,'source':2}]]
    svc=GlobalStatisticsService(CatalystRepository(db),opener=lambda req,timeout=0:FakeResponse(payload),sleeper=lambda _:None)
    svc.fetch_world_bank_data('KEN','SP.POP.TOTL',date='2024'); svc.fetch_world_bank_data('KEN','SP.POP.TOTL',date='2024')
    with connect(db,readonly=True) as c:
        assert c.execute('SELECT COUNT(*) FROM world_bank_observations').fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM global_statistics_fetches WHERE provider='world-bank'").fetchone()[0]==2


def test_migration_seventeen_rolls_back_statistics_tables(tmp_path):
    repository=CatalystRepository(tmp_path/'migration17.sqlite3'); repository.initialize(target=17)
    assert repository.health().migration_version==17
    with connect(repository.path,readonly=True) as c: assert c.execute("SELECT name FROM sqlite_master WHERE name='global_statistics_status'").fetchone()
    assert repository.rollback(1)==[17]
    with connect(repository.path,readonly=True) as c: assert c.execute("SELECT name FROM sqlite_master WHERE name='global_statistics_status'").fetchone() is None
    assert repository.migrate(target=17)==[17]


def test_public_statistics_api_reads_cache_without_provider_fetch(tmp_path):
    db=tmp_path/'public.sqlite3'
    payload=[{'page':1,'pages':1},[{'indicator':{'id':'SP.POP.TOTL','value':'Population'},'country':{'id':'KE','value':'Kenya'},'countryiso3code':'KEN','date':'2025','value':56,'source':2}]]
    svc=GlobalStatisticsService(CatalystRepository(db),opener=lambda req,timeout=0:FakeResponse(payload),sleeper=lambda _:None)
    svc.fetch_world_bank_data('KEN','SP.POP.TOTL',date='2025')
    server=CatalystApiServer(('127.0.0.1',0),svc.repository,allow_origin='https://sustainablecatalyst.com'); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start(); base=f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base+'/v1/statistics/world-bank/observations?country=KEN&indicator=SP.POP.TOTL',timeout=5) as response: body=json.loads(response.read())
        assert body['observations'][0]['country_code']=='KEN'
        with urlopen(base+'/v1/statistics/status',timeout=5) as response: status=json.loads(response.read())
        assert status['world_bank_observation_count']==1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
