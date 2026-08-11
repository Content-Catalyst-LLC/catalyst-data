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
from catalyst_data.public_api import CatalystApiServer
from catalyst_data.repository import CatalystRepository
from catalyst_data.us_public_data import (
    USPublicDataService, CensusDataAdapter, EIADataAdapter, EPAEnvirofactsAdapter, USGSWaterDataAdapter,
)


class FakeResponse:
    def __init__(self,payload,headers=None):
        self.body=json.dumps(payload).encode('utf-8'); self.status=200; self.headers=headers or {'Content-Type':'application/json'}
    def read(self,n=-1): return self.body if n<0 else self.body[:n]
    def __enter__(self): return self
    def __exit__(self,*args): return False


def test_us_public_provider_adapters_registered():
    ids={item['adapter_id'] for item in default_adapter_registry().list()}
    assert {'us-census-data','us-bls-series','us-bea-data','us-eia-data','us-epa-envirofacts','us-usgs-water-data'} <= ids


def test_provider_url_contracts():
    census=CensusDataAdapter(); config=census.normalize_config({'year':2024,'dataset':'acs/acs5','variables':['NAME','B01003_001E'],'for':'state:*'})
    uri=census.request_uri(config,{})
    q=parse_qs(urlparse(uri).query); assert q['get']==['NAME,B01003_001E'] and q['for']==['state:*']
    eia=EIADataAdapter(); config=eia.normalize_config({'route':'electricity/retail-sales','data':['sales'],'facets':{'stateid':['IL']},'length':100})
    q=parse_qs(urlparse(eia.request_uri(config,{'cursor':100})).query); assert q['data[]']==['sales'] and q['facets[stateid][]']==['IL'] and q['offset']==['100']
    epa=EPAEnvirofactsAdapter(); config=epa.normalize_config({'table':'TRI.TRI_FACILITY','filters':[{'column':'STATE_ABBR','operator':'equals','value':'IL'}],'page_size':10})
    assert '/TRI.TRI_FACILITY/STATE_ABBR/equals/IL/1:10/JSON' in epa.request_uri(config,{'cursor':1})
    usgs=USGSWaterDataAdapter(); config=usgs.normalize_config({'collection':'daily','limit':50,'parameter_code':'00060'})
    q=parse_qs(urlparse(usgs.request_uri(config,{'cursor':0})).query); assert q['limit']==['50'] and q['parameter_code']==['00060']


def test_census_and_bls_cache_with_credentials_redacted(tmp_path, monkeypatch):
    db=tmp_path/'us.sqlite3'; responses=[
        [['NAME','B01003_001E','state'],['Illinois','12700000','17']],
        {'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'LNS14000000','catalog':{'series_title':'Unemployment Rate','survey_name':'Labor Force Statistics'},'data':[{'year':'2026','period':'M07','periodName':'July','value':'4.2','latest':'true','footnotes':[]}]}]}},
    ]
    monkeypatch.setenv('TEST_CENSUS_KEY','census-secret'); monkeypatch.setenv('TEST_BLS_KEY','bls-secret')
    calls=[]
    def opener(req,timeout=0): calls.append(req.full_url); return FakeResponse(responses.pop(0))
    svc=USPublicDataService(CatalystRepository(db),opener=opener,sleeper=lambda _:None)
    assert svc.fetch_census(2024,'acs/acs5',['NAME','B01003_001E'],for_predicate='state:*',credential_env='TEST_CENSUS_KEY')['observations']==1
    assert svc.fetch_bls_series('LNS14000000',latest=True,credential_env='TEST_BLS_KEY')['records']==1
    obs=svc.observations(); assert {item['provider'] for item in obs}=={'census','bls'}
    with connect(db,readonly=True) as c:
        urls=[row[0] for row in c.execute('SELECT source_uri FROM us_public_fetches ORDER BY id')]
    assert all('secret' not in u for u in urls) and all('REDACTED' in u for u in urls)
    assert 'census-secret' in calls[0] and 'bls-secret' in calls[1]


def test_bea_eia_epa_usgs_are_cached(tmp_path, monkeypatch):
    db=tmp_path/'fed.sqlite3'; responses=[
        {'BEAAPI':{'Results':{'Statistic':'Real GDP','UnitOfMeasure':'Millions of dollars','Data':[{'Code':'RGDP','GeoFips':'17000','GeoName':'Illinois','TimePeriod':'2025','DataValue':'901234','UNIT_MULT':'6'}]}}},
        {'response':{'total':1,'data':[{'period':'2025-07','stateid':'IL','stateDescription':'Illinois','sales':'123.4','sales-units':'million kWh'}]}},
        [{'FACILITY_NAME':'Example Facility','STATE_ABBR':'IL'}],
        {'type':'FeatureCollection','numberMatched':1,'features':[{'type':'Feature','id':'USGS-1','geometry':{'type':'Point','coordinates':[-87.6,41.8]},'properties':{'monitoring_location_id':'USGS-05586300','parameter_code':'00060','statistic_id':'00003','time':'2026-08-10','value':'345','unit_of_measure':'ft3/s'}}]},
    ]
    monkeypatch.setenv('TEST_BEA_KEY','bea-secret'); monkeypatch.setenv('TEST_EIA_KEY','eia-secret'); monkeypatch.setenv('TEST_USGS_KEY','usgs-secret')
    def opener(req,timeout=0): return FakeResponse(responses.pop(0))
    svc=USPublicDataService(CatalystRepository(db),opener=opener,sleeper=lambda _:None)
    assert svc.fetch_bea_data('Regional',{'TableName':'SQGDP9N','Year':'2025'},credential_env='TEST_BEA_KEY')['records']==1
    assert svc.fetch_eia_data('electricity/retail-sales',['sales'],facets={'stateid':['IL']},length=100,max_pages=1,credential_env='TEST_EIA_KEY')['rows']==1
    assert svc.fetch_epa_records('TRI.TRI_FACILITY',filters=[{'column':'STATE_ABBR','operator':'equals','value':'IL'}],page_size=10,max_pages=1)['records']==1
    assert svc.fetch_usgs_water('daily',limit=10,max_pages=1,credential_env='TEST_USGS_KEY')['records']==1
    status=svc.status(); assert status['bea_observation_count']==1 and status['eia_observation_count']==1 and status['epa_record_count']==1 and status['usgs_observation_count']==1
    assert svc.epa_records(table='TRI.TRI_FACILITY')[0]['record']['FACILITY_NAME']=='Example Facility'


def test_migration_eighteen_rollback_and_reapply(tmp_path):
    repository=CatalystRepository(tmp_path/'migration18.sqlite3'); repository.initialize(target=18)
    assert repository.health().migration_version==18
    with connect(repository.path,readonly=True) as c: assert c.execute("SELECT name FROM sqlite_master WHERE name='us_public_data_status'").fetchone()
    assert repository.rollback(1)==[18]
    with connect(repository.path,readonly=True) as c: assert c.execute("SELECT name FROM sqlite_master WHERE name='us_public_data_status'").fetchone() is None
    assert repository.migrate(target=18)==[18]


def test_public_us_api_reads_cache_only(tmp_path, monkeypatch):
    db=tmp_path/'public.sqlite3'; monkeypatch.setenv('TEST_CENSUS_KEY','secret')
    svc=USPublicDataService(CatalystRepository(db),opener=lambda req,timeout=0:FakeResponse([['NAME','B01003_001E','state'],['Illinois','12700000','17']]),sleeper=lambda _:None)
    svc.fetch_census(2024,'acs/acs5',['NAME','B01003_001E'],for_predicate='state:*',credential_env='TEST_CENSUS_KEY')
    server=CatalystApiServer(('127.0.0.1',0),svc.repository,allow_origin='https://sustainablecatalyst.com'); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start(); base=f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base+'/v1/us-public/observations?provider=census&metric=B01003_001E',timeout=5) as response: body=json.loads(response.read())
        assert body['observations'][0]['value_numeric']==12700000.0
        with urlopen(base+'/v1/us-public/status',timeout=5) as response: status=json.loads(response.read())
        assert status['census_observation_count']==1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
