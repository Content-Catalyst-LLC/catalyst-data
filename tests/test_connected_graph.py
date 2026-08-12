from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from catalyst_data.connected_graph import ConnectedGraphService
from catalyst_data.entity_resolution import EntityResolutionService
from catalyst_data.migrations import MigrationManager
from catalyst_data.repository import CatalystRepository


def prepared(tmp_path: Path):
    repo=CatalystRepository(tmp_path/'graph.sqlite3'); repo.initialize(); return repo,ConnectedGraphService(repo)


def seed_statistical_rows(repo: CatalystRepository) -> None:
    entities=EntityResolutionService(repo); entities.seed_countries()
    kenya=entities.resolve('KEN',namespace='iso-alpha3',record_event=False)['entity']['entity_id']
    entities.add_identifier(kenya,'world-bank-country','KEN',source_uri='https://api.worldbank.org/',confidence=1.0)
    entities.add_identifier(kenya,'un-sdg-geoarea','404',source_uri='https://unstats.un.org/SDGAPI/',confidence=1.0)
    with sqlite3.connect(repo.path) as c:
        c.execute("INSERT INTO world_bank_indicators(indicator_code,name,unit,source_id,source_note,source_organization,topics_json,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",('SP.POP.TOTL','Population','people','2','Population total','World Bank','[]','{}','https://api.worldbank.org/','2026-08-11T00:00:00Z','2026-08-11T00:00:00Z'))
        c.execute("INSERT INTO world_bank_observations(observation_id,country_code,country_name,indicator_code,indicator_name,period,value_numeric,value_text,unit,decimal_places,obs_status,footnote,source_id,raw_json,source_uri,first_seen_at,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('wb:ken:2024','KEN','Kenya','SP.POP.TOTL','Population','2024',55000000,None,'people',0,None,None,'2','{}','https://api.worldbank.org/','2026-08-11T00:00:00Z','2026-08-11T00:00:00Z','2026-08-11T00:00:00Z'))
        c.execute("INSERT INTO un_sdg_indicators(indicator_code,description,goal_code,target_code,series_json,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",('1.1.1','Poverty indicator','1','1.1','[]','{}','https://unstats.un.org/SDGAPI/','2026-08-11T00:00:00Z','2026-08-11T00:00:00Z'))
        c.execute("INSERT INTO un_sdg_observations(observation_id,indicator_code,series_code,series_description,geo_area_code,geo_area_name,time_period,value_numeric,value_text,units,nature_code,dimensions_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('sdg:404:2024','1.1.1','SI_POV_DAY1','Poverty','404','Kenya','2024',30.0,None,'percent','E','{}','{}','https://unstats.un.org/SDGAPI/','2026-08-11T00:00:00Z','2026-08-11T00:00:00Z','2026-08-11T00:00:00Z'))
        c.commit()


def test_graph_sync_links_entity_provider_and_datasets(tmp_path: Path):
    repo,svc=prepared(tmp_path); seed_statistical_rows(repo)
    result=svc.sync(); assert result['node_count']>0; assert result['edge_count']>0
    kenya=EntityResolutionService(repo).resolve('KEN',namespace='iso-alpha3',record_event=False)['entity']['entity_id']
    fed=svc.federate_entity(kenya,limit_per_source=10)
    assert {s['provider'] for s in fed['sources']}=={'world-bank','un-sdg'}
    assert fed['graph_node_id']
    neighbors=svc.neighbors(fed['graph_node_id'])
    predicates={row['predicate'] for row in neighbors}
    assert 'represented-in' in predicates
    assert 'has-observation-series' in predicates


def test_graph_sync_is_rebuildable_and_history_is_immutable(tmp_path: Path):
    repo,svc=prepared(tmp_path); first=svc.sync(); second=svc.sync()
    assert first['graph_sha256']==second['graph_sha256']
    assert second['added_edge_count']==0
    with sqlite3.connect(repo.path) as c:
        row=c.execute("SELECT event_id FROM connected_graph_edge_events LIMIT 1").fetchone()
        if row:
            try: c.execute("DELETE FROM connected_graph_edge_events WHERE event_id=?",(row[0],)); c.commit()
            except sqlite3.DatabaseError: pass
            else: raise AssertionError('graph edge history must be immutable')
        row=c.execute("SELECT sync_id FROM connected_graph_sync_runs LIMIT 1").fetchone()
        try: c.execute("UPDATE connected_graph_sync_runs SET node_count=999 WHERE sync_id=?",(row[0],)); c.commit()
        except sqlite3.DatabaseError: pass
        else: raise AssertionError('graph sync history must be immutable')


def test_graph_path_and_jsonld_export(tmp_path: Path):
    repo,svc=prepared(tmp_path); seed_statistical_rows(repo); svc.sync()
    kenya=EntityResolutionService(repo).resolve('KEN',namespace='iso-alpha3',record_event=False)['entity']['entity_id']
    entity_node=svc.federate_entity(kenya)['graph_node_id']
    neighbors=svc.neighbors(entity_node,predicate='has-observation-series',direction='out')
    assert neighbors
    target=neighbors[0]['neighbor_node_id']
    path=svc.shortest_path(entity_node,target,max_depth=3); assert path['found'] and path['depth']==1
    payload=svc.export_jsonld(node_id=entity_node); assert '@context' in payload and '@graph' in payload
    assert payload['@context']['dcat']=='http://www.w3.org/ns/dcat#'


def test_migration23_rollback_reapply(tmp_path: Path):
    repo,svc=prepared(tmp_path); svc.sync()
    with sqlite3.connect(repo.path) as c:
        c.row_factory=sqlite3.Row; manager=MigrationManager(c); assert manager.current_version==23
        assert manager.rollback(1)==[23]; assert manager.current_version==22
        assert not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='connected_graph_nodes'").fetchone()
        assert manager.migrate()==[23]; assert manager.current_version==23


def test_public_api_graph_reads_do_not_mutate_history(tmp_path: Path):
    from catalyst_data.public_api import CatalystApiServer
    import threading, urllib.request
    repo,svc=prepared(tmp_path); seed_statistical_rows(repo); svc.sync()
    kenya=EntityResolutionService(repo).resolve('KEN',namespace='iso-alpha3',record_event=False)['entity']['entity_id']
    before=svc.status()['edge_event_count']
    server=CatalystApiServer(('127.0.0.1',0),repo); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        base=f"http://127.0.0.1:{server.server_address[1]}"
        payload=json.loads(urllib.request.urlopen(base+'/v1/graph/federate?value=KEN&namespace=iso-alpha3').read())
        assert payload['entity']['entity_id']==kenya
        status=json.loads(urllib.request.urlopen(base+'/v1/graph/status').read()); assert status['active_node_count']>0
        assert svc.status()['edge_event_count']==before
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_graph_cli_workflow(tmp_path: Path, capsys):
    from catalyst_data.cli import main
    database=tmp_path/'cli-graph.sqlite3'
    assert main(['graph-sync',str(database)])==0
    sync_payload=json.loads(capsys.readouterr().out); assert sync_payload['node_count']>0
    assert main(['graph-status',str(database)])==0
    status=json.loads(capsys.readouterr().out); assert status['active_node_count']>0
    assert main(['graph-search',str(database),'--node-type','provider','--limit','5'])==0
    rows=json.loads(capsys.readouterr().out); assert isinstance(rows,list) and rows


def test_graph_openapi_contract():
    from catalyst_data.public_api import openapi_document
    paths=openapi_document()['paths']
    for path in ('/v1/graph/status','/v1/graph/nodes','/v1/graph/nodes/{node_id}','/v1/graph/neighbors','/v1/graph/path','/v1/graph/federate','/v1/graph/export'):
        assert path in paths
