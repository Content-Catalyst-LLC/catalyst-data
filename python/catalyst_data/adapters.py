from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from ._version import __version__
from .connectors import ConnectorError, ConnectorFetchError, ConnectorService, get_path
from .database import connect, transaction
from .repository import CatalystRepository, canonical_json

ADAPTER_FRAMEWORK = "catalyst-data-source-adapter/1.0"
ADAPTER_STATUSES = ("active", "paused", "disabled")
PAGINATION_TYPES = ("none", "page", "offset", "cursor")


class AdapterError(RuntimeError):
    pass


class AdapterValidationError(AdapterError):
    pass


@dataclass(frozen=True)
class AdapterManifest:
    adapter_id: str
    name: str
    version: str
    provider: str
    response_format: str
    capabilities: tuple[str, ...]
    pagination: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ADAPTER_FRAMEWORK,
            "adapter_id": self.adapter_id,
            "name": self.name,
            "version": self.version,
            "provider": self.provider,
            "response_format": self.response_format,
            "capabilities": list(self.capabilities),
            "pagination": list(self.pagination),
            "description": self.description,
        }


@dataclass(frozen=True)
class AdapterPage:
    body: bytes
    rows: list[dict[str, Any]]
    request_uri: str
    response_status: int
    response_headers: dict[str, str]
    content_type: str
    etag: str | None
    last_modified: str | None
    next_cursor: str | int | None
    not_modified: bool = False


class SourceAdapter:
    manifest: AdapterManifest

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str | int | None]:
        raise NotImplementedError

    def normalize_row(self, row: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        return dict(row)


class GenericHttpAdapter(SourceAdapter):
    def __init__(self, response_format: str):
        if response_format not in ("json", "csv"):
            raise ValueError("response_format must be json or csv")
        self.response_format = response_format
        self.manifest = AdapterManifest(
            adapter_id=f"generic-http-{response_format}",
            name=f"Generic HTTP {response_format.upper()} Adapter",
            version="1.0.0",
            provider="generic",
            response_format=response_format,
            capabilities=("read", "pagination", "conditional-get", "checkpoint", "normalization"),
            pagination=PAGINATION_TYPES,
            description="Reusable governed HTTP adapter for paginated external source APIs.",
        )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise AdapterValidationError("adapter config must be an object")
        value = dict(config)
        base_url = str(value.get("base_url") or "").strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise AdapterValidationError("config.base_url must be an absolute HTTP(S) URL")
        query = dict(value.get("query") or {})
        headers = {str(k): str(v) for k, v in dict(value.get("headers") or {}).items()}
        forbidden_headers = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key"}
        forbidden_query = {"api_key", "apikey", "access_token", "token", "key", "client_secret"}
        secret_headers = sorted(k for k in headers if k.strip().lower() in forbidden_headers)
        secret_query = sorted(str(k) for k in query if str(k).strip().lower() in forbidden_query)
        if secret_headers or secret_query:
            raise AdapterValidationError(
                "adapter config must not persist credentials; use connector auth environment references"
            )
        pagination = dict(value.get("pagination") or {})
        pagination_type = str(pagination.get("type") or "none")
        if pagination_type not in PAGINATION_TYPES:
            raise AdapterValidationError("config.pagination.type is invalid")
        max_pages = int(pagination.get("max_pages") or value.get("max_pages") or 25)
        if not 1 <= max_pages <= 1000:
            raise AdapterValidationError("config.pagination.max_pages must be between 1 and 1000")
        page_size = pagination.get("page_size")
        if page_size is not None and int(page_size) < 1:
            raise AdapterValidationError("config.pagination.page_size must be positive")
        normalized = {
            "base_url": base_url,
            "query": {str(k): str(v) for k, v in query.items()},
            "headers": headers,
            "records_path": str(value.get("records_path") or "").strip() or None,
            "next_cursor_path": str(value.get("next_cursor_path") or pagination.get("next_cursor_path") or "").strip() or None,
            "user_agent": str(value.get("user_agent") or f"SustainableCatalyst-CatalystData/{__version__} (+https://sustainablecatalyst.com/)").strip(),
            "pagination": {
                "type": pagination_type,
                "param": str(pagination.get("param") or {"page":"page","offset":"offset","cursor":"cursor"}.get(pagination_type, "")).strip() or None,
                "start": pagination.get("start", 1 if pagination_type == "page" else 0),
                "page_size_param": str(pagination.get("page_size_param") or "").strip() or None,
                "page_size": int(page_size) if page_size is not None else None,
                "max_pages": max_pages,
            },
            "metadata": dict(value.get("metadata") or {}),
        }
        return normalized

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        parsed = urlparse(str(config["base_url"]))
        query = parse_qsl(parsed.query, keep_blank_values=True)
        configured = dict(config.get("query") or {})
        query.extend((str(k), str(v)) for k, v in configured.items())
        pagination = dict(config.get("pagination") or {})
        kind = pagination.get("type") or "none"
        if kind != "none":
            param = str(pagination.get("param") or kind)
            cursor = state.get("cursor")
            if cursor is None:
                cursor = pagination.get("start")
            if cursor is not None:
                query.append((param, str(cursor)))
            page_size = pagination.get("page_size")
            page_size_param = pagination.get("page_size_param")
            if page_size is not None and page_size_param:
                query.append((str(page_size_param), str(page_size)))
        return urlunparse(parsed._replace(query=urlencode(query)))

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str | int | None]:
        text = body.decode("utf-8-sig")
        pagination = dict(config.get("pagination") or {})
        kind = pagination.get("type") or "none"
        if self.response_format == "csv":
            rows = [dict(row) for row in csv.DictReader(io.StringIO(text))]
            payload: Any = rows
        else:
            payload = json.loads(text)
            selected = get_path(payload, config.get("records_path"), payload)
            if isinstance(selected, Mapping):
                if isinstance(selected.get("records"), list):
                    selected = selected["records"]
                else:
                    selected = [selected]
            if not isinstance(selected, list):
                raise AdapterValidationError("configured records_path does not resolve to an array or object")
            rows = []
            for row in selected:
                if not isinstance(row, Mapping):
                    raise AdapterValidationError("adapter records must be objects")
                rows.append(dict(row))
        if kind == "none":
            next_cursor = None
        elif kind == "cursor":
            if self.response_format != "json":
                raise AdapterValidationError("cursor pagination requires a JSON response")
            path = config.get("next_cursor_path")
            if not path:
                raise AdapterValidationError("cursor pagination requires next_cursor_path")
            next_cursor = get_path(payload, str(path))
            if next_cursor in ("", None):
                next_cursor = None
        elif kind == "page":
            current = state.get("cursor")
            if current is None:
                current = pagination.get("start", 1)
            next_cursor = int(current) + 1 if rows else None
        elif kind == "offset":
            current = state.get("cursor")
            if current is None:
                current = pagination.get("start", 0)
            step = pagination.get("page_size") or len(rows)
            next_cursor = int(current) + int(step) if rows else None
        else:
            next_cursor = None
        return [self.normalize_row(row, config) for row in rows], next_cursor


class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        adapter_id = adapter.manifest.adapter_id
        if not re.fullmatch(r"[a-z][a-z0-9._-]{2,127}", adapter_id):
            raise AdapterValidationError("adapter_id is invalid")
        existing = self._adapters.get(adapter_id)
        if existing and existing.manifest.version != adapter.manifest.version:
            raise AdapterValidationError(f"adapter already registered with a different version: {adapter_id}")
        self._adapters[adapter_id] = adapter

    def get(self, adapter_id: str) -> SourceAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise AdapterError(f"adapter not found: {adapter_id}") from exc

    def list(self) -> list[dict[str, Any]]:
        return [self._adapters[key].manifest.to_dict() for key in sorted(self._adapters)]


def default_adapter_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(GenericHttpAdapter("json"))
    registry.register(GenericHttpAdapter("csv"))
    return registry


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}:" + secrets.token_hex(12)


def _retry_after(headers: Mapping[str, str]) -> str | None:
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = int(value)
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class AdapterRunner:
    def __init__(self, repository: CatalystRepository | str, *, registry: AdapterRegistry | None = None, opener: Callable[..., Any] | None = None):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()
        self.registry = registry or default_adapter_registry()
        self.opener = opener or urlopen

    def adapters(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def bind(self, connector_id: str, adapter_id: str, config: Mapping[str, Any], *, actor: str = "principal:system", status: str = "active") -> dict[str, Any]:
        if status not in ADAPTER_STATUSES:
            raise AdapterValidationError("adapter binding status is invalid")
        adapter = self.registry.get(adapter_id)
        normalized = adapter.normalize_config(config)
        connector = ConnectorService(self.repository).get(connector_id)
        expected_type = "http-json" if adapter.manifest.response_format == "json" else "http-csv"
        if connector["connector_type"] != expected_type:
            raise AdapterValidationError(f"{adapter_id} requires connector_type {expected_type}")
        now = _now()
        binding_id = f"adapter-binding:{hashlib.sha256((connector_id+'|'+adapter_id).encode()).hexdigest()[:24]}"
        with connect(self.repository.path) as connection, transaction(connection):
            row = connection.execute("SELECT id FROM connector_definitions WHERE connector_id=?", (connector_id,)).fetchone()
            if not row:
                raise ConnectorError(f"connector not found: {connector_id}")
            connector_row_id = int(row["id"])
            existing = connection.execute("SELECT id FROM connector_adapter_bindings WHERE connector_id=?", (connector_row_id,)).fetchone()
            values = (binding_id, connector_row_id, adapter.manifest.adapter_id, adapter.manifest.version, status, canonical_json(normalized), actor, now, now)
            if existing:
                connection.execute(
                    """UPDATE connector_adapter_bindings SET binding_id=?,adapter_id=?,adapter_version=?,status=?,config_json=?,created_by=?,updated_at=? WHERE connector_id=?""",
                    (binding_id, adapter.manifest.adapter_id, adapter.manifest.version, status, canonical_json(normalized), actor, now, connector_row_id),
                )
            else:
                connection.execute(
                    """INSERT INTO connector_adapter_bindings(binding_id,connector_id,adapter_id,adapter_version,status,config_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    values,
                )
            state = connection.execute("SELECT connector_id FROM connector_adapter_state WHERE connector_id=?", (connector_row_id,)).fetchone()
            if not state:
                connection.execute("INSERT INTO connector_adapter_state(connector_id,state_json,updated_at) VALUES (?,?,?)", (connector_row_id, "{}", now))
            definition_row = connection.execute("SELECT metadata_json FROM connector_definitions WHERE id=?", (connector_row_id,)).fetchone()
            metadata = json.loads(definition_row["metadata_json"] or "{}")
            metadata["source_adapter"] = {"adapter_id": adapter.manifest.adapter_id, "adapter_version": adapter.manifest.version, "binding_id": binding_id}
            connection.execute("UPDATE connector_definitions SET metadata_json=?,updated_at=? WHERE id=?", (canonical_json(metadata), now, connector_row_id))
        return self.binding(connector_id)

    def binding(self, connector_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute(
                """SELECT cab.*,cd.connector_id AS connector_key,cas.state_json,cas.etag,cas.last_modified,cas.last_request_uri,cas.last_success_at
                   FROM connector_adapter_bindings cab JOIN connector_definitions cd ON cd.id=cab.connector_id
                   LEFT JOIN connector_adapter_state cas ON cas.connector_id=cab.connector_id WHERE cd.connector_id=?""",
                (connector_id,),
            ).fetchone()
            if not row:
                raise AdapterError(f"connector has no source adapter binding: {connector_id}")
            payload = dict(row)
            payload["connector_id"] = payload.pop("connector_key")
            payload["config"] = json.loads(payload.pop("config_json"))
            payload["state"] = json.loads(payload.pop("state_json") or "{}")
            return payload

    def bindings(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = """SELECT cab.binding_id,cd.connector_id,cab.adapter_id,cab.adapter_version,cab.status,cab.config_json,cab.created_by,cab.created_at,cab.updated_at
                 FROM connector_adapter_bindings cab JOIN connector_definitions cd ON cd.id=cab.connector_id"""
        params: list[Any] = []
        if status:
            sql += " WHERE cab.status=?"; params.append(status)
        sql += " ORDER BY cd.connector_id LIMIT ?"; params.append(limit)
        result = []
        with connect(self.repository.path, readonly=True) as connection:
            for row in connection.execute(sql, params):
                item = dict(row); item["config"] = json.loads(item.pop("config_json")); result.append(item)
        return result

    def _load_connector(self, connector_id: str) -> tuple[dict[str, Any], int]:
        service = ConnectorService(self.repository)
        definition = service.get(connector_id)
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute("SELECT id FROM connector_definitions WHERE connector_id=?", (connector_id,)).fetchone()
        if not row:
            raise ConnectorError(f"connector not found: {connector_id}")
        return definition, int(row["id"])

    @staticmethod
    def _auth_request(uri: str, headers: dict[str, str], definition: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
        auth = definition.get("auth") or {}
        auth_type = auth.get("type") or "none"
        if auth_type == "none":
            return uri, headers
        env = str(auth.get("credential_env") or "")
        credential = os.environ.get(env)
        if not credential:
            raise AdapterError(f"credential environment variable is not set: {env}")
        if auth_type == "bearer-env":
            headers["Authorization"] = "Bearer " + credential
        elif auth_type == "header-env":
            headers[str(auth.get("name") or "X-API-Key")] = credential
        elif auth_type == "query-env":
            parsed = urlparse(uri); query = parse_qsl(parsed.query, keep_blank_values=True); query.append((str(auth.get("name") or "api_key"), credential)); uri = urlunparse(parsed._replace(query=urlencode(query)))
        return uri, headers

    def _fetch_page(self, adapter: SourceAdapter, config: Mapping[str, Any], state: Mapping[str, Any], definition: Mapping[str, Any], *, conditional: bool) -> AdapterPage:
        uri = adapter.request_uri(config, state)
        headers = {str(k): str(v) for k, v in dict(config.get("headers") or {}).items()}
        headers["User-Agent"] = str(config.get("user_agent"))
        if conditional and state.get("etag"):
            headers["If-None-Match"] = str(state["etag"])
        if conditional and state.get("last_modified"):
            headers["If-Modified-Since"] = str(state["last_modified"])
        uri, headers = self._auth_request(uri, headers, definition)
        try:
            with self.opener(Request(uri, headers=headers), timeout=int(definition["governance"]["request_timeout_seconds"])) as response:
                status = int(getattr(response, "status", 200))
                response_headers = {str(k): str(v) for k, v in response.headers.items()}
                max_bytes = int(definition["source"].get("max_payload_bytes") or 20_000_000)
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise AdapterError("adapter page exceeds connector source.max_payload_bytes")
        except HTTPError as exc:
            response_headers = {str(k): str(v) for k, v in (exc.headers.items() if exc.headers else [])}
            if exc.code == 304:
                return AdapterPage(b"", [], uri, 304, response_headers, "application/octet-stream", response_headers.get("ETag"), response_headers.get("Last-Modified"), None, True)
            retry_at = _retry_after(response_headers)
            raise ConnectorFetchError(f"HTTP {exc.code}: {exc.reason}", transient=exc.code == 429 or 500 <= exc.code < 600, status=exc.code, retry_after_at=retry_at) from exc
        except URLError as exc:
            raise ConnectorFetchError(f"network error: {exc.reason}", transient=True) from exc
        content_type = response_headers.get("Content-Type", "application/json").split(";", 1)[0]
        rows, next_cursor = adapter.parse_page(body, response_headers, config, state)
        return AdapterPage(body, rows, uri, status, response_headers, content_type, response_headers.get("ETag"), response_headers.get("Last-Modified"), next_cursor)

    def run(self, connector_id: str, *, max_pages: int | None = None) -> dict[str, Any]:
        definition, connector_row_id = self._load_connector(connector_id)
        binding = self.binding(connector_id)
        if binding["status"] != "active":
            raise AdapterError(f"adapter binding is not active: {binding['status']}")
        adapter = self.registry.get(binding["adapter_id"])
        if binding["adapter_version"] != adapter.manifest.version:
            raise AdapterError(f"adapter version mismatch: binding={binding['adapter_version']} runtime={adapter.manifest.version}")
        config = adapter.normalize_config(binding["config"])
        page_cap = int(max_pages or config["pagination"]["max_pages"])
        page_cap = min(page_cap, int(config["pagination"]["max_pages"]))
        now = _now(); adapter_run_id = _id("adapter-run")
        with connect(self.repository.path) as connection, transaction(connection):
            cursor = connection.execute(
                """INSERT INTO connector_adapter_runs(adapter_run_id,connector_id,adapter_id,adapter_version,status,started_at,checkpoint_json) VALUES (?,?,?,?,?,?,?)""",
                (adapter_run_id, connector_row_id, adapter.manifest.adapter_id, adapter.manifest.version, "running", now, "{}"),
            )
            adapter_run_row_id = int(cursor.lastrowid)
            state_row = connection.execute("SELECT * FROM connector_adapter_state WHERE connector_id=?", (connector_row_id,)).fetchone()
        persisted_state = json.loads(state_row["state_json"] or "{}") if state_row else {}
        state = {"cursor": None, "etag": state_row["etag"] if state_row else None, "last_modified": state_row["last_modified"] if state_row else None}
        rows: list[dict[str, Any]] = []
        last_page: AdapterPage | None = None
        started = time.monotonic()
        try:
            for page_number in range(1, page_cap + 1):
                conditional = page_number == 1 and (config["pagination"]["type"] == "none")
                page = self._fetch_page(adapter, config, state, definition, conditional=conditional)
                last_page = page
                with connect(self.repository.path) as connection, transaction(connection):
                    connection.execute(
                        """INSERT INTO connector_adapter_pages(page_id,adapter_run_id,page_number,request_uri,response_status,response_headers_json,content_type,payload_sha256,payload_bytes,row_count,etag,last_modified,next_cursor_json,fetched_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (_id("adapter-page"), adapter_run_row_id, page_number, page.request_uri, page.response_status, canonical_json(page.response_headers), page.content_type, hashlib.sha256(page.body).hexdigest(), len(page.body), len(page.rows), page.etag, page.last_modified, canonical_json({"cursor": page.next_cursor}), _now()),
                    )
                if page.not_modified:
                    break
                rows.extend(page.rows)
                if page.next_cursor is None:
                    break
                state["cursor"] = page.next_cursor
                state["etag"] = None
                state["last_modified"] = None
            connector_result = None
            connector_run_id = None
            if last_page and not last_page.not_modified:
                payload = {"records": rows}
                connector_result = ConnectorService(self.repository).run(connector_id, trigger_type="manual", payload=payload, source_uri=config["base_url"], max_attempts=1)
                connector_run_id = connector_result.get("run", {}).get("run_id")
                connector_status = connector_result.get("run", {}).get("status")
                if connector_status not in ("succeeded", "partial"):
                    raise AdapterError(f"governed connector ingestion failed after adapter fetch: {connector_status}")
            finished = _now()
            latest_etag = last_page.etag if last_page and last_page.etag else (state_row["etag"] if state_row else None)
            latest_modified = last_page.last_modified if last_page and last_page.last_modified else (state_row["last_modified"] if state_row else None)
            checkpoint = {"cursor": state.get("cursor"), "row_count": len(rows), "page_count": page_number if last_page else 0, "not_modified": bool(last_page and last_page.not_modified)}
            with connect(self.repository.path) as connection, transaction(connection):
                connector_run_row = None
                if connector_run_id:
                    connector_run_row = connection.execute("SELECT id FROM connector_runs WHERE run_id=?", (connector_run_id,)).fetchone()
                connection.execute(
                    """UPDATE connector_adapter_runs SET status='succeeded',finished_at=?,page_count=?,row_count=?,connector_run_id=?,last_request_uri=?,checkpoint_json=? WHERE id=?""",
                    (finished, checkpoint["page_count"], len(rows), int(connector_run_row["id"]) if connector_run_row else None, last_page.request_uri if last_page else config["base_url"], canonical_json(checkpoint), adapter_run_row_id),
                )
                persistent = dict(persisted_state); persistent["last_checkpoint"] = checkpoint
                connection.execute(
                    """UPDATE connector_adapter_state SET state_json=?,etag=?,last_modified=?,last_request_uri=?,last_success_at=?,updated_at=? WHERE connector_id=?""",
                    (canonical_json(persistent), latest_etag, latest_modified, last_page.request_uri if last_page else config["base_url"], finished, finished, connector_row_id),
                )
            return {"adapter_run": self.run_details(adapter_run_id), "connector_run": connector_result}
        except Exception as exc:
            finished = _now()
            with connect(self.repository.path) as connection, transaction(connection):
                connection.execute(
                    """UPDATE connector_adapter_runs SET status='failed',finished_at=?,error_class=?,error_message=?,last_request_uri=?,checkpoint_json=? WHERE id=?""",
                    (finished, exc.__class__.__name__, str(exc), last_page.request_uri if last_page else config["base_url"], canonical_json({"elapsed_ms": int((time.monotonic()-started)*1000), "row_count": len(rows)}), adapter_run_row_id),
                )
                connection.execute("UPDATE connector_adapter_state SET updated_at=? WHERE connector_id=?", (finished, connector_row_id))
            raise

    def run_details(self, adapter_run_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute(
                """SELECT car.*,cd.connector_id AS connector_key,cr.run_id AS connector_run_key FROM connector_adapter_runs car
                   JOIN connector_definitions cd ON cd.id=car.connector_id LEFT JOIN connector_runs cr ON cr.id=car.connector_run_id WHERE car.adapter_run_id=?""",
                (adapter_run_id,),
            ).fetchone()
            if not row:
                raise AdapterError(f"adapter run not found: {adapter_run_id}")
            payload = dict(row); payload["connector_id"] = payload.pop("connector_key"); payload["connector_run_id"] = payload.pop("connector_run_key"); payload["checkpoint"] = json.loads(payload.pop("checkpoint_json") or "{}")
            pages = []
            for page in connection.execute("SELECT * FROM connector_adapter_pages WHERE adapter_run_id=? ORDER BY page_number", (payload["id"],)):
                item = dict(page); item["response_headers"] = json.loads(item.pop("response_headers_json") or "{}"); item["next_cursor"] = json.loads(item.pop("next_cursor_json") or "{}"); pages.append(item)
            payload["pages"] = pages
            return payload

    def runs(self, *, connector_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = """SELECT car.adapter_run_id,cd.connector_id,car.adapter_id,car.adapter_version,car.status,car.page_count,car.row_count,car.started_at,car.finished_at,car.error_class,car.error_message
                 FROM connector_adapter_runs car JOIN connector_definitions cd ON cd.id=car.connector_id"""
        clauses = []; params: list[Any] = []
        if connector_id: clauses.append("cd.connector_id=?"); params.append(connector_id)
        if status: clauses.append("car.status=?"); params.append(status)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY car.id DESC LIMIT ?"; params.append(limit)
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute(sql, params)]
