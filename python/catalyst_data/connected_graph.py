from __future__ import annotations

import hashlib
import json
import secrets
from collections import deque
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .database import connect, transaction
from .dataset_catalog import DatasetCatalogService
from .entity_resolution import EntityResolutionService
from .repository import CatalystRepository, canonical_json


class ConnectedGraphError(RuntimeError):
    pass


DCAT_DATASET = "http://www.w3.org/ns/dcat#Dataset"
PROV_ENTITY = "http://www.w3.org/ns/prov#Entity"
PROV_AGENT = "http://www.w3.org/ns/prov#Agent"
DCT_PUBLISHER = "http://purl.org/dc/terms/publisher"
PROV_WAS_DERIVED_FROM = "http://www.w3.org/ns/prov#wasDerivedFrom"
CATALYST_NS = "https://sustainablecatalyst.com/ns/catalyst-data#"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_node(namespace: str, resource_id: str) -> str:
    digest = hashlib.sha256(f"{namespace}|{resource_id}".encode("utf-8")).hexdigest()[:32]
    return f"graph-node:{digest}"


def _stable_edge(subject: str, predicate: str, object_id: str, source_namespace: str, source_record_id: str) -> str:
    raw = f"{subject}|{predicate}|{object_id}|{source_namespace}|{source_record_id}".encode("utf-8")
    return "graph-edge:" + hashlib.sha256(raw).hexdigest()[:32]


def _decode(row: Any) -> dict[str, Any]:
    item = dict(row)
    for key in tuple(item):
        if key.endswith("_json") and item[key] is not None:
            raw = item.pop(key)
            try:
                item[key[:-5]] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                item[key[:-5]] = raw
    return item


class ConnectedGraphService:
    """Rebuildable connected-data graph over Catalyst Data governed caches.

    The graph is an index and federation layer, never an acquisition layer.
    Provider-native tables, canonical entities, and the dataset catalog remain
    authoritative. Every edge records the source namespace and source record
    that justified it so the graph can be rebuilt or reversed safely.
    """

    def __init__(self, repository: CatalystRepository):
        self.repository = repository
        self.repository.initialize()

    @staticmethod
    def _provider_semantic_type(provider: str) -> str:
        return PROV_AGENT

    def _upsert_node(
        self,
        connection: Any,
        *,
        resource_namespace: str,
        resource_id: str,
        node_type: str,
        label: str,
        semantic_type: str = PROV_ENTITY,
        canonical_entity_id: str | None = None,
        provider: str | None = None,
        source_uri: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        now: str,
    ) -> str:
        node_id = _stable_node(resource_namespace, resource_id)
        connection.execute(
            """
            INSERT INTO connected_graph_nodes(
                node_id,node_type,semantic_type,resource_namespace,resource_id,
                canonical_entity_id,label,provider,source_uri,metadata_json,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?, 'active', ?, ?)
            ON CONFLICT(resource_namespace,resource_id) DO UPDATE SET
                node_type=excluded.node_type,semantic_type=excluded.semantic_type,
                canonical_entity_id=excluded.canonical_entity_id,label=excluded.label,
                provider=excluded.provider,source_uri=excluded.source_uri,
                metadata_json=excluded.metadata_json,status='active',updated_at=excluded.updated_at
            """,
            (
                node_id,node_type,semantic_type,resource_namespace,resource_id,
                canonical_entity_id,label,provider,source_uri,canonical_json(dict(metadata or {})),now,now,
            ),
        )
        return node_id

    def _upsert_edge(
        self,
        connection: Any,
        *,
        subject_node_id: str,
        predicate: str,
        object_node_id: str,
        source_namespace: str,
        source_record_id: str,
        source_uri: str | None = None,
        semantic_predicate: str | None = None,
        confidence: float = 1.0,
        evidence: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        now: str,
    ) -> str:
        edge_id = _stable_edge(subject_node_id,predicate,object_node_id,source_namespace,source_record_id)
        connection.execute(
            """
            INSERT INTO connected_graph_edges(
                edge_id,subject_node_id,predicate,semantic_predicate,object_node_id,
                source_namespace,source_record_id,source_uri,confidence,evidence_json,
                metadata_json,status,first_seen_at,last_seen_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?)
            ON CONFLICT(edge_id) DO UPDATE SET
                semantic_predicate=excluded.semantic_predicate,source_uri=excluded.source_uri,
                confidence=excluded.confidence,evidence_json=excluded.evidence_json,
                metadata_json=excluded.metadata_json,status='active',last_seen_at=excluded.last_seen_at,
                updated_at=excluded.updated_at
            """,
            (
                edge_id,subject_node_id,predicate,semantic_predicate,object_node_id,
                source_namespace,source_record_id,source_uri,max(0.0,min(1.0,float(confidence))),
                canonical_json(dict(evidence or {})),canonical_json(dict(metadata or {})),now,now,now,
            ),
        )
        return edge_id

    def sync(self) -> dict[str, Any]:
        # These are derived, local-only synchronizations. They do not call providers.
        entity_sync = EntityResolutionService(self.repository).sync()
        catalog_sync = DatasetCatalogService(self.repository).sync()
        now = _now()

        with connect(self.repository.path) as connection, transaction(connection):
            previous_edges = {row[0] for row in connection.execute("SELECT edge_id FROM connected_graph_edges WHERE status='active'")}
            connection.execute("UPDATE connected_graph_nodes SET status='inactive',updated_at=? WHERE status='active'", (now,))
            connection.execute("UPDATE connected_graph_edges SET status='inactive',updated_at=? WHERE status='active'", (now,))

            provider_nodes: dict[str, str] = {}
            entity_nodes: dict[str, str] = {}
            dataset_nodes: dict[str, str] = {}

            # Provider agents come from the synchronized catalog, keeping the graph provider-neutral.
            for row in connection.execute(
                "SELECT provider,MAX(publisher) AS publisher,MAX(source_uri) AS source_uri FROM dataset_catalog_entries WHERE active=1 GROUP BY provider ORDER BY provider"
            ):
                provider = row["provider"]
                provider_nodes[provider] = self._upsert_node(
                    connection,resource_namespace="provider",resource_id=provider,node_type="provider",
                    semantic_type=PROV_AGENT,label=row["publisher"] or provider,provider=provider,
                    source_uri=row["source_uri"],metadata={"provider_code":provider},now=now,
                )

            # Canonical identity nodes.
            for row in connection.execute("SELECT * FROM canonical_entities WHERE status!='deprecated' ORDER BY entity_id"):
                item = dict(row)
                entity_nodes[item["entity_id"]] = self._upsert_node(
                    connection,resource_namespace="canonical-entity",resource_id=item["entity_id"],
                    node_type=item["entity_type"],semantic_type=PROV_ENTITY,
                    canonical_entity_id=item["entity_id"],label=item["canonical_name"],source_uri=item["source_uri"],
                    metadata={"canonical_key":item["canonical_key"],"status":item["status"]},now=now,
                )

            # Dataset catalog nodes and publisher edges.
            for row in connection.execute("SELECT * FROM dataset_catalog_entries WHERE active=1 ORDER BY provider,dataset_key"):
                item = dict(row)
                node_id = self._upsert_node(
                    connection,resource_namespace="dataset-catalog",resource_id=item["catalog_id"],node_type="dataset",
                    semantic_type=DCAT_DATASET,label=item["title"],provider=item["provider"],source_uri=item["source_uri"],
                    metadata={"dataset_key":item["dataset_key"],"resource_kind":item["resource_kind"],"freshness_status":item["freshness_status"],"record_count":item["record_count"]},now=now,
                )
                dataset_nodes[item["catalog_id"]] = node_id
                provider_node = provider_nodes.get(item["provider"])
                if provider_node:
                    self._upsert_edge(
                        connection,subject_node_id=node_id,predicate="published-by",semantic_predicate=DCT_PUBLISHER,
                        object_node_id=provider_node,source_namespace="dataset-catalog",source_record_id=item["catalog_id"],
                        source_uri=item["source_uri"],metadata={"publisher":item["publisher"]},now=now,
                    )

            # Provider identifier crosswalks make identity-to-provider edges explicit.
            namespace_provider = {
                "world-bank-country":"world-bank",
                "un-sdg-geoarea":"un-sdg",
                "census-geography":"census",
            }
            for row in connection.execute(
                "SELECT entity_id,namespace,identifier,source_uri,confidence FROM entity_identifiers WHERE namespace IN ('world-bank-country','un-sdg-geoarea','census-geography') ORDER BY entity_id,namespace"
            ):
                provider = namespace_provider[row["namespace"]]
                subject = entity_nodes.get(row["entity_id"]); object_id = provider_nodes.get(provider)
                if subject and object_id:
                    self._upsert_edge(
                        connection,subject_node_id=subject,predicate="represented-in",object_node_id=object_id,
                        source_namespace="entity-identifier",source_record_id=f"{row['namespace']}:{row['identifier']}",
                        source_uri=row["source_uri"],confidence=float(row["confidence"]),
                        evidence={"namespace":row["namespace"],"identifier":row["identifier"]},now=now,
                    )

            # Cross-source statistical federation anchors: entity -> dataset series.
            statistical_specs = (
                (
                    "world-bank","world-bank-country",
                    "SELECT country_code AS geo,indicator_code AS dataset_key,COUNT(*) AS observation_count,MIN(period) AS temporal_start,MAX(period) AS temporal_end,MAX(source_uri) AS source_uri FROM world_bank_observations GROUP BY country_code,indicator_code",
                ),
                (
                    "un-sdg","un-sdg-geoarea",
                    "SELECT geo_area_code AS geo,indicator_code AS dataset_key,COUNT(*) AS observation_count,MIN(time_period) AS temporal_start,MAX(time_period) AS temporal_end,MAX(source_uri) AS source_uri FROM un_sdg_observations WHERE indicator_code IS NOT NULL GROUP BY geo_area_code,indicator_code",
                ),
                (
                    "census","census-geography",
                    "SELECT geography_id AS geo,(dataset || ':' || variable_code) AS dataset_key,COUNT(*) AS observation_count,MIN(CAST(year AS TEXT)) AS temporal_start,MAX(CAST(year AS TEXT)) AS temporal_end,MAX(source_uri) AS source_uri FROM census_observations GROUP BY geography_id,dataset,variable_code",
                ),
            )
            for provider, namespace, sql in statistical_specs:
                for row in connection.execute(sql):
                    ident = connection.execute(
                        "SELECT entity_id FROM entity_identifiers WHERE namespace=? AND identifier=? LIMIT 1",
                        (namespace,str(row["geo"])),
                    ).fetchone()
                    catalog = connection.execute(
                        "SELECT catalog_id FROM dataset_catalog_entries WHERE provider=? AND dataset_key=? AND active=1 LIMIT 1",
                        (provider,row["dataset_key"]),
                    ).fetchone()
                    if not ident or not catalog:
                        continue
                    subject = entity_nodes.get(ident["entity_id"]); object_id = dataset_nodes.get(catalog["catalog_id"])
                    if subject and object_id:
                        self._upsert_edge(
                            connection,subject_node_id=subject,predicate="has-observation-series",object_node_id=object_id,
                            source_namespace=provider,source_record_id=f"{row['geo']}|{row['dataset_key']}",source_uri=row["source_uri"],
                            evidence={"observation_count":int(row["observation_count"] or 0),"temporal_start":row["temporal_start"],"temporal_end":row["temporal_end"]},now=now,
                        )

            # Scientific object graph: JPL small bodies, close approaches, exoplanets and host stars.
            jpl_provider = provider_nodes.get("jpl-sbdb")
            small_body_nodes: dict[str,str] = {}
            for row in connection.execute("SELECT * FROM jpl_small_bodies ORDER BY object_id"):
                label = row["full_name"] or row["name"] or row["designation"] or row["object_id"]
                node = self._upsert_node(
                    connection,resource_namespace="jpl-small-body",resource_id=row["object_id"],node_type="scientific-object",
                    semantic_type=PROV_ENTITY,label=label,provider="jpl-sbdb",source_uri=row["source_uri"],
                    metadata={"spkid":row["spkid"],"designation":row["designation"],"orbit_class":row["orbit_class"],"is_neo":bool(row["is_neo"]),"is_pha":bool(row["is_pha"])},now=now,
                )
                small_body_nodes[str(row["designation"] or row["object_id"])] = node
                if jpl_provider:
                    self._upsert_edge(connection,subject_node_id=node,predicate="published-by",semantic_predicate=DCT_PUBLISHER,object_node_id=jpl_provider,source_namespace="jpl-sbdb",source_record_id=row["object_id"],source_uri=row["source_uri"],now=now)

            cneos_provider = provider_nodes.get("jpl-cneos") or jpl_provider
            for row in connection.execute("SELECT * FROM jpl_close_approaches ORDER BY approach_id"):
                event = self._upsert_node(
                    connection,resource_namespace="jpl-close-approach",resource_id=row["approach_id"],node_type="event",
                    semantic_type=PROV_ENTITY,label=f"{row['designation']} close approach {row['close_approach_time']}",provider="jpl-cneos",source_uri=row["source_uri"],
                    metadata={"designation":row["designation"],"body":row["body"],"distance_au":row["distance_au"],"relative_velocity_km_s":row["relative_velocity_km_s"]},now=now,
                )
                if cneos_provider:
                    self._upsert_edge(connection,subject_node_id=event,predicate="published-by",semantic_predicate=DCT_PUBLISHER,object_node_id=cneos_provider,source_namespace="jpl-cneos",source_record_id=row["approach_id"],source_uri=row["source_uri"],now=now)
                target = self._upsert_node(connection,resource_namespace="astronomical-body",resource_id=row["body"],node_type="astronomical-body",semantic_type=PROV_ENTITY,label=row["body"],metadata={},now=now)
                self._upsert_edge(connection,subject_node_id=event,predicate="approaches",object_node_id=target,source_namespace="jpl-cneos",source_record_id=row["approach_id"],source_uri=row["source_uri"],now=now)
                object_node = small_body_nodes.get(str(row["designation"]))
                if object_node:
                    self._upsert_edge(connection,subject_node_id=event,predicate="involves-object",object_node_id=object_node,source_namespace="jpl-cneos",source_record_id=row["approach_id"],source_uri=row["source_uri"],now=now)

            exoplanet_provider = provider_nodes.get("nasa-exoplanet-archive")
            for row in connection.execute("SELECT * FROM nasa_exoplanets ORDER BY exoplanet_id"):
                planet = self._upsert_node(
                    connection,resource_namespace="nasa-exoplanet",resource_id=row["exoplanet_id"],node_type="scientific-object",
                    semantic_type=PROV_ENTITY,label=row["planet_name"],provider="nasa-exoplanet-archive",source_uri=row["source_uri"],
                    metadata={"host_name":row["host_name"],"discovery_method":row["discovery_method"],"discovery_year":row["discovery_year"],"radius_earth":row["radius_earth"],"mass_earth":row["mass_earth"]},now=now,
                )
                if exoplanet_provider:
                    self._upsert_edge(connection,subject_node_id=planet,predicate="published-by",semantic_predicate=DCT_PUBLISHER,object_node_id=exoplanet_provider,source_namespace="nasa-exoplanet-archive",source_record_id=row["exoplanet_id"],source_uri=row["source_uri"],now=now)
                if row["host_name"]:
                    host = self._upsert_node(connection,resource_namespace="stellar-host",resource_id=row["host_name"],node_type="stellar-object",semantic_type=PROV_ENTITY,label=row["host_name"],provider="nasa-exoplanet-archive",source_uri=row["source_uri"],metadata={},now=now)
                    self._upsert_edge(connection,subject_node_id=planet,predicate="orbits",object_node_id=host,source_namespace="nasa-exoplanet-archive",source_record_id=row["exoplanet_id"],source_uri=row["source_uri"],now=now)

            active_edges = {row[0] for row in connection.execute("SELECT edge_id FROM connected_graph_edges WHERE status='active'")}
            added = sorted(active_edges - previous_edges); removed = sorted(previous_edges - active_edges)
            for edge_id, action in [(edge_id,"added") for edge_id in added] + [(edge_id,"deactivated") for edge_id in removed]:
                event_id = "graph-event:" + secrets.token_hex(12)
                connection.execute(
                    "INSERT INTO connected_graph_edge_events(event_id,edge_id,action,actor,event_at) VALUES (?,?,?,?,?)",
                    (event_id,edge_id,action,"graph-sync",now),
                )

            digest_payload = {
                "nodes":[row[0] for row in connection.execute("SELECT node_id FROM connected_graph_nodes WHERE status='active' ORDER BY node_id")],
                "edges":[row[0] for row in connection.execute("SELECT edge_id FROM connected_graph_edges WHERE status='active' ORDER BY edge_id")],
            }
            digest = hashlib.sha256(canonical_json(digest_payload).encode("utf-8")).hexdigest()
            sync_id = "graph-sync:" + secrets.token_hex(12)
            node_count = len(digest_payload["nodes"]); edge_count = len(digest_payload["edges"])
            connection.execute(
                "INSERT INTO connected_graph_sync_runs(sync_id,node_count,edge_count,added_edge_count,deactivated_edge_count,graph_sha256,synced_at) VALUES (?,?,?,?,?,?,?)",
                (sync_id,node_count,edge_count,len(added),len(removed),digest,now),
            )

        return {
            "sync_id":sync_id,"node_count":node_count,"edge_count":edge_count,
            "added_edge_count":len(added),"deactivated_edge_count":len(removed),"graph_sha256":digest,
            "entity_sync":entity_sync,"catalog_sync":catalog_sync,"status":self.status(),
        }

    def status(self) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute("SELECT * FROM connected_graph_status").fetchone()
        return dict(row) if row else {}

    def search_nodes(self, *, query: str | None=None, node_type: str | None=None, provider: str | None=None, limit: int=50, offset: int=0) -> list[dict[str,Any]]:
        clauses=["status='active'"]; params:list[Any]=[]
        if node_type: clauses.append("node_type=?"); params.append(node_type)
        if provider: clauses.append("provider=?"); params.append(provider)
        if query:
            needle=f"%{query.strip()}%"; clauses.append("(label LIKE ? OR resource_id LIKE ? OR resource_namespace LIKE ? OR metadata_json LIKE ?)"); params.extend([needle]*4)
        sql="SELECT * FROM connected_graph_nodes WHERE "+" AND ".join(clauses)+" ORDER BY node_type,label,node_id LIMIT ? OFFSET ?"
        params.extend([max(1,min(500,int(limit))),max(0,int(offset))])
        with connect(self.repository.path,readonly=True) as connection:
            return [_decode(row) for row in connection.execute(sql,tuple(params)).fetchall()]

    def get_node(self, node_id: str) -> dict[str,Any] | None:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("SELECT * FROM connected_graph_nodes WHERE node_id=?",(node_id,)).fetchone()
            if not row: return None
            item=_decode(row)
            item["outgoing_edge_count"]=int(connection.execute("SELECT COUNT(*) FROM connected_graph_edges WHERE subject_node_id=? AND status='active'",(node_id,)).fetchone()[0])
            item["incoming_edge_count"]=int(connection.execute("SELECT COUNT(*) FROM connected_graph_edges WHERE object_node_id=? AND status='active'",(node_id,)).fetchone()[0])
            return item

    def neighbors(self, node_id: str, *, predicate: str | None=None, direction: str="both", limit: int=100) -> list[dict[str,Any]]:
        if direction not in {"out","in","both"}: raise ConnectedGraphError("direction must be out, in, or both")
        params:list[Any]=[]; parts=[]
        if direction in {"out","both"}:
            clause="e.subject_node_id=? AND e.status='active'"; p=[node_id]
            if predicate: clause+=" AND e.predicate=?"; p.append(predicate)
            parts.append(("SELECT e.*,n.node_id AS neighbor_node_id,n.node_type AS neighbor_node_type,n.label AS neighbor_label,n.provider AS neighbor_provider,'out' AS direction FROM connected_graph_edges e JOIN connected_graph_nodes n ON n.node_id=e.object_node_id WHERE "+clause,p))
        if direction in {"in","both"}:
            clause="e.object_node_id=? AND e.status='active'"; p=[node_id]
            if predicate: clause+=" AND e.predicate=?"; p.append(predicate)
            parts.append(("SELECT e.*,n.node_id AS neighbor_node_id,n.node_type AS neighbor_node_type,n.label AS neighbor_label,n.provider AS neighbor_provider,'in' AS direction FROM connected_graph_edges e JOIN connected_graph_nodes n ON n.node_id=e.subject_node_id WHERE "+clause,p))
        sql=" UNION ALL ".join(part[0] for part in parts)+" ORDER BY predicate,neighbor_label LIMIT ?"
        for _,p in parts: params.extend(p)
        params.append(max(1,min(500,int(limit))))
        with connect(self.repository.path,readonly=True) as connection:
            return [_decode(row) for row in connection.execute(sql,tuple(params)).fetchall()]

    def shortest_path(self, start_node_id: str, end_node_id: str, *, max_depth: int=4) -> dict[str,Any]:
        max_depth=max(1,min(6,int(max_depth)))
        if start_node_id==end_node_id: return {"found":True,"nodes":[start_node_id],"edges":[],"depth":0}
        with connect(self.repository.path,readonly=True) as connection:
            if not connection.execute("SELECT 1 FROM connected_graph_nodes WHERE node_id=? AND status='active'",(start_node_id,)).fetchone(): raise ConnectedGraphError("start node not found")
            if not connection.execute("SELECT 1 FROM connected_graph_nodes WHERE node_id=? AND status='active'",(end_node_id,)).fetchone(): raise ConnectedGraphError("end node not found")
            queue=deque([(start_node_id,[start_node_id],[]) ]); visited={start_node_id}
            while queue:
                current,nodes,edges=queue.popleft()
                if len(edges)>=max_depth: continue
                rows=connection.execute("SELECT edge_id,subject_node_id,predicate,object_node_id FROM connected_graph_edges WHERE status='active' AND (subject_node_id=? OR object_node_id=?) ORDER BY predicate,edge_id",(current,current)).fetchall()
                for row in rows:
                    neighbor=row["object_node_id"] if row["subject_node_id"]==current else row["subject_node_id"]
                    if neighbor in visited: continue
                    edge={"edge_id":row["edge_id"],"predicate":row["predicate"],"from":current,"to":neighbor}
                    if neighbor==end_node_id:
                        return {"found":True,"nodes":nodes+[neighbor],"edges":edges+[edge],"depth":len(edges)+1}
                    visited.add(neighbor); queue.append((neighbor,nodes+[neighbor],edges+[edge]))
        return {"found":False,"nodes":[],"edges":[],"depth":None}

    def federate_entity(self, entity_id: str, *, limit_per_source: int=100) -> dict[str,Any]:
        limit=max(1,min(500,int(limit_per_source)))
        entity=EntityResolutionService(self.repository).get(entity_id)
        if entity is None: raise ConnectedGraphError("canonical entity not found")
        identifiers={item["namespace"]:item["identifier"] for item in entity.get("identifiers",[])}
        sources=[]
        with connect(self.repository.path,readonly=True) as connection:
            if identifiers.get("world-bank-country"):
                code=identifiers["world-bank-country"]
                total=int(connection.execute("SELECT COUNT(*) FROM world_bank_observations WHERE country_code=?",(code,)).fetchone()[0])
                rows=connection.execute("SELECT observation_id,indicator_code,indicator_name,period,value_numeric,value_text,unit,source_uri,fetched_at FROM world_bank_observations WHERE country_code=? ORDER BY period DESC,indicator_code LIMIT ?",(code,limit)).fetchall()
                sources.append({"provider":"world-bank","identifier":code,"total":total,"observations":[dict(r) for r in rows]})
            if identifiers.get("un-sdg-geoarea"):
                code=identifiers["un-sdg-geoarea"]
                total=int(connection.execute("SELECT COUNT(*) FROM un_sdg_observations WHERE geo_area_code=?",(code,)).fetchone()[0])
                rows=connection.execute("SELECT observation_id,indicator_code,series_code,series_description,time_period,value_numeric,value_text,units,source_uri,fetched_at FROM un_sdg_observations WHERE geo_area_code=? ORDER BY time_period DESC,indicator_code LIMIT ?",(code,limit)).fetchall()
                sources.append({"provider":"un-sdg","identifier":code,"total":total,"observations":[dict(r) for r in rows]})
            if identifiers.get("census-geography"):
                code=identifiers["census-geography"]
                total=int(connection.execute("SELECT COUNT(*) FROM census_observations WHERE geography_id=?",(code,)).fetchone()[0])
                rows=connection.execute("SELECT observation_id,dataset,year,variable_code,value_numeric,value_text,source_uri,fetched_at FROM census_observations WHERE geography_id=? ORDER BY year DESC,dataset,variable_code LIMIT ?",(code,limit)).fetchall()
                sources.append({"provider":"census","identifier":code,"total":total,"observations":[dict(r) for r in rows]})
            node=connection.execute("SELECT node_id FROM connected_graph_nodes WHERE canonical_entity_id=? AND status='active' LIMIT 1",(entity_id,)).fetchone()
        graph_node_id=node["node_id"] if node else None
        return {"entity":entity,"graph_node_id":graph_node_id,"source_count":len(sources),"sources":sources,"limit_per_source":limit}

    def export_jsonld(self, *, node_id: str | None=None, limit: int=500) -> dict[str,Any]:
        limit=max(1,min(2000,int(limit)))
        with connect(self.repository.path,readonly=True) as connection:
            if node_id:
                node_ids={node_id}
                for row in connection.execute("SELECT subject_node_id,object_node_id FROM connected_graph_edges WHERE status='active' AND (subject_node_id=? OR object_node_id=?) LIMIT ?",(node_id,node_id,limit)):
                    node_ids.add(row["subject_node_id"]); node_ids.add(row["object_node_id"])
                placeholders=",".join("?" for _ in node_ids)
                nodes=[_decode(r) for r in connection.execute(f"SELECT * FROM connected_graph_nodes WHERE node_id IN ({placeholders}) ORDER BY node_id",tuple(node_ids)).fetchall()]
                edges=[_decode(r) for r in connection.execute("SELECT * FROM connected_graph_edges WHERE status='active' AND (subject_node_id=? OR object_node_id=?) ORDER BY edge_id LIMIT ?",(node_id,node_id,limit)).fetchall()]
            else:
                nodes=[_decode(r) for r in connection.execute("SELECT * FROM connected_graph_nodes WHERE status='active' ORDER BY node_id LIMIT ?",(limit,)).fetchall()]
                edges=[_decode(r) for r in connection.execute("SELECT * FROM connected_graph_edges WHERE status='active' ORDER BY edge_id LIMIT ?",(limit,)).fetchall()]
        graph=[]
        for node in nodes:
            graph.append({"@id":node["node_id"],"@type":node.get("semantic_type") or PROV_ENTITY,"catalyst:nodeType":node["node_type"],"catalyst:label":node["label"],"catalyst:resourceNamespace":node["resource_namespace"],"catalyst:resourceId":node["resource_id"],"catalyst:provider":node.get("provider"),"catalyst:sourceUri":node.get("source_uri")})
        for edge in edges:
            graph.append({"@id":edge["edge_id"],"@type":"catalyst:Edge","catalyst:subject":{"@id":edge["subject_node_id"]},"catalyst:predicate":edge["predicate"],"catalyst:semanticPredicate":edge.get("semantic_predicate"),"catalyst:object":{"@id":edge["object_node_id"]},"catalyst:sourceNamespace":edge["source_namespace"],"catalyst:sourceRecordId":edge["source_record_id"],"catalyst:sourceUri":edge.get("source_uri"),"catalyst:confidence":edge["confidence"]})
        return {"@context":{"dcat":"http://www.w3.org/ns/dcat#","prov":"http://www.w3.org/ns/prov#","dct":"http://purl.org/dc/terms/","catalyst":CATALYST_NS},"@graph":graph,"truncated":len(nodes)>=limit or len(edges)>=limit}
