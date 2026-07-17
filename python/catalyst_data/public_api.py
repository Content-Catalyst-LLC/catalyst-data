from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from ._version import __version__
from .database import connect, transaction
from .handoff import handoff_digest, validate_handoff
from .repository import CatalystRepository, RepositoryError, canonical_json
from .validation import RecordValidationError, validate_record
from .workspaces import AccessDenied, WorkspaceService
from .connectors import ConnectorError, ConnectorService
from .platform import PlatformError, PlatformService

API_VERSION = "v2"
DEFAULT_SCOPES = ("records:write", "handoffs:write", "connectors:read", "connectors:run", "platform:read", "platform:write", "admin:keys")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _event_id(method: str, path: str, occurred_at: str, token: str) -> str:
    return "api-event:" + hashlib.sha256(f"{method}|{path}|{occurred_at}|{token}".encode()).hexdigest()[:24]


def public_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    workflow = record.get("review_workflow", {})
    gate = workflow.get("publication_gate", {}) if isinstance(workflow, Mapping) else {}
    if gate.get("status") != "external" or workflow.get("state") != "approved":
        raise PermissionError("record is not approved for external publication")
    result = deepcopy(dict(record))
    source = result.get("source")
    if isinstance(source, dict):
        source["access_notes"] = None
    evidence = result.get("evidence_chain")
    if isinstance(evidence, dict):
        for item in evidence.get("sources", []):
            if isinstance(item, dict) and isinstance(item.get("source"), dict):
                item["source"]["access_notes"] = None
    lineage = result.get("observation_lineage")
    if isinstance(lineage, dict):
        public_dataset_ids = {item.get("id") for item in lineage.get("datasets", []) if isinstance(item, dict) and item.get("access") == "public"}
        lineage["datasets"] = [item for item in lineage.get("datasets", []) if item.get("id") in public_dataset_ids]
        public_batch_ids = {item.get("id") for item in lineage.get("batches", []) if item.get("dataset_id") in public_dataset_ids}
        lineage["batches"] = [item for item in lineage.get("batches", []) if item.get("id") in public_batch_ids]
        lineage["observations"] = [item for item in lineage.get("observations", []) if item.get("batch_id") in public_batch_ids]
        for item in lineage.get("observations", []):
            if isinstance(item, dict):
                item["raw_payload"] = {}
    public_workflow = result.get("review_workflow")
    if isinstance(public_workflow, dict):
        public_workflow["assigned_reviewers"] = []
        public_workflow["decisions"] = []
        public_workflow["comments"] = [item for item in public_workflow.get("comments", []) if item.get("visibility") == "public"]
        if isinstance(public_workflow.get("quality"), dict):
            public_workflow["quality"]["assessed_by"] = "public-api"
        if isinstance(public_workflow.get("publication_gate"), dict) and public_workflow["publication_gate"].get("approved_by"):
            public_workflow["publication_gate"]["approved_by"] = "public-api"
        if isinstance(public_workflow.get("revision"), dict):
            public_workflow["revision"]["changed_by"] = "public-api"
    return result


def openapi_document(base_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Catalyst Data Public API", "version": __version__, "description": "Connected evidence and measurement platform with public-safe records, institutional workspaces, typed handoffs, governed connectors, reproducible analysis, and platform capability discovery."},
        "servers": [{"url": base_url.rstrip("/")}],
        "paths": {
            "/v1/workspaces": {"get": {"summary": "List the authenticated client workspace", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Workspace"}}}},
            "/v1/workspaces/{workspace_id}/records": {"get": {"summary": "List authorized workspace records", "security": [{"bearerAuth": []}], "parameters": [{"name": "workspace_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Workspace records"}, "403": {"description": "Forbidden"}}}},
            "/v1/connectors": {"get": {"summary": "List connectors bound to the authenticated workspace", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Connector status"}, "401": {"description": "Unauthorized"}}}},
            "/v1/connectors/runs": {"get": {"summary": "List connector runs for the authenticated workspace", "security": [{"bearerAuth": []}], "parameters": [{"name": "connector_id", "in": "query", "schema": {"type": "string"}}], "responses": {"200": {"description": "Connector runs"}}}},
            "/v1/connectors/{connector_id}/run": {"post": {"summary": "Run a connector synchronously", "security": [{"bearerAuth": []}], "parameters": [{"name": "connector_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Run result"}, "403": {"description": "Forbidden"}}}},
            "/v2/platform": {"get": {"summary": "Connected platform manifest", "responses": {"200": {"description": "Platform manifest"}}}},
            "/v2/platform/readiness": {"get": {"summary": "Integrated platform readiness", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Readiness"}, "401": {"description": "Unauthorized"}}}},
            "/v2/platform/components": {"get": {"summary": "Connected platform components", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Components"}}}, "post": {"summary": "Register or version a platform component", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Registered"}}}},
            "/v2/platform/snapshots": {"get": {"summary": "Immutable platform release snapshots", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Snapshots"}}}, "post": {"summary": "Create a platform release snapshot", "security": [{"bearerAuth": []}], "responses": {"201": {"description": "Snapshot created"}}}},
            "/health": {"get": {"summary": "Repository health", "responses": {"200": {"description": "Healthy"}}}},
            "/v1/capabilities": {"get": {"summary": "Capability discovery", "responses": {"200": {"description": "Capabilities"}}}},
            "/v1/records": {
                "get": {"summary": "List externally approved records", "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100}}, {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}}], "responses": {"200": {"description": "Record page"}}},
                "post": {"summary": "Create or update a canonical record", "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Stored"}, "201": {"description": "Created"}}},
            },
            "/v1/records/{record_id}": {"get": {"summary": "Get one externally approved record", "parameters": [{"name": "record_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Record"}, "404": {"description": "Not found"}}}},
            "/v1/handoffs": {"post": {"summary": "Receive a typed platform handoff", "security": [{"bearerAuth": []}], "responses": {"202": {"description": "Accepted"}}}},
            "/v1/openapi.json": {"get": {"summary": "OpenAPI document", "responses": {"200": {"description": "OpenAPI"}}}},
        },
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    }


@dataclass(frozen=True)
class ApiClient:
    key_id: str
    name: str
    scopes: tuple[str, ...]
    workspace_id: str
    principal_id: str


class ApiRegistry:
    def __init__(self, repository: CatalystRepository):
        self.repository = repository

    def create_key(self, name: str, scopes: list[str] | tuple[str, ...], *, workspace_id: str = "workspace:default", principal_id: str = "principal:system") -> dict[str, Any]:
        self.repository.initialize()
        clean = tuple(sorted(set(str(scope).strip() for scope in scopes if str(scope).strip())))
        if not clean:
            raise ValueError("at least one scope is required")
        token = "cd_" + secrets.token_urlsafe(32)
        key_id = "key:" + hashlib.sha256(token.encode()).hexdigest()[:16]
        workspace = WorkspaceService(self.repository)
        if workspace.context(principal_id, workspace_id) is None:
            raise ValueError("principal must be an active member of the API key workspace")
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute("INSERT INTO api_clients(key_id,name,token_sha256,scopes_json) VALUES (?,?,?,?)", (key_id, name.strip(), token_digest(token), json.dumps(clean)))
        workspace.bind_api_key(key_id, workspace_id, principal_id)
        return {"key_id": key_id, "name": name.strip(), "scopes": list(clean), "workspace_id": workspace_id, "principal_id": principal_id, "token": token}

    def list_keys(self) -> list[dict[str, Any]]:
        self.repository.initialize()
        with connect(self.repository.path, readonly=True) as connection:
            rows = connection.execute("""SELECT ac.key_id,ac.name,ac.scopes_json,ac.active,ac.created_at,ac.last_used_at,w.workspace_id,p.principal_id
                                         FROM api_clients ac LEFT JOIN api_client_workspace_bindings b ON b.key_id=ac.key_id
                                         LEFT JOIN workspaces w ON w.id=b.workspace_id LEFT JOIN principals p ON p.id=b.principal_id
                                         ORDER BY ac.id""").fetchall()
            return [{**dict(row), "scopes": json.loads(row["scopes_json"])} for row in rows]

    def revoke(self, key_id: str) -> bool:
        with connect(self.repository.path) as connection, transaction(connection):
            cursor = connection.execute("UPDATE api_clients SET active=0 WHERE key_id=? AND active=1", (key_id,))
            return bool(cursor.rowcount)

    def authenticate(self, token: str, required_scope: str) -> ApiClient | None:
        digest = token_digest(token)
        with connect(self.repository.path) as connection, transaction(connection):
            row = connection.execute("""SELECT ac.key_id,ac.name,ac.scopes_json,w.workspace_id,p.principal_id
                                         FROM api_clients ac JOIN api_client_workspace_bindings b ON b.key_id=ac.key_id
                                         JOIN workspaces w ON w.id=b.workspace_id JOIN principals p ON p.id=b.principal_id
                                         WHERE ac.token_sha256=? AND ac.active=1 AND w.status='active' AND p.active=1""", (digest,)).fetchone()
            if not row:
                return None
            scopes = tuple(json.loads(row["scopes_json"]))
            if required_scope not in scopes and "admin:*" not in scopes:
                return None
            connection.execute("UPDATE api_clients SET last_used_at=? WHERE key_id=?", (_now(), row["key_id"]))
            return ApiClient(row["key_id"], row["name"], scopes, row["workspace_id"], row["principal_id"])

    def audit(self, *, method: str, path: str, status_code: int, client: ApiClient | None = None, scope: str | None = None, record_id: str | None = None, handoff_id: str | None = None, remote_address: str | None = None, details: Mapping[str, Any] | None = None) -> None:
        occurred = _now(); nonce = secrets.token_hex(8)
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute("INSERT INTO api_audit_events(event_id,key_id,method,path,status_code,scope,record_id,handoff_id,remote_address,details_json,occurred_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (_event_id(method,path,occurred,nonce), client.key_id if client else None, method, path, status_code, scope, record_id, handoff_id, remote_address, json.dumps(details or {}, sort_keys=True), occurred))

    def receipts(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute("SELECT handoff_id,source_product,source_version,target_product,capability,action,payload_sha256,status,received_at,processed_at FROM handoff_receipts ORDER BY id DESC LIMIT ?", (limit,))]

    def receive_handoff(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        payload = validate_handoff(envelope); digest = handoff_digest(payload)
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute("INSERT OR IGNORE INTO handoff_receipts(handoff_id,schema_version,source_product,source_version,target_product,capability,action,payload_sha256,envelope_json) VALUES (?,?,?,?,?,?,?,?,?)", (payload["handoff_id"], payload["schema_version"], payload["source"]["product"], payload["source"]["version"], payload["target"]["product"], payload["target"]["capability"], payload["action"], digest, canonical_json(payload)))
        return {"handoff_id": payload["handoff_id"], "status": "accepted", "payload_sha256": digest}


class CatalystApiServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address: tuple[str, int], repository: CatalystRepository, *, allow_origin: str | None = None, public_base_url: str | None = None):
        self.repository = repository
        self.registry = ApiRegistry(repository)
        self.allow_origin = allow_origin
        self.public_base_url = public_base_url or f"http://{address[0]}:{address[1]}"
        repository.initialize()
        super().__init__(address, CatalystApiHandler)


class CatalystApiHandler(BaseHTTPRequestHandler):
    server: CatalystApiServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _headers(self, status: int, length: int, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if self.command != "GET" else "public, max-age=60")
        if self.server.allow_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def _json(self, status: int, payload: Any) -> None:
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self._headers(status, len(body)); self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}, "status": status})

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2_000_000:
            raise ValueError("request body is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _auth(self, scope: str) -> ApiClient | None:
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return None
        return self.server.registry.authenticate(value[7:].strip(), scope)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        if self.server.allow_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path); path = parsed.path
        try:
            if path == "/health":
                health = self.server.repository.health()
                self._json(200, {"status": "ok" if health.healthy else "attention", "version": __version__, "migration_version": health.migration_version, "latest_migration": health.latest_migration, "record_count": health.record_count})
                return
            if path in ("/openapi.json", "/v1/openapi.json", "/v2/openapi.json"):
                self._json(200, openapi_document(self.server.public_base_url)); return
            if path == "/v2/platform":
                self._json(200, PlatformService(self.server.repository).manifest()); return
            if path == "/v2/platform/readiness":
                client = self._auth("platform:read")
                if not client:
                    self._error(401, "unauthorized", "A platform:read bearer token is required"); return
                self._json(200, PlatformService(self.server.repository).readiness(actor=client.principal_id, persist=False)); return
            if path == "/v2/platform/components":
                client = self._auth("platform:read")
                if not client:
                    self._error(401, "unauthorized", "A platform:read bearer token is required"); return
                self._json(200, {"components": PlatformService(self.server.repository).components()}); return
            if path == "/v2/platform/snapshots":
                client = self._auth("platform:read")
                if not client:
                    self._error(401, "unauthorized", "A platform:read bearer token is required"); return
                self._json(200, {"snapshots": PlatformService(self.server.repository).snapshots()}); return
            if path == "/v1/capabilities":
                self._json(200, {"api_version": API_VERSION, "compatibility": ["v1"], "product": "catalyst-data", "version": __version__, "contracts": ["catalyst-data-record/1.0", "catalyst-data-handoff/1.0", "catalyst-data-access-governance/1.0", "catalyst-data-connector-operations/1.0", "catalyst-data-analysis-artifact/1.0", "catalyst-data-operational-hardening/1.0", "catalyst-data-platform/2.0"], "capabilities": ["public-records", "protected-record-writes", "typed-handoffs", "persistent-embeds", "institutional-workspaces", "role-based-access", "retention-governance", "connector-registry", "connector-refresh", "payload-replay", "reconciliation", "quarantine", "reproducible-analysis", "offline-operations", "platform-manifest", "platform-registry", "release-snapshots", "integrity-verification", "openapi"], "platform_targets": ["knowledge-library", "research-librarian", "site-intelligence", "workbench", "research-lab", "catalyst-analytics-r", "catalyst-canvas", "decision-studio", "platform-core"]}); return
            if path == "/v1/workspaces":
                client = self._auth("records:read")
                if not client:
                    self._error(401, "unauthorized", "A records:read bearer token is required"); return
                service = WorkspaceService(self.server.repository)
                service.authorize(client.principal_id, client.workspace_id, "records:read")
                self._json(200, {"workspaces": [service.workspace(client.workspace_id)]}); return
            if path.startswith("/v1/workspaces/") and path.endswith("/records"):
                workspace_id = unquote(path[len("/v1/workspaces/"):-len("/records")].rstrip("/"))
                client = self._auth("records:read")
                if not client:
                    self._error(401, "unauthorized", "A records:read bearer token is required"); return
                if workspace_id != client.workspace_id:
                    self._error(403, "forbidden", "API key is bound to a different workspace"); return
                service = WorkspaceService(self.server.repository)
                records = service.records(workspace_id, principal_id=client.principal_id, limit=100)
                self._json(200, {"workspace_id": workspace_id, "records": records, "total": len(records)}); return
            if path == "/v1/connectors":
                client = self._auth("connectors:read")
                if not client:
                    self._error(401, "unauthorized", "A connectors:read bearer token is required"); return
                WorkspaceService(self.server.repository).authorize(client.principal_id, client.workspace_id, "connectors:read")
                self._json(200, {"workspace_id": client.workspace_id, "connectors": ConnectorService(self.server.repository).list(workspace_id=client.workspace_id)}); return
            if path == "/v1/connectors/runs":
                client = self._auth("connectors:read")
                if not client:
                    self._error(401, "unauthorized", "A connectors:read bearer token is required"); return
                WorkspaceService(self.server.repository).authorize(client.principal_id, client.workspace_id, "connectors:read")
                query = parse_qs(parsed.query); connector_id = query.get("connector_id", [None])[0]
                service = ConnectorService(self.server.repository)
                if connector_id:
                    connector = service.get(connector_id)
                    if connector["workspace_id"] != client.workspace_id:
                        self._error(403, "forbidden", "Connector belongs to a different workspace"); return
                allowed = {item["connector_id"] for item in service.list(workspace_id=client.workspace_id)}
                runs = [item for item in service.runs(connector_id=connector_id, limit=100) if item["connector_id"] in allowed]
                self._json(200, {"workspace_id": client.workspace_id, "runs": runs, "total": len(runs)}); return
            if path == "/v1/records":
                query = parse_qs(parsed.query); limit = min(100, max(1, int(query.get("limit", [20])[0]))); offset = max(0, int(query.get("offset", [0])[0]))
                with connect(self.server.repository.path, readonly=True) as connection:
                    total = int(connection.execute("SELECT COUNT(*) FROM public_api_records").fetchone()[0])
                    rows = connection.execute("SELECT payload_json FROM public_api_records ORDER BY updated_at DESC,record_id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
                records = [public_projection(json.loads(row[0])) for row in rows]
                self._json(200, {"records": records, "pagination": {"limit": limit, "offset": offset, "total": total, "next_offset": offset + limit if offset + limit < total else None}}); return
            if path.startswith("/v1/records/"):
                record_id = unquote(path[len("/v1/records/"):]); record = self.server.repository.get_record(record_id)
                if record is None:
                    self._error(404, "record-not-found", "Record not found"); return
                try: projected = public_projection(record)
                except PermissionError:
                    self._error(404, "record-not-found", "Record not found"); return
                self._json(200, projected); return
            self._error(404, "not-found", "Endpoint not found")
        except AccessDenied as exc:
            self._error(403, "forbidden", str(exc))
        except (ValueError, sqlite3.Error, PlatformError) as exc:
            self._error(400, "invalid-request", str(exc))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        client: ApiClient | None = None
        try:
            if path == "/v2/platform/components":
                client = self._auth("platform:write")
                if not client:
                    self._error(401, "unauthorized", "A platform:write bearer token is required"); return
                result = PlatformService(self.server.repository).register_component(self._body(), actor=client.principal_id)
                self._json(200, result); self.server.registry.audit(method="POST",path=path,status_code=200,client=client,scope="platform:write",remote_address=self.client_address[0],details={"component_id":result["component_id"]}); return
            if path == "/v2/platform/snapshots":
                client = self._auth("platform:write")
                if not client:
                    self._error(401, "unauthorized", "A platform:write bearer token is required"); return
                result = PlatformService(self.server.repository).create_snapshot(actor=client.principal_id)
                self._json(201, result); self.server.registry.audit(method="POST",path=path,status_code=201,client=client,scope="platform:write",remote_address=self.client_address[0],details={"snapshot_id":result["snapshot_id"]}); return
            if path == "/v1/connectors":
                client = self._auth("connectors:read")
                if not client:
                    self._error(401, "unauthorized", "A connectors:read bearer token is required"); return
                WorkspaceService(self.server.repository).authorize(client.principal_id, client.workspace_id, "connectors:read")
                self._json(200, {"workspace_id": client.workspace_id, "connectors": ConnectorService(self.server.repository).list(workspace_id=client.workspace_id)}); return
            if path == "/v1/connectors/runs":
                client = self._auth("connectors:read")
                if not client:
                    self._error(401, "unauthorized", "A connectors:read bearer token is required"); return
                WorkspaceService(self.server.repository).authorize(client.principal_id, client.workspace_id, "connectors:read")
                query = parse_qs(parsed.query); connector_id = query.get("connector_id", [None])[0]
                service = ConnectorService(self.server.repository)
                if connector_id:
                    connector = service.get(connector_id)
                    if connector["workspace_id"] != client.workspace_id:
                        self._error(403, "forbidden", "Connector belongs to a different workspace"); return
                allowed = {item["connector_id"] for item in service.list(workspace_id=client.workspace_id)}
                runs = [item for item in service.runs(connector_id=connector_id, limit=100) if item["connector_id"] in allowed]
                self._json(200, {"workspace_id": client.workspace_id, "runs": runs, "total": len(runs)}); return
            if path.startswith("/v1/connectors/") and path.endswith("/run"):
                client = self._auth("connectors:run")
                if not client:
                    self._error(401, "unauthorized", "A connectors:run bearer token is required"); self.server.registry.audit(method="POST",path=path,status_code=401,scope="connectors:run",remote_address=self.client_address[0]); return
                WorkspaceService(self.server.repository).authorize(client.principal_id, client.workspace_id, "connectors:run")
                connector_id = unquote(path[len("/v1/connectors/"):-len("/run")].rstrip("/"))
                service = ConnectorService(self.server.repository); connector = service.get(connector_id)
                if connector["workspace_id"] != client.workspace_id:
                    self._error(403, "forbidden", "Connector belongs to a different workspace"); return
                body = self._body(); supplied = body.get("payload") if isinstance(body, Mapping) else None
                result = service.run(connector_id, payload=supplied, source_uri=body.get("source_uri") if isinstance(body, Mapping) else None, max_attempts=body.get("max_attempts") if isinstance(body, Mapping) else None)
                status = 200 if result["run"]["status"] in ("succeeded","partial") else 422
                self._json(status, result); self.server.registry.audit(method="POST",path=path,status_code=status,client=client,scope="connectors:run",remote_address=self.client_address[0],details={"connector_id":connector_id,"run_id":result["run"]["run_id"]}); return
            if path == "/v1/records":
                client = self._auth("records:write")
                if not client:
                    self._error(401, "unauthorized", "A records:write bearer token is required"); self.server.registry.audit(method="POST",path=path,status_code=401,scope="records:write",remote_address=self.client_address[0]); return
                service = WorkspaceService(self.server.repository)
                service.authorize(client.principal_id, client.workspace_id, "records:write", record_id=None)
                payload = self._body(); validate_record(payload)
                existing = self.server.repository.get_record(payload["record_id"])
                action = self.server.repository.upsert_record(payload)
                service.assign_record(payload["record_id"], client.workspace_id, actor=client.principal_id, owner_principal_id=client.principal_id, steward_principal_id=client.principal_id, custodian_principal_id=client.principal_id)
                status = 201 if existing is None else 200
                self._json(status, {"record_id": payload["record_id"], "action": action, "payload_sha256": hashlib.sha256(canonical_json(payload).encode()).hexdigest()})
                self.server.registry.audit(method="POST",path=path,status_code=status,client=client,scope="records:write",record_id=payload["record_id"],remote_address=self.client_address[0]); return
            if path == "/v1/handoffs":
                client = self._auth("handoffs:write")
                if not client:
                    self._error(401, "unauthorized", "A handoffs:write bearer token is required"); self.server.registry.audit(method="POST",path=path,status_code=401,scope="handoffs:write",remote_address=self.client_address[0]); return
                WorkspaceService(self.server.repository).authorize(client.principal_id, client.workspace_id, "handoffs:write")
                result = self.server.registry.receive_handoff(self._body())
                self._json(202, result); self.server.registry.audit(method="POST",path=path,status_code=202,client=client,scope="handoffs:write",handoff_id=result["handoff_id"],remote_address=self.client_address[0]); return
            self._error(404, "not-found", "Endpoint not found")
        except (ValueError, RecordValidationError, RepositoryError, AccessDenied, ConnectorError, sqlite3.Error) as exc:
            self._error(400, "invalid-request", str(exc))
            try: self.server.registry.audit(method="POST",path=path,status_code=400,client=client,remote_address=self.client_address[0],details={"error": str(exc)})
            except Exception: pass


def serve(repository: CatalystRepository, host: str = "127.0.0.1", port: int = 8765, *, allow_origin: str | None = None, public_base_url: str | None = None) -> None:
    server = CatalystApiServer((host, port), repository, allow_origin=allow_origin, public_base_url=public_base_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
