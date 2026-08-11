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
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from ._version import __version__
from .adapters import AdapterManifest, AdapterValidationError, SourceAdapter
from .connectors import ConnectorFetchError
from .database import connect, transaction
from .repository import CatalystRepository, canonical_json

NASA_DONKI_BASE = "https://api.nasa.gov/DONKI"
JPL_SBDB_QUERY_BASE = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
JPL_CAD_BASE = "https://ssd-api.jpl.nasa.gov/cad.api"
EXOPLANET_TAP_BASE = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
MAX_RESPONSE_BYTES = 20_000_000


class SpaceScienceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}:" + secrets.token_hex(12)


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts).encode("utf-8")
    return f"{prefix}:" + hashlib.sha256(raw).hexdigest()[:32]


def _sha(value: bytes | Mapping[str, Any] | list[Any]) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def _boolean_int(value: Any) -> int:
    return 1 if str(value or "").strip().lower() in {"1", "true", "yes", "y"} else 0


def _redact_uri(uri: str) -> str:
    parsed = urlparse(uri)
    secret_names = {"key", "api_key", "apikey", "token", "access_token"}
    query = [(key, "REDACTED" if key.lower() in secret_names else value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _append_query(uri: str, params: Mapping[str, Any]) -> str:
    parsed = urlparse(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((str(k), str(v)) for k, v in params.items() if v not in (None, ""))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _rows_from_field_data(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = payload.get("fields") or []
    data = payload.get("data") or []
    if not isinstance(fields, list) or not isinstance(data, list):
        return []
    names = [str(field) for field in fields]
    rows: list[dict[str, Any]] = []
    for values in data:
        if isinstance(values, list) and len(values) == len(names):
            rows.append(dict(zip(names, values, strict=True)))
    return rows


class NASADONKIAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="nasa-donki-space-weather",
        name="NASA DONKI Space Weather Adapter",
        version="1.0.0",
        provider="nasa-donki",
        response_format="json",
        capabilities=("read", "space-weather", "solar-events", "hazards", "time-series", "provenance"),
        pagination=("none",),
        description="Retrieves bounded NASA DONKI space-weather event collections. NASA API key is supplied only at request time.",
    )
    EVENT_TYPES = {"CME", "GST", "IPS", "FLR", "SEP", "MPC", "RBE", "HSS", "notifications"}

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        event_type = str(config.get("event_type") or "CME").strip()
        if event_type not in self.EVENT_TYPES:
            raise AdapterValidationError("config.event_type is not supported by NASA DONKI")
        params: dict[str, str] = {}
        for key in ("startDate", "endDate", "location", "catalog", "type"):
            value = config.get(key)
            if value not in (None, ""):
                params[key] = str(value).strip()
        if any(key.lower() in {"api_key", "apikey", "key"} for key in dict(config.get("params") or {})):
            raise AdapterValidationError("NASA API key must not be persisted in adapter config")
        return {"event_type": event_type, "params": params, "pagination": {"type": "none", "max_pages": 1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        query = urlencode(config["params"], doseq=True)
        return f"{NASA_DONKI_BASE}/{config['event_type']}" + (f"?{query}" if query else "")

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, list):
            raise AdapterValidationError("NASA DONKI response must be a JSON array")
        return [dict(row) for row in payload if isinstance(row, Mapping)], None


class JPLSBDBQueryAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="jpl-sbdb-query",
        name="NASA/JPL Small-Body Database Query Adapter",
        version="1.0.0",
        provider="jpl-sbdb",
        response_format="json",
        capabilities=("read", "small-bodies", "asteroids", "comets", "orbital-data", "pagination", "provenance"),
        pagination=("offset",),
        description="Queries JPL SBDB with source-native SPK/designation identifiers and bounded limit-from pagination.",
    )
    DEFAULT_FIELDS = ("spkid", "full_name", "pdes", "name", "kind", "class", "neo", "pha", "H", "diameter", "a", "e", "i", "moid", "epoch", "orbit_id")
    ALLOWED_FILTERS = {"sb-kind", "sb-class", "sb-ns", "sb-neo", "sb-pha", "sb-xfrag", "spk", "pdes", "name"}

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        fields = config.get("fields") or self.DEFAULT_FIELDS
        if isinstance(fields, str):
            fields = [part.strip() for part in fields.split(",") if part.strip()]
        fields = [str(field).strip() for field in fields]
        if not fields or len(fields) > 64 or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field) for field in fields):
            raise AdapterValidationError("config.fields must contain 1-64 valid SBDB field names")
        filters = {str(k): str(v) for k, v in dict(config.get("filters") or {}).items() if v not in (None, "")}
        if any(key not in self.ALLOWED_FILTERS for key in filters):
            raise AdapterValidationError("config.filters contains an unsupported SBDB filter")
        limit = max(1, min(5000, int(config.get("limit") or 1000)))
        offset = max(0, int(config.get("offset") or 0))
        max_pages = max(1, min(100, int(config.get("max_pages") or 10)))
        return {"fields": fields, "filters": filters, "limit": limit, "offset": offset, "pagination": {"type": "offset", "max_pages": max_pages}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params = dict(config["filters"])
        params.update({"fields": ",".join(config["fields"]), "limit": config["limit"], "limit-from": int(state.get("cursor") if state.get("cursor") is not None else config["offset"])})
        return JPL_SBDB_QUERY_BASE + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise AdapterValidationError("JPL SBDB response must be a JSON object")
        rows = _rows_from_field_data(payload)
        offset = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        next_cursor = offset + len(rows) if len(rows) >= int(config["limit"]) else None
        return rows, next_cursor


class JPLCloseApproachAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="jpl-sbdb-close-approach",
        name="NASA/JPL SBDB Close Approach Adapter",
        version="1.0.0",
        provider="jpl-cneos",
        response_format="json",
        capabilities=("read", "near-earth-objects", "close-approaches", "hazards", "pagination", "provenance"),
        pagination=("offset",),
        description="Retrieves JPL/CNEOS close-approach records with bounded paging and source-native designations.",
    )
    ALLOWED = {"date-min", "date-max", "dist-min", "dist-max", "min-dist-min", "min-dist-max", "h-min", "h-max", "v-inf-min", "v-inf-max", "v-rel-min", "v-rel-max", "class", "pha", "nea", "comet", "nea-comet", "neo", "kind", "spk", "des", "body", "sort"}

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        params = {str(k): str(v) for k, v in dict(config.get("params") or {}).items() if v not in (None, "")}
        if any(key not in self.ALLOWED for key in params):
            raise AdapterValidationError("config.params contains an unsupported JPL close-approach parameter")
        params["diameter"] = "true"
        params["fullname"] = "true"
        limit = max(1, min(5000, int(config.get("limit") or 1000)))
        offset = max(0, int(config.get("offset") or 0))
        max_pages = max(1, min(100, int(config.get("max_pages") or 10)))
        return {"params": params, "limit": limit, "offset": offset, "pagination": {"type": "offset", "max_pages": max_pages}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params = dict(config["params"])
        params["limit"] = config["limit"]
        params["limit-from"] = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        return JPL_CAD_BASE + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise AdapterValidationError("JPL close-approach response must be a JSON object")
        rows = _rows_from_field_data(payload)
        offset = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        next_cursor = offset + len(rows) if len(rows) >= int(config["limit"]) else None
        return rows, next_cursor


class NASAExoplanetTAPAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="nasa-exoplanet-tap",
        name="NASA Exoplanet Archive TAP Adapter",
        version="1.0.0",
        provider="nasa-exoplanet-archive",
        response_format="json",
        capabilities=("read", "exoplanets", "astronomy", "tap", "catalog", "provenance"),
        pagination=("none",),
        description="Queries selected NASA Exoplanet Archive TAP tables using bounded synchronous ADQL requests.",
    )
    TABLES = {"ps", "pscomppars", "toi", "stellarhosts"}
    DEFAULT_COLUMNS = ("pl_name", "hostname", "discoverymethod", "disc_year", "pl_orbper", "pl_rade", "pl_masse", "st_teff", "st_rad", "sy_dist", "ra", "dec")

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        table = str(config.get("table") or "pscomppars").strip().lower()
        if table not in self.TABLES:
            raise AdapterValidationError("config.table is not an approved Exoplanet Archive TAP table")
        columns = config.get("columns") or self.DEFAULT_COLUMNS
        if isinstance(columns, str):
            columns = [part.strip() for part in columns.split(",") if part.strip()]
        columns = [str(column).strip() for column in columns]
        if not columns or len(columns) > 64 or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", column) for column in columns):
            raise AdapterValidationError("config.columns must contain 1-64 valid TAP column names")
        where = str(config.get("where") or "").strip()
        if where and (len(where) > 1000 or any(token in where for token in (";", "--", "/*", "*/"))):
            raise AdapterValidationError("config.where contains unsupported ADQL syntax")
        limit = max(1, min(5000, int(config.get("limit") or 1000)))
        return {"table": table, "columns": columns, "where": where, "limit": limit, "pagination": {"type": "none", "max_pages": 1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        query = f"select top {config['limit']} {','.join(config['columns'])} from {config['table']}"
        if config["where"]:
            query += " where " + config["where"]
        return EXOPLANET_TAP_BASE + "?" + urlencode({"query": query, "format": "json"})

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, list):
            raise AdapterValidationError("NASA Exoplanet Archive TAP JSON response must be an array")
        return [dict(row) for row in payload if isinstance(row, Mapping)], None


class SpaceScienceService:
    def __init__(self, repository: CatalystRepository | str, *, opener: Callable[..., Any] | None = None, sleeper: Callable[[float], None] | None = None):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep

    @staticmethod
    def user_agent() -> str:
        return f"SustainableCatalyst-CatalystData/{__version__} (+https://sustainablecatalyst.com/; SpaceScienceNetwork)"

    def _fetch(self, uri: str, *, provider: str, query_credential_env: str | None = None, query_credential_name: str = "api_key", timeout: int = 45, retries: int = 3) -> tuple[bytes, dict[str, str], str]:
        request_uri = uri
        if query_credential_env:
            credential = os.environ.get(query_credential_env)
            if not credential:
                raise SpaceScienceError(f"credential environment variable is not set: {query_credential_env}")
            request_uri = _append_query(uri, {query_credential_name: credential})
        headers = {"User-Agent": self.user_agent(), "Accept": "application/json,text/plain;q=0.8,*/*;q=0.5"}
        for attempt in range(1, max(1, retries) + 1):
            try:
                with self.opener(Request(request_uri, headers=headers), timeout=timeout) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ConnectorFetchError(f"{provider} response exceeds the 20 MB safety limit", transient=False)
                    return body, {str(k): str(v) for k, v in response.headers.items()}, _redact_uri(request_uri)
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
        raise SpaceScienceError(f"{provider} request failed")

    def _record_fetch(self, connection, *, provider: str, resource_type: str, request: Mapping[str, Any], body: bytes, source_uri: str, result_count: int, now: str) -> None:
        connection.execute(
            "INSERT INTO space_science_fetches(fetch_id,provider,resource_type,request_json,result_count,response_sha256,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (_id("space-fetch"), provider, resource_type, canonical_json(dict(request)), int(result_count), _sha(body), source_uri, now),
        )

    def fetch_donki(self, *, event_type: str = "CME", start_date: str | None = None, end_date: str | None = None, credential_env: str = "CATALYST_NASA_API_KEY") -> dict[str, Any]:
        adapter = NASADONKIAdapter()
        config = adapter.normalize_config({"event_type": event_type, "startDate": start_date, "endDate": end_date})
        uri = adapter.request_uri(config, {})
        body, headers, source_uri = self._fetch(uri, provider="NASA DONKI", query_credential_env=credential_env)
        rows, _ = adapter.parse_page(body, headers, config, {})
        now = _now()
        with connect(self.repository.path) as connection, transaction(connection):
            self._record_fetch(connection, provider="nasa-donki", resource_type=event_type, request={"event_type": event_type, "start_date": start_date, "end_date": end_date}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
            for index, row in enumerate(rows):
                native_id = _text(row.get("activityID")) or _text(row.get("gstID")) or _text(row.get("flrID")) or _text(row.get("sepID")) or _text(row.get("messageID")) or _stable_id("donki-native", event_type, index, canonical_json(row))
                event_time = _text(row.get("startTime")) or _text(row.get("beginTime")) or _text(row.get("peakTime")) or _text(row.get("eventTime")) or _text(row.get("messageIssueTime"))
                connection.execute(
                    """INSERT INTO nasa_space_weather_events(event_id,event_type,source_native_id,event_time,end_time,title,status,location,details_json,source_uri,first_seen_at,fetched_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(event_type,source_native_id) DO UPDATE SET event_time=excluded.event_time,end_time=excluded.end_time,title=excluded.title,status=excluded.status,location=excluded.location,details_json=excluded.details_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                    (_stable_id("space-weather", event_type, native_id), event_type, native_id, event_time, _text(row.get("endTime")), _text(row.get("messageType")) or _text(row.get("classType")) or event_type, _text(row.get("catalog")), _text(row.get("sourceLocation")) or _text(row.get("location")), canonical_json(row), source_uri, now, now, now),
                )
        return {"provider": "nasa-donki", "event_type": event_type, "events": len(rows), "status": self.status()}

    def fetch_small_bodies(self, *, fields: Sequence[str] | str | None = None, filters: Mapping[str, Any] | None = None, limit: int = 1000, offset: int = 0, max_pages: int = 10) -> dict[str, Any]:
        adapter = JPLSBDBQueryAdapter(); config = adapter.normalize_config({"fields": fields or adapter.DEFAULT_FIELDS, "filters": filters or {}, "limit": limit, "offset": offset, "max_pages": max_pages})
        cursor: int | None = config["offset"]; pages = 0; total = 0
        while cursor is not None and pages < config["pagination"]["max_pages"]:
            uri = adapter.request_uri(config, {"cursor": cursor}); body, headers, source_uri = self._fetch(uri, provider="NASA/JPL SBDB")
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="jpl-sbdb", resource_type="small-bodies", request={"fields": config["fields"], "filters": config["filters"], "limit": limit, "offset": cursor}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                for row in rows:
                    spkid = _text(row.get("spkid")); designation = _text(row.get("pdes")) or _text(row.get("full_name"))
                    if not spkid and not designation:
                        continue
                    native = spkid or designation or "unknown"
                    connection.execute(
                        """INSERT INTO jpl_small_bodies(object_id,spkid,designation,full_name,name,kind,orbit_class,is_neo,is_pha,absolute_magnitude,diameter_km,semimajor_axis_au,eccentricity,inclination_deg,moid_au,epoch,orbit_id,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(object_id) DO UPDATE SET spkid=excluded.spkid,designation=excluded.designation,full_name=excluded.full_name,name=excluded.name,kind=excluded.kind,orbit_class=excluded.orbit_class,is_neo=excluded.is_neo,is_pha=excluded.is_pha,absolute_magnitude=excluded.absolute_magnitude,diameter_km=excluded.diameter_km,semimajor_axis_au=excluded.semimajor_axis_au,eccentricity=excluded.eccentricity,inclination_deg=excluded.inclination_deg,moid_au=excluded.moid_au,epoch=excluded.epoch,orbit_id=excluded.orbit_id,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (_stable_id("small-body", native), spkid, designation, _text(row.get("full_name")), _text(row.get("name")), _text(row.get("kind")), _text(row.get("class")), _boolean_int(row.get("neo")), _boolean_int(row.get("pha")), _numeric(row.get("H")), _numeric(row.get("diameter")), _numeric(row.get("a")), _numeric(row.get("e")), _numeric(row.get("i")), _numeric(row.get("moid")), _text(row.get("epoch")), _text(row.get("orbit_id")), canonical_json(row), source_uri, now, now, now),
                    )
            total += len(rows); pages += 1; cursor = int(next_cursor) if next_cursor is not None else None
        return {"provider": "jpl-sbdb", "pages": pages, "objects": total, "status": self.status()}

    def fetch_close_approaches(self, *, params: Mapping[str, Any] | None = None, limit: int = 1000, offset: int = 0, max_pages: int = 10) -> dict[str, Any]:
        adapter = JPLCloseApproachAdapter(); config = adapter.normalize_config({"params": params or {}, "limit": limit, "offset": offset, "max_pages": max_pages})
        cursor: int | None = config["offset"]; pages = 0; total = 0
        while cursor is not None and pages < config["pagination"]["max_pages"]:
            uri = adapter.request_uri(config, {"cursor": cursor}); body, headers, source_uri = self._fetch(uri, provider="NASA/JPL CNEOS")
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="jpl-cneos", resource_type="close-approaches", request={"params": config["params"], "limit": limit, "offset": cursor}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                for row in rows:
                    designation = _text(row.get("des")) or _text(row.get("fullname")) or "unknown"
                    close_time = _text(row.get("cd")) or _text(row.get("jd")) or "unknown"
                    body_name = _text(row.get("body")) or _text(config["params"].get("body")) or "Earth"
                    approach_id = _stable_id("close-approach", designation, body_name, close_time, row.get("orbit_id"))
                    connection.execute(
                        """INSERT INTO jpl_close_approaches(approach_id,designation,full_name,orbit_id,close_approach_time,julian_date,body,distance_au,distance_min_au,distance_max_au,relative_velocity_km_s,infinity_velocity_km_s,time_uncertainty,absolute_magnitude,diameter_km,diameter_sigma_km,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(approach_id) DO UPDATE SET full_name=excluded.full_name,distance_au=excluded.distance_au,distance_min_au=excluded.distance_min_au,distance_max_au=excluded.distance_max_au,relative_velocity_km_s=excluded.relative_velocity_km_s,infinity_velocity_km_s=excluded.infinity_velocity_km_s,time_uncertainty=excluded.time_uncertainty,absolute_magnitude=excluded.absolute_magnitude,diameter_km=excluded.diameter_km,diameter_sigma_km=excluded.diameter_sigma_km,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (approach_id, designation, _text(row.get("fullname")), _text(row.get("orbit_id")), close_time, _text(row.get("jd")), body_name, _numeric(row.get("dist")), _numeric(row.get("dist_min")), _numeric(row.get("dist_max")), _numeric(row.get("v_rel")), _numeric(row.get("v_inf")), _text(row.get("t_sigma_f")), _numeric(row.get("h")), _numeric(row.get("diameter")), _numeric(row.get("diameter_sigma")), canonical_json(row), source_uri, now, now, now),
                    )
            total += len(rows); pages += 1; cursor = int(next_cursor) if next_cursor is not None else None
        return {"provider": "jpl-cneos", "pages": pages, "approaches": total, "status": self.status()}

    def fetch_exoplanets(self, *, table: str = "pscomppars", columns: Sequence[str] | str | None = None, where: str = "", limit: int = 1000) -> dict[str, Any]:
        adapter = NASAExoplanetTAPAdapter(); config = adapter.normalize_config({"table": table, "columns": columns or adapter.DEFAULT_COLUMNS, "where": where, "limit": limit})
        uri = adapter.request_uri(config, {}); body, headers, source_uri = self._fetch(uri, provider="NASA Exoplanet Archive")
        rows, _ = adapter.parse_page(body, headers, config, {}); now = _now()
        with connect(self.repository.path) as connection, transaction(connection):
            self._record_fetch(connection, provider="nasa-exoplanet-archive", resource_type=table, request={"table": table, "columns": config["columns"], "where": where, "limit": limit}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
            for index, row in enumerate(rows):
                planet_name = _text(row.get("pl_name")) or _text(row.get("toi")) or _stable_id("exoplanet-row", table, index, canonical_json(row))
                host_name = _text(row.get("hostname")) or _text(row.get("tic_id"))
                connection.execute(
                    """INSERT INTO nasa_exoplanets(exoplanet_id,table_name,planet_name,host_name,discovery_method,discovery_year,orbital_period_days,radius_earth,mass_earth,stellar_temperature_k,stellar_radius_solar,distance_pc,ra_deg,dec_deg,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(exoplanet_id) DO UPDATE SET host_name=excluded.host_name,discovery_method=excluded.discovery_method,discovery_year=excluded.discovery_year,orbital_period_days=excluded.orbital_period_days,radius_earth=excluded.radius_earth,mass_earth=excluded.mass_earth,stellar_temperature_k=excluded.stellar_temperature_k,stellar_radius_solar=excluded.stellar_radius_solar,distance_pc=excluded.distance_pc,ra_deg=excluded.ra_deg,dec_deg=excluded.dec_deg,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                    (_stable_id("exoplanet", table, planet_name, host_name), table, planet_name, host_name, _text(row.get("discoverymethod")), int(float(row["disc_year"])) if row.get("disc_year") not in (None, "") else None, _numeric(row.get("pl_orbper")), _numeric(row.get("pl_rade")), _numeric(row.get("pl_masse")), _numeric(row.get("st_teff")), _numeric(row.get("st_rad")), _numeric(row.get("sy_dist")), _numeric(row.get("ra")), _numeric(row.get("dec")), canonical_json(row), source_uri, now, now, now),
                )
        return {"provider": "nasa-exoplanet-archive", "table": table, "planets": len(rows), "status": self.status()}

    def space_weather_events(self, *, event_type: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT event_id,event_type,source_native_id,event_time,end_time,title,status,location,details_json,source_uri,fetched_at FROM nasa_space_weather_events"; clauses=[]; params: list[Any]=[]
        if event_type: clauses.append("event_type=?"); params.append(event_type)
        if start_time: clauses.append("COALESCE(event_time,'')>=?"); params.append(start_time)
        if end_time: clauses.append("COALESCE(event_time,'')<=?"); params.append(end_time)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(event_time,fetched_at) DESC,event_id LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        out=[]
        with connect(self.repository.path,readonly=True) as connection:
            for row in connection.execute(sql,params): item=dict(row); item["details"]=json.loads(item.pop("details_json")); out.append(item)
        return out

    def small_bodies(self, *, neo: bool | None = None, pha: bool | None = None, orbit_class: str | None = None, query: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql="SELECT object_id,spkid,designation,full_name,name,kind,orbit_class,is_neo,is_pha,absolute_magnitude,diameter_km,semimajor_axis_au,eccentricity,inclination_deg,moid_au,epoch,orbit_id,source_uri,fetched_at FROM jpl_small_bodies"; clauses=[]; params: list[Any]=[]
        if neo is not None: clauses.append("is_neo=?"); params.append(1 if neo else 0)
        if pha is not None: clauses.append("is_pha=?"); params.append(1 if pha else 0)
        if orbit_class: clauses.append("orbit_class=?"); params.append(orbit_class)
        if query: clauses.append("(LOWER(COALESCE(full_name,'')) LIKE ? OR LOWER(COALESCE(name,'')) LIKE ? OR LOWER(COALESCE(designation,'')) LIKE ?)"); needle=f"%{query.lower()}%"; params += [needle,needle,needle]
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(name,full_name,designation),object_id LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        with connect(self.repository.path,readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params)]

    def close_approaches(self, *, body: str | None = None, start_time: str | None = None, end_time: str | None = None, max_distance_au: float | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql="SELECT approach_id,designation,full_name,orbit_id,close_approach_time,julian_date,body,distance_au,distance_min_au,distance_max_au,relative_velocity_km_s,infinity_velocity_km_s,time_uncertainty,absolute_magnitude,diameter_km,diameter_sigma_km,source_uri,fetched_at FROM jpl_close_approaches"; clauses=[]; params: list[Any]=[]
        if body: clauses.append("body=?"); params.append(body)
        if start_time: clauses.append("close_approach_time>=?"); params.append(start_time)
        if end_time: clauses.append("close_approach_time<=?"); params.append(end_time)
        if max_distance_au is not None: clauses.append("distance_au<=?"); params.append(float(max_distance_au))
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY close_approach_time,approach_id LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        with connect(self.repository.path,readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params)]

    def exoplanets(self, *, query: str | None = None, discovery_method: str | None = None, min_radius_earth: float | None = None, max_radius_earth: float | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql="SELECT exoplanet_id,table_name,planet_name,host_name,discovery_method,discovery_year,orbital_period_days,radius_earth,mass_earth,stellar_temperature_k,stellar_radius_solar,distance_pc,ra_deg,dec_deg,source_uri,fetched_at FROM nasa_exoplanets"; clauses=[]; params: list[Any]=[]
        if query: clauses.append("(LOWER(planet_name) LIKE ? OR LOWER(COALESCE(host_name,'')) LIKE ?)"); needle=f"%{query.lower()}%"; params += [needle,needle]
        if discovery_method: clauses.append("discovery_method=?"); params.append(discovery_method)
        if min_radius_earth is not None: clauses.append("radius_earth>=?"); params.append(float(min_radius_earth))
        if max_radius_earth is not None: clauses.append("radius_earth<=?"); params.append(float(max_radius_earth))
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY planet_name,host_name LIMIT ? OFFSET ?"; params += [max(1,min(500,int(limit))),max(0,int(offset))]
        with connect(self.repository.path,readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params)]

    def status(self) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute("SELECT * FROM space_science_status").fetchone()
            return dict(row) if row else {}
