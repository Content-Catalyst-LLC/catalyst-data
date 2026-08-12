import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from catalyst_data.entity_resolution import EntityResolutionError, EntityResolutionService
from catalyst_data.cli import main
from catalyst_data.public_api import CatalystApiServer, openapi_document
from catalyst_data.repository import CatalystRepository


def test_country_seed_resolves_iso_and_m49_to_same_entity(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'entities.sqlite3'); svc=EntityResolutionService(repo)
    result=svc.seed_countries(); assert result['entities'] >= 249
    iso3=svc.resolve('KEN',namespace='iso-alpha3',record_event=False)
    iso2=svc.resolve('KE',namespace='iso-alpha2',record_event=False)
    m49=svc.resolve('404',namespace='un-m49',record_event=False)
    assert iso3['status']==iso2['status']==m49['status']=='resolved'
    assert iso3['entity']['entity_id']==iso2['entity']['entity_id']==m49['entity']['entity_id']
    assert iso3['entity']['canonical_name']=='Kenya'


def test_provider_crosswalks_attach_to_authoritative_country(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'providers.sqlite3'); svc=EntityResolutionService(repo); svc.seed_countries()
    with sqlite3.connect(repo.path) as con:
        con.execute("INSERT INTO world_bank_countries(country_code,iso2_code,name,metadata_json,source_uri,fetched_at,updated_at) VALUES ('KEN','KE','Kenya','{}','https://api.worldbank.org/v2/country/KEN','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
        con.execute("INSERT INTO un_sdg_geoareas(geo_area_code,geo_area_name,type_code,parent_code,metadata_json,source_uri,fetched_at,updated_at) VALUES ('404','Kenya',NULL,NULL,'{}','https://unstats.un.org/SDGAPI/','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
    synced=svc.sync_provider_identifiers(); assert synced['added']['world_bank']==1 and synced['added']['un_sdg']==1
    wb=svc.resolve('KEN',namespace='world-bank-country',record_event=False); un=svc.resolve('404',namespace='un-sdg-geoarea',record_event=False)
    assert wb['entity']['entity_id']==un['entity']['entity_id']==svc.resolve('KEN',namespace='iso-alpha3',record_event=False)['entity']['entity_id']


def test_identifier_conflict_is_fail_closed(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'conflict.sqlite3'); svc=EntityResolutionService(repo)
    a=svc.register_entity('organization','a','A'); b=svc.register_entity('organization','b','B')
    svc.add_identifier(a['entity_id'],'example','123')
    try: svc.add_identifier(b['entity_id'],'example','123')
    except EntityResolutionError: pass
    else: raise AssertionError('identifier conflict must fail closed')


def test_resolution_history_and_migration22_rollback(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'migration22.sqlite3'); svc=EntityResolutionService(repo); svc.seed_countries()
    result=svc.resolve('KEN',namespace='iso-alpha3'); assert result['status']=='resolved' and result['event_id'].startswith('resolution:')
    with sqlite3.connect(repo.path) as con:
        assert con.execute('SELECT COUNT(*) FROM entity_resolution_events').fetchone()[0]==1
    repo.rollback(1); assert repo.health().migration_version==21
    repo.migrate(target=22); assert repo.health().migration_version==22


def test_public_entity_openapi_is_read_only_discovery(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'api.sqlite3'); svc=EntityResolutionService(repo); svc.seed_countries()
    doc=openapi_document(); assert '/v1/entities/status' in doc['paths'] and '/v1/entities/resolve' in doc['paths'] and '/v1/entities/{entity_id}' in doc['paths']
    before=svc.status()['resolution_event_count']; result=svc.resolve('KEN',namespace='iso-alpha3',record_event=False); after=svc.status()['resolution_event_count']
    assert result['status']=='resolved' and before==after==0


def test_public_entity_http_resolver_reads_registry_only(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'http.sqlite3'); svc=EntityResolutionService(repo); svc.seed_countries()
    server=CatalystApiServer(("127.0.0.1",0),repo,allow_origin="https://sustainablecatalyst.com")
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start(); base=f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base+"/v1/entities/resolve?value=KEN&namespace=iso-alpha3",timeout=5) as response: payload=json.loads(response.read())
        assert payload['status']=='resolved' and payload['entity']['canonical_name']=='Kenya'
        entity_id=payload['entity']['entity_id']
        with urlopen(base+"/v1/entities/"+quote(entity_id,safe=''),timeout=5) as response: item=json.loads(response.read())
        assert any(identifier['namespace']=='un-m49' and identifier['identifier']=='404' for identifier in item['identifiers'])
        assert svc.status()['resolution_event_count']==0
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_entity_cli_seed_and_resolve(tmp_path: Path, capsys):
    database=tmp_path/'cli.sqlite3'
    assert main(['entity-seed-countries',str(database)])==0
    seeded=json.loads(capsys.readouterr().out); assert seeded['entities']>=249
    assert main(['entity-resolve',str(database),'KEN','--namespace','iso-alpha3','--no-record'])==0
    resolved=json.loads(capsys.readouterr().out); assert resolved['status']=='resolved' and resolved['entity']['canonical_name']=='Kenya'
