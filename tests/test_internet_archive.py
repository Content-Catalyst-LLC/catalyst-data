from __future__ import annotations
import json, sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'python'))
from catalyst_data.internet_archive import InternetArchiveService, InternetArchiveSearchAdapter, InternetArchiveMetadataAdapter, WaybackAvailabilityAdapter, WaybackCDXAdapter
from catalyst_data.adapters import default_adapter_registry
from catalyst_data.repository import CatalystRepository

class FakeResponse:
    def __init__(self,payload,headers=None):
        self.body=payload if isinstance(payload,bytes) else json.dumps(payload).encode(); self.status=200; self.headers=headers or {'Content-Type':'application/json'}
    def read(self,n=-1): return self.body if n<0 else self.body[:n]
    def __enter__(self): return self
    def __exit__(self,*a): return False

def test_provider_adapters_registered():
    ids={x['adapter_id'] for x in default_adapter_registry().list()}
    assert {'internet-archive-search','internet-archive-metadata','wayback-availability','wayback-cdx'} <= ids

def test_archive_search_uri_is_provider_owned():
    a=InternetArchiveSearchAdapter(); c=a.normalize_config({'query':'subject:"energy"','rows':25})
    u=a.request_uri(c,{'cursor':2}); p=urlparse(u); q=parse_qs(p.query)
    assert p.netloc=='archive.org' and p.path=='/advancedsearch.php'; assert q['q']==['subject:"energy"']; assert q['page']==['2']; assert q['rows']==['25']; assert 'identifier' in q['fl[]']

def test_metadata_identifier_rejects_path_injection():
    a=InternetArchiveMetadataAdapter()
    try: a.normalize_config({'identifier':'../../secret'})
    except Exception: pass
    else: raise AssertionError('unsafe identifier accepted')

def test_search_persists_catalog_without_measurement_coercion(tmp_path):
    db=tmp_path/'data.sqlite3'; calls=[]
    payload={'response':{'numFound':1,'docs':[{'identifier':'energy_test','title':'Energy Test','creator':'Archive Author','mediatype':'texts','subject':['energy']}]}}
    def opener(req,timeout=0): calls.append(req); return FakeResponse(payload)
    svc=InternetArchiveService(CatalystRepository(db),opener=opener,sleeper=lambda _:None)
    result=svc.search('subject:energy',rows=10)
    assert result['num_found']==1; assert svc.items(query='Energy')[0]['item_identifier']=='energy_test'; assert calls[0].headers['User-agent'].startswith('SustainableCatalyst-CatalystData/2.8.0')

def test_item_metadata_versions_and_files(tmp_path):
    db=tmp_path/'data.sqlite3'; payload={'metadata':{'identifier':'book1','title':'Book One','mediatype':'texts','creator':['A']},'files':[{'name':'book1.pdf','format':'Text PDF','size':'123','md5':'a'*32}]}
    state={'payload':payload}
    svc=InternetArchiveService(CatalystRepository(db),opener=lambda req,timeout=0:FakeResponse(state['payload']),sleeper=lambda _:None)
    item=svc.fetch_item('book1'); assert item['item_identifier']=='book1'; assert item['files'][0]['file_name']=='book1.pdf'
    svc.fetch_item('book1')
    from catalyst_data.database import connect
    with connect(db,readonly=True) as c: assert c.execute('SELECT COUNT(*) FROM internet_archive_item_versions').fetchone()[0]==1
    state['payload']={'metadata':payload['metadata'],'files':[{'name':'book1.txt','format':'Full Text','size':'99'}]}
    item=svc.fetch_item('book1')
    assert [f['file_name'] for f in item['files']]==['book1.txt']
    with connect(db,readonly=True) as c: assert c.execute('SELECT COUNT(*) FROM internet_archive_item_versions').fetchone()[0]==2

def test_wayback_availability_and_cdx_persist(tmp_path):
    db=tmp_path/'data.sqlite3'; responses=[
      {'url':'https://example.org','archived_snapshots':{'closest':{'available':True,'status':'200','timestamp':'20200102030405','url':'https://web.archive.org/web/20200102030405/https://example.org'}}},
      [['urlkey','timestamp','original','mimetype','statuscode','digest','length'],['org,example)/','20200102030405','https://example.org','text/html','200','ABC','321']]
    ]
    def opener(req,timeout=0): return FakeResponse(responses.pop(0))
    svc=InternetArchiveService(CatalystRepository(db),opener=opener,sleeper=lambda _:None)
    assert svc.wayback_available('https://example.org')['closest']['available'] is True
    out=svc.fetch_wayback_captures('https://example.org'); assert out['captures'][0]['digest']=='ABC'; assert svc.status()['wayback_capture_count']==1

def test_wayback_url_validation():
    a=WaybackAvailabilityAdapter()
    try: a.normalize_config({'url':'javascript:alert(1)'})
    except Exception: pass
    else: raise AssertionError('unsafe URL accepted')
    c=WaybackCDXAdapter().normalize_config({'url':'https://example.org','limit':5}); assert c['limit']==5

def test_public_archive_api_serves_cached_catalog_without_provider_fetch(tmp_path):
    import threading
    from urllib.request import urlopen
    from catalyst_data.public_api import CatalystApiServer
    db=tmp_path/'public.sqlite3'
    payload={'response':{'numFound':1,'docs':[{'identifier':'cached_book','title':'Cached Book','mediatype':'texts'}]}}
    svc=InternetArchiveService(CatalystRepository(db),opener=lambda req,timeout=0:FakeResponse(payload),sleeper=lambda _:None)
    svc.search('cached',rows=10)
    server=CatalystApiServer(('127.0.0.1',0),svc.repository,allow_origin='https://sustainablecatalyst.com')
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base=f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base+'/v1/archive/items?query=Cached&limit=5',timeout=5) as response:
            body=json.loads(response.read())
        assert body['items'][0]['item_identifier']=='cached_book'
        with urlopen(base+'/v1/archive/status',timeout=5) as response:
            status=json.loads(response.read())
        assert status['item_count']==1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
