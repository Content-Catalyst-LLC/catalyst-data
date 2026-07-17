from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .database import connect, transaction
from .migrations import MigrationManager, discover_migrations
from .repository import CatalystRepository, canonical_json


OPERATIONAL_SCHEMA_VERSION = "catalyst-data-operational-hardening/1.0"


class OperationalError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


class OperationalService:
    def __init__(self, repository: CatalystRepository):
        self.repository = repository

    def create_backup(self, destination: str | Path, *, actor: str = "principal:system") -> dict[str, Any]:
        self.repository.initialize()
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination == self.repository.path.resolve():
            raise OperationalError("backup destination must differ from the repository path")
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        with closing(connect(self.repository.path)) as source, closing(sqlite3.connect(temporary)) as target:
            source.execute("PRAGMA wal_checkpoint(PASSIVE)")
            source.backup(target)
            target.commit()
        with closing(sqlite3.connect(temporary)) as check:
            integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                temporary.unlink(missing_ok=True)
                raise OperationalError(f"backup integrity check failed: {integrity}")
            manager = MigrationManager(check)
            schema_version = manager.current_version
            record_count = int(check.execute("SELECT COUNT(*) FROM data_records").fetchone()[0]) if schema_version >= 2 else 0
            repository_row = check.execute("SELECT repository_id FROM repository_metadata WHERE id=1").fetchone() if schema_version >= 2 else None
            repository_id = str(repository_row[0]) if repository_row else None
        temporary.replace(destination)
        digest = _sha256_path(destination)
        backup_id = _id("backup")
        manifest = {
            "schema_version": OPERATIONAL_SCHEMA_VERSION,
            "backup_id": backup_id,
            "repository_id": repository_id,
            "source_path": str(self.repository.path.resolve()),
            "backup_path": str(destination),
            "database_sha256": digest,
            "byte_size": destination.stat().st_size,
            "migration_version": schema_version,
            "record_count": record_count,
            "created_by": actor,
            "created_at": _now(),
        }
        sidecar = destination.with_suffix(destination.suffix + ".manifest.json")
        sidecar.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            connection.execute(
                """INSERT INTO operational_backups(
                    backup_id,repository_id,source_path,backup_path,database_sha256,byte_size,
                    schema_version,record_count,manifest_json,status,created_by,created_at,verified_at
                ) VALUES (?,?,?,?,?,?,?,?,?,'verified',?,?,?)""",
                (
                    backup_id, repository_id, manifest["source_path"], str(destination), digest,
                    manifest["byte_size"], schema_version, record_count, _json(manifest), actor,
                    manifest["created_at"], manifest["created_at"],
                ),
            )
        return {**manifest, "manifest_path": str(sidecar), "status": "verified"}

    def verify_backup(self, backup: str | Path) -> dict[str, Any]:
        backup = Path(backup).expanduser().resolve()
        if not backup.is_file():
            raise OperationalError(f"backup not found: {backup}")
        digest = _sha256_path(backup)
        sidecar = backup.with_suffix(backup.suffix + ".manifest.json")
        manifest: dict[str, Any] | None = None
        if sidecar.exists():
            value = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise OperationalError("backup manifest must contain an object")
            manifest = value
            if manifest.get("database_sha256") != digest:
                raise OperationalError("backup checksum does not match its manifest")
        with closing(sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise OperationalError(f"backup integrity check failed: {integrity}")
            manager = MigrationManager(connection)
            version = manager.current_version
            if version > discover_migrations()[-1].version:
                raise OperationalError("backup was created by a newer unsupported schema")
            record_count = int(connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0]) if version >= 2 else 0
        return {
            "schema_version": OPERATIONAL_SCHEMA_VERSION,
            "backup_path": str(backup),
            "manifest_path": str(sidecar) if sidecar.exists() else None,
            "database_sha256": digest,
            "byte_size": backup.stat().st_size,
            "migration_version": version,
            "record_count": record_count,
            "integrity": integrity,
            "verified": True,
            "manifest": manifest,
        }

    def restore_backup(
        self,
        backup: str | Path,
        target: str | Path | None = None,
        *,
        actor: str = "principal:system",
        force: bool = False,
    ) -> dict[str, Any]:
        verification = self.verify_backup(backup)
        backup_path = Path(backup).expanduser().resolve()
        target_path = Path(target or self.repository.path).expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and not force:
            raise OperationalError("target exists; pass force=True to restore over it")
        pre_sha = _sha256_path(target_path) if target_path.exists() else None
        safety_backup: str | None = None
        if target_path.exists():
            safety = target_path.with_name(f"{target_path.stem}.before-restore-{_stamp()}{target_path.suffix}")
            with closing(sqlite3.connect(target_path)) as source, closing(sqlite3.connect(safety)) as output:
                source.backup(output)
            safety_backup = str(safety)
        temporary = target_path.with_suffix(target_path.suffix + ".restore-tmp")
        temporary.unlink(missing_ok=True)
        with closing(sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(temporary)) as output:
            source.backup(output)
        temporary.replace(target_path)
        restored = CatalystRepository(target_path)
        restored.initialize()
        post_sha = _sha256_path(target_path)
        manifest = verification.get("manifest") or {}
        restore_id = _id("restore")
        details = {
            "schema_version": OPERATIONAL_SCHEMA_VERSION,
            "safety_backup": safety_backup,
            "source_migration_version": verification["migration_version"],
            "restored_migration_version": restored.health().migration_version,
        }
        with closing(connect(target_path)) as connection, transaction(connection):
            connection.execute(
                """INSERT INTO restore_events(
                    restore_id,backup_id,backup_path,target_path,pre_restore_sha256,post_restore_sha256,
                    schema_version,actor,status,details_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?, 'completed', ?,?)""",
                (
                    restore_id, manifest.get("backup_id"), str(backup_path), str(target_path), pre_sha,
                    post_sha, restored.health().migration_version, actor, _json(details), _now(),
                ),
            )
        return {
            "schema_version": OPERATIONAL_SCHEMA_VERSION,
            "restore_id": restore_id,
            "backup_id": manifest.get("backup_id"),
            "target_path": str(target_path),
            "database_sha256": post_sha,
            "migration_version": restored.health().migration_version,
            "record_count": restored.health().record_count,
            "safety_backup": safety_backup,
            "status": "completed",
        }

    def backups(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(
                "SELECT * FROM operational_backups ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]

    def restore_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(
                "SELECT * FROM restore_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]

    def queue_operation(
        self,
        operation_type: str,
        payload: Mapping[str, Any],
        *,
        workspace_id: str = "workspace:default",
        actor: str = "principal:system",
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        self.repository.initialize()
        if operation_type not in {"record-upsert", "connector-run", "query-run", "analysis-run", "handoff-receive", "custom"}:
            raise OperationalError(f"unsupported operation type: {operation_type}")
        clean_payload = json.loads(canonical_json(payload))
        digest = hashlib.sha256(canonical_json(clean_payload).encode("utf-8")).hexdigest()
        operation_id = _id("offline-operation")
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            workspace = connection.execute("SELECT id FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
            if workspace is None:
                raise OperationalError(f"workspace not found: {workspace_id}")
            connection.execute(
                """INSERT INTO offline_operations(
                    operation_id,workspace_id,operation_type,payload_json,payload_sha256,status,
                    attempts,max_attempts,queued_by,queued_at
                ) VALUES (?,?,?,?,?,'queued',0,?,?,?)""",
                (operation_id, workspace[0], operation_type, _json(clean_payload), digest, max_attempts, actor, _now()),
            )
        return self.operation(operation_id)

    def operation(self, operation_id: str) -> dict[str, Any]:
        with closing(connect(self.repository.path, readonly=True)) as connection:
            row = connection.execute(
                """SELECT oo.*,w.workspace_id FROM offline_operations oo
                   LEFT JOIN workspaces w ON w.id=oo.workspace_id WHERE oo.operation_id=?""", (operation_id,)
            ).fetchone()
            if row is None:
                raise OperationalError(f"offline operation not found: {operation_id}")
            return _row(row)

    def operations(self, *, status: str | None = None, workspace_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("oo.status=?"); values.append(status)
        if workspace_id:
            clauses.append("w.workspace_id=?"); values.append(workspace_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(connect(self.repository.path, readonly=True)) as connection:
            rows = connection.execute(
                f"""SELECT oo.*,w.workspace_id FROM offline_operations oo
                    LEFT JOIN workspaces w ON w.id=oo.workspace_id{where}
                    ORDER BY oo.id DESC LIMIT ?""", (*values, limit)
            ).fetchall()
            return [_row(row) for row in rows]

    def _dispatch(self, operation_type: str, payload: Mapping[str, Any]) -> Any:
        if operation_type == "record-upsert":
            record = payload.get("record")
            if not isinstance(record, Mapping):
                raise OperationalError("record-upsert requires payload.record")
            return self.repository.upsert_record(record)
        if operation_type == "connector-run":
            from .connectors import ConnectorService
            connector_id = str(payload.get("connector_id", ""))
            if not connector_id:
                raise OperationalError("connector-run requires connector_id")
            raw = payload.get("payload")
            body = json.dumps(raw).encode("utf-8") if raw is not None else None
            return ConnectorService(self.repository).run(connector_id, payload=body, source_uri=payload.get("source_uri"))
        if operation_type == "query-run":
            from .query_studio import QueryStudio
            query_id = str(payload.get("query_id", ""))
            if not query_id:
                raise OperationalError("query-run requires query_id")
            return QueryStudio(self.repository).run(query_id)
        if operation_type == "analysis-run":
            from .analysis_artifacts import AnalysisArtifactService
            artifact_id = str(payload.get("artifact_id", ""))
            if not artifact_id:
                raise OperationalError("analysis-run requires artifact_id")
            return AnalysisArtifactService(self.repository).run(
                artifact_id,
                record_ids=payload.get("record_ids"),
                parameters=payload.get("parameters"),
                actor=str(payload.get("actor", "principal:system")),
            )
        if operation_type == "handoff-receive":
            from .public_api import ApiRegistry
            envelope = payload.get("handoff")
            if not isinstance(envelope, Mapping):
                raise OperationalError("handoff-receive requires payload.handoff")
            return ApiRegistry(self.repository).receive_handoff(dict(envelope))
        raise OperationalError("custom operations require an external synchronizer")

    def sync_offline(
        self,
        *,
        workspace_id: str | None = None,
        actor: str = "principal:system",
        limit: int = 100,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        self.repository.initialize()
        statuses = ("queued", "failed") if retry_failed else ("queued",)
        placeholders = ",".join("?" for _ in statuses)
        clauses = [f"oo.status IN ({placeholders})", "oo.attempts < oo.max_attempts"]
        values: list[Any] = list(statuses)
        if workspace_id:
            clauses.append("w.workspace_id=?"); values.append(workspace_id)
        with closing(connect(self.repository.path, readonly=True)) as connection:
            rows = connection.execute(
                f"""SELECT oo.operation_id,oo.operation_type,oo.payload_json,w.workspace_id
                    FROM offline_operations oo LEFT JOIN workspaces w ON w.id=oo.workspace_id
                    WHERE {' AND '.join(clauses)} ORDER BY oo.queued_at,oo.id LIMIT ?""",
                (*values, limit),
            ).fetchall()
        started = _now()
        results: list[dict[str, Any]] = []
        for row in rows:
            operation_id = row["operation_id"]
            with closing(connect(self.repository.path)) as connection, transaction(connection):
                connection.execute(
                    "UPDATE offline_operations SET status='running',attempts=attempts+1,started_at=?,error_message=NULL WHERE operation_id=?",
                    (_now(), operation_id),
                )
            try:
                result = self._dispatch(row["operation_type"], json.loads(row["payload_json"]))
                normalized = json.loads(json.dumps(result, ensure_ascii=False, default=str))
                with closing(connect(self.repository.path)) as connection, transaction(connection):
                    connection.execute(
                        "UPDATE offline_operations SET status='succeeded',finished_at=?,result_json=? WHERE operation_id=?",
                        (_now(), _json(normalized), operation_id),
                    )
                results.append({"operation_id": operation_id, "status": "succeeded", "result": normalized})
            except Exception as exc:
                with closing(connect(self.repository.path)) as connection, transaction(connection):
                    connection.execute(
                        "UPDATE offline_operations SET status='failed',finished_at=?,error_message=? WHERE operation_id=?",
                        (_now(), str(exc), operation_id),
                    )
                results.append({"operation_id": operation_id, "status": "failed", "error": str(exc)})
        succeeded = sum(item["status"] == "succeeded" for item in results)
        failed = sum(item["status"] == "failed" for item in results)
        status = "completed" if failed == 0 else ("failed" if succeeded == 0 and failed else "partial")
        sync_id = _id("offline-sync")
        finished = _now()
        summary = {"operations": results, "workspace_id": workspace_id, "retry_failed": retry_failed}
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            workspace_db_id = None
            if workspace_id:
                workspace = connection.execute("SELECT id FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
                workspace_db_id = workspace[0] if workspace else None
            cursor = connection.execute(
                """INSERT INTO offline_sync_runs(
                    sync_id,workspace_id,status,queued_count,succeeded_count,failed_count,actor,
                    started_at,finished_at,summary_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sync_id, workspace_db_id, status, len(results), succeeded, failed, actor, started, finished, _json(summary)),
            )
            sync_db_id = cursor.lastrowid
            for item in results:
                operation = connection.execute("SELECT id FROM offline_operations WHERE operation_id=?", (item["operation_id"],)).fetchone()
                connection.execute(
                    "INSERT INTO offline_sync_items(sync_id,operation_id,status,details_json) VALUES (?,?,?,?)",
                    (sync_db_id, operation[0], item["status"], _json(item)),
                )
        return {
            "schema_version": OPERATIONAL_SCHEMA_VERSION,
            "sync_id": sync_id,
            "status": status,
            "queued_count": len(results),
            "succeeded_count": succeeded,
            "failed_count": failed,
            "operations": results,
        }

    def sync_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute(
                "SELECT * FROM offline_sync_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]

    def benchmark(self, *, actor: str = "principal:system", iterations: int = 3) -> dict[str, Any]:
        self.repository.initialize()
        timings: dict[str, list[float]] = {"integrity_check_ms": [], "stats_ms": [], "record_page_ms": []}
        for _ in range(max(1, iterations)):
            started = time.perf_counter()
            with closing(connect(self.repository.path, readonly=True)) as connection:
                integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            timings["integrity_check_ms"].append((time.perf_counter() - started) * 1000)
            started = time.perf_counter(); stats = self.repository.stats(); timings["stats_ms"].append((time.perf_counter() - started) * 1000)
            started = time.perf_counter(); self.repository.list_records(limit=100); timings["record_page_ms"].append((time.perf_counter() - started) * 1000)
        metrics = {name: {"min": round(min(values), 3), "max": round(max(values), 3), "mean": round(sum(values) / len(values), 3)} for name, values in timings.items()}
        metrics["integrity"] = integrity
        metrics["record_count"] = stats["records"]
        status = "pass"
        if integrity != "ok": status = "fail"
        elif metrics["record_page_ms"]["max"] > 1000 or metrics["stats_ms"]["max"] > 1000: status = "warning"
        benchmark_id = _id("benchmark")
        environment = {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version}
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            metadata = connection.execute("SELECT repository_id FROM repository_metadata WHERE id=1").fetchone()
            connection.execute(
                """INSERT INTO performance_benchmarks(
                    benchmark_id,benchmark_name,repository_id,schema_version,record_count,metrics_json,
                    environment_json,status,created_by,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (benchmark_id, "repository-readiness", metadata[0] if metadata else None, discover_migrations()[-1].version, stats["records"], _json(metrics), _json(environment), status, actor, _now()),
            )
        return {"schema_version": OPERATIONAL_SCHEMA_VERSION, "benchmark_id": benchmark_id, "status": status, "metrics": metrics, "environment": environment}

    def benchmarks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute("SELECT * FROM performance_benchmarks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def security_audit(self, *, actor: str = "principal:system") -> dict[str, Any]:
        self.repository.initialize()
        checks: list[dict[str, Any]] = []
        with closing(connect(self.repository.path)) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            checks.append({"name": "database-integrity", "status": "pass" if integrity == "ok" else "fail", "details": {"result": integrity}})
            violations = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
            checks.append({"name": "foreign-key-integrity", "status": "pass" if not violations else "fail", "details": {"violations": violations[:20], "count": len(violations)}})
            token_rows = int(connection.execute("SELECT COUNT(*) FROM api_clients WHERE length(token_sha256)<>64").fetchone()[0])
            checks.append({"name": "api-token-hashing", "status": "pass" if token_rows == 0 else "fail", "details": {"invalid_digest_count": token_rows}})
            credential_rows = connection.execute("SELECT config_json FROM connector_versions").fetchall()
            embedded = 0
            for row in credential_rows:
                definition = json.loads(row[0])
                auth = definition.get("source", {}).get("authentication", {})
                if any(key in auth for key in ("token", "password", "secret", "api_key")):
                    embedded += 1
            checks.append({"name": "connector-secret-storage", "status": "pass" if embedded == 0 else "fail", "details": {"embedded_secret_definitions": embedded}})
            mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            checks.append({"name": "sqlite-journal-mode", "status": "pass" if mode in {"wal", "delete"} else "warning", "details": {"journal_mode": mode}})
        if os.name == "posix":
            permissions = self.repository.path.stat().st_mode & 0o777
            writable = bool(permissions & 0o022)
            checks.append({"name": "database-file-permissions", "status": "warning" if writable else "pass", "details": {"mode": oct(permissions)}})
        created_at = _now()
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            for check in checks:
                connection.execute(
                    "INSERT INTO security_audit_events(audit_id,check_name,status,details_json,created_by,created_at) VALUES (?,?,?,?,?,?)",
                    (_id("security-audit"), check["name"], check["status"], _json(check["details"]), actor, created_at),
                )
        overall = "fail" if any(item["status"] == "fail" for item in checks) else ("warning" if any(item["status"] == "warning" for item in checks) else "pass")
        return {"schema_version": OPERATIONAL_SCHEMA_VERSION, "status": overall, "checks": checks, "created_at": created_at}

    def security_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute("SELECT * FROM security_audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def create_release_attestation(self, source_root: str | Path, output: str | Path, *, actor: str = "principal:system") -> dict[str, Any]:
        from . import __version__
        root = Path(source_root).expanduser().resolve()
        output_path = Path(output).expanduser().resolve()
        if not root.is_dir():
            raise OperationalError(f"source root not found: {root}")
        excluded_parts = {".git", "__pycache__", ".pytest_cache", ".release-check-pycache", "build", "*.egg-info"}
        files: list[dict[str, Any]] = []
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            parts = set(path.relative_to(root).parts)
            if parts & {".git", "__pycache__", ".pytest_cache", ".release-check-pycache", "build"}:
                continue
            if any(part.endswith(".egg-info") for part in path.relative_to(root).parts):
                continue
            if path.resolve() == output_path:
                continue
            file_sha = _sha256_path(path)
            item = {"path": relative, "sha256": file_sha, "byte_size": path.stat().st_size}
            files.append(item)
            digest.update(relative.encode("utf-8") + b"\0" + file_sha.encode("ascii") + b"\n")
        repository_sha = digest.hexdigest()
        manifest = {"schema_version": OPERATIONAL_SCHEMA_VERSION, "release_version": __version__, "files": files, "file_count": len(files), "repository_sha256": repository_sha}
        sbom = {
            "format": "catalyst-data-sbom/1.0",
            "component": {"name": "catalyst-data", "version": __version__, "type": "application"},
            "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
            "declared_dependencies": ["jsonschema>=4.21"],
            "package_modules": sorted(path.stem for path in (root / "python/catalyst_data").glob("*.py")) if (root / "python/catalyst_data").exists() else [],
        }
        attestation_id = _id("attestation")
        payload = {"schema_version": OPERATIONAL_SCHEMA_VERSION, "attestation_id": attestation_id, "created_by": actor, "created_at": _now(), "manifest": manifest, "sbom": sbom}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            connection.execute(
                "INSERT INTO release_attestations(attestation_id,release_version,repository_sha256,manifest_json,sbom_json,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                (attestation_id, __version__, repository_sha, _json(manifest), _json(sbom), actor, payload["created_at"]),
            )
        return {**payload, "output_path": str(output_path)}

    def attestations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [_row(row) for row in connection.execute("SELECT * FROM release_attestations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def readiness(self) -> dict[str, Any]:
        self.repository.initialize()
        with closing(connect(self.repository.path, readonly=True)) as connection:
            row = connection.execute("SELECT * FROM operational_readiness").fetchone()
            return {"schema_version": OPERATIONAL_SCHEMA_VERSION, **dict(row)}
