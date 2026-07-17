CREATE TABLE institutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE principals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    principal_id TEXT NOT NULL UNIQUE,
    principal_type TEXT NOT NULL CHECK(principal_type IN ('user','service','group')),
    display_name TEXT NOT NULL,
    email TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE retention_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id TEXT NOT NULL UNIQUE,
    institution_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    retention_days INTEGER CHECK(retention_days IS NULL OR retention_days >= 0),
    disposition_action TEXT NOT NULL DEFAULT 'review' CHECK(disposition_action IN ('review','archive','delete')),
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(institution_id) REFERENCES institutions(id) ON DELETE CASCADE
);

CREATE TABLE workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL UNIQUE,
    institution_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','shared','institutional','public')),
    classification TEXT NOT NULL DEFAULT 'internal' CHECK(classification IN ('public','internal','restricted','confidential')),
    default_retention_policy_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(institution_id, slug),
    FOREIGN KEY(institution_id) REFERENCES institutions(id) ON DELETE CASCADE,
    FOREIGN KEY(default_retention_policy_id) REFERENCES retention_policies(id) ON DELETE SET NULL
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, slug),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE workspace_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    principal_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('viewer','contributor','analyst','reviewer','approver','publisher','administrator')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','invited','suspended','expired','revoked')),
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    granted_by TEXT,
    UNIQUE(workspace_id, principal_id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE CASCADE
);

CREATE TABLE role_permissions (
    role TEXT NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY(role, permission)
);

CREATE TABLE record_access_governance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER NOT NULL,
    project_id INTEGER,
    owner_principal_id INTEGER,
    steward_principal_id INTEGER,
    custodian_principal_id INTEGER,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','shared','institutional','public')),
    classification TEXT NOT NULL DEFAULT 'internal' CHECK(classification IN ('public','internal','restricted','confidential')),
    retention_policy_id INTEGER,
    legal_hold INTEGER NOT NULL DEFAULT 0 CHECK(legal_hold IN (0,1)),
    disposition_due_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY(owner_principal_id) REFERENCES principals(id) ON DELETE SET NULL,
    FOREIGN KEY(steward_principal_id) REFERENCES principals(id) ON DELETE SET NULL,
    FOREIGN KEY(custodian_principal_id) REFERENCES principals(id) ON DELETE SET NULL,
    FOREIGN KEY(retention_policy_id) REFERENCES retention_policies(id) ON DELETE SET NULL
);

CREATE TABLE api_client_workspace_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER NOT NULL,
    principal_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(key_id) REFERENCES api_clients(key_id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE CASCADE
);

CREATE TABLE access_governance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER,
    record_id TEXT,
    principal_id INTEGER,
    event_type TEXT NOT NULL CHECK(event_type IN ('institution_created','workspace_created','project_created','principal_created','membership_granted','membership_changed','record_assigned','visibility_changed','classification_changed','retention_assigned','legal_hold_set','legal_hold_released','record_transferred','access_allowed','access_denied','workspace_exported')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE SET NULL,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE SET NULL
);

CREATE TABLE workspace_transfer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    from_workspace_id INTEGER,
    to_workspace_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE CASCADE,
    FOREIGN KEY(from_workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
    FOREIGN KEY(to_workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

INSERT INTO role_permissions(role,permission) VALUES
('viewer','records:read'),
('contributor','records:read'),('contributor','records:write'),
('analyst','records:read'),('analyst','records:write'),('analyst','queries:run'),('analyst','exports:create'),('analyst','handoffs:write'),
('reviewer','records:read'),('reviewer','reviews:comment'),('reviewer','reviews:decide'),
('approver','records:read'),('approver','reviews:comment'),('approver','reviews:decide'),('approver','records:approve'),
('publisher','records:read'),('publisher','records:publish'),('publisher','exports:create'),('publisher','handoffs:write'),
('administrator','*');

INSERT INTO institutions(institution_id,name,slug,metadata_json)
VALUES ('institution:sustainable-catalyst','Sustainable Catalyst','sustainable-catalyst','{"system_default":true}');

INSERT INTO principals(principal_id,principal_type,display_name,email,metadata_json)
VALUES ('principal:system','service','Catalyst Data System',NULL,'{"system_default":true}');

INSERT INTO retention_policies(policy_id,institution_id,name,retention_days,disposition_action,description)
SELECT 'retention:default',id,'Default retention',NULL,'review','Retain until an authorized institutional review.' FROM institutions WHERE institution_id='institution:sustainable-catalyst';

INSERT INTO workspaces(workspace_id,institution_id,name,slug,visibility,classification,default_retention_policy_id,metadata_json)
SELECT 'workspace:default',i.id,'Default Workspace','default','institutional','internal',r.id,'{"system_default":true}'
FROM institutions i JOIN retention_policies r ON r.institution_id=i.id
WHERE i.institution_id='institution:sustainable-catalyst' AND r.policy_id='retention:default';

INSERT INTO workspace_memberships(workspace_id,principal_id,role,status,granted_by)
SELECT w.id,p.id,'administrator','active','migration-009'
FROM workspaces w CROSS JOIN principals p
WHERE w.workspace_id='workspace:default' AND p.principal_id='principal:system';

INSERT INTO record_access_governance(record_id,workspace_id,owner_principal_id,steward_principal_id,custodian_principal_id,visibility,classification,retention_policy_id)
SELECT dr.record_id,w.id,p.id,p.id,p.id,
       CASE WHEN rc.current_state='approved' AND rc.publication_status='external' THEN 'public' ELSE 'private' END,
       CASE WHEN rc.current_state='approved' AND rc.publication_status='external' THEN 'public' ELSE 'internal' END,
       r.id
FROM data_records dr
JOIN workspaces w ON w.workspace_id='workspace:default'
JOIN principals p ON p.principal_id='principal:system'
JOIN retention_policies r ON r.policy_id='retention:default'
LEFT JOIN review_cases rc ON rc.record_id=dr.record_id;

INSERT INTO api_client_workspace_bindings(key_id,workspace_id,principal_id)
SELECT ac.key_id,w.id,p.id FROM api_clients ac
JOIN workspaces w ON w.workspace_id='workspace:default'
JOIN principals p ON p.principal_id='principal:system';

DROP VIEW IF EXISTS public_api_records;
CREATE VIEW public_api_records AS
SELECT dr.record_id, dr.payload_sha256, dr.payload_json, dr.created_at, dr.updated_at,
       rag.workspace_id AS workspace_row_id
FROM data_records dr
JOIN review_cases rc ON rc.record_id = dr.record_id
JOIN record_access_governance rag ON rag.record_id = dr.record_id
WHERE rc.current_state = 'approved'
  AND rc.publication_status = 'external'
  AND rag.visibility = 'public'
  AND rag.classification = 'public';

CREATE VIEW workspace_record_access AS
SELECT rag.record_id,w.workspace_id,w.name AS workspace_name,i.institution_id,i.name AS institution_name,
       p.project_id,p.name AS project_name,
       owner.principal_id AS owner_principal_id,steward.principal_id AS steward_principal_id,custodian.principal_id AS custodian_principal_id,
       rag.visibility,rag.classification,rp.policy_id AS retention_policy_id,rp.name AS retention_policy_name,
       rag.legal_hold,rag.disposition_due_at,rag.created_at,rag.updated_at
FROM record_access_governance rag
JOIN workspaces w ON w.id=rag.workspace_id
JOIN institutions i ON i.id=w.institution_id
LEFT JOIN projects p ON p.id=rag.project_id
LEFT JOIN principals owner ON owner.id=rag.owner_principal_id
LEFT JOIN principals steward ON steward.id=rag.steward_principal_id
LEFT JOIN principals custodian ON custodian.id=rag.custodian_principal_id
LEFT JOIN retention_policies rp ON rp.id=rag.retention_policy_id;

CREATE INDEX idx_workspace_memberships_lookup ON workspace_memberships(workspace_id,principal_id,status);
CREATE INDEX idx_record_access_workspace ON record_access_governance(workspace_id,visibility,classification);
CREATE INDEX idx_access_events_workspace ON access_governance_events(workspace_id,occurred_at,id);
CREATE INDEX idx_transfers_record ON workspace_transfer_events(record_id,occurred_at,id);


CREATE TRIGGER data_records_assign_default_workspace AFTER INSERT ON data_records
WHEN NOT EXISTS (SELECT 1 FROM record_access_governance WHERE record_id=NEW.record_id)
BEGIN
  INSERT INTO record_access_governance(record_id,workspace_id,owner_principal_id,steward_principal_id,custodian_principal_id,visibility,classification,retention_policy_id)
  SELECT NEW.record_id,w.id,p.id,p.id,p.id,'private','internal',r.id
  FROM workspaces w JOIN principals p ON p.principal_id='principal:system'
  JOIN retention_policies r ON r.policy_id='retention:default'
  WHERE w.workspace_id='workspace:default';
END;

CREATE TRIGGER access_governance_events_no_update BEFORE UPDATE ON access_governance_events
BEGIN SELECT RAISE(ABORT, 'access governance events are append-only'); END;
CREATE TRIGGER access_governance_events_no_delete BEFORE DELETE ON access_governance_events
BEGIN SELECT RAISE(ABORT, 'access governance events are append-only'); END;
CREATE TRIGGER workspace_transfer_events_no_update BEFORE UPDATE ON workspace_transfer_events
BEGIN SELECT RAISE(ABORT, 'workspace transfer events are append-only'); END;
CREATE TRIGGER workspace_transfer_events_no_delete BEFORE DELETE ON workspace_transfer_events
BEGIN SELECT RAISE(ABORT, 'workspace transfer events are append-only'); END;
