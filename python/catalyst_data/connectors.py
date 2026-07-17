from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import secrets
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .database import connect, transaction
from .engine import build_record, stable_id
from .repository import CatalystRepository, RepositoryError, canonical_json

CONNECTOR_CONTRACT = "catalyst-data-connector-operations/1.0"
CONNECTOR_SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-connector-operations-1.0.json"
CONNECTOR_TYPES = ("http-json", "http-csv", "file-json", "file-csv", "manual", "replay")
AUTH_TYPES = ("none", "bearer-env", "header-env", "query-env")
RUN_STATUSES = ("queued", "running", "succeeded", "partial", "failed", "quarantined", "dead-letter", "cancelled")
ALERT_TYPES = ("fetch-failure", "rate-limit", "freshness", "license", "schema-drift", "record-drift", "reconciliation", "quarantine", "dead-letter", "health")


class ConnectorError(RuntimeError):
    pass


class ConnectorValidationError(ConnectorError):
    pass


class ConnectorRateLimited(ConnectorError):
    def __init__(self, message: str, retry_after_at: str | None = None):
        super().__init__(message)
        self.retry_after_at = retry_after_at


class ConnectorFetchError(ConnectorError):
    def __init__(self, message: str, *, transient: bool = False, status: int | None = None, retry_after_at: str | None = None):
        super().__init__(message)
        self.transient = transient
        self.status = status
        self.retry_after_at = retry_after_at


@dataclass(frozen=True)
class FetchedPayload:
    body: bytes
    content_type: str
    source_uri: str
    response_status: int | None
    response_headers: dict[str, str]
    source_modified_at: str | None
    latency_ms: int


def _now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None = None) -> str:
    candidate = value or _now_dt()
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            candidate = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc)


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return clean[:80] or "connector"


def _digest(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = canonical_json(value if isinstance(value, Mapping) else {"value": value}).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identifier(prefix: str, *parts: str) -> str:
    nonce = secrets.token_hex(6)
    return f"{prefix}:" + hashlib.sha256(("|".join(parts) + "|" + nonce).encode("utf-8")).hexdigest()[:24]


def connector_schema() -> dict[str, Any]:
    path = files("catalyst_data").joinpath("schemas/catalyst_data_connector_operations_1_0.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_with_schema(payload: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return
    errors = sorted(Draft202012Validator(connector_schema()).iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        raise ConnectorValidationError(f"{location}: {error.message}")


def normalize_connector_definition(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ConnectorValidationError("connector definition must be an object")
    value = deepcopy(dict(payload))
    name = str(value.get("name", "")).strip()
    if not name:
        raise ConnectorValidationError("name is required")
    connector_type = str(value.get("connector_type", "")).strip()
    if connector_type not in CONNECTOR_TYPES:
        raise ConnectorValidationError("connector_type is invalid")
    version = str(value.get("version", "1.0.0")).strip()
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}", version):
        raise ConnectorValidationError("version is invalid")
    connector_id = str(value.get("connector_id") or stable_id("connector", name, connector_type))
    workspace_id = str(value.get("workspace_id") or "workspace:default")
    principal_id = str(value.get("principal_id") or "principal:system")
    source = dict(value.get("source") or {})
    uri = source.get("uri")
    if connector_type not in ("manual", "replay") and not str(uri or "").strip():
        raise ConnectorValidationError("source.uri is required")
    records_path = source.get("records_path")
    source_key_path = source.get("source_key_path")
    modified_at_path = source.get("modified_at_path")
    governance = dict(value.get("governance") or {})
    auth = dict(value.get("auth") or {})
    auth_type = str(auth.get("type") or "none")
    if auth_type not in AUTH_TYPES:
        raise ConnectorValidationError("auth.type is invalid")
    credential_env = auth.get("credential_env")
    if credential_env is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", str(credential_env)):
        raise ConnectorValidationError("auth.credential_env must be an uppercase environment variable name")
    if auth_type != "none" and not credential_env:
        raise ConnectorValidationError("auth.credential_env is required for configured authentication")
    mapping = value.get("mapping") or {}
    transformations = value.get("transformations") or {}
    if not isinstance(mapping, Mapping) or not isinstance(transformations, Mapping):
        raise ConnectorValidationError("mapping and transformations must be objects")
    schedule = dict(value.get("schedule") or {})
    frequency = schedule.get("frequency_minutes")
    if frequency is not None and int(frequency) < 60:
        raise ConnectorValidationError("schedule.frequency_minutes must be at least 60")
    normalized = {
        "$schema": CONNECTOR_SCHEMA_URI,
        "schema_version": CONNECTOR_CONTRACT,
        "connector_id": connector_id,
        "name": name,
        "connector_type": connector_type,
        "version": version,
        "workspace_id": workspace_id,
        "principal_id": principal_id,
        "status": str(value.get("status") or "active"),
        "source": {
            "uri": str(uri).strip() if uri is not None else None,
            "records_path": str(records_path).strip() if records_path else None,
            "source_key_path": str(source_key_path).strip() if source_key_path else None,
            "modified_at_path": str(modified_at_path).strip() if modified_at_path else None,
            "content_type": str(source.get("content_type") or "").strip() or None,
            "headers": {str(k): str(v) for k, v in dict(source.get("headers") or {}).items()},
            "max_payload_bytes": int(source.get("max_payload_bytes") or 20_000_000),
        },
        "governance": {
            "license": str(governance.get("license") or "").strip() or None,
            "license_url": str(governance.get("license_url") or "").strip() or None,
            "license_status": str(governance.get("license_status") or "unknown"),
            "freshness_sla_seconds": int(governance["freshness_sla_seconds"]) if governance.get("freshness_sla_seconds") is not None else None,
            "request_timeout_seconds": int(governance.get("request_timeout_seconds") or 30),
            "rate_limit_per_hour": int(governance["rate_limit_per_hour"]) if governance.get("rate_limit_per_hour") is not None else None,
            "max_attempts": int(governance.get("max_attempts") or 3),
            "retry_backoff_seconds": int(governance.get("retry_backoff_seconds") or 30),
            "drift_missing_ratio": float(governance.get("drift_missing_ratio") or 0.25),
            "publisher": str(governance.get("publisher") or "").strip() or None,
            "citation": str(governance.get("citation") or "").strip() or None,
            "access_notes": str(governance.get("access_notes") or "").strip() or None,
        },
        "auth": {
            "type": auth_type,
            "credential_env": str(credential_env) if credential_env else None,
            "name": str(auth.get("name") or "").strip() or None,
        },
        "capabilities": sorted(set(str(item).strip() for item in value.get("capabilities", ["read", "snapshot", "replay", "reconciliation"]) if str(item).strip())),
        "mapping": deepcopy(dict(mapping)),
        "transformations": deepcopy(dict(transformations)),
        "schedule": {
            "enabled": bool(schedule.get("enabled", False)),
            "frequency_minutes": int(frequency) if frequency is not None else None,
            "next_run_at": str(schedule.get("next_run_at") or "").strip() or None,
        },
        "metadata": deepcopy(dict(value.get("metadata") or {})),
    }
    if normalized["status"] not in ("active", "paused", "disabled", "archived"):
        raise ConnectorValidationError("status is invalid")
    if normalized["governance"]["license_status"] not in ("compliant", "restricted", "unknown"):
        raise ConnectorValidationError("governance.license_status is invalid")
    if not 1 <= normalized["governance"]["request_timeout_seconds"] <= 300:
        raise ConnectorValidationError("request timeout must be between 1 and 300 seconds")
    if not 1 <= normalized["governance"]["max_attempts"] <= 20:
        raise ConnectorValidationError("max_attempts must be between 1 and 20")
    if not 0 <= normalized["governance"]["drift_missing_ratio"] <= 1:
        raise ConnectorValidationError("drift_missing_ratio must be between 0 and 1")
    if normalized["source"]["max_payload_bytes"] < 1:
        raise ConnectorValidationError("source.max_payload_bytes must be positive")
    _validate_with_schema(normalized)
    return normalized


def _path_parts(path: str | None) -> list[str]:
    if not path:
        return []
    return [part for part in re.split(r"[./]", path) if part]


def get_path(payload: Any, path: str | None, default: Any = None) -> Any:
    current = payload
    for part in _path_parts(path):
        if isinstance(current, Mapping):
            if part not in current:
                return default
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return default
            current = current[index]
        else:
            return default
    return current


def set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    parts = _path_parts(path)
    if not parts:
        raise ConnectorValidationError("mapping target path cannot be empty")
    current = payload
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _transform(value: Any, operation: Any) -> Any:
    if isinstance(operation, str):
        name, config = operation, {}
    elif isinstance(operation, Mapping):
        name = str(operation.get("operation") or operation.get("type") or "")
        config = dict(operation)
    else:
        raise ConnectorValidationError("transform operation must be a string or object")
    if name == "trim":
        return value.strip() if isinstance(value, str) else value
    if name == "lower":
        return str(value).lower()
    if name == "upper":
        return str(value).upper()
    if name == "float":
        return float(value)
    if name == "integer":
        return int(value)
    if name == "string":
        return str(value)
    if name == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if name == "split":
        delimiter = str(config.get("delimiter") or "|")
        return [item.strip() for item in str(value).split(delimiter) if item.strip()]
    if name == "multiply":
        return float(value) * float(config.get("value", 1))
    if name == "divide":
        divisor = float(config.get("value", 1))
        if divisor == 0:
            raise ConnectorValidationError("divide transform cannot use zero")
        return float(value) / divisor
    if name == "replace":
        return str(value).replace(str(config.get("old", "")), str(config.get("new", "")))
    if name == "coalesce":
        return config.get("value") if value in (None, "") else value
    if name in ("", "identity"):
        return value
    raise ConnectorValidationError(f"unsupported transform: {name}")


def map_source_row(row: Mapping[str, Any], definition: Mapping[str, Any], *, run_id: str, source_key: str, row_digest: str, occurred_at: str) -> dict[str, Any]:
    mapping = definition.get("mapping") or {}
    profile = definition.get("transformations") or {}
    if mapping:
        payload: dict[str, Any] = deepcopy(dict(profile.get("defaults") or {}))
        for target, raw_rule in mapping.items():
            if isinstance(raw_rule, str):
                rule = {"source": raw_rule}
            elif isinstance(raw_rule, Mapping):
                rule = dict(raw_rule)
            else:
                raise ConnectorValidationError(f"mapping rule for {target} is invalid")
            missing = object()
            value = get_path(row, str(rule.get("source") or ""), missing)
            if value is missing or value in (None, ""):
                if "default" in rule:
                    value = deepcopy(rule["default"])
                elif rule.get("required"):
                    raise ConnectorValidationError(f"required source field is missing for {target}")
                else:
                    value = None
            for operation in rule.get("transforms", []):
                value = _transform(value, operation)
            set_path(payload, str(target), value)
        for target, value in dict(profile.get("constants") or {}).items():
            set_path(payload, str(target), deepcopy(value))
        for operation in profile.get("operations", []):
            if not isinstance(operation, Mapping) or not operation.get("target"):
                raise ConnectorValidationError("global transformation operations require a target")
            target = str(operation["target"])
            value = get_path(payload, target)
            set_path(payload, target, _transform(value, operation))
    else:
        payload = deepcopy(dict(row))

    source = payload.setdefault("source", {})
    governance = definition["governance"]
    source.setdefault("name", definition["name"])
    source.setdefault("type", "api" if definition["connector_type"].startswith("http") else "third-party dataset")
    source_uri = definition["source"].get("uri")
    if source_uri and definition["connector_type"].startswith("file-") and not urlparse(str(source_uri)).scheme:
        source_uri = Path(str(source_uri)).expanduser().resolve().as_uri()
    source.setdefault("url", source_uri)
    source.setdefault("publisher", governance.get("publisher"))
    source.setdefault("license", governance.get("license"))
    source.setdefault("retrieved_at", occurred_at)
    source.setdefault("citation", governance.get("citation") or f"{definition['name']} connector source.")
    source.setdefault("checksum", "sha256:" + row_digest)
    source.setdefault("access_notes", governance.get("access_notes"))
    source.setdefault("id", stable_id("source", definition["connector_id"], definition["source"].get("uri") or definition["name"]))
    payload.setdefault("confidence", {"score": 50, "basis": "Imported through a governed connector; independent review may still be required."})
    payload.setdefault("method", {"notes": f"Imported through {definition['connector_id']} version {definition['version']}.", "assumptions": [], "limitations": [], "uncertainty": None, "quality_flags": []})
    payload.setdefault("reviewer_notes", "")
    payload.setdefault("created_at", occurred_at)
    payload.setdefault("updated_at", occurred_at)
    extensions = payload.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        raise ConnectorValidationError("extensions must be an object")
    extensions["org.sustainablecatalyst.connector"] = {
        "connector_id": definition["connector_id"],
        "connector_version": definition["version"],
        "run_id": run_id,
        "source_key": source_key,
        "source_payload_sha256": row_digest,
    }
    return payload


def _flatten_schema(value: Any, prefix: str = "") -> list[str]:
    result: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            result.append(f"{path}:object" if isinstance(value[key], Mapping) else f"{path}:{type(value[key]).__name__}")
            result.extend(_flatten_schema(value[key], path))
    elif isinstance(value, list) and value:
        result.extend(_flatten_schema(value[0], prefix + "[]"))
    return result


def schema_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str | None:
    if not rows:
        return None
    fields: set[str] = set()
    for row in rows[:25]:
        fields.update(_flatten_schema(row))
    return hashlib.sha256("\n".join(sorted(fields)).encode("utf-8")).hexdigest()


class ConnectorService:
    def __init__(self, repository: CatalystRepository | str | Path):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()

    @staticmethod
    def _definition_row(connection, connector_id: str):
        row = connection.execute(
            """SELECT cd.*,w.workspace_id AS workspace_key,p.principal_id AS principal_key FROM connector_definitions cd
               JOIN workspaces w ON w.id=cd.workspace_id JOIN principals p ON p.id=cd.principal_id
               WHERE cd.connector_id=?""",
            (connector_id,),
        ).fetchone()
        if not row:
            raise ConnectorError(f"connector not found: {connector_id}")
        return row

    @staticmethod
    def _active_version_row(connection, connector_row_id: int):
        row = connection.execute(
            """SELECT cv.* FROM connector_version_activations a
               JOIN connector_versions cv ON cv.id=a.connector_version_id
               WHERE a.connector_id=? ORDER BY a.id DESC LIMIT 1""",
            (connector_row_id,),
        ).fetchone()
        if not row:
            raise ConnectorError("connector has no active version")
        return row

    @staticmethod
    def _definition_payload(definition_row, version_row) -> dict[str, Any]:
        config = json.loads(version_row["config_json"])
        return {
            "$schema": CONNECTOR_SCHEMA_URI,
            "schema_version": CONNECTOR_CONTRACT,
            "connector_id": definition_row["connector_id"],
            "name": definition_row["name"],
            "connector_type": definition_row["connector_type"],
            "version": version_row["version"],
            "workspace_id": definition_row["workspace_key"],
            "principal_id": definition_row["principal_key"],
            "status": definition_row["status"],
            "source": config.get("source", {}),
            "governance": config.get("governance", {}),
            "auth": config.get("auth", {}),
            "capabilities": json.loads(version_row["capabilities_json"]),
            "mapping": json.loads(version_row["field_mapping_json"]),
            "transformations": json.loads(version_row["transformation_profile_json"]),
            "schedule": config.get("schedule", {}),
            "metadata": json.loads(definition_row["metadata_json"]),
        }

    def register(self, payload: Mapping[str, Any], *, actor: str = "principal:system", activate: bool = True) -> dict[str, Any]:
        definition = normalize_connector_definition(payload)
        version_payload = {
            "source": definition["source"],
            "governance": definition["governance"],
            "auth": definition["auth"],
            "schedule": definition["schedule"],
            "mapping": definition["mapping"],
            "transformations": definition["transformations"],
            "capabilities": definition["capabilities"],
        }
        digest = hashlib.sha256(canonical_json(version_payload).encode("utf-8")).hexdigest()
        with connect(self.repository.path) as connection, transaction(connection):
            workspace = connection.execute("SELECT id FROM workspaces WHERE workspace_id=?", (definition["workspace_id"],)).fetchone()
            principal = connection.execute("SELECT id FROM principals WHERE principal_id=?", (definition["principal_id"],)).fetchone()
            if not workspace:
                raise ConnectorError(f"workspace not found: {definition['workspace_id']}")
            if not principal:
                raise ConnectorError(f"principal not found: {definition['principal_id']}")
            existing = connection.execute("SELECT id FROM connector_definitions WHERE connector_id=?", (definition["connector_id"],)).fetchone()
            if existing:
                connector_row_id = int(existing["id"])
                connection.execute(
                    """UPDATE connector_definitions SET workspace_id=?,principal_id=?,name=?,connector_type=?,base_uri=?,status=?,license_name=?,license_url=?,
                       freshness_sla_seconds=?,request_timeout_seconds=?,rate_limit_per_hour=?,max_attempts=?,retry_backoff_seconds=?,credential_env=?,auth_type=?,auth_name=?,metadata_json=?,updated_at=?
                       WHERE id=?""",
                    (
                        workspace["id"], principal["id"], definition["name"], definition["connector_type"], definition["source"].get("uri"), definition["status"],
                        definition["governance"].get("license"), definition["governance"].get("license_url"), definition["governance"].get("freshness_sla_seconds"),
                        definition["governance"]["request_timeout_seconds"], definition["governance"].get("rate_limit_per_hour"), definition["governance"]["max_attempts"],
                        definition["governance"]["retry_backoff_seconds"], definition["auth"].get("credential_env"), definition["auth"]["type"], definition["auth"].get("name"),
                        canonical_json(definition["metadata"]), _iso(), connector_row_id,
                    ),
                )
            else:
                cursor = connection.execute(
                    """INSERT INTO connector_definitions(connector_id,workspace_id,principal_id,name,connector_type,base_uri,status,license_name,license_url,
                       freshness_sla_seconds,request_timeout_seconds,rate_limit_per_hour,max_attempts,retry_backoff_seconds,credential_env,auth_type,auth_name,metadata_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        definition["connector_id"], workspace["id"], principal["id"], definition["name"], definition["connector_type"], definition["source"].get("uri"),
                        definition["status"], definition["governance"].get("license"), definition["governance"].get("license_url"), definition["governance"].get("freshness_sla_seconds"),
                        definition["governance"]["request_timeout_seconds"], definition["governance"].get("rate_limit_per_hour"), definition["governance"]["max_attempts"],
                        definition["governance"]["retry_backoff_seconds"], definition["auth"].get("credential_env"), definition["auth"]["type"], definition["auth"].get("name"),
                        canonical_json(definition["metadata"]),
                    ),
                )
                connector_row_id = int(cursor.lastrowid)
                connection.execute("INSERT INTO connector_state(connector_id,health_status) VALUES (?,'unknown')", (connector_row_id,))
            version_row = connection.execute("SELECT id,payload_sha256 FROM connector_versions WHERE connector_id=? AND version=?", (connector_row_id, definition["version"])).fetchone()
            if version_row:
                if version_row["payload_sha256"] != digest:
                    raise ConnectorError("connector version already exists with a different immutable payload")
                version_row_id = int(version_row["id"])
            else:
                cursor = connection.execute(
                    """INSERT INTO connector_versions(connector_id,version,status,capabilities_json,config_json,field_mapping_json,transformation_profile_json,payload_sha256,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        connector_row_id, definition["version"], "active" if activate else "draft", json.dumps(definition["capabilities"], ensure_ascii=False),
                        canonical_json({"source": definition["source"], "governance": definition["governance"], "auth": definition["auth"], "schedule": definition["schedule"]}),
                        canonical_json(definition["mapping"]), canonical_json(definition["transformations"]), digest, actor,
                    ),
                )
                version_row_id = int(cursor.lastrowid)
            if activate:
                current = connection.execute("SELECT connector_version_id FROM connector_version_activations WHERE connector_id=? ORDER BY id DESC LIMIT 1", (connector_row_id,)).fetchone()
                if not current or int(current["connector_version_id"]) != version_row_id:
                    connection.execute(
                        "INSERT INTO connector_version_activations(activation_id,connector_id,connector_version_id,activated_by,activated_at) VALUES (?,?,?,?,?)",
                        (_identifier("connector-activation", definition["connector_id"], definition["version"]), connector_row_id, version_row_id, actor, _iso()),
                    )
            schedule = definition["schedule"]
            if schedule.get("frequency_minutes"):
                next_run = schedule.get("next_run_at") or _iso(_now_dt() + timedelta(minutes=int(schedule["frequency_minutes"])))
                connection.execute(
                    """INSERT INTO connector_schedules(schedule_id,connector_id,enabled,frequency_minutes,next_run_at,created_by)
                       VALUES (?,?,?,?,?,?) ON CONFLICT(connector_id) DO UPDATE SET enabled=excluded.enabled,frequency_minutes=excluded.frequency_minutes,
                       next_run_at=excluded.next_run_at,updated_at=datetime('now')""",
                    (_identifier("connector-schedule", definition["connector_id"]), connector_row_id, int(schedule["enabled"]), int(schedule["frequency_minutes"]), next_run, actor),
                )
        return self.get(definition["connector_id"])

    def activate_version(self, connector_id: str, version: str, *, actor: str = "principal:system") -> dict[str, Any]:
        with connect(self.repository.path) as connection, transaction(connection):
            definition = self._definition_row(connection, connector_id)
            version_row = connection.execute("SELECT id FROM connector_versions WHERE connector_id=? AND version=?", (definition["id"], version)).fetchone()
            if not version_row:
                raise ConnectorError(f"connector version not found: {version}")
            current = connection.execute("SELECT connector_version_id FROM connector_version_activations WHERE connector_id=? ORDER BY id DESC LIMIT 1", (definition["id"],)).fetchone()
            if not current or int(current["connector_version_id"]) != int(version_row["id"]):
                connection.execute(
                    "INSERT INTO connector_version_activations(activation_id,connector_id,connector_version_id,activated_by,activated_at) VALUES (?,?,?,?,?)",
                    (_identifier("connector-activation", connector_id, version), definition["id"], version_row["id"], actor, _iso()),
                )
        return self.get(connector_id)

    def get(self, connector_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            definition = self._definition_row(connection, connector_id)
            version = self._active_version_row(connection, definition["id"])
            payload = self._definition_payload(definition, version)
            status = connection.execute("SELECT * FROM connector_operational_status WHERE connector_id=?", (connector_id,)).fetchone()
            payload["operations"] = dict(status) if status else {}
            return payload

    def list(self, *, workspace_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM connector_operational_status"
        params: list[Any] = []
        if workspace_id:
            sql += " WHERE workspace_id=?"; params.append(workspace_id)
        sql += " ORDER BY name"
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def versions(self, connector_id: str) -> list[dict[str, Any]]:
        with connect(self.repository.path, readonly=True) as connection:
            definition = self._definition_row(connection, connector_id)
            active = self._active_version_row(connection, definition["id"])
            rows = connection.execute("SELECT id,version,status,capabilities_json,payload_sha256,created_by,created_at FROM connector_versions WHERE connector_id=? ORDER BY id", (definition["id"],)).fetchall()
            result=[]
            for row in rows:
                item=dict(row); item["capabilities"]=json.loads(item.pop("capabilities_json")); item["active"]=int(row["id"])==int(active["id"]); result.append(item)
            return result

    def set_schedule(self, connector_id: str, frequency_minutes: int, *, enabled: bool = True, next_run_at: str | None = None, actor: str = "principal:system") -> dict[str, Any]:
        if frequency_minutes < 60:
            raise ConnectorError("frequency_minutes must be at least 60")
        next_run = next_run_at or _iso(_now_dt() + timedelta(minutes=frequency_minutes))
        with connect(self.repository.path) as connection, transaction(connection):
            definition = self._definition_row(connection, connector_id)
            connection.execute(
                """INSERT INTO connector_schedules(schedule_id,connector_id,enabled,frequency_minutes,next_run_at,created_by)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(connector_id) DO UPDATE SET enabled=excluded.enabled,frequency_minutes=excluded.frequency_minutes,
                   next_run_at=excluded.next_run_at,updated_at=datetime('now')""",
                (_identifier("connector-schedule", connector_id), definition["id"], int(enabled), frequency_minutes, next_run, actor),
            )
        return self.schedule(connector_id)

    def schedule(self, connector_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            definition = self._definition_row(connection, connector_id)
            row = connection.execute("SELECT schedule_id,enabled,frequency_minutes,next_run_at,last_run_at,created_by,created_at,updated_at FROM connector_schedules WHERE connector_id=?", (definition["id"],)).fetchone()
            if not row:
                raise ConnectorError("connector has no schedule")
            return dict(row)

    def due(self, *, as_of: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        instant = as_of or _iso()
        sql = """SELECT cos.* FROM connector_operational_status cos
                 JOIN connector_definitions cd ON cd.connector_id=cos.connector_id
                 JOIN connector_schedules sch ON sch.connector_id=cd.id
                 WHERE sch.enabled=1 AND sch.next_run_at<=? AND cd.status='active'"""
        params: list[Any] = [instant]
        if workspace_id:
            sql += " AND cos.workspace_id=?"; params.append(workspace_id)
        sql += " ORDER BY sch.next_run_at"
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def _log(self, connection, run_row_id: int, level: str, event_type: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        connection.execute(
            "INSERT INTO connector_run_logs(log_id,run_id,level,event_type,message,details_json,occurred_at) VALUES (?,?,?,?,?,?,?)",
            (_identifier("connector-log", str(run_row_id), event_type), run_row_id, level, event_type, message, canonical_json(details or {}), _iso()),
        )

    def _alert(self, connection, connector_row_id: int, run_row_id: int | None, alert_type: str, severity: str, message: str, details: Mapping[str, Any] | None = None) -> str:
        alert_id = _identifier("connector-alert", str(connector_row_id), alert_type)
        connection.execute(
            "INSERT INTO connector_alerts(alert_id,connector_id,run_id,alert_type,severity,message,details_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (alert_id, connector_row_id, run_row_id, alert_type, severity, message, canonical_json(details or {}), _iso()),
        )
        return alert_id

    def _create_run(self, connector_row_id: int, version_row_id: int, trigger_type: str, attempt: int, input_uri: str | None, parent_run_row_id: int | None = None) -> tuple[int, str]:
        run_id = _identifier("connector-run", str(connector_row_id), trigger_type, str(attempt))
        with connect(self.repository.path) as connection, transaction(connection):
            cursor = connection.execute(
                """INSERT INTO connector_runs(run_id,connector_id,connector_version_id,parent_run_id,trigger_type,status,attempt_number,input_uri,started_at)
                   VALUES (?,?,?,?,?,'running',?,?,?)""",
                (run_id, connector_row_id, version_row_id, parent_run_row_id, trigger_type, attempt, input_uri, _iso()),
            )
            row_id = int(cursor.lastrowid)
            self._log(connection, row_id, "info", "run-started", f"Connector run {run_id} started.", {"attempt": attempt, "trigger": trigger_type})
        return row_id, run_id

    def _assert_rate_limit(self, definition_row) -> None:
        with connect(self.repository.path, readonly=True) as connection:
            state = connection.execute("SELECT next_allowed_at FROM connector_state WHERE connector_id=?", (definition_row["id"],)).fetchone()
        if state and state["next_allowed_at"]:
            next_allowed = _parse_time(state["next_allowed_at"])
            if next_allowed and next_allowed > _now_dt():
                raise ConnectorRateLimited(f"connector is rate limited until {state['next_allowed_at']}", state["next_allowed_at"])

    def _fetch(self, definition: Mapping[str, Any], *, payload_override: bytes | None = None, source_uri_override: str | None = None) -> FetchedPayload:
        started = time.monotonic()
        connector_type = definition["connector_type"]
        source = definition["source"]
        uri = source_uri_override or source.get("uri") or "manual://payload"
        content_type = source.get("content_type") or ("text/csv" if connector_type.endswith("csv") else "application/json")
        if payload_override is not None:
            return FetchedPayload(payload_override, content_type, uri, None, {}, None, int((time.monotonic()-started)*1000))
        if connector_type in ("manual", "replay"):
            raise ConnectorFetchError("manual and replay connectors require an explicit payload")
        if connector_type.startswith("file-"):
            parsed = urlparse(uri)
            path = Path(parsed.path if parsed.scheme == "file" else uri).expanduser()
            try:
                body = path.read_bytes()
                modified = _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
            except OSError as exc:
                raise ConnectorFetchError(str(exc), transient=False) from exc
            if len(body) > int(source["max_payload_bytes"]):
                raise ConnectorFetchError("connector payload exceeds max_payload_bytes")
            return FetchedPayload(body, content_type, str(path), None, {}, modified, int((time.monotonic()-started)*1000))
        if connector_type.startswith("http-"):
            headers = {str(k): str(v) for k, v in source.get("headers", {}).items()}
            auth = definition["auth"]
            credential = None
            if auth["type"] != "none":
                credential = os.environ.get(str(auth.get("credential_env") or ""))
                if not credential:
                    raise ConnectorFetchError(f"credential environment variable is not set: {auth.get('credential_env')}")
            request_uri = uri
            if auth["type"] == "bearer-env":
                headers["Authorization"] = "Bearer " + str(credential)
            elif auth["type"] == "header-env":
                headers[str(auth.get("name") or "X-API-Key")] = str(credential)
            elif auth["type"] == "query-env":
                parsed = urlparse(uri); query = parse_qsl(parsed.query, keep_blank_values=True); query.append((str(auth.get("name") or "api_key"), str(credential)))
                request_uri = urlunparse(parsed._replace(query=urlencode(query)))
            try:
                with urlopen(Request(request_uri, headers=headers), timeout=int(definition["governance"]["request_timeout_seconds"])) as response:
                    body = response.read(int(source["max_payload_bytes"]) + 1)
                    response_headers = {str(k): str(v) for k, v in response.headers.items()}
                    status = int(response.status)
            except HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                retry_at = None
                if retry_after:
                    try: retry_at = _iso(_now_dt() + timedelta(seconds=int(retry_after)))
                    except ValueError: retry_at = _iso(_parse_time(retry_after)) if _parse_time(retry_after) else None
                raise ConnectorFetchError(f"HTTP {exc.code}: {exc.reason}", transient=exc.code == 429 or 500 <= exc.code < 600, status=exc.code, retry_after_at=retry_at) from exc
            except URLError as exc:
                raise ConnectorFetchError(f"network error: {exc.reason}", transient=True) from exc
            if len(body) > int(source["max_payload_bytes"]):
                raise ConnectorFetchError("connector payload exceeds max_payload_bytes")
            modified = response_headers.get("Last-Modified")
            modified_iso = _iso(_parse_time(modified)) if _parse_time(modified) else None
            return FetchedPayload(body, response_headers.get("Content-Type", content_type).split(";",1)[0], uri, status, response_headers, modified_iso, int((time.monotonic()-started)*1000))
        raise ConnectorFetchError(f"unsupported connector type: {connector_type}")

    @staticmethod
    def _parse_rows(fetched: FetchedPayload, definition: Mapping[str, Any]) -> list[dict[str, Any]]:
        connector_type = definition["connector_type"]
        is_csv = connector_type.endswith("csv") or "csv" in fetched.content_type
        text = fetched.body.decode("utf-8-sig")
        if is_csv:
            return [dict(row) for row in csv.DictReader(io.StringIO(text))]
        value = json.loads(text)
        selected = get_path(value, definition["source"].get("records_path"), value)
        if isinstance(selected, Mapping):
            if isinstance(selected.get("records"), list):
                selected = selected["records"]
            else:
                selected = [selected]
        if not isinstance(selected, list):
            raise ConnectorFetchError("configured JSON records path does not contain an array or object")
        result=[]
        for row in selected:
            if not isinstance(row, Mapping):
                raise ConnectorFetchError("connector rows must be JSON objects")
            result.append(dict(row))
        return result

    def _source_key(self, row: Mapping[str, Any], definition: Mapping[str, Any], index: int) -> str:
        path = definition["source"].get("source_key_path")
        value = get_path(row, path) if path else row.get("record_id") or row.get("id")
        if value in (None, ""):
            value = f"row-{index}-{_digest(row)[:12]}"
        return str(value)

    def _store_payload(self, run_row_id: int, run_id: str, fetched: FetchedPayload) -> int:
        digest = hashlib.sha256(fetched.body).hexdigest()
        with connect(self.repository.path) as connection, transaction(connection):
            cursor = connection.execute(
                """INSERT INTO connector_payload_snapshots(payload_id,run_id,content_type,payload_blob,payload_sha256,payload_bytes,source_uri,captured_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_identifier("connector-payload", run_id), run_row_id, fetched.content_type, fetched.body, digest, len(fetched.body), fetched.source_uri, _iso()),
            )
            return int(cursor.lastrowid)

    def _assign_workspace(self, connection, record_id: str, definition_row) -> None:
        connection.execute(
            """UPDATE record_access_governance SET workspace_id=?,owner_principal_id=?,steward_principal_id=?,custodian_principal_id=?,
               visibility='private',classification='internal',updated_at=? WHERE record_id=?""",
            (definition_row["workspace_id_row"], definition_row["principal_id_row"], definition_row["principal_id_row"], definition_row["principal_id_row"], _iso(), record_id),
        )

    def _finish_failed(self, run_row_id: int, connector_row_id: int, error: Exception, *, retry_after_at: str | None, response_status: int | None = None, dead_letter: bool = False, payload_snapshot_id: int | None = None) -> None:
        status = "dead-letter" if dead_letter else "failed"
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute(
                """UPDATE connector_runs SET status=?,finished_at=?,response_status=?,retry_after_at=?,error_class=?,error_message=?,reconciliation_status='failed' WHERE id=?""",
                (status, _iso(), response_status, retry_after_at, type(error).__name__, str(error), run_row_id),
            )
            self._log(connection, run_row_id, "error", "run-failed", str(error), {"retry_after_at": retry_after_at, "dead_letter": dead_letter})
            self._alert(connection, connector_row_id, run_row_id, "dead-letter" if dead_letter else "fetch-failure", "critical" if dead_letter else "warning", str(error), {"retry_after_at": retry_after_at})
            connection.execute(
                """UPDATE connector_state SET health_status='unhealthy',consecutive_failures=consecutive_failures+1,last_attempt_at=?,last_run_id=?,next_allowed_at=COALESCE(?,next_allowed_at),updated_at=? WHERE connector_id=?""",
                (_iso(), connection.execute("SELECT run_id FROM connector_runs WHERE id=?", (run_row_id,)).fetchone()[0], retry_after_at, _iso(), connector_row_id),
            )
            if dead_letter:
                connection.execute(
                    "INSERT INTO connector_dead_letters(dead_letter_id,connector_id,run_id,payload_snapshot_id,reason) VALUES (?,?,?,?,?)",
                    (_identifier("connector-dead-letter", str(run_row_id)), connector_row_id, run_row_id, payload_snapshot_id, str(error)),
                )

    def run(
        self,
        connector_id: str,
        *,
        trigger_type: str = "manual",
        payload: bytes | str | Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        source_uri: str | None = None,
        max_attempts: int | None = None,
        _parent_run_row_id: int | None = None,
        _rows_override: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if trigger_type not in ("manual", "scheduled", "retry", "replay", "recovery"):
            raise ConnectorError("invalid trigger type")
        with connect(self.repository.path, readonly=True) as connection:
            raw_definition = self._definition_row(connection, connector_id)
            raw_version = self._active_version_row(connection, raw_definition["id"])
            definition = self._definition_payload(raw_definition, raw_version)
            definition_row = dict(raw_definition)
            definition_row["workspace_id_row"] = int(raw_definition["workspace_id"])
            definition_row["principal_id_row"] = int(raw_definition["principal_id"])
        if definition["status"] != "active":
            raise ConnectorError(f"connector is not active: {definition['status']}")
        try:
            self._assert_rate_limit(raw_definition)
        except ConnectorRateLimited as exc:
            run_row_id, _ = self._create_run(int(raw_definition["id"]), int(raw_version["id"]), trigger_type, 1, source_uri or definition["source"].get("uri"), _parent_run_row_id)
            self._finish_failed(run_row_id, int(raw_definition["id"]), exc, retry_after_at=exc.retry_after_at)
            with connect(self.repository.path) as connection, transaction(connection):
                self._alert(connection, int(raw_definition["id"]), run_row_id, "rate-limit", "warning", str(exc), {"retry_after_at": exc.retry_after_at})
            return self.run_details_by_row(run_row_id)

        payload_bytes: bytes | None
        if payload is None:
            payload_bytes = None
        elif isinstance(payload, bytes):
            payload_bytes = payload
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        attempts = int(max_attempts or definition["governance"]["max_attempts"])
        parent = _parent_run_row_id
        last_result: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            run_trigger = trigger_type if attempt == 1 else "retry"
            run_row_id, run_id = self._create_run(int(raw_definition["id"]), int(raw_version["id"]), run_trigger, attempt, source_uri or definition["source"].get("uri"), parent)
            parent = run_row_id
            payload_snapshot_id: int | None = None
            try:
                fetched = self._fetch(definition, payload_override=payload_bytes, source_uri_override=source_uri)
                payload_snapshot_id = self._store_payload(run_row_id, run_id, fetched)
                rows = _rows_override if _rows_override is not None else self._parse_rows(fetched, definition)
                last_result = self._process_rows(run_row_id, run_id, definition_row, raw_version, definition, fetched, rows)
                return last_result
            except (ConnectorFetchError, ConnectorValidationError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                transient = isinstance(exc, ConnectorFetchError) and exc.transient
                retry_after = exc.retry_after_at if isinstance(exc, ConnectorFetchError) else None
                status = exc.status if isinstance(exc, ConnectorFetchError) else None
                should_retry = transient and attempt < attempts
                if should_retry and not retry_after:
                    retry_after = _iso(_now_dt() + timedelta(seconds=int(definition["governance"]["retry_backoff_seconds"]) * attempt))
                self._finish_failed(run_row_id, int(raw_definition["id"]), exc, retry_after_at=retry_after, response_status=status, dead_letter=not should_retry, payload_snapshot_id=payload_snapshot_id)
                last_result = self.run_details_by_row(run_row_id)
                if not should_retry:
                    return last_result
        return last_result or {}

    def _process_rows(self, run_row_id: int, run_id: str, definition_row: Mapping[str, Any], version_row, definition: Mapping[str, Any], fetched: FetchedPayload, rows: list[dict[str, Any]]) -> dict[str, Any]:
        connector_row_id = int(definition_row["id"])
        occurred_at = _iso()
        payload_digest = hashlib.sha256(fetched.body).hexdigest()
        fingerprint = schema_fingerprint(rows)
        with connect(self.repository.path, readonly=True) as connection:
            state = connection.execute("SELECT * FROM connector_state WHERE connector_id=?", (connector_row_id,)).fetchone()
            previous_rows = connection.execute("SELECT source_key,source_payload_sha256,record_id FROM connector_record_state WHERE connector_id=? AND active=1", (connector_row_id,)).fetchall()
            previous = {row["source_key"]: {"sha": row["source_payload_sha256"], "record_id": row["record_id"]} for row in previous_rows}
            previous_run = connection.execute("SELECT id,run_id FROM connector_runs WHERE connector_id=? AND status IN ('succeeded','partial') AND id<>? ORDER BY id DESC LIMIT 1", (connector_row_id, run_row_id)).fetchone()
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        prepared: list[dict[str, Any]] = []
        failed_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            source_key = self._source_key(row, definition, index)
            row_json = canonical_json(row)
            row_digest = hashlib.sha256(row_json.encode("utf-8")).hexdigest()
            if source_key in seen:
                duplicates.append(source_key)
                failed_rows.append({"row_number": index, "source_key": source_key, "digest": row_digest, "row": row, "error": "duplicate source key in connector payload"})
                continue
            seen[source_key] = row_digest
            if source_key in previous and previous[source_key]["sha"] == row_digest:
                prepared.append({"row_number": index, "source_key": source_key, "digest": row_digest, "row": row, "record": None, "record_id": previous[source_key]["record_id"], "action": "skipped"})
                continue
            try:
                authoring = map_source_row(row, definition, run_id=run_id, source_key=source_key, row_digest=row_digest, occurred_at=occurred_at)
                record = build_record(authoring, now=_now_dt(), producer_component="connector-service")
                prepared.append({"row_number": index, "source_key": source_key, "digest": row_digest, "row": row, "record": record, "record_id": record["record_id"], "action": None})
            except Exception as exc:
                failed_rows.append({"row_number": index, "source_key": source_key, "digest": row_digest, "row": row, "error": str(exc)})

        atomic = bool(definition["transformations"].get("atomic", False))
        if atomic and failed_rows:
            for item in prepared:
                if item["action"] != "skipped":
                    item["action"] = "not-applied"
        else:
            data_connection = connect(self.repository.path)
            try:
                if atomic:
                    data_connection.execute("BEGIN IMMEDIATE")
                for item in prepared:
                    if item["action"] == "skipped":
                        continue
                    try:
                        if not atomic:
                            data_connection.execute("BEGIN IMMEDIATE")
                        action = self.repository.upsert_record(item["record"], connection=data_connection)
                        self._assign_workspace(data_connection, item["record_id"], definition_row)
                        item["action"] = action
                        if not atomic:
                            data_connection.commit()
                    except Exception as exc:
                        if data_connection.in_transaction:
                            data_connection.rollback()
                        item["action"] = "quarantined"
                        failed_rows.append({"row_number": item["row_number"], "source_key": item["source_key"], "digest": item["digest"], "row": item["row"], "error": str(exc)})
                if atomic and data_connection.in_transaction:
                    data_connection.commit()
            finally:
                data_connection.close()

        actual_keys = set(seen)
        previous_keys = set(previous)
        missing_keys = sorted(previous_keys - actual_keys)
        unexpected_keys = sorted(actual_keys - previous_keys) if previous else []
        matched = sorted(key for key in actual_keys & previous_keys if seen[key] == previous[key]["sha"])
        changed = sorted(key for key in actual_keys & previous_keys if seen[key] != previous[key]["sha"])
        freshness_seconds = None
        source_modified_at = fetched.source_modified_at
        modified_path = definition["source"].get("modified_at_path")
        if modified_path:
            row_times = [_parse_time(str(get_path(row, modified_path) or "")) for row in rows]
            row_times = [value for value in row_times if value is not None]
            if row_times:
                source_modified_at = _iso(max(row_times))
        modified = _parse_time(source_modified_at)
        if modified:
            freshness_seconds = max(0, int((_now_dt() - modified).total_seconds()))
        freshness_sla = definition["governance"].get("freshness_sla_seconds")
        freshness_status = "unknown" if freshness_seconds is None else ("stale" if freshness_sla is not None and freshness_seconds > int(freshness_sla) else "current")
        license_status = "restricted" if definition["governance"].get("license_status") == "restricted" else ("compliant" if definition["governance"].get("license") else "missing")
        schema_changed = bool(state and state["last_schema_fingerprint"] and fingerprint and state["last_schema_fingerprint"] != fingerprint)
        missing_ratio = len(missing_keys) / len(previous_keys) if previous_keys else 0.0
        drift_changed = schema_changed or missing_ratio > float(definition["governance"].get("drift_missing_ratio") or 0.25)
        drift_status = "changed" if drift_changed else ("stable" if fingerprint else "unknown")
        inserted = sum(item["action"] == "inserted" for item in prepared)
        updated = sum(item["action"] == "updated" for item in prepared)
        skipped = sum(item["action"] == "skipped" for item in prepared)
        quarantined = len(failed_rows)
        not_applied = sum(item["action"] == "not-applied" for item in prepared)
        if atomic and failed_rows:
            status = "failed"
        elif quarantined and inserted + updated + skipped:
            status = "partial"
        elif quarantined:
            status = "quarantined"
        else:
            status = "succeeded"
        reconciliation_status = "balanced" if not (missing_keys or unexpected_keys or duplicates or failed_rows or not_applied) else ("failed" if status == "failed" else "warning")
        summary = {
            "previous_run_id": previous_run["run_id"] if previous_run else None,
            "expected_count": len(previous_keys), "actual_count": len(actual_keys), "matched_count": len(matched), "changed_count": len(changed),
            "missing_count": len(missing_keys), "unexpected_count": len(unexpected_keys), "duplicate_count": len(set(duplicates)),
            "missing_keys": missing_keys, "unexpected_keys": unexpected_keys, "duplicate_keys": sorted(set(duplicates)), "status": reconciliation_status,
        }
        summary_sha = hashlib.sha256(canonical_json(summary).encode("utf-8")).hexdigest()
        with connect(self.repository.path) as connection, transaction(connection):
            for item in prepared:
                if item["action"] == "quarantined":
                    continue
                transformed = canonical_json(item["record"]) if item.get("record") else None
                connection.execute(
                    """INSERT INTO connector_run_records(run_id,row_number,source_key,source_payload_sha256,source_payload_json,transformed_payload_json,record_id,action,error_message)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (run_row_id, item["row_number"], item["source_key"], item["digest"], canonical_json(item["row"]), transformed, None if item["action"] == "not-applied" else item.get("record_id"), item["action"], None),
                )
                if item["action"] in ("inserted", "updated", "skipped"):
                    existing_state = connection.execute("SELECT first_seen_run_id,first_seen_at FROM connector_record_state WHERE connector_id=? AND source_key=?", (connector_row_id,item["source_key"])).fetchone()
                    first_run = existing_state["first_seen_run_id"] if existing_state else run_row_id
                    first_at = existing_state["first_seen_at"] if existing_state else occurred_at
                    connection.execute(
                        """INSERT INTO connector_record_state(connector_id,source_key,source_payload_sha256,record_id,first_seen_run_id,last_seen_run_id,first_seen_at,last_seen_at,active)
                           VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(connector_id,source_key) DO UPDATE SET source_payload_sha256=excluded.source_payload_sha256,
                           record_id=excluded.record_id,last_seen_run_id=excluded.last_seen_run_id,last_seen_at=excluded.last_seen_at,active=1""",
                        (connector_row_id,item["source_key"],item["digest"],item.get("record_id"),first_run,run_row_id,first_at,occurred_at),
                    )
            for item in failed_rows:
                connection.execute(
                    """INSERT INTO connector_run_records(run_id,row_number,source_key,source_payload_sha256,source_payload_json,record_id,action,error_message)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (run_row_id,item["row_number"],item["source_key"],item["digest"],canonical_json(item["row"]),None,"quarantined",item["error"]),
                )
                connection.execute(
                    "INSERT INTO connector_quarantine(quarantine_id,run_id,row_number,source_key,reason,raw_payload_json) VALUES (?,?,?,?,?,?)",
                    (_identifier("connector-quarantine", run_id, item["source_key"]),run_row_id,item["row_number"],item["source_key"],item["error"],canonical_json(item["row"])),
                )
            if missing_keys:
                placeholders = ",".join("?" for _ in missing_keys)
                connection.execute(f"UPDATE connector_record_state SET active=0,last_seen_at=? WHERE connector_id=? AND source_key IN ({placeholders})", [occurred_at,connector_row_id,*missing_keys])
            connection.execute(
                """INSERT INTO connector_reconciliations(reconciliation_id,run_id,previous_run_id,expected_count,actual_count,matched_count,changed_count,missing_count,unexpected_count,duplicate_count,
                   missing_keys_json,unexpected_keys_json,duplicate_keys_json,status,summary_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_identifier("connector-reconciliation",run_id),run_row_id,previous_run["id"] if previous_run else None,len(previous_keys),len(actual_keys),len(matched),len(changed),len(missing_keys),len(unexpected_keys),len(set(duplicates)),json.dumps(missing_keys),json.dumps(unexpected_keys),json.dumps(sorted(set(duplicates))),reconciliation_status,summary_sha),
            )
            next_allowed = None
            rate = definition["governance"].get("rate_limit_per_hour")
            if rate:
                next_allowed = _iso(_now_dt() + timedelta(seconds=max(1, int(3600/int(rate)))))
            health = "healthy" if status == "succeeded" and freshness_status != "stale" and drift_status != "changed" and license_status == "compliant" else ("unhealthy" if status in ("failed","quarantined") else "degraded")
            connection.execute(
                """UPDATE connector_runs SET status=?,finished_at=?,latency_ms=?,response_status=?,response_headers_json=?,source_modified_at=?,freshness_seconds=?,payload_bytes=?,payload_sha256=?,row_count=?,
                   inserted_count=?,updated_count=?,skipped_count=?,failed_count=?,quarantined_count=?,license_status=?,freshness_status=?,drift_status=?,reconciliation_status=? WHERE id=?""",
                (status,_iso(),fetched.latency_ms,fetched.response_status,canonical_json(fetched.response_headers),source_modified_at,freshness_seconds,len(fetched.body),payload_digest,len(rows),inserted,updated,skipped,not_applied,quarantined,license_status,freshness_status,drift_status,reconciliation_status,run_row_id),
            )
            connection.execute(
                """UPDATE connector_state SET health_status=?,consecutive_failures=?,last_attempt_at=?,last_success_at=CASE WHEN ? IN ('succeeded','partial') THEN ? ELSE last_success_at END,
                   last_run_id=?,last_payload_sha256=?,last_schema_fingerprint=?,last_source_modified_at=?,next_allowed_at=?,updated_at=? WHERE connector_id=?""",
                (health,0 if status in ("succeeded","partial") else (int(state["consecutive_failures"]) + 1 if state else 1),occurred_at,status,occurred_at,run_id,payload_digest,fingerprint,source_modified_at,next_allowed,occurred_at,connector_row_id),
            )
            schedule = connection.execute("SELECT frequency_minutes FROM connector_schedules WHERE connector_id=?",(connector_row_id,)).fetchone()
            if schedule:
                connection.execute("UPDATE connector_schedules SET last_run_at=?,next_run_at=?,updated_at=? WHERE connector_id=?",(occurred_at,_iso(_now_dt()+timedelta(minutes=int(schedule["frequency_minutes"]))),occurred_at,connector_row_id))
            self._log(connection,run_row_id,"info","run-completed",f"Connector run completed with status {status}.",{"inserted":inserted,"updated":updated,"skipped":skipped,"quarantined":quarantined,"reconciliation":summary})
            if freshness_status == "stale": self._alert(connection,connector_row_id,run_row_id,"freshness","warning","Connector source is older than its freshness SLA.",{"freshness_seconds":freshness_seconds,"sla_seconds":freshness_sla})
            if license_status == "missing": self._alert(connection,connector_row_id,run_row_id,"license","warning","Connector source has no governed license record.")
            if license_status == "restricted": self._alert(connection,connector_row_id,run_row_id,"license","critical","Connector license is marked restricted.")
            if schema_changed: self._alert(connection,connector_row_id,run_row_id,"schema-drift","critical","Connector source schema changed.",{"previous":state["last_schema_fingerprint"] if state else None,"current":fingerprint})
            if missing_keys or unexpected_keys: self._alert(connection,connector_row_id,run_row_id,"record-drift","warning","Connector record population changed.",{"missing_keys":missing_keys,"unexpected_keys":unexpected_keys})
            if failed_rows: self._alert(connection,connector_row_id,run_row_id,"quarantine","warning",f"{len(failed_rows)} connector row(s) were quarantined.")
            if reconciliation_status != "balanced": self._alert(connection,connector_row_id,run_row_id,"reconciliation","warning" if status != "failed" else "critical","Connector reconciliation requires attention.",summary)
        return self.run_details_by_row(run_row_id)

    def runs(self, *, connector_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql="SELECT * FROM connector_run_summary"; clauses=[]; params=[]
        if connector_id: clauses.append("connector_id=?"); params.append(connector_id)
        if status: clauses.append("status=?"); params.append(status)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC,run_id DESC LIMIT ?"; params.append(limit)
        with connect(self.repository.path,readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params)]

    def run_details_by_row(self, run_row_id: int) -> dict[str, Any]:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("SELECT * FROM connector_run_summary WHERE run_id=(SELECT run_id FROM connector_runs WHERE id=?)",(run_row_id,)).fetchone()
            if not row: raise ConnectorError("connector run not found")
            run_id=row["run_id"]
            records=[]
            for item in connection.execute("SELECT row_number,source_key,source_payload_sha256,record_id,action,error_message FROM connector_run_records WHERE run_id=? ORDER BY row_number,id",(run_row_id,)):
                records.append(dict(item))
            logs=[]
            for item in connection.execute("SELECT level,event_type,message,details_json,occurred_at FROM connector_run_logs WHERE run_id=? ORDER BY id",(run_row_id,)):
                value=dict(item); value["details"]=json.loads(value.pop("details_json")); logs.append(value)
            reconciliation=connection.execute("SELECT * FROM connector_reconciliations WHERE run_id=?",(run_row_id,)).fetchone()
            rec=None
            if reconciliation:
                rec=dict(reconciliation)
                for key in ("missing_keys_json","unexpected_keys_json","duplicate_keys_json"): rec[key[:-5]]=json.loads(rec.pop(key))
            return {"run":dict(row),"records":records,"logs":logs,"reconciliation":rec}

    def run_details(self, run_id: str) -> dict[str, Any]:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("SELECT id FROM connector_runs WHERE run_id=?",(run_id,)).fetchone()
            if not row: raise ConnectorError(f"connector run not found: {run_id}")
            return self.run_details_by_row(int(row["id"]))

    def replay(self, run_id: str) -> dict[str, Any]:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("""SELECT cr.id,cd.connector_id,cps.payload_blob,cps.source_uri FROM connector_runs cr JOIN connector_definitions cd ON cd.id=cr.connector_id
                                      JOIN connector_payload_snapshots cps ON cps.run_id=cr.id WHERE cr.run_id=?""",(run_id,)).fetchone()
            if not row: raise ConnectorError("run has no payload snapshot")
            payload=bytes(row["payload_blob"]); connector_id=row["connector_id"]; parent=int(row["id"]); source_uri=row["source_uri"]
        return self.run(connector_id,trigger_type="replay",payload=payload,source_uri=source_uri,max_attempts=1,_parent_run_row_id=parent)

    def recover_quarantine(self, quarantine_id: str) -> dict[str, Any]:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("""SELECT cq.id,cq.status,cq.raw_payload_json,cr.id AS original_run_row_id,cd.connector_id
                                      FROM connector_quarantine cq JOIN connector_runs cr ON cr.id=cq.run_id JOIN connector_definitions cd ON cd.id=cr.connector_id
                                      WHERE cq.quarantine_id=?""",(quarantine_id,)).fetchone()
            if not row: raise ConnectorError("quarantine item not found")
            if row["status"] not in ("open","released"): raise ConnectorError("quarantine item is already resolved")
            raw=json.loads(row["raw_payload_json"]); connector_id=row["connector_id"]
        result=self.run(connector_id,trigger_type="recovery",payload={"records":[raw]},source_uri=f"quarantine://{quarantine_id}",max_attempts=1,_parent_run_row_id=int(row["original_run_row_id"]),_rows_override=[raw])
        run_status=result["run"]["status"]
        if run_status in ("succeeded","partial"):
            with connect(self.repository.path) as connection,transaction(connection):
                recovered=connection.execute("SELECT id FROM connector_runs WHERE run_id=?",(result["run"]["run_id"],)).fetchone()
                connection.execute("UPDATE connector_quarantine SET status='resolved',recovered_run_id=?,resolved_at=? WHERE id=?",(recovered["id"],_iso(),row["id"]))
        return result

    def replay_dead_letter(self, dead_letter_id: str) -> dict[str, Any]:
        with connect(self.repository.path,readonly=True) as connection:
            row=connection.execute("""SELECT dl.id,dl.status,cr.run_id,cd.connector_id,cps.payload_blob,cps.source_uri
                                      FROM connector_dead_letters dl JOIN connector_runs cr ON cr.id=dl.run_id JOIN connector_definitions cd ON cd.id=dl.connector_id
                                      LEFT JOIN connector_payload_snapshots cps ON cps.id=dl.payload_snapshot_id WHERE dl.dead_letter_id=?""",(dead_letter_id,)).fetchone()
            if not row: raise ConnectorError("dead letter not found")
            payload=bytes(row["payload_blob"]) if row["payload_blob"] is not None else None
        result=self.run(row["connector_id"],trigger_type="replay",payload=payload,source_uri=row["source_uri"],max_attempts=1)
        if result["run"]["status"] in ("succeeded","partial"):
            with connect(self.repository.path) as connection,transaction(connection):
                replay=connection.execute("SELECT id FROM connector_runs WHERE run_id=?",(result["run"]["run_id"],)).fetchone()
                connection.execute("UPDATE connector_dead_letters SET status='replayed',replay_run_id=?,resolved_at=? WHERE id=?",(replay["id"],_iso(),row["id"]))
        return result

    def quarantine(self, *, connector_id: str | None = None, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        sql="""SELECT cq.quarantine_id,cd.connector_id,cr.run_id,cq.row_number,cq.source_key,cq.reason,cq.status,cq.resolution_notes,cq.created_at,cq.resolved_at
               FROM connector_quarantine cq JOIN connector_runs cr ON cr.id=cq.run_id JOIN connector_definitions cd ON cd.id=cr.connector_id WHERE cq.status=?"""
        params=[status]
        if connector_id: sql += " AND cd.connector_id=?"; params.append(connector_id)
        sql += " ORDER BY cq.created_at DESC,cq.id DESC LIMIT ?"; params.append(limit)
        with connect(self.repository.path,readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params)]

    def dead_letters(self, *, connector_id: str | None = None, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        sql="""SELECT dl.dead_letter_id,cd.connector_id,cr.run_id,dl.reason,dl.status,dl.created_at,dl.resolved_at
               FROM connector_dead_letters dl JOIN connector_definitions cd ON cd.id=dl.connector_id JOIN connector_runs cr ON cr.id=dl.run_id WHERE dl.status=?"""
        params=[status]
        if connector_id: sql += " AND cd.connector_id=?"; params.append(connector_id)
        sql += " ORDER BY dl.created_at DESC,dl.id DESC LIMIT ?"; params.append(limit)
        with connect(self.repository.path,readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params)]

    def alerts(self, *, connector_id: str | None = None, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        sql="""SELECT ca.alert_id,cd.connector_id,cr.run_id,ca.alert_type,ca.severity,ca.status,ca.message,ca.details_json,ca.created_at,ca.acknowledged_at,ca.resolved_at
               FROM connector_alerts ca JOIN connector_definitions cd ON cd.id=ca.connector_id LEFT JOIN connector_runs cr ON cr.id=ca.run_id WHERE ca.status=?"""
        params=[status]
        if connector_id: sql += " AND cd.connector_id=?"; params.append(connector_id)
        sql += " ORDER BY CASE ca.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,ca.created_at DESC LIMIT ?"; params.append(limit)
        result=[]
        with connect(self.repository.path,readonly=True) as connection:
            for row in connection.execute(sql,params):
                item=dict(row); item["details"]=json.loads(item.pop("details_json")); result.append(item)
        return result

    def set_alert_status(self, alert_id: str, status: str) -> dict[str, Any]:
        if status not in ("acknowledged","resolved"):
            raise ConnectorError("alert status must be acknowledged or resolved")
        with connect(self.repository.path) as connection,transaction(connection):
            row=connection.execute("SELECT id FROM connector_alerts WHERE alert_id=?",(alert_id,)).fetchone()
            if not row: raise ConnectorError("alert not found")
            if status=="acknowledged": connection.execute("UPDATE connector_alerts SET status='acknowledged',acknowledged_at=? WHERE id=?",(_iso(),row["id"]))
            else: connection.execute("UPDATE connector_alerts SET status='resolved',resolved_at=? WHERE id=?",(_iso(),row["id"]))
        return next(item for item in self.alerts(status=status,limit=1000) if item["alert_id"]==alert_id)

    def run_due(self, *, as_of: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        return [self.run(item["connector_id"],trigger_type="scheduled") for item in self.due(as_of=as_of,workspace_id=workspace_id)]
