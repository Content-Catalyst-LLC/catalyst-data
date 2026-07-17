from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import re
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from jsonschema import Draft202012Validator
except ImportError:  # Portable installer environments may validate with the built-in checks.
    Draft202012Validator = None

from .database import connect, transaction
from .repository import CatalystRepository, RepositoryError, canonical_json, payload_hash

ANALYSIS_SCHEMA_VERSION = "catalyst-data-analysis-artifact/1.0"
PACKAGE_SCHEMA_VERSION = "catalyst-data-reproducible-package/1.0"
OUTPUT_SCHEMA_VERSION = "catalyst-data-analysis-output/1.0"
INPUT_ROLES = {"input", "baseline", "reference", "training", "validation", "comparison"}
OUTPUT_TYPES = {"table", "figure", "model", "scenario", "forecast", "sensitivity", "document", "dataset", "metric", "log", "other"}
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class AnalysisArtifactError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable(prefix: str, *parts: Any) -> str:
    value = canonical_json({"parts": [str(part) for part in parts]})
    return f"{prefix}:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return clean[:120] or "artifact"


def _schema() -> dict[str, Any]:
    resource = files("catalyst_data").joinpath("schemas/catalyst_data_analysis_artifact_1_0.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def normalize_analysis_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisArtifactError("analysis definition must be an object")
    allowed = {"schema_version","artifact_id","workspace_id","project_id","name","description","analysis_type","version","inputs","parameters","environment","code_reference","outputs","platform_links","extensions"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AnalysisArtifactError("unknown analysis fields: " + ", ".join(unknown))
    nested_allowed = {
        "inputs": {"record_ids","roles"},
        "environment": {"runtime","dependencies","container","hardware","notes"},
        "code_reference": {"repository","revision","path","entrypoint","checksum"},
    }
    for field, names in nested_allowed.items():
        raw = value.get(field) or {}
        if isinstance(raw, Mapping):
            extras = sorted(set(raw) - names)
            if extras:
                raise AnalysisArtifactError(f"unknown {field} fields: " + ", ".join(extras))
    name = str(value.get("name") or "").strip()
    workspace_id = str(value.get("workspace_id") or "workspace:default").strip()
    artifact_id = str(value.get("artifact_id") or _stable("analysis", workspace_id, name)).strip()
    environment = dict(value.get("environment") or {})
    code = dict(value.get("code_reference") or {})
    inputs = dict(value.get("inputs") or {})
    roles = {str(key): str(role) for key, role in dict(inputs.get("roles") or {}).items()}
    record_ids = [str(item) for item in inputs.get("record_ids") or []]
    output_specs = []
    for item in value.get("outputs") or []:
        output_specs.append({
            "name": str(item.get("name") or "Output").strip(),
            "output_type": str(item.get("output_type") or "other").strip(),
            "media_type": str(item.get("media_type") or "application/octet-stream").strip(),
            "description": str(item.get("description") or "").strip() or None,
        })
    platform_links = []
    for item in value.get("platform_links") or []:
        platform_links.append({
            "product": str(item.get("product") or "other").strip(),
            "capability": str(item.get("capability") or "").strip() or None,
            "external_artifact_id": str(item.get("external_artifact_id") or "").strip() or None,
            "uri": str(item.get("uri") or "").strip() or None,
            "relation": str(item.get("relation") or "related").strip(),
            "metadata": dict(item.get("metadata") or {}),
        })
    normalized = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "workspace_id": workspace_id,
        "project_id": str(value.get("project_id") or "").strip() or None,
        "name": name,
        "description": str(value.get("description") or "").strip() or None,
        "analysis_type": str(value.get("analysis_type") or "analysis").strip(),
        "version": str(value.get("version") or "1.0").strip(),
        "inputs": {"record_ids": list(dict.fromkeys(record_ids)), "roles": roles},
        "parameters": dict(value.get("parameters") or {}),
        "environment": {
            "runtime": str(environment.get("runtime") or "").strip() or None,
            "dependencies": sorted({str(item).strip() for item in environment.get("dependencies") or [] if str(item).strip()}),
            "container": str(environment.get("container") or "").strip() or None,
            "hardware": str(environment.get("hardware") or "").strip() or None,
            "notes": str(environment.get("notes") or "").strip() or None,
        },
        "code_reference": {
            "repository": str(code.get("repository") or "").strip() or None,
            "revision": str(code.get("revision") or "").strip() or None,
            "path": str(code.get("path") or "").strip() or None,
            "entrypoint": str(code.get("entrypoint") or "").strip() or None,
            "checksum": str(code.get("checksum") or "").strip() or None,
        },
        "outputs": output_specs,
        "platform_links": platform_links,
        "extensions": dict(value.get("extensions") or {}),
    }
    if not normalized["name"]:
        raise AnalysisArtifactError("analysis name is required")
    if not normalized["artifact_id"].startswith("analysis:"):
        raise AnalysisArtifactError("artifact_id must begin with analysis:")
    if normalized["analysis_type"] not in {"analysis","model","scenario","forecast","sensitivity","replication"}:
        raise AnalysisArtifactError("invalid analysis type")
    if not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", normalized["version"]):
        raise AnalysisArtifactError("analysis version must use numeric dotted notation")
    if Draft202012Validator is not None:
        errors = sorted(Draft202012Validator(_schema()).iter_errors(normalized), key=lambda error: list(error.path))
        if errors:
            messages = []
            for error in errors[:20]:
                path = ".".join(str(item) for item in error.path) or "$"
                messages.append(f"{path}: {error.message}")
            raise AnalysisArtifactError("invalid analysis definition: " + "; ".join(messages))
    unknown_roles = sorted(set(roles.values()) - INPUT_ROLES)
    if unknown_roles:
        raise AnalysisArtifactError("invalid input roles: " + ", ".join(unknown_roles))
    return normalized


def _row_json(row: Mapping[str, Any], *fields: str) -> dict[str, Any]:
    result = dict(row)
    for field in fields:
        raw = result.pop(field, None)
        result[field.removesuffix("_json")] = json.loads(raw) if raw else ({ } if field.endswith("_json") else raw)
    return result


def _output_bytes(output: Mapping[str, Any]) -> tuple[bytes, str, str, dict[str, Any]]:
    name = str(output.get("name") or "Output").strip()
    output_type = str(output.get("output_type") or "other")
    if output_type not in OUTPUT_TYPES:
        raise AnalysisArtifactError(f"invalid output type: {output_type}")
    media_type = str(output.get("media_type") or "application/octet-stream")
    metadata = dict(output.get("metadata") or {})
    if "content" in output:
        content = output["content"]
        if isinstance(content, bytes):
            data = content
        elif isinstance(content, str):
            data = content.encode("utf-8")
        else:
            data = (json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
            if media_type == "application/octet-stream":
                media_type = "application/json"
    elif output.get("path"):
        path = Path(str(output["path"]))
        data = path.read_bytes()
        if media_type == "application/octet-stream":
            media_type = mimetypes.guess_type(path.name)[0] or media_type
        metadata.setdefault("source_filename", path.name)
    else:
        data = b""
    return data, name, media_type, {"output_type": output_type, **metadata}


class AnalysisArtifactService:
    def __init__(self, repository: CatalystRepository | str | Path):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()

    @staticmethod
    def _workspace(connection, workspace_id: str):
        row = connection.execute("SELECT id,workspace_id FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
        if not row:
            raise RepositoryError(f"workspace not found: {workspace_id}")
        return row

    @staticmethod
    def _project(connection, project_id: str | None, workspace_row_id: int):
        if not project_id:
            return None
        row = connection.execute("SELECT id,project_id FROM projects WHERE project_id=? AND workspace_id=?", (project_id, workspace_row_id)).fetchone()
        if not row:
            raise RepositoryError(f"project not found in workspace: {project_id}")
        return row

    def register(self, definition: Mapping[str, Any], *, actor: str = "principal:system", activate: bool = True) -> dict[str, Any]:
        normalized = normalize_analysis_definition(definition)
        digest = payload_hash(normalized)
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            workspace = self._workspace(connection, normalized["workspace_id"])
            project = self._project(connection, normalized["project_id"], workspace["id"])
            existing = connection.execute("SELECT id FROM analysis_artifacts WHERE artifact_id=?", (normalized["artifact_id"],)).fetchone()
            if existing:
                artifact_row_id = int(existing["id"])
                connection.execute(
                    """UPDATE analysis_artifacts SET workspace_id=?,project_id=?,name=?,analysis_type=?,description=?,
                       status=CASE WHEN status='archived' THEN status ELSE 'active' END,target_product=?,target_uri=?,updated_at=? WHERE id=?""",
                    (workspace["id"], project["id"] if project else None, normalized["name"], normalized["analysis_type"], normalized["description"],
                     normalized["platform_links"][0]["product"] if normalized["platform_links"] else None,
                     normalized["platform_links"][0]["uri"] if normalized["platform_links"] else None, _now(), artifact_row_id),
                )
            else:
                cursor = connection.execute(
                    """INSERT INTO analysis_artifacts(artifact_id,workspace_id,project_id,name,analysis_type,description,status,target_product,target_uri,created_by)
                       VALUES (?,?,?,?,?,?,'active',?,?,?)""",
                    (normalized["artifact_id"], workspace["id"], project["id"] if project else None, normalized["name"], normalized["analysis_type"],
                     normalized["description"], normalized["platform_links"][0]["product"] if normalized["platform_links"] else None,
                     normalized["platform_links"][0]["uri"] if normalized["platform_links"] else None, actor),
                )
                artifact_row_id = int(cursor.lastrowid)
            version_row = connection.execute(
                "SELECT id,version,payload_sha256 FROM analysis_versions WHERE artifact_id=? AND payload_sha256=?",
                (artifact_row_id, digest),
            ).fetchone()
            created = False
            if version_row:
                version_id = int(version_row["id"])
            else:
                conflict = connection.execute("SELECT payload_sha256 FROM analysis_versions WHERE artifact_id=? AND version=?", (artifact_row_id, normalized["version"])).fetchone()
                if conflict:
                    raise AnalysisArtifactError(f"analysis version {normalized['version']} already exists with different content")
                cursor = connection.execute(
                    """INSERT INTO analysis_versions(artifact_id,version,definition_json,environment_json,code_reference_json,payload_sha256,created_by)
                       VALUES (?,?,?,?,?,?,?)""",
                    (artifact_row_id, normalized["version"], canonical_json(normalized), canonical_json(normalized["environment"]),
                     canonical_json(normalized["code_reference"]), digest, actor),
                )
                version_id = int(cursor.lastrowid); created = True
            if activate:
                current = connection.execute("SELECT analysis_version_id FROM analysis_version_activations WHERE artifact_id=? ORDER BY id DESC LIMIT 1", (artifact_row_id,)).fetchone()
                if not current or int(current[0]) != version_id:
                    activation_id = _stable("analysis-activation", normalized["artifact_id"], normalized["version"], _now(), uuid.uuid4().hex)
                    connection.execute(
                        "INSERT INTO analysis_version_activations(activation_id,artifact_id,analysis_version_id,activated_by) VALUES (?,?,?,?)",
                        (activation_id, artifact_row_id, version_id, actor),
                    )
            for link in normalized["platform_links"]:
                link_id = _stable("analysis-link", normalized["artifact_id"], link["product"], link.get("external_artifact_id"), link.get("uri"), link["relation"])
                connection.execute(
                    """INSERT OR IGNORE INTO analysis_platform_links(link_id,artifact_id,product,capability,external_artifact_id,uri,relation,metadata_json,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (link_id, artifact_row_id, link["product"], link["capability"], link["external_artifact_id"], link["uri"], link["relation"], canonical_json(link["metadata"]), actor),
                )
        result = self.get(normalized["artifact_id"])
        result["version_created"] = created
        return result

    def activate_version(self, artifact_id: str, version: str, *, actor: str = "principal:system") -> dict[str, Any]:
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            row = connection.execute(
                """SELECT aa.id AS artifact_row_id,av.id AS version_row_id FROM analysis_artifacts aa
                   JOIN analysis_versions av ON av.artifact_id=aa.id WHERE aa.artifact_id=? AND av.version=?""",
                (artifact_id, version),
            ).fetchone()
            if not row:
                raise RepositoryError(f"analysis version not found: {artifact_id} {version}")
            current = connection.execute("SELECT analysis_version_id FROM analysis_version_activations WHERE artifact_id=? ORDER BY id DESC LIMIT 1", (row["artifact_row_id"],)).fetchone()
            if not current or int(current[0]) != int(row["version_row_id"]):
                connection.execute(
                    "INSERT INTO analysis_version_activations(activation_id,artifact_id,analysis_version_id,activated_by) VALUES (?,?,?,?)",
                    (_stable("analysis-activation", artifact_id, version, _now(), uuid.uuid4().hex), row["artifact_row_id"], row["version_row_id"], actor),
                )
        return self.get(artifact_id)

    def list(self, *, workspace_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM analysis_artifact_status"
        params: list[Any] = []
        clauses = []
        if workspace_id:
            clauses.append("workspace_id=?"); params.append(workspace_id)
        if status:
            clauses.append("status=?"); params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name,artifact_id"
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def versions(self, artifact_id: str) -> list[dict[str, Any]]:
        with closing(connect(self.repository.path, readonly=True)) as connection:
            rows = connection.execute(
                """SELECT av.version,av.payload_sha256,av.created_by,av.created_at,av.definition_json,
                          CASE WHEN av.id=(SELECT analysis_version_id FROM analysis_version_activations x WHERE x.artifact_id=aa.id ORDER BY x.id DESC LIMIT 1) THEN 1 ELSE 0 END AS active
                   FROM analysis_artifacts aa JOIN analysis_versions av ON av.artifact_id=aa.id
                   WHERE aa.artifact_id=? ORDER BY av.id DESC""", (artifact_id,),
            ).fetchall()
            result=[]
            for row in rows:
                item=dict(row); item["definition"]=json.loads(item.pop("definition_json")); item["active"]=bool(item["active"]); result.append(item)
            return result

    def get(self, artifact_id: str) -> dict[str, Any]:
        with closing(connect(self.repository.path, readonly=True)) as connection:
            row = connection.execute("SELECT * FROM analysis_artifact_status WHERE artifact_id=?", (artifact_id,)).fetchone()
            if not row:
                raise RepositoryError(f"analysis artifact not found: {artifact_id}")
            result = dict(row)
            versions = self.versions(artifact_id)
            result["active_definition"] = next((item["definition"] for item in versions if item["active"]), versions[0]["definition"] if versions else None)
            result["platform_links"] = [
                _row_json(item, "metadata_json") for item in connection.execute(
                    """SELECT apl.link_id,apl.product,apl.capability,apl.external_artifact_id,apl.uri,apl.relation,apl.metadata_json,apl.created_at
                       FROM analysis_platform_links apl JOIN analysis_artifacts aa ON aa.id=apl.artifact_id
                       WHERE aa.artifact_id=? ORDER BY apl.id""", (artifact_id,),
                ).fetchall()
            ]
            return result

    def _active_version(self, connection, artifact_id: str):
        row = connection.execute(
            """SELECT aa.id AS artifact_row_id,aa.artifact_id,aa.name,aa.analysis_type,aa.workspace_id,
                      av.id AS version_row_id,av.version,av.definition_json,av.environment_json,av.code_reference_json,av.payload_sha256
               FROM analysis_artifacts aa
               JOIN analysis_version_activations ava ON ava.id=(SELECT MAX(x.id) FROM analysis_version_activations x WHERE x.artifact_id=aa.id)
               JOIN analysis_versions av ON av.id=ava.analysis_version_id
               WHERE aa.artifact_id=?""", (artifact_id,),
        ).fetchone()
        if not row:
            raise RepositoryError(f"active analysis version not found: {artifact_id}")
        return row

    def run(
        self,
        artifact_id: str,
        *,
        record_ids: Sequence[str] | None = None,
        parameters: Mapping[str, Any] | None = None,
        outputs: Sequence[Mapping[str, Any]] | None = None,
        actor: str = "principal:system",
    ) -> dict[str, Any]:
        started_at = _now()
        run_public_id = "analysis-run:" + uuid.uuid4().hex
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            active = self._active_version(connection, artifact_id)
            definition = json.loads(active["definition_json"])
            selected = list(dict.fromkeys(str(item) for item in (record_ids if record_ids is not None else definition["inputs"]["record_ids"])))
            if not selected:
                raise AnalysisArtifactError("analysis run requires at least one record input")
            effective_parameters = dict(definition.get("parameters") or {})
            effective_parameters.update(parameters or {})
            cursor = connection.execute(
                """INSERT INTO analysis_runs(run_id,artifact_id,analysis_version_id,status,executed_by,started_at,parameters_json,environment_json,reproducibility_status)
                   VALUES (?,?,?,'running',?,?,?,?, 'pending')""",
                (run_public_id, active["artifact_row_id"], active["version_row_id"], actor, started_at, canonical_json(effective_parameters), active["environment_json"]),
            )
            run_row_id = int(cursor.lastrowid)
            input_manifest=[]
            frozen_records=[]
            for ordinal, record_id in enumerate(selected):
                row = connection.execute("SELECT payload_json,payload_sha256 FROM data_records WHERE record_id=?", (record_id,)).fetchone()
                if not row:
                    raise RepositoryError(f"analysis input record not found: {record_id}")
                role = definition["inputs"]["roles"].get(record_id, "input")
                input_id = _stable("analysis-input", run_public_id, record_id, role, ordinal)
                connection.execute(
                    """INSERT INTO analysis_run_inputs(input_id,run_id,record_id,role,ordinal,payload_json,payload_sha256,frozen_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (input_id, run_row_id, record_id, role, ordinal, row["payload_json"], row["payload_sha256"], started_at),
                )
                input_manifest.append({"input_id": input_id, "record_id": record_id, "role": role, "ordinal": ordinal, "payload_sha256": row["payload_sha256"]})
                frozen_records.append(json.loads(row["payload_json"]))
            input_digest = hashlib.sha256(canonical_json({"inputs": input_manifest}).encode("utf-8")).hexdigest()
            supplied_outputs = list(outputs or [])
            values = [float(record["measurement"]["current"]) for record in frozen_records]
            summary = {
                "schema_version": OUTPUT_SCHEMA_VERSION,
                "artifact_id": artifact_id,
                "run_id": run_public_id,
                "input_count": len(frozen_records),
                "record_ids": selected,
                "measurement_summary": {
                    "count": len(values),
                    "minimum": min(values),
                    "maximum": max(values),
                    "mean": sum(values) / len(values),
                },
                "parameters": effective_parameters,
            }
            supplied_outputs.insert(0, {"name": "analysis-summary.json", "output_type": "document", "media_type": "application/json", "content": summary, "metadata": {"generated": True}})
            output_manifest=[]
            for ordinal, output in enumerate(supplied_outputs):
                data, name, media_type, metadata = _output_bytes(output)
                digest = hashlib.sha256(data).hexdigest()
                output_id = _stable("analysis-output", run_public_id, ordinal, name, digest)
                connection.execute(
                    """INSERT INTO analysis_outputs(output_id,run_id,output_type,name,media_type,content_blob,external_uri,payload_sha256,byte_size,metadata_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (output_id, run_row_id, metadata.pop("output_type"), name, media_type, data, output.get("external_uri"), digest, len(data), canonical_json(metadata)),
                )
                output_manifest.append({"output_id": output_id, "name": name, "media_type": media_type, "payload_sha256": digest, "byte_size": len(data)})
            output_digest = hashlib.sha256(canonical_json({"outputs": output_manifest}).encode("utf-8")).hexdigest()
            connection.execute(
                """UPDATE analysis_runs SET status='completed',finished_at=?,input_manifest_sha256=?,output_manifest_sha256=?,reproducibility_status='reproducible'
                   WHERE id=?""", (_now(), input_digest, output_digest, run_row_id),
            )
            connection.execute("UPDATE analysis_artifacts SET status='completed',updated_at=? WHERE id=?", (_now(), active["artifact_row_id"]))
        return self.run_details(run_public_id)

    def runs(self, *, artifact_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = """SELECT ar.run_id,aa.artifact_id,aa.name,av.version,ar.status,ar.reproducibility_status,ar.executed_by,
                        ar.started_at,ar.finished_at,ar.input_manifest_sha256,ar.output_manifest_sha256,
                        (SELECT COUNT(*) FROM analysis_run_inputs i WHERE i.run_id=ar.id) AS input_count,
                        (SELECT COUNT(*) FROM analysis_outputs o WHERE o.run_id=ar.id) AS output_count
                 FROM analysis_runs ar JOIN analysis_artifacts aa ON aa.id=ar.artifact_id
                 JOIN analysis_versions av ON av.id=ar.analysis_version_id"""
        params=[]; clauses=[]
        if artifact_id: clauses.append("aa.artifact_id=?"); params.append(artifact_id)
        if status: clauses.append("ar.status=?"); params.append(status)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ar.id DESC LIMIT ?"; params.append(limit)
        with closing(connect(self.repository.path, readonly=True)) as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def run_details(self, run_id: str, *, include_payloads: bool = False) -> dict[str, Any]:
        with closing(connect(self.repository.path, readonly=True)) as connection:
            run = connection.execute(
                """SELECT ar.*,aa.artifact_id,aa.name,av.version,av.definition_json,av.code_reference_json
                   FROM analysis_runs ar JOIN analysis_artifacts aa ON aa.id=ar.artifact_id
                   JOIN analysis_versions av ON av.id=ar.analysis_version_id WHERE ar.run_id=?""", (run_id,),
            ).fetchone()
            if not run:
                raise RepositoryError(f"analysis run not found: {run_id}")
            result = dict(run)
            result["parameters"] = json.loads(result.pop("parameters_json")); result["environment"] = json.loads(result.pop("environment_json"))
            result["definition"] = json.loads(result.pop("definition_json")); result["code_reference"] = json.loads(result.pop("code_reference_json"))
            input_fields = "input_id,record_id,role,ordinal,payload_sha256,frozen_at" + (",payload_json" if include_payloads else "")
            inputs=[]
            for row in connection.execute(f"SELECT {input_fields} FROM analysis_run_inputs WHERE run_id=? ORDER BY ordinal,id", (run["id"],)).fetchall():
                item=dict(row)
                if include_payloads: item["payload"]=json.loads(item.pop("payload_json"))
                inputs.append(item)
            outputs=[]
            for row in connection.execute("SELECT output_id,output_type,name,media_type,external_uri,payload_sha256,byte_size,metadata_json,created_at FROM analysis_outputs WHERE run_id=? ORDER BY id", (run["id"],)).fetchall():
                item=dict(row); item["metadata"]=json.loads(item.pop("metadata_json")); outputs.append(item)
            invalidations=[]
            for row in connection.execute(
                """SELECT aie.invalidation_id,aie.record_id,aie.frozen_sha256,aie.current_sha256,aie.reason,aie.severity,aie.detected_at,aie.details_json,
                          (SELECT action FROM analysis_invalidation_resolutions r WHERE r.invalidation_id=aie.id ORDER BY r.id DESC LIMIT 1) AS resolution
                   FROM analysis_invalidation_events aie WHERE aie.run_id=? ORDER BY aie.id""", (run["id"],),
            ).fetchall():
                item=dict(row); item["details"]=json.loads(item.pop("details_json")); invalidations.append(item)
            replications=[]
            for row in connection.execute("SELECT replication_id,status,reviewer,notes,evidence_json,evidence_sha256,created_at FROM analysis_replication_reviews WHERE run_id=? ORDER BY id", (run["id"],)).fetchall():
                item=dict(row); item["evidence"]=json.loads(item.pop("evidence_json")); replications.append(item)
            result["inputs"]=inputs; result["outputs"]=outputs; result["invalidations"]=invalidations; result["replications"]=replications
            return result

    def add_derived_lineage(self, run_id: str, derived_record_id: str, source_record_ids: Sequence[str], *, transformation: Mapping[str, Any] | None = None, output_id: str | None = None, actor: str = "principal:system") -> list[dict[str, Any]]:
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            run = connection.execute("SELECT id FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
            if not run: raise RepositoryError(f"analysis run not found: {run_id}")
            for record_id in [derived_record_id, *source_record_ids]:
                if not connection.execute("SELECT 1 FROM data_records WHERE record_id=?", (record_id,)).fetchone():
                    raise RepositoryError(f"record not found: {record_id}")
            output_row_id = None
            if output_id:
                row=connection.execute("SELECT id FROM analysis_outputs WHERE output_id=? AND run_id=?", (output_id, run["id"])).fetchone()
                if not row: raise RepositoryError(f"analysis output not found for run: {output_id}")
                output_row_id=int(row["id"])
            for source_record_id in dict.fromkeys(source_record_ids):
                lineage_id = _stable("derived-lineage", run_id, derived_record_id, source_record_id)
                connection.execute(
                    """INSERT OR IGNORE INTO derived_measurement_lineage(lineage_id,run_id,output_id,derived_record_id,source_record_id,transformation_json,created_by)
                       VALUES (?,?,?,?,?,?,?)""",
                    (lineage_id, run["id"], output_row_id, derived_record_id, source_record_id, canonical_json(transformation or {}), actor),
                )
        return self.derived_lineage(derived_record_id)

    def derived_lineage(self, record_id: str) -> list[dict[str, Any]]:
        with closing(connect(self.repository.path, readonly=True)) as connection:
            rows=connection.execute(
                """SELECT dml.lineage_id,ar.run_id,aa.artifact_id,ao.output_id,dml.derived_record_id,dml.source_record_id,
                          dml.transformation_json,dml.created_by,dml.created_at
                   FROM derived_measurement_lineage dml JOIN analysis_runs ar ON ar.id=dml.run_id
                   JOIN analysis_artifacts aa ON aa.id=ar.artifact_id LEFT JOIN analysis_outputs ao ON ao.id=dml.output_id
                   WHERE dml.derived_record_id=? OR dml.source_record_id=? ORDER BY dml.id""", (record_id, record_id),
            ).fetchall()
            result=[]
            for row in rows:
                item=dict(row); item["transformation"]=json.loads(item.pop("transformation_json")); result.append(item)
            return result

    def detect_invalidations(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            sql = """SELECT ari.run_id AS run_row_id,ar.run_id,ar.artifact_id,ari.record_id,ari.payload_sha256 AS frozen_sha256,dr.payload_sha256 AS current_sha256
                     FROM analysis_run_inputs ari JOIN analysis_runs ar ON ar.id=ari.run_id
                     LEFT JOIN data_records dr ON dr.record_id=ari.record_id
                     WHERE (dr.record_id IS NULL OR dr.payload_sha256<>ari.payload_sha256)"""
            params=[]
            if run_id: sql += " AND ar.run_id=?"; params.append(run_id)
            rows=connection.execute(sql,params).fetchall()
            for row in rows:
                reason = "upstream-record-missing" if row["current_sha256"] is None else "upstream-record-changed"
                key = _stable("invalidation", row["run_id"], row["record_id"], row["frozen_sha256"], row["current_sha256"] or "missing")
                connection.execute(
                    """INSERT OR IGNORE INTO analysis_invalidation_events(invalidation_id,run_id,record_id,frozen_sha256,current_sha256,reason,severity,detected_at,details_json)
                       VALUES (?,?,?,?,?,?, 'warning', ?, ?)""",
                    (key,row["run_row_id"],row["record_id"],row["frozen_sha256"],row["current_sha256"],reason,_now(),canonical_json({"detector":"analysis-service"})),
                )
                connection.execute("UPDATE analysis_runs SET reproducibility_status='invalidated' WHERE id=?", (row["run_row_id"],))
                connection.execute("UPDATE analysis_artifacts SET status='invalidated',updated_at=? WHERE id=?", (_now(),row["artifact_id"]))
        if run_id:
            return self.run_details(run_id)["invalidations"]
        with closing(connect(self.repository.path,readonly=True)) as connection:
            return [dict(row) for row in connection.execute("SELECT invalidation_id,record_id,reason,severity,detected_at FROM analysis_invalidation_events ORDER BY id DESC").fetchall()]

    def resolve_invalidation(self, invalidation_id: str, action: str, *, actor: str, notes: str | None = None) -> dict[str, Any]:
        if action not in {"acknowledged","rerun","accepted","resolved"}:
            raise AnalysisArtifactError("invalid invalidation resolution action")
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            row=connection.execute("SELECT id,run_id FROM analysis_invalidation_events WHERE invalidation_id=?",(invalidation_id,)).fetchone()
            if not row: raise RepositoryError(f"analysis invalidation not found: {invalidation_id}")
            resolution_id=_stable("invalidation-resolution",invalidation_id,action,actor,_now(),uuid.uuid4().hex)
            connection.execute("INSERT INTO analysis_invalidation_resolutions(resolution_id,invalidation_id,action,actor,notes) VALUES (?,?,?,?,?)",(resolution_id,row["id"],action,actor,notes))
            return {"resolution_id":resolution_id,"invalidation_id":invalidation_id,"action":action,"actor":actor,"notes":notes}

    def add_replication_review(self, run_id: str, status: str, reviewer: str, *, notes: str | None = None, evidence: Mapping[str, Any] | None = None, reproduced_run_id: str | None = None) -> dict[str, Any]:
        allowed={"pending","confirmed","partial","failed","not-reproducible"}
        if status not in allowed: raise AnalysisArtifactError("invalid replication status")
        evidence_payload=dict(evidence or {}); evidence_digest=hashlib.sha256(canonical_json(evidence_payload).encode("utf-8")).hexdigest()
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            run=connection.execute("SELECT id FROM analysis_runs WHERE run_id=?",(run_id,)).fetchone()
            if not run: raise RepositoryError(f"analysis run not found: {run_id}")
            reproduced_id=None
            if reproduced_run_id:
                row=connection.execute("SELECT id FROM analysis_runs WHERE run_id=?",(reproduced_run_id,)).fetchone()
                if not row: raise RepositoryError(f"reproduced run not found: {reproduced_run_id}")
                reproduced_id=row["id"]
            replication_id=_stable("replication",run_id,status,reviewer,evidence_digest,_now(),uuid.uuid4().hex)
            connection.execute(
                """INSERT INTO analysis_replication_reviews(replication_id,run_id,status,reviewer,reproduced_run_id,notes,evidence_json,evidence_sha256)
                   VALUES (?,?,?,?,?,?,?,?)""",(replication_id,run["id"],status,reviewer,reproduced_id,notes,canonical_json(evidence_payload),evidence_digest),
            )
        return {"replication_id":replication_id,"run_id":run_id,"status":status,"reviewer":reviewer,"notes":notes,"evidence":evidence_payload,"evidence_sha256":evidence_digest}

    def _package_files(self, run_id: str) -> tuple[dict[str, bytes], dict[str, Any]]:
        details=self.run_details(run_id,include_payloads=True)
        files_map: dict[str,bytes]={}
        files_map["analysis-definition.json"]=(json.dumps(details["definition"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        files_map["environment.json"]=(json.dumps(details["environment"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        files_map["code-reference.json"]=(json.dumps(details["code_reference"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        files_map["parameters.json"]=(json.dumps(details["parameters"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        input_index=[]
        for item in details["inputs"]:
            filename=f"inputs/{item['ordinal']:04d}-{_safe_name(item['record_id'])}.json"
            files_map[filename]=(json.dumps(item["payload"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
            input_index.append({key:value for key,value in item.items() if key!="payload"}|{"path":filename})
        files_map["inputs/index.json"]=(json.dumps(input_index,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        with closing(connect(self.repository.path,readonly=True)) as connection:
            run_row=connection.execute("SELECT id FROM analysis_runs WHERE run_id=?",(run_id,)).fetchone()
            output_index=[]
            for ordinal,row in enumerate(connection.execute("SELECT output_id,output_type,name,media_type,content_blob,external_uri,payload_sha256,byte_size,metadata_json FROM analysis_outputs WHERE run_id=? ORDER BY id",(run_row["id"],)).fetchall()):
                item=dict(row); data=bytes(item.pop("content_blob") or b""); metadata=json.loads(item.pop("metadata_json"))
                suffix=mimetypes.guess_extension(item["media_type"].split(";")[0].strip()) or Path(item["name"]).suffix or ".bin"
                filename=f"outputs/{ordinal:04d}-{_safe_name(Path(item['name']).stem)}{suffix}"
                files_map[filename]=data
                item["metadata"]=metadata; item["path"]=filename; output_index.append(item)
            files_map["outputs/index.json"]=(json.dumps(output_index,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        provenance={}
        review={}
        for item in details["inputs"]:
            provenance[item["record_id"]]=self.repository.provenance(item["record_id"])
            review[item["record_id"]]=self.repository.review_history(item["record_id"])
        files_map["provenance/records.json"]=(json.dumps(provenance,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        files_map["review/records.json"]=(json.dumps(review,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        files_map["invalidation-warnings.json"]=(json.dumps(details["invalidations"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        files_map["replication-reviews.json"]=(json.dumps(details["replications"],ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        readme=(f"# Reproducible Analysis Package\n\nArtifact: {details['artifact_id']}\nRun: {run_id}\nVersion: {details['version']}\n"
                f"Status: {details['status']}\nInputs: {len(details['inputs'])}\nOutputs: {len(details['outputs'])}\n\n"
                "This package freezes the exact canonical records, parameters, environment, code reference, outputs, provenance, and review state used by the run.\n")
        files_map["README.md"]=readme.encode()
        checksums={name:hashlib.sha256(data).hexdigest() for name,data in sorted(files_map.items())}
        manifest={
            "schema_version":PACKAGE_SCHEMA_VERSION,
            "artifact_id":details["artifact_id"],"run_id":run_id,"analysis_version":details["version"],
            "started_at":details["started_at"],"finished_at":details["finished_at"],
            "input_manifest_sha256":details["input_manifest_sha256"],"output_manifest_sha256":details["output_manifest_sha256"],
            "reproducibility_status":details["reproducibility_status"],"files":checksums,
        }
        files_map["manifest.json"]=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
        checksum_lines=[f"{hashlib.sha256(files_map[name]).hexdigest()}  {name}" for name in sorted(files_map)]
        files_map["SHA256SUMS"]=("\n".join(checksum_lines)+"\n").encode()
        return files_map,manifest

    @staticmethod
    def _zip_bytes(files_map: Mapping[str,bytes]) -> bytes:
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for name in sorted(files_map):
                info=zipfile.ZipInfo(name,FIXED_ZIP_DATE); info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=0o100644<<16; info.create_system=3
                archive.writestr(info,files_map[name])
        return stream.getvalue()

    def export_package(self, run_id: str, output: str | Path, *, actor: str = "principal:system") -> dict[str, Any]:
        output_path=Path(output); files_map,manifest=self._package_files(run_id)
        if output_path.suffix.lower()==".zip":
            payload=self._zip_bytes(files_map); output_path.parent.mkdir(parents=True,exist_ok=True); output_path.write_bytes(payload); format_name="zip"
        else:
            output_path.mkdir(parents=True,exist_ok=True)
            for name,data in sorted(files_map.items()):
                target=output_path/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
            payload=canonical_json({name:hashlib.sha256(data).hexdigest() for name,data in sorted(files_map.items())}).encode(); format_name="directory"
        package_digest=hashlib.sha256(payload).hexdigest(); package_id=_stable("analysis-package",run_id,package_digest)
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            run=connection.execute("SELECT id FROM analysis_runs WHERE run_id=?",(run_id,)).fetchone()
            if not run: raise RepositoryError(f"analysis run not found: {run_id}")
            connection.execute(
                """INSERT OR IGNORE INTO analysis_package_exports(package_id,run_id,schema_version,manifest_json,package_sha256,byte_size,format,created_by)
                   VALUES (?,?,?,?,?,?,?,?)""",(package_id,run["id"],PACKAGE_SCHEMA_VERSION,canonical_json(manifest),package_digest,len(payload),format_name,actor),
            )
        return {"package_id":package_id,"run_id":run_id,"path":str(output_path),"format":format_name,"package_sha256":package_digest,"byte_size":len(payload),"manifest":manifest}

    def packages(self, run_id: str | None = None) -> list[dict[str, Any]]:
        sql="""SELECT ape.package_id,ar.run_id,aa.artifact_id,ape.schema_version,ape.package_sha256,ape.byte_size,ape.format,ape.created_by,ape.created_at,ape.manifest_json
               FROM analysis_package_exports ape JOIN analysis_runs ar ON ar.id=ape.run_id JOIN analysis_artifacts aa ON aa.id=ar.artifact_id"""
        params=[]
        if run_id: sql+=" WHERE ar.run_id=?"; params.append(run_id)
        sql+=" ORDER BY ape.id DESC"
        with closing(connect(self.repository.path,readonly=True)) as connection:
            result=[]
            for row in connection.execute(sql,params).fetchall():
                item=dict(row); item["manifest"]=json.loads(item.pop("manifest_json")); result.append(item)
            return result
