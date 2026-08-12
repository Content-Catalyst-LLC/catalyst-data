from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .database import connect, transaction
from .repository import CatalystRepository, canonical_json


class DatasetCatalogError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(provider: str, dataset_key: str) -> str:
    raw = f"{provider}|{dataset_key}".encode("utf-8")
    return "dataset:" + hashlib.sha256(raw).hexdigest()[:32]


def _freshness(timestamp: str | None) -> str:
    if not timestamp:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days
    except (TypeError, ValueError):
        return "unknown"
    if age <= 30:
        return "fresh"
    if age <= 90:
        return "aging"
    return "stale"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _rowdict(row: Any) -> dict[str, Any]:
    return dict(row)


class DatasetCatalogService:
    """Derived registry over provider-native Catalyst Data caches.

    The catalog never owns acquisition. ``sync`` rebuilds discovery metadata from
    governed provider tables already present in Catalyst Data.
    """

    def __init__(self, repository: CatalystRepository):
        self.repository = repository
        self.repository.initialize()

    def _entry(
        self,
        *,
        provider: str,
        dataset_key: str,
        title: str,
        resource_kind: str,
        publisher: str,
        source_uri: str,
        description: str | None = None,
        record_count: int = 0,
        geographic_coverage: str | None = None,
        temporal_start: str | None = None,
        temporal_end: str | None = None,
        last_source_fetch_at: str | None = None,
        tags: Iterable[str] = (),
        metadata: Mapping[str, Any] | None = None,
        license_code: str | None = "source-defined",
        update_frequency: str | None = "source-defined",
    ) -> dict[str, Any]:
        return {
            "catalog_id": _stable_id(provider, dataset_key),
            "provider": provider,
            "dataset_key": dataset_key,
            "title": title.strip(),
            "description": _text(description),
            "resource_kind": resource_kind,
            "publisher": publisher,
            "source_uri": source_uri,
            "license_code": license_code,
            "geographic_coverage": geographic_coverage,
            "temporal_start": temporal_start,
            "temporal_end": temporal_end,
            "update_frequency": update_frequency,
            "freshness_status": _freshness(last_source_fetch_at),
            "record_count": max(0, int(record_count or 0)),
            "tags_json": canonical_json(sorted({str(tag).strip().lower() for tag in tags if str(tag).strip()})),
            "metadata_json": canonical_json(dict(metadata or {})),
            "last_source_fetch_at": last_source_fetch_at,
        }

    def _aggregate(self, connection: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []

        # Archive / web history are catalog resources rather than numeric datasets.
        row = connection.execute("SELECT COUNT(*) AS count, MAX(fetched_at) AS latest FROM internet_archive_items").fetchone()
        entries.append(self._entry(provider="internet-archive", dataset_key="item-catalog", title="Internet Archive Item Catalog", resource_kind="archive-catalog", publisher="Internet Archive", source_uri="https://archive.org/advancedsearch.php", description="Cataloged Internet Archive items and file inventories cached by Catalyst Data.", record_count=row["count"], last_source_fetch_at=row["latest"], tags=("archive","texts","media","history")))
        row = connection.execute("SELECT COUNT(*) AS count, MAX(last_seen_at) AS latest FROM wayback_captures").fetchone()
        entries.append(self._entry(provider="internet-archive", dataset_key="wayback-captures", title="Wayback Machine Capture History", resource_kind="archive-timeline", publisher="Internet Archive", source_uri="https://web.archive.org/", description="Historical web captures cached through the Wayback Machine interfaces.", record_count=row["count"], last_source_fetch_at=row["latest"], tags=("wayback","web history","archive")))

        # World Bank indicators become first-class discoverable datasets.
        rows = connection.execute("""
            SELECT i.indicator_code,i.name,i.unit,i.source_note,i.source_organization,i.source_uri,
                   COUNT(o.id) AS record_count,MIN(o.period) AS temporal_start,MAX(o.period) AS temporal_end,
                   MAX(o.fetched_at) AS latest
            FROM world_bank_indicators i LEFT JOIN world_bank_observations o ON o.indicator_code=i.indicator_code
            GROUP BY i.indicator_code,i.name,i.unit,i.source_note,i.source_organization,i.source_uri
            ORDER BY i.indicator_code
        """).fetchall()
        for row in rows:
            entries.append(self._entry(provider="world-bank", dataset_key=row["indicator_code"], title=row["name"], resource_kind="indicator-series", publisher=row["source_organization"] or "World Bank", source_uri=row["source_uri"], description=row["source_note"], record_count=row["record_count"], geographic_coverage="global", temporal_start=row["temporal_start"], temporal_end=row["temporal_end"], last_source_fetch_at=row["latest"], tags=("world bank","development","statistics",row["unit"] or ""), metadata={"indicator_code": row["indicator_code"], "unit": row["unit"]}))

        rows = connection.execute("""
            SELECT i.indicator_code,i.description,i.goal_code,i.target_code,i.source_uri,
                   COUNT(o.id) AS record_count,MIN(o.time_period) AS temporal_start,MAX(o.time_period) AS temporal_end,
                   MAX(o.fetched_at) AS latest
            FROM un_sdg_indicators i LEFT JOIN un_sdg_observations o ON o.indicator_code=i.indicator_code
            GROUP BY i.indicator_code,i.description,i.goal_code,i.target_code,i.source_uri
            ORDER BY i.indicator_code
        """).fetchall()
        for row in rows:
            entries.append(self._entry(provider="un-sdg", dataset_key=row["indicator_code"], title=f"SDG Indicator {row['indicator_code']}", resource_kind="indicator-series", publisher="United Nations Statistics Division", source_uri=row["source_uri"], description=row["description"], record_count=row["record_count"], geographic_coverage="global (UN M49)", temporal_start=row["temporal_start"], temporal_end=row["temporal_end"], last_source_fetch_at=row["latest"], tags=("un","sdg","sustainable development",f"goal {row['goal_code'] or ''}"), metadata={"indicator_code": row["indicator_code"], "goal_code": row["goal_code"], "target_code": row["target_code"]}))

        # U.S. public data: derive series/dataset keys from cached observations.
        rows = connection.execute("""SELECT dataset,variable_code,COUNT(*) AS record_count,MIN(year) AS temporal_start,MAX(year) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM census_observations GROUP BY dataset,variable_code ORDER BY dataset,variable_code""").fetchall()
        for row in rows:
            key=f"{row['dataset']}:{row['variable_code']}"
            entries.append(self._entry(provider="census",dataset_key=key,title=f"Census {row['variable_code']} — {row['dataset']}",resource_kind="statistical-series",publisher="U.S. Census Bureau",source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="United States",temporal_start=str(row["temporal_start"]),temporal_end=str(row["temporal_end"]),last_source_fetch_at=row["latest"],tags=("census","demographics","united states"),metadata={"dataset":row["dataset"],"variable_code":row["variable_code"]}))

        rows = connection.execute("""SELECT s.series_id,s.title,s.survey_name,s.source_uri,COUNT(o.id) AS record_count,MIN(o.year) AS temporal_start,MAX(o.year) AS temporal_end,MAX(o.fetched_at) AS latest FROM bls_series s LEFT JOIN bls_observations o ON o.series_id=s.series_id GROUP BY s.series_id,s.title,s.survey_name,s.source_uri ORDER BY s.series_id""").fetchall()
        for row in rows:
            entries.append(self._entry(provider="bls",dataset_key=row["series_id"],title=row["title"] or row["series_id"],resource_kind="time-series",publisher="U.S. Bureau of Labor Statistics",source_uri=row["source_uri"],description=row["survey_name"],record_count=row["record_count"],geographic_coverage="United States",temporal_start=row["temporal_start"],temporal_end=row["temporal_end"],last_source_fetch_at=row["latest"],tags=("bls","labor","economics","united states"),metadata={"series_id":row["series_id"]}))

        for provider, sql, publisher, tags in (
            ("bea", "SELECT dataset,metric_code,MAX(metric_name) AS title,COUNT(*) AS record_count,MIN(period) AS temporal_start,MAX(period) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM bea_observations GROUP BY dataset,metric_code ORDER BY dataset,metric_code", "U.S. Bureau of Economic Analysis", ("bea","economics","united states")),
            ("eia", "SELECT route AS dataset,metric_code,metric_code AS title,COUNT(*) AS record_count,MIN(period) AS temporal_start,MAX(period) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM eia_observations GROUP BY route,metric_code ORDER BY route,metric_code", "U.S. Energy Information Administration", ("eia","energy","united states")),
        ):
            for row in connection.execute(sql).fetchall():
                key=f"{row['dataset']}:{row['metric_code']}"
                entries.append(self._entry(provider=provider,dataset_key=key,title=row["title"] or row["metric_code"],resource_kind="statistical-series",publisher=publisher,source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="United States",temporal_start=row["temporal_start"],temporal_end=row["temporal_end"],last_source_fetch_at=row["latest"],tags=tags,metadata={"dataset":row["dataset"],"metric_code":row["metric_code"]}))

        for row in connection.execute("SELECT table_name,COUNT(*) AS record_count,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM epa_envirofacts_records GROUP BY table_name ORDER BY table_name").fetchall():
            entries.append(self._entry(provider="epa",dataset_key=row["table_name"],title=f"EPA Envirofacts — {row['table_name']}",resource_kind="environmental-table",publisher="U.S. Environmental Protection Agency",source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="United States",last_source_fetch_at=row["latest"],tags=("epa","environment","pollution","united states")))

        for row in connection.execute("SELECT collection_name,COALESCE(parameter_code,'') AS parameter_code,COUNT(*) AS record_count,MIN(period) AS temporal_start,MAX(period) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM usgs_water_observations GROUP BY collection_name,COALESCE(parameter_code,'') ORDER BY collection_name,parameter_code").fetchall():
            key=f"{row['collection_name']}:{row['parameter_code']}"
            entries.append(self._entry(provider="usgs-water",dataset_key=key,title=f"USGS Water — {row['collection_name']} {row['parameter_code']}".strip(),resource_kind="environmental-series",publisher="U.S. Geological Survey",source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="United States",temporal_start=row["temporal_start"],temporal_end=row["temporal_end"],last_source_fetch_at=row["latest"],tags=("usgs","water","hydrology","united states")))

        # Earth/ocean catalogs and observations.
        for row in connection.execute("SELECT dataset_key,dataset_id,title,institution,service_kind,source_uri,fetched_at FROM erddap_datasets ORDER BY dataset_key").fetchall():
            obs=connection.execute("SELECT COUNT(*) AS count,MIN(period) AS start,MAX(period) AS end,MAX(fetched_at) AS latest FROM earth_climate_observations WHERE provider='erddap' AND dataset_id=?",(row["dataset_id"],)).fetchone()
            entries.append(self._entry(provider="erddap",dataset_key=row["dataset_key"],title=row["title"],resource_kind="earth-ocean-dataset",publisher=row["institution"] or "ERDDAP provider",source_uri=row["source_uri"],record_count=obs["count"],geographic_coverage="source-defined",temporal_start=obs["start"],temporal_end=obs["end"],last_source_fetch_at=obs["latest"] or row["fetched_at"],tags=("erddap","ocean","climate",row["service_kind"] or ""),metadata={"dataset_id":row["dataset_id"],"service_kind":row["service_kind"]}))

        for row in connection.execute("SELECT dataset_id,name,title,organization,notes,source_uri,fetched_at FROM ioos_datasets ORDER BY dataset_id").fetchall():
            entries.append(self._entry(provider="ioos",dataset_key=row["dataset_id"],title=row["title"] or row["name"] or row["dataset_id"],resource_kind="ocean-coastal-dataset",publisher=row["organization"] or "U.S. IOOS",source_uri=row["source_uri"],description=row["notes"],record_count=0,geographic_coverage="U.S. coastal/ocean network",last_source_fetch_at=row["fetched_at"],tags=("ioos","ocean","coastal","marine")))

        for row in connection.execute("SELECT dataset_id,metric_code,COUNT(*) AS record_count,MIN(period) AS temporal_start,MAX(period) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM earth_climate_observations WHERE provider='ncei' GROUP BY dataset_id,metric_code ORDER BY dataset_id,metric_code").fetchall():
            key=f"{row['dataset_id']}:{row['metric_code']}"
            entries.append(self._entry(provider="noaa-ncei",dataset_key=key,title=f"NOAA NCEI {row['dataset_id']} — {row['metric_code']}",resource_kind="climate-series",publisher="NOAA National Centers for Environmental Information",source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="source-defined",temporal_start=row["temporal_start"],temporal_end=row["temporal_end"],last_source_fetch_at=row["latest"],tags=("noaa","ncei","climate","weather")))

        row=connection.execute("SELECT COUNT(*) AS count,MIN(event_time) AS start,MAX(event_time) AS end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM usgs_earthquakes").fetchone()
        entries.append(self._entry(provider="usgs-earthquake",dataset_key="earthquake-events",title="USGS Earthquake Event Feed",resource_kind="event-feed",publisher="U.S. Geological Survey",source_uri=row["source_uri"] or "https://earthquake.usgs.gov/fdsnws/event/1/",record_count=row["count"],geographic_coverage="global",temporal_start=row["start"],temporal_end=row["end"],last_source_fetch_at=row["latest"],tags=("usgs","earthquake","seismic","hazard")))

        # Space/science resource families.
        for row in connection.execute("SELECT event_type,COUNT(*) AS record_count,MIN(event_time) AS temporal_start,MAX(event_time) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM nasa_space_weather_events GROUP BY event_type ORDER BY event_type").fetchall():
            entries.append(self._entry(provider="nasa-donki",dataset_key=row["event_type"],title=f"NASA DONKI {row['event_type']} Events",resource_kind="space-weather-feed",publisher="NASA",source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="heliophysics",temporal_start=row["temporal_start"],temporal_end=row["temporal_end"],last_source_fetch_at=row["latest"],tags=("nasa","space weather","heliophysics",row["event_type"])))
        row=connection.execute("SELECT COUNT(*) AS count,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM jpl_small_bodies").fetchone()
        entries.append(self._entry(provider="jpl-sbdb",dataset_key="small-bodies",title="NASA/JPL Small-Body Database Cache",resource_kind="scientific-catalog",publisher="NASA Jet Propulsion Laboratory",source_uri=row["source_uri"] or "https://ssd-api.jpl.nasa.gov/sbdb_query.api",record_count=row["count"],geographic_coverage="Solar System",last_source_fetch_at=row["latest"],tags=("nasa","jpl","asteroids","comets","neo")))
        row=connection.execute("SELECT COUNT(*) AS count,MIN(close_approach_time) AS start,MAX(close_approach_time) AS end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM jpl_close_approaches").fetchone()
        entries.append(self._entry(provider="jpl-cneos",dataset_key="close-approaches",title="NASA/JPL Close-Approach Data",resource_kind="hazard-event-series",publisher="NASA Jet Propulsion Laboratory",source_uri=row["source_uri"] or "https://ssd-api.jpl.nasa.gov/cad.api",record_count=row["count"],geographic_coverage="Solar System",temporal_start=row["start"],temporal_end=row["end"],last_source_fetch_at=row["latest"],tags=("nasa","jpl","neo","close approach","hazard")))
        for row in connection.execute("SELECT table_name,COUNT(*) AS record_count,MIN(discovery_year) AS temporal_start,MAX(discovery_year) AS temporal_end,MAX(fetched_at) AS latest,MAX(source_uri) AS source_uri FROM nasa_exoplanets GROUP BY table_name ORDER BY table_name").fetchall():
            entries.append(self._entry(provider="nasa-exoplanet-archive",dataset_key=row["table_name"],title=f"NASA Exoplanet Archive — {row['table_name']}",resource_kind="scientific-catalog",publisher="NASA Exoplanet Science Institute",source_uri=row["source_uri"],record_count=row["record_count"],geographic_coverage="extrasolar planetary systems",temporal_start=str(row["temporal_start"]) if row["temporal_start"] is not None else None,temporal_end=str(row["temporal_end"]) if row["temporal_end"] is not None else None,last_source_fetch_at=row["latest"],tags=("nasa","exoplanets","astronomy","planetary science")))

        return entries

    def sync(self) -> dict[str, Any]:
        now=_now()
        with connect(self.repository.path) as connection, transaction(connection):
            entries=self._aggregate(connection)
            connection.execute("UPDATE dataset_catalog_entries SET active=0,updated_at=?",(now,))
            for item in entries:
                connection.execute("""
                    INSERT INTO dataset_catalog_entries(
                        catalog_id,provider,dataset_key,title,description,resource_kind,publisher,source_uri,license_code,
                        geographic_coverage,temporal_start,temporal_end,update_frequency,freshness_status,record_count,
                        tags_json,metadata_json,active,first_seen_at,last_seen_at,last_source_fetch_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)
                    ON CONFLICT(provider,dataset_key) DO UPDATE SET
                        catalog_id=excluded.catalog_id,title=excluded.title,description=excluded.description,
                        resource_kind=excluded.resource_kind,publisher=excluded.publisher,source_uri=excluded.source_uri,
                        license_code=excluded.license_code,geographic_coverage=excluded.geographic_coverage,
                        temporal_start=excluded.temporal_start,temporal_end=excluded.temporal_end,
                        update_frequency=excluded.update_frequency,freshness_status=excluded.freshness_status,
                        record_count=excluded.record_count,tags_json=excluded.tags_json,metadata_json=excluded.metadata_json,
                        active=1,last_seen_at=excluded.last_seen_at,last_source_fetch_at=excluded.last_source_fetch_at,
                        updated_at=excluded.updated_at
                """,(
                    item["catalog_id"],item["provider"],item["dataset_key"],item["title"],item["description"],item["resource_kind"],item["publisher"],item["source_uri"],item["license_code"],item["geographic_coverage"],item["temporal_start"],item["temporal_end"],item["update_frequency"],item["freshness_status"],item["record_count"],item["tags_json"],item["metadata_json"],now,now,item["last_source_fetch_at"],now,
                ))
            digest=hashlib.sha256(canonical_json({"catalog_ids":sorted(item["catalog_id"] for item in entries)}).encode("utf-8")).hexdigest()
            run_id="catalog-sync:"+hashlib.sha256(f"{now}|{digest}|{secrets.token_hex(8)}".encode()).hexdigest()[:24]
            connection.execute("INSERT INTO dataset_catalog_sync_runs(sync_id,entry_count,catalog_sha256,synced_at) VALUES (?,?,?,?)",(run_id,len(entries),digest,now))
        return {"sync_id":run_id,"entries":len(entries),"catalog_sha256":digest,"synced_at":now}

    def search(self, *, query: str | None=None, provider: str | None=None, resource_kind: str | None=None, freshness: str | None=None, active_only: bool=True, limit: int=50, offset: int=0) -> list[dict[str, Any]]:
        clauses=[]; params:list[Any]=[]
        if active_only: clauses.append("active=1")
        if provider: clauses.append("provider=?"); params.append(provider)
        if resource_kind: clauses.append("resource_kind=?"); params.append(resource_kind)
        if freshness: clauses.append("freshness_status=?"); params.append(freshness)
        if query:
            needle=f"%{query.strip()}%"
            clauses.append("(title LIKE ? OR description LIKE ? OR provider LIKE ? OR dataset_key LIKE ? OR tags_json LIKE ? OR publisher LIKE ?)")
            params.extend([needle]*6)
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        sql="SELECT * FROM dataset_catalog_entries"+where+" ORDER BY provider,title,catalog_id LIMIT ? OFFSET ?"
        params.extend([max(1,min(500,int(limit))),max(0,int(offset))])
        with connect(self.repository.path,readonly=True) as connection:
            rows=connection.execute(sql,tuple(params)).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, catalog_id: str) -> dict[str, Any] | None:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("SELECT * FROM dataset_catalog_entries WHERE catalog_id=?",(catalog_id,)).fetchone()
        return self._decode(row) if row else None

    def status(self) -> dict[str, Any]:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("SELECT * FROM dataset_catalog_status").fetchone()
        return _rowdict(row)

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        item=_rowdict(row)
        for key in ("tags_json","metadata_json"):
            raw=item.pop(key,None)
            item[key[:-5] if key.endswith("_json") else key]=json.loads(raw or "[]" if key=="tags_json" else raw or "{}")
        return item
