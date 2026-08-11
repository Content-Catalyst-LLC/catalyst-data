from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from ._version import __version__
from .adapters import AdapterManifest, AdapterValidationError, SourceAdapter
from .connectors import ConnectorFetchError
from .database import connect, transaction
from .repository import CatalystRepository, canonical_json

NCEI_CDO_BASE = "https://www.ncei.noaa.gov/cdo-web/api/v2"
NCEI_ERDDAP_BASE = "https://www.ncei.noaa.gov/erddap"
IOOS_CATALOG_BASE = "https://data.ioos.us/api/3/action/package_search"
IOOS_SENSOR_ERDDAP_BASE = "https://erddap.sensors.ioos.us/erddap"
USGS_EARTHQUAKE_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MAX_RESPONSE_BYTES = 20_000_000


class EarthClimateOceanError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha(value: bytes | Mapping[str, Any] | list[Any]) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}:" + secrets.token_hex(12)


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts).encode("utf-8")
    return f"{prefix}:" + hashlib.sha256(raw).hexdigest()[:32]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    text = str(value).strip()
    return text or None


def _numeric(value: Any) -> float | None:
    if value in (None, "", "NA", "N/A", "null", "NaN", "nan", "--"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _safe_id(value: str, *, label: str, pattern: str = r"[A-Za-z0-9_.:/-]+") -> str:
    text = str(value or "").strip()
    if not text or not re.fullmatch(pattern, text):
        raise AdapterValidationError(f"{label} is invalid")
    return text


def _safe_https_base(value: str, *, label: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise AdapterValidationError(f"{label} must be an absolute HTTPS URL without embedded credentials")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _redact_uri(uri: str) -> str:
    parsed = urlparse(uri)
    secret_names = {"key", "api_key", "apikey", "token", "access_token"}
    query = [(k, "REDACTED" if k.lower() in secret_names else v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _table_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    table = payload.get("table") if isinstance(payload, Mapping) else None
    if not isinstance(table, Mapping):
        return []
    names = table.get("columnNames") or []
    rows = table.get("rows") or []
    if not isinstance(names, list) or not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    for values in rows:
        if isinstance(values, list) and len(values) == len(names):
            output.append(dict(zip([str(n) for n in names], values, strict=True)))
    return output


class NCEICDODataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="noaa-ncei-cdo-v2",
        name="NOAA NCEI Climate Data Online v2 Adapter",
        version="1.0.0",
        provider="noaa-ncei",
        response_format="json",
        capabilities=("read", "climate", "stations", "observations", "pagination", "provenance"),
        pagination=("offset",),
        description="NOAA NCEI Climate Data Online v2 dataset and observation retrieval; token supplied at request time.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        endpoint = str(config.get("endpoint") or "data").strip().lower()
        if endpoint not in {"datasets", "datatypes", "locations", "stations", "data"}:
            raise AdapterValidationError("config.endpoint is not supported by the NCEI CDO v2 adapter")
        params = {str(k): str(v) for k, v in dict(config.get("params") or {}).items() if v not in (None, "")}
        if any(k.lower() == "token" for k in params):
            raise AdapterValidationError("NCEI token must not be persisted in adapter config")
        limit = max(1, min(1000, int(config.get("limit") or params.pop("limit", 1000))))
        offset = max(1, int(config.get("offset") or params.pop("offset", 1)))
        max_pages = max(1, min(100, int(config.get("max_pages") or 10)))
        return {"endpoint": endpoint, "params": params, "limit": limit, "offset": offset, "max_pages": max_pages, "pagination": {"type": "offset", "max_pages": max_pages}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params = dict(config["params"])
        params["limit"] = str(config["limit"])
        params["offset"] = str(state.get("cursor") or config["offset"])
        return f"{NCEI_CDO_BASE}/{config['endpoint']}?" + urlencode(params, doseq=True)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise AdapterValidationError("NCEI response must be a JSON object")
        rows = payload.get("results") or []
        if not isinstance(rows, list):
            rows = []
        resultset = ((payload.get("metadata") or {}).get("resultset") or {}) if isinstance(payload.get("metadata"), Mapping) else {}
        offset = int(resultset.get("offset") or state.get("cursor") or config["offset"])
        limit = int(resultset.get("limit") or config["limit"])
        count = int(resultset.get("count") or len(rows))
        next_cursor = offset + limit if rows and offset + limit <= count else None
        return [dict(row) for row in rows if isinstance(row, Mapping)], next_cursor


class ERDDAPCatalogAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="noaa-erddap-catalog",
        name="ERDDAP Dataset Catalog Adapter",
        version="1.0.0",
        provider="erddap",
        response_format="json",
        capabilities=("read", "ocean", "climate", "dataset-catalog", "griddap", "tabledap", "provenance"),
        pagination=("page",),
        description="Catalogs datasets from NOAA or IOOS-compatible ERDDAP servers through the standard info index JSON surface.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        server = _safe_https_base(str(config.get("server") or NCEI_ERDDAP_BASE), label="config.server")
        page = max(1, int(config.get("page") or 1))
        items = max(1, min(10000, int(config.get("items_per_page") or 1000)))
        return {"server": server, "page": page, "items_per_page": items, "pagination": {"type": "page", "max_pages": max(1, min(100, int(config.get("max_pages") or 10)))}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        page = int(state.get("cursor") or config["page"])
        return f"{config['server']}/info/index.json?" + urlencode({"page": page, "itemsPerPage": config["items_per_page"]})

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        rows = _table_rows(payload)
        page = int(state.get("cursor") or config["page"])
        next_cursor = page + 1 if len(rows) >= int(config["items_per_page"]) else None
        return rows, next_cursor


class ERDDAPTabledapAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="erddap-tabledap-json",
        name="ERDDAP TableDAP JSON Adapter",
        version="1.0.0",
        provider="erddap",
        response_format="json",
        capabilities=("read", "ocean", "climate", "tabular-observations", "spatiotemporal", "provenance"),
        pagination=("none",),
        description="Retrieves bounded tabular observations from an HTTPS ERDDAP TableDAP dataset.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        server = _safe_https_base(str(config.get("server") or NCEI_ERDDAP_BASE), label="config.server")
        dataset_id = _safe_id(str(config.get("dataset_id") or ""), label="config.dataset_id", pattern=r"[A-Za-z0-9_.-]+")
        variables = config.get("variables") or []
        if isinstance(variables, str):
            variables = [part.strip() for part in variables.split(",") if part.strip()]
        variables = [_safe_id(str(v), label="config.variables", pattern=r"[A-Za-z0-9_.-]+") for v in variables]
        if not variables or len(variables) > 64:
            raise AdapterValidationError("config.variables must contain 1-64 variable names")
        constraints = []
        for item in config.get("constraints") or []:
            text = str(item).strip()
            if not text or any(ch in text for ch in "\r\n#") or len(text) > 500:
                raise AdapterValidationError("config.constraints contains an invalid constraint")
            constraints.append(text)
        return {"server": server, "dataset_id": dataset_id, "variables": variables, "constraints": constraints, "pagination": {"type": "none", "max_pages": 1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        query = ",".join(config["variables"])
        if config["constraints"]:
            query += "&" + "&".join(config["constraints"])
        return f"{config['server']}/tabledap/{quote(str(config['dataset_id']), safe='._-')}.json?" + quote(query, safe=",&=><!()[]:+-._~\"'")

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise AdapterValidationError("ERDDAP TableDAP response must be a JSON object")
        return _table_rows(payload), None


class IOOSCatalogAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="ioos-data-catalog",
        name="U.S. IOOS Data Catalog Adapter",
        version="1.0.0",
        provider="ioos",
        response_format="json",
        capabilities=("read", "ocean", "coastal", "dataset-catalog", "ckan", "provenance"),
        pagination=("offset",),
        description="Searches the CKAN-based U.S. IOOS Data Catalog and preserves provider data-access resources.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        query = str(config.get("query") or "").strip()
        rows = max(1, min(1000, int(config.get("rows") or 100)))
        start = max(0, int(config.get("start") or 0))
        return {"query": query, "rows": rows, "start": start, "pagination": {"type": "offset", "max_pages": max(1, min(100, int(config.get("max_pages") or 10)))}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params = {"q": config["query"], "rows": config["rows"], "start": int(state.get("cursor") if state.get("cursor") is not None else config["start"])}
        return IOOS_CATALOG_BASE + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping) or payload.get("success") is False:
            raise AdapterValidationError("IOOS catalog request was not successful")
        result = payload.get("result") or {}
        rows = result.get("results") or [] if isinstance(result, Mapping) else []
        if not isinstance(rows, list):
            rows = []
        start = int(state.get("cursor") if state.get("cursor") is not None else config["start"])
        count = int(result.get("count") or len(rows)) if isinstance(result, Mapping) else len(rows)
        next_cursor = start + len(rows) if rows and start + len(rows) < count else None
        return [dict(row) for row in rows if isinstance(row, Mapping)], next_cursor


class USGSEarthquakeAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="usgs-earthquake-fdsn",
        name="USGS Earthquake FDSN GeoJSON Adapter",
        version="1.0.0",
        provider="usgs-earthquake",
        response_format="geojson",
        capabilities=("read", "earthquake", "hazards", "geospatial", "time-series", "provenance"),
        pagination=("offset",),
        description="Queries the USGS FDSN Event service using bounded GeoJSON requests and source-native event identifiers.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"format": "geojson", "orderby": str(config.get("orderby") or "time")}
        for key in ("starttime", "endtime", "updatedafter", "minmagnitude", "maxmagnitude", "minlatitude", "maxlatitude", "minlongitude", "maxlongitude", "latitude", "longitude", "maxradiuskm", "eventtype", "catalog", "contributor"):
            value = config.get(key)
            if value not in (None, ""):
                params[key] = str(value)
        limit = max(1, min(20000, int(config.get("limit") or 1000)))
        offset = max(1, int(config.get("offset") or 1))
        params["limit"] = limit
        return {"params": params, "offset": offset, "limit": limit, "pagination": {"type": "offset", "max_pages": max(1, min(100, int(config.get("max_pages") or 10)))}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params = dict(config["params"])
        params["offset"] = int(state.get("cursor") or config["offset"])
        return USGS_EARTHQUAKE_BASE + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping) or payload.get("type") != "FeatureCollection":
            raise AdapterValidationError("USGS earthquake response must be a GeoJSON FeatureCollection")
        rows = payload.get("features") or []
        if not isinstance(rows, list):
            rows = []
        offset = int(state.get("cursor") or config["offset"])
        next_cursor = offset + len(rows) if len(rows) >= int(config["limit"]) else None
        return [dict(row) for row in rows if isinstance(row, Mapping)], next_cursor


class EarthClimateOceanService:
    def __init__(self, repository: CatalystRepository | str, *, opener: Callable[..., Any] | None = None, sleeper: Callable[[float], None] | None = None):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep

    @staticmethod
    def user_agent() -> str:
        return f"SustainableCatalyst-CatalystData/{__version__} (+https://sustainablecatalyst.com/; EarthClimateOceanNetwork)"

    def _fetch(self, uri: str, *, provider: str, credential_env: str | None = None, credential_header: str | None = None, timeout: int = 45, retries: int = 3) -> tuple[bytes, dict[str, str], str]:
        headers = {"User-Agent": self.user_agent(), "Accept": "application/json,application/geo+json,text/plain;q=0.8,*/*;q=0.5"}
        if credential_env and credential_header:
            value = os.environ.get(credential_env)
            if not value:
                raise EarthClimateOceanError(f"credential environment variable is not set: {credential_env}")
            headers[credential_header] = value
        for attempt in range(1, max(1, retries) + 1):
            try:
                with self.opener(Request(uri, headers=headers), timeout=timeout) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ConnectorFetchError(f"{provider} response exceeds the 20 MB safety limit", transient=False)
                    return body, {str(k): str(v) for k, v in response.headers.items()}, _redact_uri(uri)
            except HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code < 600
                if not transient or attempt >= retries:
                    raise ConnectorFetchError(f"{provider} HTTP {exc.code}: {exc.reason}", transient=transient, status=exc.code) from exc
                raw = exc.headers.get("Retry-After") if exc.headers else None
                delay: int | None = None
                if raw and str(raw).isdigit():
                    delay = min(60, max(1, int(raw)))
                elif raw:
                    try:
                        at = parsedate_to_datetime(str(raw)); at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
                        delay = min(60, max(1, int((at - datetime.now(timezone.utc)).total_seconds())))
                    except (TypeError, ValueError, OverflowError):
                        delay = None
                self.sleeper(float(delay or min(2 ** (attempt - 1), 8)))
            except URLError as exc:
                if attempt >= retries:
                    raise ConnectorFetchError(f"{provider} network error: {exc.reason}", transient=True) from exc
                self.sleeper(float(min(2 ** (attempt - 1), 8)))
        raise EarthClimateOceanError(f"{provider} request failed")

    def _record_fetch(self, connection, *, provider: str, resource_type: str, request: Mapping[str, Any], body: bytes, source_uri: str, result_count: int, now: str) -> None:
        connection.execute(
            "INSERT INTO earth_climate_fetches(fetch_id,provider,resource_type,request_json,result_count,response_sha256,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (_id("earth-fetch"), provider, resource_type, canonical_json(dict(request)), int(result_count), _sha(body), source_uri, now),
        )

    def _upsert_observation(self, connection, *, provider: str, dataset_id: str, native_id: str, metric: str, period: str, value: Any, unit: str | None, latitude: Any, longitude: Any, depth: Any, station_id: str | None, geometry: Mapping[str, Any] | None, raw: Mapping[str, Any], source_uri: str, now: str) -> None:
        numeric = _numeric(value)
        observation_id = _stable_id("earth-observation", provider, dataset_id, native_id, metric, period)
        connection.execute(
            """INSERT INTO earth_climate_observations(observation_id,provider,dataset_id,source_native_id,metric_code,period,value_numeric,value_text,unit,latitude,longitude,depth,station_id,geometry_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,dataset_id,source_native_id,metric_code,period) DO UPDATE SET value_numeric=excluded.value_numeric,value_text=excluded.value_text,unit=excluded.unit,latitude=excluded.latitude,longitude=excluded.longitude,depth=excluded.depth,station_id=excluded.station_id,geometry_json=excluded.geometry_json,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
            (observation_id, provider, dataset_id, native_id, metric, period, numeric, None if numeric is not None or value is None else _text(value), unit, _numeric(latitude), _numeric(longitude), _numeric(depth), station_id, canonical_json(dict(geometry or {})), canonical_json(dict(raw)), source_uri, now, now, now),
        )

    def fetch_ncei_cdo(self, *, endpoint: str = "data", params: Mapping[str, Any] | None = None, limit: int = 1000, offset: int = 1, max_pages: int = 10, credential_env: str = "CATALYST_NCEI_TOKEN") -> dict[str, Any]:
        adapter = NCEICDODataAdapter(); config = adapter.normalize_config({"endpoint": endpoint, "params": params or {}, "limit": limit, "offset": offset, "max_pages": max_pages})
        cursor: int | None = config["offset"]; pages = 0; total = 0; observations = 0
        while cursor is not None and pages < config["max_pages"]:
            uri = adapter.request_uri(config, {"cursor": cursor}); body, headers, source_uri = self._fetch(uri, provider="NOAA NCEI", credential_env=credential_env, credential_header="token")
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="ncei", resource_type=endpoint, request={"endpoint": endpoint, "params": config["params"], "offset": cursor, "limit": limit}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                if endpoint == "data":
                    for index, row in enumerate(rows):
                        dataset = _text(row.get("datasetid")) or _text(config["params"].get("datasetid")) or "ncei-cdo"
                        metric = _text(row.get("datatype")) or _text(row.get("datatypeid")) or "value"
                        period = _text(row.get("date")) or _text(row.get("mindate")) or "unknown"
                        native = _text(row.get("station")) or _text(row.get("stationid")) or _stable_id("ncei-row", cursor, index, canonical_json(row))
                        self._upsert_observation(connection, provider="ncei", dataset_id=dataset, native_id=native, metric=metric, period=period, value=row.get("value"), unit=_text(row.get("attributes")), latitude=row.get("latitude"), longitude=row.get("longitude"), depth=None, station_id=_text(row.get("station")) or _text(row.get("stationid")), geometry=None, raw=row, source_uri=source_uri, now=now); observations += 1
            total += len(rows); pages += 1; cursor = int(next_cursor) if next_cursor is not None else None
        return {"provider": "ncei", "endpoint": endpoint, "pages": pages, "rows": total, "observations": observations, "status": self.status()}

    def fetch_erddap_catalog(self, *, server: str = NCEI_ERDDAP_BASE, items_per_page: int = 1000, max_pages: int = 10) -> dict[str, Any]:
        adapter = ERDDAPCatalogAdapter(); config = adapter.normalize_config({"server": server, "items_per_page": items_per_page, "max_pages": max_pages})
        cursor: int | None = config["page"]; pages = 0; total = 0
        while cursor is not None and pages < config["pagination"]["max_pages"]:
            uri = adapter.request_uri(config, {"cursor": cursor}); body, headers, source_uri = self._fetch(uri, provider="ERDDAP")
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="erddap", resource_type="catalog", request={"server": config["server"], "page": cursor, "items_per_page": items_per_page}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                for row in rows:
                    dataset_id = _text(row.get("Dataset ID")) or _text(row.get("datasetID")) or _text(row.get("dataset_id"))
                    if not dataset_id or dataset_id == "allDatasets":
                        continue
                    title = _text(row.get("Title")) or dataset_id
                    institution = _text(row.get("Institution"))
                    service_kind = "both" if row.get("griddap") and row.get("tabledap") else "griddap" if row.get("griddap") else "tabledap" if row.get("tabledap") else "unknown"
                    connection.execute(
                        """INSERT INTO erddap_datasets(dataset_key,server_url,dataset_id,title,institution,service_kind,metadata_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(server_url,dataset_id) DO UPDATE SET title=excluded.title,institution=excluded.institution,service_kind=excluded.service_kind,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (_stable_id("erddap-dataset", config["server"], dataset_id), config["server"], dataset_id, title, institution, service_kind, canonical_json(row), source_uri, now, now, now),
                    )
            total += len(rows); pages += 1; cursor = int(next_cursor) if next_cursor is not None else None
        return {"provider": "erddap", "server": config["server"], "pages": pages, "rows": total, "status": self.status()}

    def fetch_erddap_tabledap(self, dataset_id: str, variables: Sequence[str] | str, *, server: str = NCEI_ERDDAP_BASE, constraints: Sequence[str] = ()) -> dict[str, Any]:
        adapter = ERDDAPTabledapAdapter(); config = adapter.normalize_config({"server": server, "dataset_id": dataset_id, "variables": variables, "constraints": constraints})
        uri = adapter.request_uri(config, {}); body, headers, source_uri = self._fetch(uri, provider="ERDDAP")
        rows, _ = adapter.parse_page(body, headers, config, {}); now = _now(); observations = 0
        coordinate_names = {"time", "latitude", "longitude", "depth", "altitude", "station", "station_id", "site", "id"}
        with connect(self.repository.path) as connection, transaction(connection):
            self._record_fetch(connection, provider="erddap", resource_type=dataset_id, request={"server": config["server"], "dataset_id": dataset_id, "variables": config["variables"], "constraints": config["constraints"]}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
            for index, row in enumerate(rows):
                period = _text(row.get("time")) or "unknown"
                native = _text(row.get("id")) or _text(row.get("station")) or _text(row.get("station_id")) or _stable_id("erddap-row", dataset_id, period, index, canonical_json(row))
                for metric in config["variables"]:
                    if metric.lower() in coordinate_names or metric not in row:
                        continue
                    self._upsert_observation(connection, provider="erddap", dataset_id=dataset_id, native_id=native, metric=metric, period=period, value=row.get(metric), unit=None, latitude=row.get("latitude"), longitude=row.get("longitude"), depth=row.get("depth") or row.get("altitude"), station_id=_text(row.get("station")) or _text(row.get("station_id")) or _text(row.get("site")), geometry=None, raw=row, source_uri=source_uri, now=now); observations += 1
        return {"provider": "erddap", "dataset_id": dataset_id, "rows": len(rows), "observations": observations, "status": self.status()}

    def fetch_ioos_catalog(self, query: str = "", *, rows: int = 100, start: int = 0, max_pages: int = 10) -> dict[str, Any]:
        adapter = IOOSCatalogAdapter(); config = adapter.normalize_config({"query": query, "rows": rows, "start": start, "max_pages": max_pages})
        cursor: int | None = config["start"]; pages = 0; total = 0
        while cursor is not None and pages < config["pagination"]["max_pages"]:
            uri = adapter.request_uri(config, {"cursor": cursor}); body, headers, source_uri = self._fetch(uri, provider="IOOS")
            items, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="ioos", resource_type="catalog", request={"query": query, "rows": rows, "start": cursor}, body=body, source_uri=source_uri, result_count=len(items), now=now)
                for item in items:
                    dataset_id = _text(item.get("id")) or _text(item.get("name"))
                    if not dataset_id:
                        continue
                    resources = item.get("resources") if isinstance(item.get("resources"), list) else []
                    connection.execute(
                        """INSERT INTO ioos_datasets(dataset_id,name,title,organization,notes,resources_json,metadata_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dataset_id) DO UPDATE SET name=excluded.name,title=excluded.title,organization=excluded.organization,notes=excluded.notes,resources_json=excluded.resources_json,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (dataset_id, _text(item.get("name")), _text(item.get("title")), _text((item.get("organization") or {}).get("title") if isinstance(item.get("organization"), Mapping) else None), _text(item.get("notes")), canonical_json(resources), canonical_json(item), source_uri, now, now, now),
                    )
            total += len(items); pages += 1; cursor = int(next_cursor) if next_cursor is not None else None
        return {"provider": "ioos", "query": query, "pages": pages, "datasets": total, "status": self.status()}

    def fetch_usgs_earthquakes(self, *, starttime: str | None = None, endtime: str | None = None, minmagnitude: float | None = None, bbox: Sequence[float] | None = None, limit: int = 1000, offset: int = 1, max_pages: int = 10) -> dict[str, Any]:
        config_data: dict[str, Any] = {"starttime": starttime, "endtime": endtime, "minmagnitude": minmagnitude, "limit": limit, "offset": offset, "max_pages": max_pages}
        if bbox is not None:
            if len(bbox) != 4:
                raise EarthClimateOceanError("bbox must contain minlongitude,minlatitude,maxlongitude,maxlatitude")
            config_data.update({"minlongitude": bbox[0], "minlatitude": bbox[1], "maxlongitude": bbox[2], "maxlatitude": bbox[3]})
        adapter = USGSEarthquakeAdapter(); config = adapter.normalize_config(config_data)
        cursor: int | None = config["offset"]; pages = 0; total = 0
        while cursor is not None and pages < config["pagination"]["max_pages"]:
            uri = adapter.request_uri(config, {"cursor": cursor}); body, headers, source_uri = self._fetch(uri, provider="USGS Earthquake")
            features, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="usgs-earthquake", resource_type="events", request={"params": config["params"], "offset": cursor}, body=body, source_uri=source_uri, result_count=len(features), now=now)
                for feature in features:
                    event_id = _text(feature.get("id")); properties = feature.get("properties") if isinstance(feature.get("properties"), Mapping) else {}; geometry = feature.get("geometry") if isinstance(feature.get("geometry"), Mapping) else {}
                    coords = geometry.get("coordinates") if isinstance(geometry.get("coordinates"), list) else []
                    if not event_id:
                        continue
                    epoch_ms = properties.get("time"); event_time = None
                    if isinstance(epoch_ms, (int, float)):
                        event_time = datetime.fromtimestamp(float(epoch_ms) / 1000.0, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    event_time = event_time or _text(properties.get("time")) or "unknown"
                    connection.execute(
                        """INSERT INTO usgs_earthquakes(event_id,event_time,updated_time,magnitude,magnitude_type,place,status,tsunami,significance,alert,latitude,longitude,depth_km,geometry_json,properties_json,detail_uri,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time=excluded.event_time,updated_time=excluded.updated_time,magnitude=excluded.magnitude,magnitude_type=excluded.magnitude_type,place=excluded.place,status=excluded.status,tsunami=excluded.tsunami,significance=excluded.significance,alert=excluded.alert,latitude=excluded.latitude,longitude=excluded.longitude,depth_km=excluded.depth_km,geometry_json=excluded.geometry_json,properties_json=excluded.properties_json,detail_uri=excluded.detail_uri,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (event_id, event_time, _text(properties.get("updated")), _numeric(properties.get("mag")), _text(properties.get("magType")), _text(properties.get("place")), _text(properties.get("status")), int(bool(properties.get("tsunami"))), int(properties.get("sig") or 0), _text(properties.get("alert")), _numeric(coords[1]) if len(coords) > 1 else None, _numeric(coords[0]) if len(coords) > 0 else None, _numeric(coords[2]) if len(coords) > 2 else None, canonical_json(geometry), canonical_json(dict(properties)), _text(properties.get("detail")), source_uri, now, now, now),
                    )
            total += len(features); pages += 1; cursor = int(next_cursor) if next_cursor is not None else None
        return {"provider": "usgs-earthquake", "pages": pages, "events": total, "status": self.status()}

    def observations(self, *, provider: str | None = None, dataset_id: str | None = None, metric: str | None = None, station_id: str | None = None, start_period: str | None = None, end_period: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        clauses: list[str] = []; params: list[Any] = []
        for column, value in (("provider", provider), ("dataset_id", dataset_id), ("metric_code", metric), ("station_id", station_id)):
            if value:
                clauses.append(f"{column}=?"); params.append(value)
        if start_period:
            clauses.append("period>=?"); params.append(start_period)
        if end_period:
            clauses.append("period<=?"); params.append(end_period)
        sql = "SELECT observation_id,provider,dataset_id,source_native_id,metric_code,period,value_numeric,value_text,unit,latitude,longitude,depth,station_id,geometry_json,source_uri,fetched_at FROM earth_climate_observations"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY period DESC,provider,dataset_id,metric_code LIMIT ? OFFSET ?"; params += [max(1, min(500, int(limit))), max(0, int(offset))]
        output: list[dict[str, Any]] = []
        with connect(self.repository.path, readonly=True) as connection:
            for row in connection.execute(sql, params):
                item = dict(row); item["geometry"] = json.loads(item.pop("geometry_json")); output.append(item)
        return output

    def erddap_datasets(self, *, server: str | None = None, query: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT dataset_key,server_url,dataset_id,title,institution,service_kind,metadata_json,source_uri,fetched_at FROM erddap_datasets"; clauses=[]; params: list[Any]=[]
        if server: clauses.append("server_url=?"); params.append(server.rstrip("/"))
        if query: clauses.append("(LOWER(title) LIKE ? OR LOWER(dataset_id) LIKE ?)"); needle=f"%{query.lower()}%"; params += [needle, needle]
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY title,dataset_id LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        out=[]
        with connect(self.repository.path,readonly=True) as connection:
            for row in connection.execute(sql,params): item=dict(row); item["metadata"]=json.loads(item.pop("metadata_json")); out.append(item)
        return out

    def ioos_datasets(self, *, query: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql="SELECT dataset_id,name,title,organization,notes,resources_json,source_uri,fetched_at FROM ioos_datasets"; params: list[Any]=[]
        if query: sql += " WHERE LOWER(title) LIKE ? OR LOWER(name) LIKE ? OR LOWER(notes) LIKE ?"; needle=f"%{query.lower()}%"; params += [needle,needle,needle]
        sql += " ORDER BY title,name LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        out=[]
        with connect(self.repository.path,readonly=True) as connection:
            for row in connection.execute(sql,params): item=dict(row); item["resources"]=json.loads(item.pop("resources_json")); out.append(item)
        return out

    def earthquakes(self, *, min_magnitude: float | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql="SELECT event_id,event_time,updated_time,magnitude,magnitude_type,place,status,tsunami,significance,alert,latitude,longitude,depth_km,geometry_json,detail_uri,source_uri,fetched_at FROM usgs_earthquakes"; clauses=[]; params: list[Any]=[]
        if min_magnitude is not None: clauses.append("magnitude>=?"); params.append(float(min_magnitude))
        if start_time: clauses.append("event_time>=?"); params.append(start_time)
        if end_time: clauses.append("event_time<=?"); params.append(end_time)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY event_time DESC,event_id LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        out=[]
        with connect(self.repository.path,readonly=True) as connection:
            for row in connection.execute(sql,params): item=dict(row); item["geometry"]=json.loads(item.pop("geometry_json")); out.append(item)
        return out

    def status(self) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute("SELECT * FROM earth_climate_ocean_status").fetchone()
            return dict(row) if row else {}
