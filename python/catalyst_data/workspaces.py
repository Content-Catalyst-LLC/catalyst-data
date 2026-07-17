from __future__ import annotations

import hashlib
import uuid
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .database import connect, transaction
from .repository import CatalystRepository, RepositoryError, canonical_json

ACCESS_GOVERNANCE_CONTRACT = "catalyst-data-access-governance/1.0"
ACCESS_GOVERNANCE_SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-access-governance-1.0.json"

WORKSPACE_ROLES = ("viewer", "contributor", "analyst", "reviewer", "approver", "publisher", "administrator")
WORKSPACE_VISIBILITIES = ("private", "shared", "institutional", "public")
DATA_CLASSIFICATIONS = ("public", "internal", "restricted", "confidential")
PRINCIPAL_TYPES = ("user", "service", "group")


class AccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class AccessContext:
    principal_id: str
    workspace_id: str
    role: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    import re
    clean = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return clean[:80] or "workspace"


def _stable(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{_slug(parts[0] if parts else prefix)}:{digest}"


def _event_id(event_type: str, actor: str, occurred_at: str, details: Mapping[str, Any]) -> str:
    # Events may occur more than once in the same second with identical details.
    # A random nonce prevents primary-key collisions without weakening the
    # append-only event payload or its audit timestamps.
    nonce = uuid.uuid4().hex
    return "access-event:" + hashlib.sha256(
        f"{event_type}|{actor}|{occurred_at}|{canonical_json(details)}|{nonce}".encode("utf-8")
    ).hexdigest()[:24]


class WorkspaceService:
    def __init__(self, repository: CatalystRepository | str | Path):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()

    def _event(
        self,
        connection,
        event_type: str,
        actor: str,
        details: Mapping[str, Any],
        *,
        workspace_row_id: int | None = None,
        record_id: str | None = None,
        principal_row_id: int | None = None,
    ) -> None:
        occurred = _now()
        connection.execute(
            """INSERT INTO access_governance_events(
                event_id,workspace_id,record_id,principal_id,event_type,actor,details_json,occurred_at
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                _event_id(event_type, actor, occurred, details),
                workspace_row_id,
                record_id,
                principal_row_id,
                event_type,
                actor,
                canonical_json(details),
                occurred,
            ),
        )

    @staticmethod
    def _workspace_row(connection, workspace_id: str):
        row = connection.execute(
            """SELECT w.*,i.institution_id FROM workspaces w
               JOIN institutions i ON i.id=w.institution_id WHERE w.workspace_id=?""",
            (workspace_id,),
        ).fetchone()
        if not row:
            raise RepositoryError(f"workspace not found: {workspace_id}")
        return row

    @staticmethod
    def _principal_row(connection, principal_id: str):
        row = connection.execute("SELECT * FROM principals WHERE principal_id=?", (principal_id,)).fetchone()
        if not row:
            raise RepositoryError(f"principal not found: {principal_id}")
        return row

    def create_institution(self, name: str, *, institution_id: str | None = None, actor: str = "system", metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean = name.strip()
        if not clean:
            raise ValueError("institution name is required")
        institution_id = institution_id or _stable("institution", clean)
        slug = _slug(clean)
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute(
                "INSERT INTO institutions(institution_id,name,slug,metadata_json) VALUES (?,?,?,?)",
                (institution_id, clean, slug, canonical_json(metadata or {})),
            )
            self._event(connection, "institution_created", actor, {"institution_id": institution_id, "name": clean})
        return self.institution(institution_id)

    def institution(self, institution_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute("SELECT institution_id,name,slug,status,metadata_json,created_at,updated_at FROM institutions WHERE institution_id=?", (institution_id,)).fetchone()
            if not row:
                raise RepositoryError(f"institution not found: {institution_id}")
            item = dict(row); item["metadata"] = json.loads(item.pop("metadata_json")); return item

    def institutions(self) -> list[dict[str, Any]]:
        with connect(self.repository.path, readonly=True) as connection:
            rows = connection.execute("SELECT institution_id,name,slug,status,metadata_json,created_at,updated_at FROM institutions ORDER BY name").fetchall()
            result=[]
            for row in rows:
                item=dict(row); item["metadata"]=json.loads(item.pop("metadata_json")); result.append(item)
            return result

    def create_workspace(
        self,
        institution_id: str,
        name: str,
        *,
        workspace_id: str | None = None,
        visibility: str = "private",
        classification: str = "internal",
        actor: str = "system",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if visibility not in WORKSPACE_VISIBILITIES:
            raise ValueError("invalid workspace visibility")
        if classification not in DATA_CLASSIFICATIONS:
            raise ValueError("invalid workspace classification")
        clean = name.strip()
        workspace_id = workspace_id or _stable("workspace", institution_id, clean)
        with connect(self.repository.path) as connection, transaction(connection):
            institution = connection.execute("SELECT id FROM institutions WHERE institution_id=?", (institution_id,)).fetchone()
            if not institution:
                raise RepositoryError(f"institution not found: {institution_id}")
            retention = connection.execute("SELECT id FROM retention_policies WHERE institution_id=? AND active=1 ORDER BY id LIMIT 1", (institution["id"],)).fetchone()
            connection.execute(
                """INSERT INTO workspaces(workspace_id,institution_id,name,slug,visibility,classification,default_retention_policy_id,metadata_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (workspace_id, institution["id"], clean, _slug(clean), visibility, classification, retention["id"] if retention else None, canonical_json(metadata or {})),
            )
            workspace_row = connection.execute("SELECT id FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
            self._event(connection, "workspace_created", actor, {"workspace_id": workspace_id, "institution_id": institution_id, "name": clean}, workspace_row_id=workspace_row["id"])
        return self.workspace(workspace_id)

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row = connection.execute(
                """SELECT w.workspace_id,w.name,w.slug,w.visibility,w.classification,w.status,w.metadata_json,
                          i.institution_id,r.policy_id AS default_retention_policy_id,w.created_at,w.updated_at
                   FROM workspaces w JOIN institutions i ON i.id=w.institution_id
                   LEFT JOIN retention_policies r ON r.id=w.default_retention_policy_id
                   WHERE w.workspace_id=?""",
                (workspace_id,),
            ).fetchone()
            if not row:
                raise RepositoryError(f"workspace not found: {workspace_id}")
            item=dict(row); item["metadata"]=json.loads(item.pop("metadata_json")); return item

    def workspaces(self, *, institution_id: str | None = None) -> list[dict[str, Any]]:
        sql="""SELECT w.workspace_id,w.name,w.slug,w.visibility,w.classification,w.status,i.institution_id,
                      COUNT(DISTINCT wm.id) AS member_count,COUNT(DISTINCT rag.id) AS record_count
               FROM workspaces w JOIN institutions i ON i.id=w.institution_id
               LEFT JOIN workspace_memberships wm ON wm.workspace_id=w.id AND wm.status='active'
               LEFT JOIN record_access_governance rag ON rag.workspace_id=w.id"""
        params=[]
        if institution_id:
            sql += " WHERE i.institution_id=?"; params.append(institution_id)
        sql += " GROUP BY w.id ORDER BY i.name,w.name"
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def create_project(self, workspace_id: str, name: str, *, project_id: str | None = None, actor: str = "system", metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean=name.strip(); project_id=project_id or _stable("project", workspace_id, clean)
        with connect(self.repository.path) as connection, transaction(connection):
            workspace=self._workspace_row(connection,workspace_id)
            connection.execute("INSERT INTO projects(project_id,workspace_id,name,slug,metadata_json) VALUES (?,?,?,?,?)",(project_id,workspace["id"],clean,_slug(clean),canonical_json(metadata or {})))
            self._event(connection,"project_created",actor,{"project_id":project_id,"workspace_id":workspace_id,"name":clean},workspace_row_id=workspace["id"])
        return {"project_id":project_id,"workspace_id":workspace_id,"name":clean,"status":"active"}

    def create_principal(self, display_name: str, *, principal_type: str = "user", email: str | None = None, principal_id: str | None = None, actor: str = "system", metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if principal_type not in PRINCIPAL_TYPES:
            raise ValueError("invalid principal type")
        clean=display_name.strip(); principal_id=principal_id or _stable("principal", email or clean, principal_type)
        with connect(self.repository.path) as connection, transaction(connection):
            connection.execute("INSERT INTO principals(principal_id,principal_type,display_name,email,metadata_json) VALUES (?,?,?,?,?)",(principal_id,principal_type,clean,email,canonical_json(metadata or {})))
            row=connection.execute("SELECT id FROM principals WHERE principal_id=?",(principal_id,)).fetchone()
            self._event(connection,"principal_created",actor,{"principal_id":principal_id,"type":principal_type},principal_row_id=row["id"])
        return self.principal(principal_id)

    def principal(self, principal_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row=connection.execute("SELECT principal_id,principal_type,display_name,email,active,metadata_json,created_at,updated_at FROM principals WHERE principal_id=?",(principal_id,)).fetchone()
            if not row: raise RepositoryError(f"principal not found: {principal_id}")
            item=dict(row); item["active"]=bool(item["active"]); item["metadata"]=json.loads(item.pop("metadata_json")); return item

    def principals(self) -> list[dict[str, Any]]:
        with connect(self.repository.path, readonly=True) as connection:
            return [dict(row) for row in connection.execute("SELECT principal_id,principal_type,display_name,email,active,created_at FROM principals ORDER BY display_name").fetchall()]

    def add_member(self, workspace_id: str, principal_id: str, role: str, *, actor: str = "system", expires_at: str | None = None) -> dict[str, Any]:
        if role not in WORKSPACE_ROLES:
            raise ValueError("invalid workspace role")
        with connect(self.repository.path) as connection, transaction(connection):
            workspace=self._workspace_row(connection,workspace_id); principal=self._principal_row(connection,principal_id)
            existing=connection.execute("SELECT role FROM workspace_memberships WHERE workspace_id=? AND principal_id=?",(workspace["id"],principal["id"])).fetchone()
            connection.execute(
                """INSERT INTO workspace_memberships(workspace_id,principal_id,role,status,expires_at,granted_by)
                   VALUES (?,?,?,'active',?,?)
                   ON CONFLICT(workspace_id,principal_id) DO UPDATE SET role=excluded.role,status='active',expires_at=excluded.expires_at,granted_by=excluded.granted_by""",
                (workspace["id"],principal["id"],role,expires_at,actor),
            )
            self._event(connection,"membership_changed" if existing else "membership_granted",actor,{"workspace_id":workspace_id,"principal_id":principal_id,"role":role,"previous_role":existing["role"] if existing else None},workspace_row_id=workspace["id"],principal_row_id=principal["id"])
        return {"workspace_id":workspace_id,"principal_id":principal_id,"role":role,"status":"active","expires_at":expires_at}

    def members(self, workspace_id: str) -> list[dict[str, Any]]:
        with connect(self.repository.path, readonly=True) as connection:
            workspace=self._workspace_row(connection,workspace_id)
            rows=connection.execute("""SELECT p.principal_id,p.principal_type,p.display_name,p.email,wm.role,wm.status,wm.joined_at,wm.expires_at
                                      FROM workspace_memberships wm JOIN principals p ON p.id=wm.principal_id
                                      WHERE wm.workspace_id=? ORDER BY p.display_name""",(workspace["id"],)).fetchall()
            return [dict(row) for row in rows]

    def context(self, principal_id: str, workspace_id: str) -> AccessContext | None:
        with connect(self.repository.path, readonly=True) as connection:
            row=connection.execute("""SELECT wm.role,wm.status,wm.expires_at FROM workspace_memberships wm
                                      JOIN workspaces w ON w.id=wm.workspace_id JOIN principals p ON p.id=wm.principal_id
                                      WHERE w.workspace_id=? AND p.principal_id=? AND p.active=1 AND w.status='active'""",(workspace_id,principal_id)).fetchone()
            if not row or row["status"]!="active": return None
            if row["expires_at"] and row["expires_at"] <= _now(): return None
            return AccessContext(principal_id,workspace_id,row["role"])

    def authorize(self, principal_id: str, workspace_id: str, permission: str, *, record_id: str | None = None, audit: bool = True) -> AccessContext:
        ctx=self.context(principal_id,workspace_id)
        allowed=False
        workspace_row_id=None; principal_row_id=None
        with connect(self.repository.path) as connection, transaction(connection):
            workspace=self._workspace_row(connection,workspace_id); workspace_row_id=workspace["id"]
            principal=self._principal_row(connection,principal_id); principal_row_id=principal["id"]
            if ctx:
                allowed=bool(connection.execute("SELECT 1 FROM role_permissions WHERE role=? AND permission IN (?, '*')",(ctx.role,permission)).fetchone())
            if audit:
                self._event(connection,"access_allowed" if allowed else "access_denied",principal_id,{"permission":permission,"workspace_id":workspace_id,"record_id":record_id,"role":ctx.role if ctx else None},workspace_row_id=workspace_row_id,record_id=record_id,principal_row_id=principal_row_id)
        if not allowed or ctx is None:
            raise AccessDenied(f"{principal_id} is not authorized for {permission} in {workspace_id}")
        return ctx

    def create_retention_policy(self, institution_id: str, name: str, *, retention_days: int | None = None, disposition_action: str = "review", policy_id: str | None = None, description: str | None = None, actor: str = "system") -> dict[str, Any]:
        if retention_days is not None and retention_days < 0: raise ValueError("retention_days cannot be negative")
        if disposition_action not in ("review","archive","delete"): raise ValueError("invalid disposition action")
        policy_id=policy_id or _stable("retention",institution_id,name)
        with connect(self.repository.path) as connection, transaction(connection):
            inst=connection.execute("SELECT id FROM institutions WHERE institution_id=?",(institution_id,)).fetchone()
            if not inst: raise RepositoryError(f"institution not found: {institution_id}")
            connection.execute("INSERT INTO retention_policies(policy_id,institution_id,name,retention_days,disposition_action,description) VALUES (?,?,?,?,?,?)",(policy_id,inst["id"],name.strip(),retention_days,disposition_action,description))
        return {"policy_id":policy_id,"institution_id":institution_id,"name":name.strip(),"retention_days":retention_days,"disposition_action":disposition_action,"description":description}

    def retention_policies(self, institution_id: str | None = None) -> list[dict[str, Any]]:
        sql="""SELECT r.policy_id,i.institution_id,r.name,r.retention_days,r.disposition_action,r.description,r.active,r.created_at
               FROM retention_policies r JOIN institutions i ON i.id=r.institution_id"""; params=[]
        if institution_id: sql+=" WHERE i.institution_id=?"; params.append(institution_id)
        sql+=" ORDER BY i.name,r.name"
        with connect(self.repository.path, readonly=True) as connection: return [dict(row) for row in connection.execute(sql,params).fetchall()]

    def assign_record(
        self,
        record_id: str,
        workspace_id: str,
        *,
        actor: str,
        project_id: str | None = None,
        owner_principal_id: str | None = None,
        steward_principal_id: str | None = None,
        custodian_principal_id: str | None = None,
        visibility: str | None = None,
        classification: str | None = None,
        retention_policy_id: str | None = None,
    ) -> dict[str, Any]:
        if visibility is not None and visibility not in WORKSPACE_VISIBILITIES: raise ValueError("invalid visibility")
        if classification is not None and classification not in DATA_CLASSIFICATIONS: raise ValueError("invalid classification")
        with connect(self.repository.path) as connection, transaction(connection):
            if not connection.execute("SELECT 1 FROM data_records WHERE record_id=?",(record_id,)).fetchone(): raise RepositoryError(f"record not found: {record_id}")
            workspace=self._workspace_row(connection,workspace_id)
            old=connection.execute("SELECT * FROM record_access_governance WHERE record_id=?",(record_id,)).fetchone()
            project_row=None
            if project_id:
                project_row=connection.execute("SELECT id FROM projects WHERE project_id=? AND workspace_id=?",(project_id,workspace["id"])).fetchone()
                if not project_row: raise RepositoryError(f"project not found in workspace: {project_id}")
            def principal_row_id(value: str | None):
                return self._principal_row(connection,value)["id"] if value else None
            retention_row=None
            if retention_policy_id:
                retention_row=connection.execute("SELECT id,retention_days FROM retention_policies WHERE policy_id=? AND institution_id=?",(retention_policy_id,workspace["institution_id"] if "institution_id" in workspace.keys() else workspace["institution_id"])).fetchone()
                if not retention_row: raise RepositoryError(f"retention policy not found: {retention_policy_id}")
            else:
                retention_row=connection.execute("SELECT id,retention_days FROM retention_policies WHERE id=?",(workspace["default_retention_policy_id"],)).fetchone() if workspace["default_retention_policy_id"] else None
            due=None
            if retention_row and retention_row["retention_days"] is not None:
                due=(datetime.now(timezone.utc)+timedelta(days=int(retention_row["retention_days"]))).replace(microsecond=0).isoformat().replace("+00:00","Z")
            values={
                "project_id":project_row["id"] if project_row else (old["project_id"] if old else None),
                "owner":principal_row_id(owner_principal_id) if owner_principal_id else (old["owner_principal_id"] if old else None),
                "steward":principal_row_id(steward_principal_id) if steward_principal_id else (old["steward_principal_id"] if old else None),
                "custodian":principal_row_id(custodian_principal_id) if custodian_principal_id else (old["custodian_principal_id"] if old else None),
                "visibility":visibility or (old["visibility"] if old else workspace["visibility"]),
                "classification":classification or (old["classification"] if old else workspace["classification"]),
                "retention":retention_row["id"] if retention_row else (old["retention_policy_id"] if old else None),
                "due":due if retention_policy_id else (old["disposition_due_at"] if old else due),
            }
            connection.execute("""INSERT INTO record_access_governance(record_id,workspace_id,project_id,owner_principal_id,steward_principal_id,custodian_principal_id,visibility,classification,retention_policy_id,disposition_due_at,updated_at)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?)
                                  ON CONFLICT(record_id) DO UPDATE SET workspace_id=excluded.workspace_id,project_id=excluded.project_id,owner_principal_id=excluded.owner_principal_id,steward_principal_id=excluded.steward_principal_id,custodian_principal_id=excluded.custodian_principal_id,visibility=excluded.visibility,classification=excluded.classification,retention_policy_id=excluded.retention_policy_id,disposition_due_at=excluded.disposition_due_at,updated_at=excluded.updated_at""",
                               (record_id,workspace["id"],values["project_id"],values["owner"],values["steward"],values["custodian"],values["visibility"],values["classification"],values["retention"],values["due"],_now()))
            event_type="record_transferred" if old and old["workspace_id"]!=workspace["id"] else "record_assigned"
            self._event(connection,event_type,actor,{"record_id":record_id,"workspace_id":workspace_id,"visibility":values["visibility"],"classification":values["classification"]},workspace_row_id=workspace["id"],record_id=record_id)
            if event_type=="record_transferred":
                transfer_id="transfer:"+hashlib.sha256(f"{record_id}|{old['workspace_id']}|{workspace['id']}|{_now()}".encode()).hexdigest()[:24]
                connection.execute("INSERT INTO workspace_transfer_events(transfer_id,record_id,from_workspace_id,to_workspace_id,actor,reason) VALUES (?,?,?,?,?,?)",(transfer_id,record_id,old["workspace_id"],workspace["id"],actor,"Workspace reassignment"))
        return self.record_access(record_id)

    def record_access(self, record_id: str) -> dict[str, Any]:
        with connect(self.repository.path, readonly=True) as connection:
            row=connection.execute("SELECT * FROM workspace_record_access WHERE record_id=?",(record_id,)).fetchone()
            if not row: raise RepositoryError(f"record access governance not found: {record_id}")
            item=dict(row); item["legal_hold"]=bool(item["legal_hold"]); item["schema_version"]=ACCESS_GOVERNANCE_CONTRACT; return item

    def records(self, workspace_id: str, *, principal_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if principal_id: self.authorize(principal_id,workspace_id,"records:read")
        with connect(self.repository.path, readonly=True) as connection:
            workspace=self._workspace_row(connection,workspace_id)
            rows=connection.execute("""SELECT dr.payload_json,rag.visibility,rag.classification,rag.legal_hold,rag.disposition_due_at
                                      FROM record_access_governance rag JOIN data_records dr ON dr.record_id=rag.record_id
                                      WHERE rag.workspace_id=? ORDER BY dr.updated_at DESC LIMIT ?""",(workspace["id"],limit)).fetchall()
            result=[]
            for row in rows:
                item=json.loads(row["payload_json"]); item["access_governance"]={"workspace_id":workspace_id,"visibility":row["visibility"],"classification":row["classification"],"legal_hold":bool(row["legal_hold"]),"disposition_due_at":row["disposition_due_at"]}; result.append(item)
            return result

    def set_visibility(self, record_id: str, visibility: str, classification: str, *, actor: str) -> dict[str, Any]:
        if visibility not in WORKSPACE_VISIBILITIES or classification not in DATA_CLASSIFICATIONS: raise ValueError("invalid visibility or classification")
        with connect(self.repository.path) as connection, transaction(connection):
            row=connection.execute("SELECT workspace_id,visibility,classification FROM record_access_governance WHERE record_id=?",(record_id,)).fetchone()
            if not row: raise RepositoryError(f"record not found: {record_id}")
            connection.execute("UPDATE record_access_governance SET visibility=?,classification=?,updated_at=? WHERE record_id=?",(visibility,classification,_now(),record_id))
            self._event(connection,"visibility_changed",actor,{"from":row["visibility"],"to":visibility,"classification_from":row["classification"],"classification_to":classification},workspace_row_id=row["workspace_id"],record_id=record_id)
        return self.record_access(record_id)

    def set_legal_hold(self, record_id: str, enabled: bool, *, actor: str, reason: str | None = None) -> dict[str, Any]:
        with connect(self.repository.path) as connection, transaction(connection):
            row=connection.execute("SELECT workspace_id,legal_hold FROM record_access_governance WHERE record_id=?",(record_id,)).fetchone()
            if not row: raise RepositoryError(f"record not found: {record_id}")
            connection.execute("UPDATE record_access_governance SET legal_hold=?,updated_at=? WHERE record_id=?",(1 if enabled else 0,_now(),record_id))
            self._event(connection,"legal_hold_set" if enabled else "legal_hold_released",actor,{"enabled":enabled,"reason":reason},workspace_row_id=row["workspace_id"],record_id=record_id)
        return self.record_access(record_id)

    def can_dispose(self, record_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        access=self.record_access(record_id); as_of=as_of or _now()
        reasons=[]
        if access["legal_hold"]: reasons.append("legal hold is active")
        if not access["disposition_due_at"]: reasons.append("no disposition date is assigned")
        elif access["disposition_due_at"] > as_of: reasons.append("retention period has not expired")
        return {"record_id":record_id,"eligible":not reasons,"reasons":reasons,"as_of":as_of,"disposition_due_at":access["disposition_due_at"]}

    def events(self, *, workspace_id: str | None = None, record_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql="""SELECT age.event_id,w.workspace_id,age.record_id,p.principal_id,age.event_type,age.actor,age.details_json,age.occurred_at
               FROM access_governance_events age LEFT JOIN workspaces w ON w.id=age.workspace_id LEFT JOIN principals p ON p.id=age.principal_id WHERE 1=1"""; params=[]
        if workspace_id: sql+=" AND w.workspace_id=?"; params.append(workspace_id)
        if record_id: sql+=" AND age.record_id=?"; params.append(record_id)
        sql+=" ORDER BY age.id DESC LIMIT ?"; params.append(limit)
        with connect(self.repository.path, readonly=True) as connection:
            result=[]
            for row in connection.execute(sql,params).fetchall():
                item=dict(row); item["details"]=json.loads(item.pop("details_json")); result.append(item)
            return result

    def bind_api_key(self, key_id: str, workspace_id: str, principal_id: str) -> None:
        with connect(self.repository.path) as connection, transaction(connection):
            workspace=self._workspace_row(connection,workspace_id); principal=self._principal_row(connection,principal_id)
            connection.execute("INSERT INTO api_client_workspace_bindings(key_id,workspace_id,principal_id) VALUES (?,?,?) ON CONFLICT(key_id) DO UPDATE SET workspace_id=excluded.workspace_id,principal_id=excluded.principal_id",(key_id,workspace["id"],principal["id"]))

    def export_workspace_manifest(self, workspace_id: str, *, principal_id: str, actor: str | None = None) -> dict[str, Any]:
        self.authorize(principal_id,workspace_id,"exports:create")
        records=self.records(workspace_id)
        payload={"schema_version":"catalyst-data-workspace-export/1.0","workspace":self.workspace(workspace_id),"record_count":len(records),"records":[{"record_id":r["record_id"],"payload_sha256":hashlib.sha256(canonical_json(r).encode()).hexdigest()} for r in records],"exported_at":_now(),"exported_by":actor or principal_id}
        with connect(self.repository.path) as connection, transaction(connection):
            workspace=self._workspace_row(connection,workspace_id); principal=self._principal_row(connection,principal_id)
            self._event(connection,"workspace_exported",actor or principal_id,{"record_count":len(records),"manifest_sha256":hashlib.sha256(canonical_json(payload).encode()).hexdigest()},workspace_row_id=workspace["id"],principal_row_id=principal["id"])
        return payload
