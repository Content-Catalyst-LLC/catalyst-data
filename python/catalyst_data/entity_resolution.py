from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any, Mapping

from .database import connect, transaction
from .repository import CatalystRepository, canonical_json


class EntityResolutionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(entity_type: str, canonical_key: str) -> str:
    raw=f"{entity_type}|{canonical_key}".encode("utf-8")
    return "entity:"+hashlib.sha256(raw).hexdigest()[:32]


def _normalize(value: str) -> str:
    text=unicodedata.normalize("NFKD", str(value or "")).casefold()
    text="".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _row(row: Any) -> dict[str, Any]:
    item=dict(row)
    for key in tuple(item):
        if key.endswith("_json") and item[key] is not None:
            try: item[key[:-5]]=json.loads(item.pop(key))
            except (TypeError, json.JSONDecodeError): pass
    return item


class EntityResolutionService:
    """Canonical entity registry and identifier resolver.

    Exact identifiers are authoritative. Name/alias matching is deliberately
    conservative; no provider record is merged into another entity through
    fuzzy similarity alone.
    """

    def __init__(self, repository: CatalystRepository):
        self.repository=repository
        self.repository.initialize()

    def register_entity(self, entity_type: str, canonical_key: str, canonical_name: str, *, parent_entity_id: str | None=None, source_uri: str | None=None, metadata: Mapping[str,Any] | None=None, status: str="active") -> dict[str,Any]:
        entity_type=str(entity_type).strip().lower(); canonical_key=str(canonical_key).strip(); canonical_name=str(canonical_name).strip()
        if not entity_type or not canonical_key or not canonical_name: raise EntityResolutionError("entity_type, canonical_key, and canonical_name are required")
        if status not in {"active","historical","provisional","deprecated"}: raise EntityResolutionError("invalid entity status")
        entity_id=_stable_id(entity_type,canonical_key); now=_now()
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute("""INSERT INTO canonical_entities(entity_id,entity_type,canonical_key,canonical_name,canonical_name_normalized,parent_entity_id,status,source_uri,metadata_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(entity_type,canonical_key) DO UPDATE SET canonical_name=excluded.canonical_name,canonical_name_normalized=excluded.canonical_name_normalized,parent_entity_id=excluded.parent_entity_id,status=excluded.status,source_uri=excluded.source_uri,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                (entity_id,entity_type,canonical_key,canonical_name,_normalize(canonical_name),parent_entity_id,status,source_uri,canonical_json(dict(metadata or {})),now,now))
        return self.get(entity_id) or {}

    def add_identifier(self, entity_id: str, namespace: str, identifier: str, *, identifier_type: str="provider", source_uri: str | None=None, confidence: float=1.0, primary: bool=False, metadata: Mapping[str,Any] | None=None) -> dict[str,Any]:
        namespace=str(namespace).strip().lower(); identifier=str(identifier).strip()
        if not namespace or not identifier: raise EntityResolutionError("namespace and identifier are required")
        confidence=max(0.0,min(1.0,float(confidence))); now=_now()
        identifier_id="identifier:"+hashlib.sha256(f"{namespace}|{identifier}".encode()).hexdigest()[:32]
        with connect(self.repository.path) as connection, transaction(connection):
            if not connection.execute("SELECT 1 FROM canonical_entities WHERE entity_id=?",(entity_id,)).fetchone(): raise EntityResolutionError("entity does not exist")
            existing=connection.execute("SELECT entity_id FROM entity_identifiers WHERE namespace=? AND identifier=?",(namespace,identifier)).fetchone()
            if existing and existing["entity_id"] != entity_id: raise EntityResolutionError(f"identifier already belongs to {existing['entity_id']}")
            connection.execute("""INSERT INTO entity_identifiers(identifier_id,entity_id,namespace,identifier,identifier_normalized,identifier_type,source_uri,confidence,is_primary,metadata_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(namespace,identifier) DO UPDATE SET identifier_type=excluded.identifier_type,source_uri=excluded.source_uri,confidence=excluded.confidence,is_primary=excluded.is_primary,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                (identifier_id,entity_id,namespace,identifier,_normalize(identifier),identifier_type,source_uri,confidence,1 if primary else 0,canonical_json(dict(metadata or {})),now,now))
            row=connection.execute("SELECT * FROM entity_identifiers WHERE namespace=? AND identifier=?",(namespace,identifier)).fetchone()
        return _row(row)

    def add_alias(self, entity_id: str, alias: str, *, language: str="und", alias_type: str="name", source_uri: str | None=None, confidence: float=1.0) -> dict[str,Any]:
        alias=str(alias).strip(); language=str(language or "und").strip().lower(); alias_norm=_normalize(alias)
        if not alias_norm: raise EntityResolutionError("alias is required")
        now=_now(); alias_id="alias:"+hashlib.sha256(f"{entity_id}|{language}|{alias_type}|{alias_norm}".encode()).hexdigest()[:32]
        with connect(self.repository.path) as connection, transaction(connection):
            if not connection.execute("SELECT 1 FROM canonical_entities WHERE entity_id=?",(entity_id,)).fetchone(): raise EntityResolutionError("entity does not exist")
            connection.execute("""INSERT INTO entity_aliases(alias_id,entity_id,alias,alias_normalized,language,alias_type,source_uri,confidence,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id,alias_normalized,language,alias_type) DO UPDATE SET alias=excluded.alias,source_uri=excluded.source_uri,confidence=excluded.confidence,updated_at=excluded.updated_at""",
                (alias_id,entity_id,alias,alias_norm,language,alias_type,source_uri,max(0.0,min(1.0,float(confidence))),now,now))
            row=connection.execute("SELECT * FROM entity_aliases WHERE alias_id=?",(alias_id,)).fetchone()
        return _row(row)

    def seed_countries(self) -> dict[str,Any]:
        payload=json.loads(files("catalyst_data").joinpath("resources/country_identifiers_seed.json").read_text(encoding="utf-8"))
        source_m49="https://unstats.un.org/unsd/methodology/m49/overview/"; source_iso="https://www.iso.org/iso-3166-country-codes.html"
        count=0; ids=0; aliases=0; now=_now()
        with connect(self.repository.path) as connection, transaction(connection):
            for record in payload["records"]:
                entity_id=_stable_id("country-area",record["alpha3"])
                connection.execute("""INSERT INTO canonical_entities(entity_id,entity_type,canonical_key,canonical_name,canonical_name_normalized,parent_entity_id,status,source_uri,metadata_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(entity_type,canonical_key) DO UPDATE SET canonical_name=excluded.canonical_name,canonical_name_normalized=excluded.canonical_name_normalized,status=excluded.status,source_uri=excluded.source_uri,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                    (entity_id,"country-area",record["alpha3"],record["name"],_normalize(record["name"]),None,"active",source_m49,canonical_json({"seed_schema":payload["schema_version"],"official_name":record.get("official_name")}),now,now))
                count+=1
                for ns,key,itype,src,primary in (("iso-alpha2","alpha2","standard",source_iso,0),("iso-alpha3","alpha3","standard",source_iso,1),("un-m49","m49","statistical-area",source_m49,0)):
                    identifier=record[key]; identifier_id="identifier:"+hashlib.sha256(f"{ns}|{identifier}".encode()).hexdigest()[:32]
                    connection.execute("""INSERT INTO entity_identifiers(identifier_id,entity_id,namespace,identifier,identifier_normalized,identifier_type,source_uri,confidence,is_primary,metadata_json,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(namespace,identifier) DO UPDATE SET entity_id=excluded.entity_id,identifier_type=excluded.identifier_type,source_uri=excluded.source_uri,confidence=excluded.confidence,is_primary=excluded.is_primary,updated_at=excluded.updated_at""",
                        (identifier_id,entity_id,ns,identifier,_normalize(identifier),itype,src,1.0,primary,"{}",now,now)); ids+=1
                aliases_to_add=[(record["name"],"canonical",source_m49)]
                if record.get("official_name") and record["official_name"] != record["name"]: aliases_to_add.append((record["official_name"],"official",source_iso))
                for alias,alias_type,src in aliases_to_add:
                    norm=_normalize(alias); alias_id="alias:"+hashlib.sha256(f"{entity_id}|en|{alias_type}|{norm}".encode()).hexdigest()[:32]
                    connection.execute("""INSERT INTO entity_aliases(alias_id,entity_id,alias,alias_normalized,language,alias_type,source_uri,confidence,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id,alias_normalized,language,alias_type) DO UPDATE SET alias=excluded.alias,source_uri=excluded.source_uri,confidence=excluded.confidence,updated_at=excluded.updated_at""",
                        (alias_id,entity_id,alias,norm,"en",alias_type,src,1.0,now,now)); aliases+=1
        return {"entities":count,"identifiers":ids,"aliases":aliases,"seed_schema":payload["schema_version"]}

    def sync_provider_identifiers(self) -> dict[str,Any]:
        added={"world_bank":0,"un_sdg":0,"census_geographies":0}; unresolved=[]
        with connect(self.repository.path, readonly=True) as connection:
            wb=[dict(r) for r in connection.execute("SELECT country_code,iso2_code,name,source_uri FROM world_bank_countries ORDER BY country_code")]
            un=[dict(r) for r in connection.execute("SELECT geo_area_code,geo_area_name,source_uri FROM un_sdg_geoareas ORDER BY geo_area_code")]
            census=[dict(r) for r in connection.execute("SELECT geography_id,MAX(geography_name) AS geography_name,MAX(geography_json) AS geography_json,MAX(source_uri) AS source_uri FROM census_observations GROUP BY geography_id ORDER BY geography_id")]
        for r in wb:
            match=None
            if r.get("iso2_code"): match=self.resolve(r["iso2_code"],namespace="iso-alpha2",record_event=False)
            if (not match or match["status"]!="resolved") and r.get("country_code"): match=self.resolve(r["country_code"],namespace="iso-alpha3",record_event=False)
            if match and match["status"]=="resolved":
                self.add_identifier(match["entity"]["entity_id"],"world-bank-country",r["country_code"],identifier_type="provider",source_uri=r.get("source_uri"),confidence=1.0)
                if r.get("name"): self.add_alias(match["entity"]["entity_id"],r["name"],language="en",alias_type="provider-name",source_uri=r.get("source_uri"),confidence=1.0)
                added["world_bank"]+=1
            else: unresolved.append({"provider":"world-bank","identifier":r.get("country_code"),"name":r.get("name")})
        for r in un:
            match=self.resolve(str(r["geo_area_code"]).zfill(3),namespace="un-m49",record_event=False)
            if match["status"]=="resolved":
                self.add_identifier(match["entity"]["entity_id"],"un-sdg-geoarea",str(r["geo_area_code"]),identifier_type="provider",source_uri=r.get("source_uri"),confidence=1.0)
                self.add_alias(match["entity"]["entity_id"],r["geo_area_name"],language="en",alias_type="provider-name",source_uri=r.get("source_uri"),confidence=1.0); added["un_sdg"]+=1
            else: unresolved.append({"provider":"un-sdg","identifier":r.get("geo_area_code"),"name":r.get("geo_area_name")})
        us=self.resolve("USA",namespace="iso-alpha3",record_event=False); us_id=us.get("entity",{}).get("entity_id") if us["status"]=="resolved" else None
        for r in census:
            try: geo=json.loads(r.get("geography_json") or "{}")
            except json.JSONDecodeError: geo={}
            entity=self.register_entity("subnational-geography",f"census:{r['geography_id']}",r.get("geography_name") or r["geography_id"],parent_entity_id=us_id,source_uri=r.get("source_uri"),metadata={"provider":"census","geography":geo})
            self.add_identifier(entity["entity_id"],"census-geography",r["geography_id"],identifier_type="provider",source_uri=r.get("source_uri"),confidence=1.0,primary=True)
            added["census_geographies"]+=1
        return {"added":added,"unresolved_count":len(unresolved),"unresolved":unresolved[:100]}

    def sync(self) -> dict[str,Any]:
        seeded=self.seed_countries(); providers=self.sync_provider_identifiers(); now=_now()
        with connect(self.repository.path) as connection, transaction(connection):
            digest_rows=[dict(r) for r in connection.execute("SELECT entity_id,entity_type,canonical_key,canonical_name,status FROM canonical_entities ORDER BY entity_id")]
            digest=hashlib.sha256(canonical_json(digest_rows).encode()).hexdigest(); sync_id="entity-sync:"+secrets.token_hex(12)
            connection.execute("INSERT INTO entity_sync_runs(sync_id,entity_count,registry_sha256,synced_at) VALUES (?,?,?,?)",(sync_id,len(digest_rows),digest,now))
        return {"sync_id":sync_id,"entity_count":len(digest_rows),"registry_sha256":digest,"seeded":seeded,"providers":providers,"status":self.status()}

    def resolve(self, value: str, *, namespace: str | None=None, entity_type: str | None=None, limit: int=10, record_event: bool=True, actor: str="system") -> dict[str,Any]:
        value=str(value or "").strip(); norm=_normalize(value); candidates=[]; method="none"
        if not value: raise EntityResolutionError("value is required")
        with connect(self.repository.path, readonly=True) as connection:
            if namespace:
                rows=connection.execute("""SELECT e.*,i.namespace,i.identifier,i.confidence AS match_confidence FROM entity_identifiers i JOIN canonical_entities e ON e.entity_id=i.entity_id WHERE i.namespace=? AND (i.identifier=? OR i.identifier_normalized=?) AND e.status!='deprecated' ORDER BY i.confidence DESC,e.canonical_name LIMIT ?""",(namespace.lower(),value,norm,max(1,min(100,limit)))).fetchall(); method="identifier"
            else:
                rows=connection.execute("""SELECT e.*,1.0 AS match_confidence FROM canonical_entities e WHERE e.canonical_name_normalized=? AND e.status!='deprecated' UNION SELECT e.*,a.confidence AS match_confidence FROM entity_aliases a JOIN canonical_entities e ON e.entity_id=a.entity_id WHERE a.alias_normalized=? AND e.status!='deprecated' LIMIT ?""",(norm,norm,max(1,min(100,limit)))).fetchall(); method="name-or-alias"
                if not rows:
                    rows=connection.execute("""SELECT e.*,0.65 AS match_confidence FROM canonical_entities e WHERE e.canonical_name_normalized LIKE ? AND e.status!='deprecated' ORDER BY e.canonical_name LIMIT ?""",(f"%{norm}%",max(1,min(100,limit)))).fetchall(); method="substring"
            for r in rows:
                item=_row(r)
                if entity_type and item["entity_type"]!=entity_type: continue
                item["match_confidence"]=float(item.get("match_confidence") or 0); candidates.append(item)
        uniq={c["entity_id"]:c for c in candidates}; candidates=list(uniq.values())
        status="not-found"; selected=None
        if len(candidates)==1: status="resolved"; selected=candidates[0]
        elif len(candidates)>1: status="ambiguous"
        result={"status":status,"query":value,"namespace":namespace,"method":method,"entity":selected,"candidates":candidates}
        if record_event:
            now=_now(); event_id="resolution:"+secrets.token_hex(12)
            with connect(self.repository.path) as connection, transaction(connection):
                connection.execute("INSERT INTO entity_resolution_events(event_id,query_value,namespace,entity_type,resolution_status,resolution_method,selected_entity_id,candidate_count,candidates_json,actor,resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(event_id,value,namespace,entity_type,status,method,selected["entity_id"] if selected else None,len(candidates),canonical_json([{"entity_id":c["entity_id"],"confidence":c["match_confidence"]} for c in candidates]),actor,now))
            result["event_id"]=event_id
        return result

    def get(self, entity_id: str) -> dict[str,Any] | None:
        with connect(self.repository.path, readonly=True) as connection:
            row=connection.execute("SELECT * FROM canonical_entities WHERE entity_id=?",(entity_id,)).fetchone()
            if not row: return None
            item=_row(row)
            item["identifiers"]=[_row(r) for r in connection.execute("SELECT * FROM entity_identifiers WHERE entity_id=? ORDER BY namespace,identifier",(entity_id,))]
            item["aliases"]=[_row(r) for r in connection.execute("SELECT * FROM entity_aliases WHERE entity_id=? ORDER BY language,alias",(entity_id,))]
            return item

    def status(self) -> dict[str,Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row=connection.execute("SELECT * FROM entity_registry_status").fetchone()
            return dict(row) if row else {}
