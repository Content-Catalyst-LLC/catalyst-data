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

CENSUS_BASE = "https://api.census.gov/data"
BLS_BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data"
BEA_BASE = "https://apps.bea.gov/api/data"
EIA_BASE = "https://api.eia.gov/v2"
EPA_BASE = "https://data.epa.gov/dmapservice"
USGS_WATER_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
MAX_RESPONSE_BYTES = 20_000_000

_PROVIDER_NAMES = {
    "census": "U.S. Census Bureau",
    "bls": "U.S. Bureau of Labor Statistics",
    "bea": "U.S. Bureau of Economic Analysis",
    "eia": "U.S. Energy Information Administration",
    "epa": "U.S. Environmental Protection Agency",
    "usgs": "U.S. Geological Survey",
}


class USPublicDataError(RuntimeError):
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
    if isinstance(value, Mapping):
        for key in ("value", "name", "title", "description"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return canonical_json(dict(value))
    if isinstance(value, list):
        text = "; ".join(str(item) for item in value if item not in (None, ""))
        return text or None
    text = str(value).strip()
    return text or None


def _numeric(value: Any) -> float | None:
    if value in (None, "", "NA", "N/A", "null", "--", "(NA)"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _redact_uri(uri: str) -> str:
    parsed = urlparse(uri)
    secret_names = {"key", "api_key", "apikey", "userid", "registrationkey", "token", "access_token"}
    query = [(key, "REDACTED" if key.lower() in secret_names else value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _safe_token(value: str, *, label: str, pattern: str = r"[A-Za-z0-9_.:/-]+") -> str:
    text = str(value or "").strip()
    if not text or not re.fullmatch(pattern, text):
        raise AdapterValidationError(f"{label} is invalid")
    return text


class CensusDataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="us-census-data",
        name="U.S. Census Data API Adapter",
        version="1.0.0",
        provider="us-census",
        response_format="json",
        capabilities=("read", "statistics", "geography", "variables", "provenance"),
        pagination=("none",),
        description="Census Data API dataset queries with source-native variables and geography predicates.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        year = int(config.get("year") or 0)
        if year < 1990 or year > 2100:
            raise AdapterValidationError("config.year must be a plausible Census dataset year")
        dataset = _safe_token(str(config.get("dataset") or ""), label="config.dataset", pattern=r"[A-Za-z0-9_./-]+")
        variables = config.get("variables") or config.get("get") or []
        if isinstance(variables, str):
            variables = [part.strip() for part in variables.split(",") if part.strip()]
        variables = [str(item).strip() for item in variables if str(item).strip()]
        if not variables or len(variables) > 49 or any(not re.fullmatch(r"[A-Za-z0-9_]+", item) for item in variables):
            raise AdapterValidationError("config.variables must contain 1-49 Census variable names")
        for_predicate = str(config.get("for") or "").strip()
        if not for_predicate or any(ch in for_predicate for ch in "\r\n"):
            raise AdapterValidationError("config.for is required")
        in_predicate = str(config.get("in") or "").strip() or None
        return {
            "year": year,
            "dataset": dataset,
            "variables": variables,
            "for": for_predicate,
            "in": in_predicate,
            "pagination": {"type": "none", "max_pages": 1},
        }

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params: list[tuple[str, str]] = [("get", ",".join(config["variables"])), ("for", str(config["for"]))]
        if config.get("in"):
            params.append(("in", str(config["in"])))
        return f"{CENSUS_BASE}/{config['year']}/{config['dataset']}?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
            raise AdapterValidationError("Census response must be a header row followed by data rows")
        columns = [str(item) for item in payload[0]]
        rows = []
        for values in payload[1:]:
            if not isinstance(values, list) or len(values) != len(columns):
                continue
            rows.append(dict(zip(columns, values, strict=True)))
        return rows, None


class BLSSeriesAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="us-bls-series",
        name="BLS Public Data API Series Adapter",
        version="1.0.0",
        provider="us-bls",
        response_format="json",
        capabilities=("read", "time-series", "footnotes", "catalog", "provenance"),
        pagination=("none",),
        description="BLS Public Data API v2 single-series retrieval and latest-data queries.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        series_id = _safe_token(str(config.get("series_id") or ""), label="config.series_id", pattern=r"[A-Za-z0-9_-]+")
        return {"series_id": series_id, "latest": bool(config.get("latest", False)), "pagination": {"type": "none", "max_pages": 1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        uri = f"{BLS_BASE}/{quote(str(config['series_id']), safe='-_')}"
        return uri + ("?latest=true" if config.get("latest") else "")

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if str(payload.get("status") or "").upper() not in ("REQUEST_SUCCEEDED", ""):
            raise AdapterValidationError("BLS API request did not succeed")
        results = payload.get("Results") or {}
        if isinstance(results, list) and results:
            results = results[0]
        series = results.get("series") if isinstance(results, Mapping) else None
        if not isinstance(series, list):
            series = []
        rows: list[dict[str, Any]] = []
        for item in series:
            if not isinstance(item, Mapping):
                continue
            series_id = str(item.get("seriesID") or config["series_id"])
            catalog = item.get("catalog") if isinstance(item.get("catalog"), Mapping) else {}
            for point in item.get("data") or []:
                if isinstance(point, Mapping):
                    row = dict(point)
                    row["seriesID"] = series_id
                    row["catalog"] = dict(catalog)
                    rows.append(row)
        return rows, None


class BEADataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="us-bea-data",
        name="BEA Data Retrieval API Adapter",
        version="1.0.0",
        provider="us-bea",
        response_format="json",
        capabilities=("read", "economic-statistics", "metadata", "provenance"),
        pagination=("none",),
        description="BEA Data Retrieval API GetData and metadata responses; UserID supplied through connector authentication.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        method = str(config.get("method") or "GetData").strip()
        if method.lower() not in {"getdata", "getdatasetlist", "getparameterlist", "getparametervalues", "getparametervaluesfiltered"}:
            raise AdapterValidationError("config.method is not a supported BEA API method")
        dataset = str(config.get("dataset") or config.get("datasetname") or "").strip()
        if method.lower() != "getdatasetlist":
            dataset = _safe_token(dataset, label="config.dataset", pattern=r"[A-Za-z0-9_]+")
        params = {str(key): str(value) for key, value in dict(config.get("parameters") or {}).items() if value not in (None, "")}
        if any(str(key).lower() in {"userid", "key", "api_key"} for key in params):
            raise AdapterValidationError("BEA credentials must not be persisted in adapter config")
        return {"method": method, "dataset": dataset or None, "parameters": params, "pagination": {"type": "none", "max_pages": 1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params: list[tuple[str, str]] = [("method", str(config["method"])), ("ResultFormat", "JSON")]
        if config.get("dataset"):
            params.append(("datasetname", str(config["dataset"])))
        params.extend((str(key), str(value)) for key, value in config.get("parameters", {}).items())
        return BEA_BASE + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        root = payload.get("BEAAPI") if isinstance(payload, Mapping) else None
        results = root.get("Results") if isinstance(root, Mapping) else None
        if not isinstance(results, Mapping):
            raise AdapterValidationError("BEA API response does not contain BEAAPI.Results")
        if isinstance(results.get("Error"), Mapping):
            err = results["Error"]
            raise AdapterValidationError(str(err.get("APIErrorDescription") or "BEA API returned an error"))
        for key in ("Data", "Dataset", "Parameter", "ParamValue"):
            rows = results.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)], None
        return [], None


class EIADataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="us-eia-data",
        name="EIA Open Data API v2 Adapter",
        version="1.0.0",
        provider="us-eia",
        response_format="json",
        capabilities=("read", "energy-statistics", "facets", "time-series", "offset-pagination", "provenance"),
        pagination=("offset",),
        description="EIA API v2 route/data queries with source-native facets and explicit requested data columns.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        route = _safe_token(str(config.get("route") or ""), label="config.route", pattern=r"[A-Za-z0-9_./-]+")
        route = route.strip("/")
        data = config.get("data") or []
        if isinstance(data, str):
            data = [part.strip() for part in data.split(",") if part.strip()]
        data = [str(item).strip() for item in data if str(item).strip()]
        if not data or any(not re.fullmatch(r"[A-Za-z0-9_-]+", item) for item in data):
            raise AdapterValidationError("config.data requires one or more EIA data columns")
        facets: dict[str, list[str]] = {}
        for key, values in dict(config.get("facets") or {}).items():
            facet = _safe_token(str(key), label="config.facets key", pattern=r"[A-Za-z0-9_-]+")
            if isinstance(values, str):
                values = [values]
            facets[facet] = [str(value) for value in values if str(value) != ""]
        length = max(1, min(5000, int(config.get("length") or 1000)))
        offset = max(0, int(config.get("offset") or 0))
        return {
            "route": route,
            "data": data,
            "facets": facets,
            "frequency": _text(config.get("frequency")),
            "start": _text(config.get("start")),
            "end": _text(config.get("end")),
            "length": length,
            "offset": offset,
            "pagination": {"type": "offset", "start": offset, "page_size": length, "max_pages": int(config.get("max_pages") or 25)},
        }

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        offset = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        params: list[tuple[str, str]] = []
        params.extend(("data[]", str(item)) for item in config["data"])
        for facet, values in config["facets"].items():
            params.extend((f"facets[{facet}][]", str(value)) for value in values)
        for key in ("frequency", "start", "end"):
            if config.get(key):
                params.append((key, str(config[key])))
        params.extend((("offset", str(offset)), ("length", str(config["length"]))))
        return f"{EIA_BASE}/{config['route']}/data/?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if isinstance(payload, Mapping) and payload.get("error"):
            raise AdapterValidationError(str(payload.get("error")))
        response = payload.get("response") if isinstance(payload, Mapping) else None
        if not isinstance(response, Mapping):
            raise AdapterValidationError("EIA API response does not contain response")
        rows = [dict(row) for row in response.get("data") or [] if isinstance(row, Mapping)]
        total = int(response.get("total") or len(rows))
        current = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        next_offset = current + len(rows) if rows and current + len(rows) < total else None
        return rows, next_offset


class EPAEnvirofactsAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="us-epa-envirofacts",
        name="EPA Envirofacts Data Service Adapter",
        version="1.0.0",
        provider="us-epa",
        response_format="json",
        capabilities=("read", "environmental-records", "filters", "range-pagination", "provenance"),
        pagination=("offset",),
        description="EPA Envirofacts DMAP REST table queries with bounded record ranges and explicit filters.",
    )
    OPERATORS = {"equals", "notEquals", "lessThan", "lessThanEqual", "greaterThan", "greaterThanEqual", "beginsWith", "endsWith", "contains", "excludes", "like", "notLike", "in", "notIn"}

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        table = _safe_token(str(config.get("table") or ""), label="config.table", pattern=r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+")
        filters = []
        for item in config.get("filters") or []:
            if not isinstance(item, Mapping):
                raise AdapterValidationError("config.filters entries must be objects")
            column = _safe_token(str(item.get("column") or ""), label="filter.column", pattern=r"[A-Za-z0-9_.]+")
            operator = str(item.get("operator") or "equals")
            if operator not in self.OPERATORS:
                raise AdapterValidationError("filter.operator is invalid")
            value = str(item.get("value") or "")
            if not value or any(ch in value for ch in "\r\n/"):
                raise AdapterValidationError("filter.value is invalid")
            filters.append({"column": column, "operator": operator, "value": value})
        first = max(1, int(config.get("first") or 1))
        page_size = max(1, min(5000, int(config.get("page_size") or 500)))
        sort = str(config.get("sort") or "").strip() or None
        if sort and not re.fullmatch(r"[A-Za-z0-9_.:-]+(?:,[A-Za-z0-9_.:-]+)*", sort):
            raise AdapterValidationError("config.sort is invalid")
        return {"table": table, "filters": filters, "first": first, "page_size": page_size, "sort": sort, "pagination": {"type": "offset", "start": first, "page_size": page_size, "max_pages": int(config.get("max_pages") or 25)}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        first = int(state.get("cursor") if state.get("cursor") is not None else config["first"])
        last = first + int(config["page_size"]) - 1
        parts = [EPA_BASE, quote(str(config["table"]), safe="._")]
        for index, item in enumerate(config["filters"]):
            if index:
                parts.append("and")
            parts.extend((quote(item["column"], safe="._"), item["operator"], quote(item["value"], safe=",@._-")))
        parts.append(f"{first}:{last}")
        if config.get("sort"):
            parts.extend(("sort", quote(str(config["sort"]), safe=",:._-")))
        parts.append("JSON")
        return "/".join(part.strip("/") for part in parts if part != "") if not parts[0].startswith("http") else parts[0].rstrip("/") + "/" + "/".join(part.strip("/") for part in parts[1:])

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        rows = [dict(row) for row in payload if isinstance(row, Mapping)] if isinstance(payload, list) else []
        current = int(state.get("cursor") if state.get("cursor") is not None else config["first"])
        next_first = current + len(rows) if len(rows) >= int(config["page_size"]) else None
        return rows, next_first


class USGSWaterDataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="us-usgs-water-data",
        name="USGS Water Data OGC API Adapter",
        version="1.0.0",
        provider="us-usgs",
        response_format="json",
        capabilities=("read", "water-observations", "ogc-api", "geospatial", "offset-pagination", "provenance"),
        pagination=("offset",),
        description="USGS Water Data OGC API collection items for continuous, daily, and monitoring-location data.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        collection = _safe_token(str(config.get("collection") or "daily"), label="config.collection", pattern=r"[A-Za-z0-9_-]+")
        limit = max(1, min(10000, int(config.get("limit") or 500)))
        offset = max(0, int(config.get("offset") or 0))
        params: dict[str, str] = {}
        for key in ("datetime", "bbox", "monitoring_location_id", "parameter_code", "statistic_id"):
            value = config.get(key)
            if value not in (None, ""):
                params[key] = str(value)
        return {"collection": collection, "limit": limit, "offset": offset, "params": params, "pagination": {"type": "offset", "start": offset, "page_size": limit, "max_pages": int(config.get("max_pages") or 25)}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        offset = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        params = dict(config.get("params") or {})
        params.update({"limit": str(config["limit"]), "offset": str(offset)})
        return f"{USGS_WATER_BASE}/{quote(str(config['collection']), safe='-_')}/items?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise AdapterValidationError("USGS Water Data API response must be an object")
        features = [dict(item) for item in payload.get("features") or [] if isinstance(item, Mapping)]
        current = int(state.get("cursor") if state.get("cursor") is not None else config["offset"])
        matched = payload.get("numberMatched")
        next_offset = current + len(features) if features and (matched is None or current + len(features) < int(matched)) else None
        return features, next_offset


class USPublicDataService:
    def __init__(self, repository: CatalystRepository | str, *, opener: Callable[..., Any] | None = None, sleeper: Callable[[float], None] | None = None):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep

    @staticmethod
    def user_agent() -> str:
        return f"SustainableCatalyst-CatalystData/{__version__} (+https://sustainablecatalyst.com/; USPublicDataAdapter)"

    @staticmethod
    def _credential(env_name: str | None, *, required: bool = False) -> str | None:
        if not env_name:
            if required:
                raise USPublicDataError("credential environment variable name is required")
            return None
        value = os.environ.get(env_name)
        if required and not value:
            raise USPublicDataError(f"credential environment variable is not set: {env_name}")
        return value

    def _fetch(self, uri: str, *, provider: str, credential_env: str | None = None, credential_name: str | None = None, required_credential: bool = False, timeout: int = 30, retries: int = 3) -> tuple[bytes, dict[str, str], str]:
        credential = self._credential(credential_env, required=required_credential)
        request_uri = uri
        if credential and credential_name:
            parsed = urlparse(uri)
            query = parse_qsl(parsed.query, keep_blank_values=True)
            query.append((credential_name, credential))
            request_uri = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        headers = {"User-Agent": self.user_agent(), "Accept": "application/json,text/plain;q=0.9,*/*;q=0.5"}
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
                        at = parsedate_to_datetime(str(raw))
                        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
                        delay = min(60, max(1, int((at - datetime.now(timezone.utc)).total_seconds())))
                    except (TypeError, ValueError, OverflowError):
                        delay = None
                self.sleeper(float(delay or min(2 ** (attempt - 1), 8)))
            except URLError as exc:
                if attempt >= retries:
                    raise ConnectorFetchError(f"{provider} network error: {exc.reason}", transient=True) from exc
                self.sleeper(float(min(2 ** (attempt - 1), 8)))
        raise USPublicDataError(f"{provider} request failed")

    def _record_fetch(self, connection, *, provider: str, resource_type: str, request: Mapping[str, Any], body: bytes, source_uri: str, result_count: int, now: str) -> None:
        connection.execute(
            "INSERT INTO us_public_fetches(fetch_id,provider,resource_type,request_json,result_count,response_sha256,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (_id("us-fetch"), provider, resource_type, canonical_json(dict(request)), int(result_count), _sha(body), source_uri, now),
        )

    def fetch_census(self, year: int, dataset: str, variables: Sequence[str] | str, *, for_predicate: str, in_predicate: str | None = None, credential_env: str | None = "CATALYST_CENSUS_API_KEY") -> dict[str, Any]:
        adapter = CensusDataAdapter()
        config = adapter.normalize_config({"year": year, "dataset": dataset, "variables": variables, "for": for_predicate, "in": in_predicate})
        uri = adapter.request_uri(config, {})
        body, headers, source_uri = self._fetch(uri, provider="Census", credential_env=credential_env, credential_name="key")
        rows, _ = adapter.parse_page(body, headers, config, {})
        now = _now()
        requested = list(config["variables"])
        with connect(self.repository.path) as connection, transaction(connection):
            self._record_fetch(connection, provider="census", resource_type=f"{year}/{dataset}", request={"year": year, "dataset": dataset, "variables": requested, "for": for_predicate, "in": in_predicate}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
            for row in rows:
                geography = {key: value for key, value in row.items() if key not in requested and key != "NAME"}
                geography_json = canonical_json(geography)
                geography_name = _text(row.get("NAME"))
                geography_id = ";".join(f"{key}:{value}" for key, value in sorted(geography.items())) or geography_name or "unknown"
                for variable in requested:
                    if variable == "NAME" or variable not in row:
                        continue
                    value = row.get(variable)
                    numeric = _numeric(value)
                    obs_id = _stable_id("census-observation", year, dataset, geography_json, variable)
                    connection.execute(
                        """INSERT INTO census_observations(observation_id,dataset,year,geography_id,geography_name,geography_json,variable_code,value_numeric,value_text,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(dataset,year,geography_json,variable_code) DO UPDATE SET geography_id=excluded.geography_id,geography_name=excluded.geography_name,value_numeric=excluded.value_numeric,value_text=excluded.value_text,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (obs_id, dataset, int(year), geography_id, geography_name, geography_json, variable, numeric, None if numeric is not None or value is None else _text(value), canonical_json(row), source_uri, now, now, now),
                    )
        return {"provider": "census", "dataset": dataset, "year": year, "rows": len(rows), "observations": len(rows) * len([v for v in requested if v != "NAME"]), "status": self.status()}

    def fetch_bls_series(self, series_id: str, *, latest: bool = False, credential_env: str | None = "CATALYST_BLS_API_KEY") -> dict[str, Any]:
        adapter = BLSSeriesAdapter()
        config = adapter.normalize_config({"series_id": series_id, "latest": latest})
        uri = adapter.request_uri(config, {})
        body, headers, source_uri = self._fetch(uri, provider="BLS", credential_env=credential_env, credential_name="registrationkey")
        rows, _ = adapter.parse_page(body, headers, config, {})
        now = _now()
        catalog = rows[0].get("catalog") if rows and isinstance(rows[0].get("catalog"), Mapping) else {}
        with connect(self.repository.path) as connection, transaction(connection):
            self._record_fetch(connection, provider="bls", resource_type="timeseries", request={"series_id": series_id, "latest": bool(latest)}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
            connection.execute(
                """INSERT INTO bls_series(series_id,title,survey_name,survey_abbreviation,seasonality,catalog_json,source_uri,fetched_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET title=excluded.title,survey_name=excluded.survey_name,survey_abbreviation=excluded.survey_abbreviation,seasonality=excluded.seasonality,catalog_json=excluded.catalog_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                (series_id, _text(catalog.get("series_title")), _text(catalog.get("survey_name")), _text(catalog.get("survey_abbreviation")), _text(catalog.get("seasonality")), canonical_json(catalog), source_uri, now, now),
            )
            for row in rows:
                year = str(row.get("year") or "")
                period = str(row.get("period") or "")
                if not year or not period:
                    continue
                footnotes = row.get("footnotes") if isinstance(row.get("footnotes"), list) else []
                value = row.get("value")
                numeric = _numeric(value)
                obs_id = _stable_id("bls-observation", series_id, year, period)
                connection.execute(
                    """INSERT INTO bls_observations(observation_id,series_id,year,period,period_name,value_numeric,value_text,latest,footnotes_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id,year,period) DO UPDATE SET period_name=excluded.period_name,value_numeric=excluded.value_numeric,value_text=excluded.value_text,latest=excluded.latest,footnotes_json=excluded.footnotes_json,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                    (obs_id, series_id, year, period, _text(row.get("periodName")), numeric, None if numeric is not None or value is None else _text(value), 1 if str(row.get("latest") or "").lower() == "true" else 0, canonical_json(footnotes), canonical_json(row), source_uri, now, now, now),
                )
        return {"provider": "bls", "series_id": series_id, "records": len(rows), "status": self.status()}

    def fetch_bea_data(self, dataset: str, parameters: Mapping[str, Any], *, credential_env: str = "CATALYST_BEA_API_KEY") -> dict[str, Any]:
        adapter = BEADataAdapter()
        config = adapter.normalize_config({"method": "GetData", "dataset": dataset, "parameters": parameters})
        uri = adapter.request_uri(config, {})
        body, headers, source_uri = self._fetch(uri, provider="BEA", credential_env=credential_env, credential_name="UserID", required_credential=True)
        rows, _ = adapter.parse_page(body, headers, config, {})
        payload = json.loads(body.decode("utf-8-sig")); results = payload.get("BEAAPI", {}).get("Results", {}) if isinstance(payload, Mapping) else {}
        statistic = _text(results.get("Statistic")); unit_of_measure = _text(results.get("UnitOfMeasure"))
        now = _now()
        with connect(self.repository.path) as connection, transaction(connection):
            self._record_fetch(connection, provider="bea", resource_type=dataset, request={"dataset": dataset, "parameters": dict(parameters)}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
            for row in rows:
                code = _text(row.get("Code")) or dataset
                geo = _text(row.get("GeoFips") or row.get("GeoFIPS")) or "unknown"
                geo_name = _text(row.get("GeoName"))
                period = _text(row.get("TimePeriod") or row.get("Year")) or "unknown"
                value = row.get("DataValue") if "DataValue" in row else row.get("Value")
                numeric = _numeric(value)
                dimensions = {key: value for key, value in row.items() if key not in {"DataValue", "Value"}}
                obs_id = _stable_id("bea-observation", dataset, code, geo, period, canonical_json(parameters))
                connection.execute(
                    """INSERT INTO bea_observations(observation_id,dataset,metric_code,metric_name,geography_id,geography_name,period,value_numeric,value_text,unit,unit_multiplier,dimensions_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dataset,metric_code,geography_id,period,dimensions_json) DO UPDATE SET metric_name=excluded.metric_name,geography_name=excluded.geography_name,value_numeric=excluded.value_numeric,value_text=excluded.value_text,unit=excluded.unit,unit_multiplier=excluded.unit_multiplier,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                    (obs_id, dataset, code, statistic, geo, geo_name, period, numeric, None if numeric is not None or value is None else _text(value), _text(row.get("CL_UNIT")) or unit_of_measure, int(row.get("UNIT_MULT") or 0) if str(row.get("UNIT_MULT") or "0").lstrip("-").isdigit() else None, canonical_json(dimensions), canonical_json(row), source_uri, now, now, now),
                )
        return {"provider": "bea", "dataset": dataset, "records": len(rows), "status": self.status()}

    def fetch_eia_data(self, route: str, data: Sequence[str] | str, *, facets: Mapping[str, Sequence[str] | str] | None = None, frequency: str | None = None, start: str | None = None, end: str | None = None, length: int = 1000, max_pages: int = 25, credential_env: str = "CATALYST_EIA_API_KEY") -> dict[str, Any]:
        adapter = EIADataAdapter()
        config = adapter.normalize_config({"route": route, "data": data, "facets": facets or {}, "frequency": frequency, "start": start, "end": end, "length": length, "max_pages": max_pages})
        cursor = config["offset"]
        pages = 0
        total_rows = 0
        while cursor is not None and pages < max(1, max_pages):
            uri = adapter.request_uri(config, {"cursor": cursor})
            body, headers, source_uri = self._fetch(uri, provider="EIA", credential_env=credential_env, credential_name="api_key", required_credential=True)
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor})
            now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="eia", resource_type=route, request={"route": route, "data": list(config["data"]), "facets": config["facets"], "frequency": frequency, "start": start, "end": end, "offset": cursor, "length": length}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                for row in rows:
                    period = _text(row.get("period")) or "unknown"
                    geography_id = _text(row.get("stateid") or row.get("location") or row.get("area") or row.get("region"))
                    geography_name = _text(row.get("stateDescription") or row.get("location-name") or row.get("area-name") or row.get("regionName"))
                    for metric in config["data"]:
                        if metric not in row:
                            continue
                        value = row.get(metric); numeric = _numeric(value)
                        dimensions = {key: value for key, value in row.items() if key not in set(config["data"]) and not key.endswith("-units")}
                        dimensions_json = canonical_json(dimensions)
                        obs_id = _stable_id("eia-observation", route, metric, period, geography_id, dimensions_json)
                        connection.execute(
                            """INSERT INTO eia_observations(observation_id,route,metric_code,period,geography_id,geography_name,value_numeric,value_text,unit,dimensions_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(route,metric_code,period,dimensions_json) DO UPDATE SET geography_id=excluded.geography_id,geography_name=excluded.geography_name,value_numeric=excluded.value_numeric,value_text=excluded.value_text,unit=excluded.unit,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                            (obs_id, route, metric, period, geography_id, geography_name, numeric, None if numeric is not None or value is None else _text(value), _text(row.get(f"{metric}-units")), dimensions_json, canonical_json(row), source_uri, now, now, now),
                        )
            total_rows += len(rows); pages += 1; cursor = next_cursor
        return {"provider": "eia", "route": route, "pages": pages, "rows": total_rows, "status": self.status()}

    def fetch_epa_records(self, table: str, *, filters: Sequence[Mapping[str, Any]] = (), first: int = 1, page_size: int = 500, max_pages: int = 10, sort: str | None = None) -> dict[str, Any]:
        adapter = EPAEnvirofactsAdapter()
        config = adapter.normalize_config({"table": table, "filters": filters, "first": first, "page_size": page_size, "max_pages": max_pages, "sort": sort})
        cursor = config["first"]; pages = 0; total = 0
        filters_json = canonical_json(config["filters"])
        while cursor is not None and pages < max(1, max_pages):
            uri = adapter.request_uri(config, {"cursor": cursor})
            body, headers, source_uri = self._fetch(uri, provider="EPA")
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="epa", resource_type=table, request={"table": table, "filters": config["filters"], "first": cursor, "page_size": page_size, "sort": sort}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                for row in rows:
                    raw_json = canonical_json(row); record_id = _stable_id("epa-record", table, raw_json)
                    connection.execute(
                        """INSERT INTO epa_envirofacts_records(record_id,table_name,filters_json,record_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET filters_json=excluded.filters_json,record_json=excluded.record_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (record_id, table, filters_json, raw_json, source_uri, now, now, now),
                    )
            total += len(rows); pages += 1; cursor = next_cursor
        return {"provider": "epa", "table": table, "pages": pages, "records": total, "status": self.status()}

    def fetch_usgs_water(self, collection: str = "daily", *, limit: int = 500, offset: int = 0, max_pages: int = 10, datetime_filter: str | None = None, bbox: str | None = None, monitoring_location_id: str | None = None, parameter_code: str | None = None, statistic_id: str | None = None, credential_env: str | None = "CATALYST_USGS_API_KEY") -> dict[str, Any]:
        adapter = USGSWaterDataAdapter()
        config = adapter.normalize_config({"collection": collection, "limit": limit, "offset": offset, "max_pages": max_pages, "datetime": datetime_filter, "bbox": bbox, "monitoring_location_id": monitoring_location_id, "parameter_code": parameter_code, "statistic_id": statistic_id})
        cursor = config["offset"]; pages = 0; total = 0
        while cursor is not None and pages < max(1, max_pages):
            uri = adapter.request_uri(config, {"cursor": cursor})
            body, headers, source_uri = self._fetch(uri, provider="USGS", credential_env=credential_env, credential_name="api_key")
            rows, next_cursor = adapter.parse_page(body, headers, config, {"cursor": cursor}); now = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                self._record_fetch(connection, provider="usgs", resource_type=collection, request={"collection": collection, "limit": limit, "offset": cursor, "params": config["params"]}, body=body, source_uri=source_uri, result_count=len(rows), now=now)
                for feature in rows:
                    properties = feature.get("properties") if isinstance(feature.get("properties"), Mapping) else {}
                    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), Mapping) else {}
                    feature_id = _text(feature.get("id")) or _stable_id("usgs-feature", canonical_json(feature))
                    location = _text(properties.get("monitoring_location_id"))
                    parameter = _text(properties.get("parameter_code"))
                    period = _text(properties.get("time")) or "unknown"
                    statistic = _text(properties.get("statistic_id")) or ""
                    value = properties.get("value"); numeric = _numeric(value)
                    obs_id = _stable_id("usgs-observation", collection, feature_id, location, parameter, statistic, period)
                    connection.execute(
                        """INSERT INTO usgs_water_observations(observation_id,collection_name,feature_id,monitoring_location_id,parameter_code,statistic_id,period,value_numeric,value_text,unit,qualifier_json,geometry_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(collection_name,feature_id) DO UPDATE SET monitoring_location_id=excluded.monitoring_location_id,parameter_code=excluded.parameter_code,statistic_id=excluded.statistic_id,period=excluded.period,value_numeric=excluded.value_numeric,value_text=excluded.value_text,unit=excluded.unit,qualifier_json=excluded.qualifier_json,geometry_json=excluded.geometry_json,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at""",
                        (obs_id, collection, feature_id, location, parameter, statistic, period, numeric, None if numeric is not None or value is None else _text(value), _text(properties.get("unit_of_measure")), canonical_json(properties.get("qualifier") or properties.get("approvals_status") or []), canonical_json(geometry), canonical_json(feature), source_uri, now, now, now),
                    )
            total += len(rows); pages += 1; cursor = next_cursor
        return {"provider": "usgs", "collection": collection, "pages": pages, "records": total, "status": self.status()}

    def observations(self, *, provider: str | None = None, metric: str | None = None, geography: str | None = None, start_period: str | None = None, end_period: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if provider and provider not in {"census", "bls", "bea", "eia", "usgs"}:
            raise USPublicDataError("provider must be census, bls, bea, eia, or usgs")
        clauses: list[str] = []; params: list[Any] = []
        for column, value in (("provider", provider), ("metric_code", metric), ("geography_id", geography)):
            if value:
                clauses.append(f"{column}=?"); params.append(value)
        if start_period:
            clauses.append("period>=?"); params.append(start_period)
        if end_period:
            clauses.append("period<=?"); params.append(end_period)
        sql = "SELECT provider,observation_id,dataset_or_route,geography_id,geography_name,metric_code,metric_name,period,value_numeric,value_text,unit,source_uri,fetched_at FROM us_public_observations"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY period DESC,provider,metric_code LIMIT ? OFFSET ?"
        params += [max(1, min(500, int(limit))), max(0, int(offset))]
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def epa_records(self, *, table: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT record_id,table_name,filters_json,record_json,source_uri,fetched_at FROM epa_envirofacts_records"
        params: list[Any] = []
        if table:
            sql += " WHERE table_name=?"; params.append(table)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"; params += [max(1, min(500, limit)), max(0, offset)]
        out = []
        with connect(self.repository.path, readonly=True) as connection:
            for row in connection.execute(sql, params):
                item = dict(row); item["filters"] = json.loads(item.pop("filters_json")); item["record"] = json.loads(item.pop("record_json")); out.append(item)
        return out

    def status(self) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute("SELECT * FROM us_public_data_status").fetchone()
            return dict(row) if row else {}
