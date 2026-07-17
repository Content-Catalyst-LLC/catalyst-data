from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from ._version import __version__
from .database import connect, transaction
from .migrations import discover_migrations
from .operations import OperationalService
from .repository import CatalystRepository, canonical_json

PLATFORM_SCHEMA_VERSION = "catalyst-data-platform/2.0"
COMPONENT_TYPES = {"core", "platform-product", "connector", "external"}
COMPONENT_STATUSES = {"active", "degraded", "offline", "disabled", "unconfigured"}
LINK_RELATIONSHIPS = {"handoff", "data-source", "analysis", "publication", "embed", "api", "federation"}
LINK_STATUSES = {"active", "degraded", "disabled"}
KNOWN_PLATFORM_PRODUCTS = (
    "knowledge-library",
    "research-librarian",
    "site-intelligence",
    "workbench",
    "research-lab",
    "catalyst-analytics-r",
    "catalyst-canvas",
    "decision-studio",
    "platform-core",
)


class PlatformError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:24]}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key in tuple(payload):
        if key.endswith("_json") and payload[key] is not None:
            payload[key[:-5]] = json.loads(payload.pop(key))
    return payload


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise PlatformError("capabilities and contracts must be arrays")
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _component_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "component_id": payload["component_id"],
        "name": payload["name"],
        "product_code": payload["product_code"],
        "component_type": payload["component_type"],
        "version": payload.get("version"),
        "endpoint": payload.get("endpoint"),
        "capabilities": _clean_list(payload.get("capabilities")),
        "contracts": _clean_list(payload.get("contracts")),
        "metadata": dict(payload.get("metadata") or {}),
    }


def platform_schema() -> dict[str, Any]:
    path = files("catalyst_data").joinpath("schemas/catalyst_data_platform_2_0.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


class PlatformService:
    def __init__(self, repository: CatalystRepository):
        self.repository = repository

    def register_component(
        self,
        definition: Mapping[str, Any],
        *,
        actor: str = "principal:system",
        status: str = "active",
    ) -> dict[str, Any]:
        self.repository.initialize()
        manifest = _component_manifest(definition)
        component_id = str(manifest["component_id"]).strip()
        name = str(manifest["name"]).strip()
        product_code = str(manifest["product_code"]).strip()
        component_type = str(manifest["component_type"]).strip()
        version = str(manifest.get("version") or "").strip() or None
        if not component_id or not name or not product_code:
            raise PlatformError("component_id, name, and product_code are required")
        if component_type not in COMPONENT_TYPES:
            raise PlatformError(f"unsupported component_type: {component_type}")
        if status not in COMPONENT_STATUSES:
            raise PlatformError(f"unsupported component status: {status}")
        digest = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
        now = _now()
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            existing = connection.execute(
                "SELECT * FROM platform_components WHERE component_id=?", (component_id,)
            ).fetchone()
            values = (
                name,
                product_code,
                component_type,
                status,
                version,
                manifest.get("endpoint"),
                definition.get("workspace_id"),
                _json(manifest["capabilities"]),
                _json(manifest["contracts"]),
                _json(manifest["metadata"]),
                actor,
                now,
            )
            if existing:
                connection.execute(
                    """UPDATE platform_components SET
                       name=?,product_code=?,component_type=?,status=?,current_version=?,endpoint=?,workspace_id=?,
                       capabilities_json=?,contracts_json=?,metadata_json=?,registered_by=?,updated_at=?
                       WHERE component_id=?""",
                    values + (component_id,),
                )
                action = "updated"
            else:
                connection.execute(
                    """INSERT INTO platform_components(
                       name,product_code,component_type,status,current_version,endpoint,workspace_id,
                       capabilities_json,contracts_json,metadata_json,registered_by,updated_at,component_id
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values + (component_id,),
                )
                action = "inserted"
            if version:
                version_id = f"component-version:{product_code}:{version}:{digest[:12]}"
                connection.execute(
                    """INSERT OR IGNORE INTO platform_component_versions(
                       component_version_id,component_id,version,manifest_sha256,capabilities_json,
                       contracts_json,metadata_json,registered_by,registered_at
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        version_id,
                        component_id,
                        version,
                        digest,
                        _json(manifest["capabilities"]),
                        _json(manifest["contracts"]),
                        _json(manifest["metadata"]),
                        actor,
                        now,
                    ),
                )
            connection.execute(
                "INSERT INTO platform_events(event_id,event_type,component_id,actor,details_json,occurred_at) VALUES (?,?,?,?,?,?)",
                (_id("platform-event"), "component_registered", component_id, actor, _json({"action": action, "manifest_sha256": digest}), now),
            )
        return {"schema_version": PLATFORM_SCHEMA_VERSION, "action": action, "manifest_sha256": digest, **manifest, "status": status}

    def components(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.repository.initialize()
        sql = "SELECT * FROM platform_component_status"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"; params.append(status)
        sql += " ORDER BY component_type,name LIMIT ?"; params.append(limit)
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(sql, params).fetchall()]

    def component_versions(self, component_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(
                "SELECT * FROM platform_component_versions WHERE component_id=? ORDER BY id DESC LIMIT ?",
                (component_id, limit),
            ).fetchall()]

    def register_contract(
        self,
        contract_id: str,
        schema_path: str | Path,
        *,
        schema_uri: str | None = None,
        contract_version: str = "1.0",
        actor: str = "principal:system",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.repository.initialize()
        path = Path(schema_path)
        if not path.is_file():
            raise PlatformError(f"schema not found: {path}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        registration_id = f"contract-registration:{hashlib.sha256((contract_id + '|' + digest).encode()).hexdigest()[:24]}"
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            connection.execute(
                """INSERT OR IGNORE INTO platform_contracts(
                   contract_registration_id,contract_id,contract_version,schema_uri,schema_path,
                   schema_sha256,status,metadata_json,registered_by,registered_at
                   ) VALUES (?,?,?,?,?,?,'active',?,?,?)""",
                (
                    registration_id,
                    contract_id,
                    contract_version,
                    schema_uri,
                    str(path),
                    digest,
                    _json(dict(metadata or {})),
                    actor,
                    _now(),
                ),
            )
        return {
            "schema_version": PLATFORM_SCHEMA_VERSION,
            "contract_registration_id": registration_id,
            "contract_id": contract_id,
            "contract_version": contract_version,
            "schema_uri": schema_uri,
            "schema_path": str(path),
            "schema_sha256": digest,
            "status": "active",
        }

    def sync_builtin_contracts(self, *, actor: str = "principal:system") -> list[dict[str, Any]]:
        root = files("catalyst_data").joinpath("schemas")
        results: list[dict[str, Any]] = []
        for item in sorted(root.iterdir(), key=lambda value: value.name):
            if not item.name.endswith(".schema.json"):
                continue
            payload = json.loads(item.read_text(encoding="utf-8"))
            properties = payload.get("properties", {}) if isinstance(payload, dict) else {}
            contract_id = properties.get("schema_version", {}).get("const")
            if not contract_id:
                continue
            with item.open("rb") as source:
                raw = source.read()
            digest = hashlib.sha256(raw).hexdigest()
            registration_id = f"contract-registration:{hashlib.sha256((contract_id + '|' + digest).encode()).hexdigest()[:24]}"
            with closing(connect(self.repository.path)) as connection, transaction(connection):
                connection.execute(
                    """INSERT OR IGNORE INTO platform_contracts(
                       contract_registration_id,contract_id,contract_version,schema_uri,schema_path,
                       schema_sha256,status,metadata_json,registered_by,registered_at
                       ) VALUES (?,?,?,?,?,?,'active','{}',?,?)""",
                    (
                        registration_id,
                        contract_id,
                        contract_id.rsplit("/", 1)[-1],
                        payload.get("$id"),
                        f"package:schemas/{item.name}",
                        digest,
                        actor,
                        _now(),
                    ),
                )
            results.append({"contract_id": contract_id, "schema_sha256": digest, "registration_id": registration_id})
        return results

    def contracts(self, *, contract_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.repository.initialize()
        sql = "SELECT * FROM platform_contracts"; params: list[Any] = []
        if contract_id:
            sql += " WHERE contract_id=?"; params.append(contract_id)
        sql += " ORDER BY contract_id,id DESC LIMIT ?"; params.append(limit)
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(sql, params).fetchall()]

    def link(
        self,
        source_component_id: str,
        target_component_id: str,
        relationship: str,
        capability: str,
        *,
        contract_id: str | None = None,
        actor: str = "principal:system",
        status: str = "active",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.repository.initialize()
        if relationship not in LINK_RELATIONSHIPS:
            raise PlatformError(f"unsupported platform relationship: {relationship}")
        if status not in LINK_STATUSES:
            raise PlatformError(f"unsupported platform link status: {status}")
        link_key = f"{source_component_id}|{target_component_id}|{relationship}|{capability}"
        link_id = "platform-link:" + hashlib.sha256(link_key.encode()).hexdigest()[:24]
        now = _now()
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            missing = [item for item in (source_component_id, target_component_id) if connection.execute(
                "SELECT 1 FROM platform_components WHERE component_id=?", (item,)
            ).fetchone() is None]
            if missing:
                raise PlatformError(f"unknown platform component: {', '.join(missing)}")
            connection.execute(
                """INSERT INTO platform_links(
                   link_id,source_component_id,target_component_id,relationship,capability,contract_id,status,
                   metadata_json,created_by,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_component_id,target_component_id,relationship,capability)
                   DO UPDATE SET contract_id=excluded.contract_id,status=excluded.status,metadata_json=excluded.metadata_json""",
                (link_id, source_component_id, target_component_id, relationship, capability, contract_id, status, _json(dict(metadata or {})), actor, now),
            )
            connection.execute(
                "INSERT INTO platform_events(event_id,event_type,link_id,actor,details_json,occurred_at) VALUES (?,?,?,?,?,?)",
                (_id("platform-event"), "component_linked", link_id, actor, _json({"source": source_component_id, "target": target_component_id, "relationship": relationship, "capability": capability}), now),
            )
        return {"schema_version": PLATFORM_SCHEMA_VERSION, "link_id": link_id, "source_component_id": source_component_id, "target_component_id": target_component_id, "relationship": relationship, "capability": capability, "contract_id": contract_id, "status": status}

    def links(self, *, component_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.repository.initialize()
        sql = "SELECT * FROM platform_links"; params: list[Any] = []
        if component_id:
            sql += " WHERE source_component_id=? OR target_component_id=?"; params.extend([component_id, component_id])
        sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(sql, params).fetchall()]

    def _counts(self, connection: sqlite3.Connection) -> dict[str, int]:
        tables = {
            "records": "data_records",
            "sources": "sources",
            "indicators": "indicators",
            "observations": "observations",
            "review_cases": "review_cases",
            "saved_queries": "saved_queries",
            "query_runs": "query_runs",
            "workspaces": "workspaces",
            "connectors": "connector_definitions",
            "analysis_artifacts": "analysis_artifacts",
            "analysis_runs": "analysis_runs",
            "backups": "operational_backups",
            "handoffs": "handoff_receipts",
        }
        result: dict[str, int] = {}
        for key, table in tables.items():
            result[key] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return result

    def manifest(self) -> dict[str, Any]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            metadata = connection.execute("SELECT repository_id FROM repository_metadata WHERE id=1").fetchone()
            components = [_row(row) for row in connection.execute("SELECT * FROM platform_component_status ORDER BY component_id").fetchall()]
            contracts = [_row(row) for row in connection.execute("SELECT * FROM platform_contracts WHERE status='active' ORDER BY contract_id,id").fetchall()]
            counts = self._counts(connection)
        capabilities = sorted({capability for component in components for capability in component.get("capabilities", [])})
        return {
            "schema_version": PLATFORM_SCHEMA_VERSION,
            "product": "catalyst-data",
            "release_version": __version__,
            "repository_id": metadata[0] if metadata else None,
            "migration_version": discover_migrations()[-1].version,
            "local_first": True,
            "platform_core_optional": True,
            "counts": counts,
            "contracts": [
                {"contract_id": item["contract_id"], "contract_version": item["contract_version"], "schema_uri": item.get("schema_uri"), "schema_sha256": item["schema_sha256"]}
                for item in contracts
            ],
            "components": [
                {"component_id": item["component_id"], "product_code": item["product_code"], "status": item["status"], "version": item.get("current_version"), "capabilities": item.get("capabilities", []), "contracts": item.get("contracts", [])}
                for item in components
            ],
            "capabilities": capabilities,
            "platform_targets": list(KNOWN_PLATFORM_PRODUCTS),
            "boundaries": ["not compliance certification", "not professional advice", "human approval required"],
        }

    def create_snapshot(self, *, actor: str = "principal:system") -> dict[str, Any]:
        self.sync_builtin_contracts(actor=actor)
        manifest = self.manifest()
        digest = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
        snapshot_id = f"platform-snapshot:{digest[:24]}"
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            connection.execute(
                """INSERT OR IGNORE INTO platform_release_snapshots(
                   snapshot_id,release_version,repository_id,migration_version,manifest_sha256,manifest_json,created_by,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (snapshot_id, __version__, manifest.get("repository_id"), manifest["migration_version"], digest, canonical_json(manifest), actor, _now()),
            )
            connection.execute(
                "INSERT INTO platform_events(event_id,event_type,snapshot_id,actor,details_json,occurred_at) VALUES (?,?,?,?,?,?)",
                (_id("platform-event"), "release_snapshot_created", snapshot_id, actor, _json({"manifest_sha256": digest}), _now()),
            )
        return {"schema_version": PLATFORM_SCHEMA_VERSION, "snapshot_id": snapshot_id, "manifest_sha256": digest, "manifest": manifest}

    def snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute("SELECT * FROM platform_release_snapshots ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def verify_snapshot(self, snapshot_id: str, *, actor: str = "principal:system") -> dict[str, Any]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            row = connection.execute("SELECT * FROM platform_release_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise PlatformError(f"platform snapshot not found: {snapshot_id}")
        manifest = json.loads(row["manifest_json"])
        digest = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
        checks = [
            {"subsystem": "snapshot", "name": "manifest-checksum", "status": "pass" if digest == row["manifest_sha256"] else "fail", "details": {"expected": row["manifest_sha256"], "actual": digest}},
            {"subsystem": "migration", "name": "supported-schema", "status": "pass" if int(row["migration_version"]) <= discover_migrations()[-1].version else "fail", "details": {"snapshot": int(row["migration_version"]), "supported": discover_migrations()[-1].version}},
            {"subsystem": "release", "name": "release-version", "status": "pass" if row["release_version"] == __version__ else "warning", "details": {"snapshot": row["release_version"], "runtime": __version__}},
        ]
        checked_at = _now()
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            for check in checks:
                connection.execute(
                    "INSERT INTO platform_integrity_checks(check_id,snapshot_id,subsystem,check_name,status,details_json,checked_by,checked_at) VALUES (?,?,?,?,?,?,?,?)",
                    (_id("platform-check"), snapshot_id, check["subsystem"], check["name"], check["status"], _json(check["details"]), actor, checked_at),
                )
        overall = "fail" if any(item["status"] == "fail" for item in checks) else ("warning" if any(item["status"] == "warning" for item in checks) else "pass")
        return {"schema_version": PLATFORM_SCHEMA_VERSION, "snapshot_id": snapshot_id, "status": overall, "checks": checks, "checked_at": checked_at}

    def integrity(self, *, actor: str = "principal:system", persist: bool = True) -> dict[str, Any]:
        self.repository.initialize()
        health = self.repository.health()
        with closing(connect(self.repository.path)) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            self_component = connection.execute("SELECT status,current_version FROM platform_components WHERE component_id='component:catalyst-data'").fetchone()
            contract_count = int(connection.execute("SELECT COUNT(*) FROM platform_contracts WHERE status='active'").fetchone()[0])
            unowned_records = int(connection.execute("SELECT COUNT(*) FROM data_records d LEFT JOIN record_access_governance a ON a.record_id=d.record_id WHERE a.record_id IS NULL").fetchone()[0])
        checks = [
            {"subsystem": "database", "name": "integrity", "status": "pass" if integrity == "ok" else "fail", "details": {"result": integrity}},
            {"subsystem": "database", "name": "foreign-keys", "status": "pass" if not foreign_keys else "fail", "details": {"violations": len(foreign_keys)}},
            {"subsystem": "migration", "name": "current-schema", "status": "pass" if health.migration_version == health.latest_migration else "fail", "details": {"current": health.migration_version, "latest": health.latest_migration}},
            {"subsystem": "platform", "name": "core-component", "status": "pass" if self_component and self_component["status"] == "active" and self_component["current_version"] == __version__ else "fail", "details": {"component": dict(self_component) if self_component else None, "runtime": __version__}},
            {"subsystem": "contracts", "name": "contract-registry", "status": "pass" if contract_count >= 12 else "warning", "details": {"active_contracts": contract_count}},
            {"subsystem": "access", "name": "record-governance-coverage", "status": "pass" if unowned_records == 0 else "warning", "details": {"records_without_access_policy": unowned_records}},
        ]
        checked_at = _now()
        if persist:
            with closing(connect(self.repository.path)) as connection, transaction(connection):
                for check in checks:
                    connection.execute(
                        "INSERT INTO platform_integrity_checks(check_id,subsystem,check_name,status,details_json,checked_by,checked_at) VALUES (?,?,?,?,?,?,?)",
                        (_id("platform-check"), check["subsystem"], check["name"], check["status"], _json(check["details"]), actor, checked_at),
                    )
        overall = "blocked" if any(item["status"] == "fail" for item in checks) else ("attention" if any(item["status"] == "warning" for item in checks) else "ready")
        return {"schema_version": PLATFORM_SCHEMA_VERSION, "status": overall, "checks": checks, "checked_at": checked_at}

    def readiness(self, *, actor: str = "principal:system", persist: bool = True) -> dict[str, Any]:
        integrity = self.integrity(actor=actor, persist=persist)
        operational = OperationalService(self.repository).readiness()
        status = integrity["status"]
        if status == "ready" and (operational.get("failed_security_checks", 0) or operational.get("failed_benchmarks", 0)):
            status = "attention"
        return {
            "schema_version": PLATFORM_SCHEMA_VERSION,
            "status": status,
            "release_version": __version__,
            "migration_version": discover_migrations()[-1].version,
            "platform": integrity,
            "operations": operational,
            "manifest": self.manifest(),
        }

    def events(self, *, component_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.repository.initialize()
        sql = "SELECT * FROM platform_events"; params: list[Any] = []
        if component_id:
            sql += " WHERE component_id=?"; params.append(component_id)
        sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(sql, params).fetchall()]
