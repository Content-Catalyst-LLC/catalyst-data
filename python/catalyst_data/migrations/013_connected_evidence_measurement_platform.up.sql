-- Catalyst Data v2.0.0 connected evidence and measurement platform.

CREATE TABLE platform_contracts (
    id INTEGER PRIMARY KEY,
    contract_registration_id TEXT NOT NULL UNIQUE,
    contract_id TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    schema_uri TEXT,
    schema_path TEXT,
    schema_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deprecated','retired')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    registered_by TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (contract_id, schema_sha256)
);

CREATE TABLE platform_components (
    id INTEGER PRIMARY KEY,
    component_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    product_code TEXT NOT NULL,
    component_type TEXT NOT NULL CHECK (component_type IN ('core','platform-product','connector','external')),
    status TEXT NOT NULL DEFAULT 'unconfigured' CHECK (status IN ('active','degraded','offline','disabled','unconfigured')),
    current_version TEXT,
    endpoint TEXT,
    workspace_id TEXT REFERENCES workspaces(workspace_id),
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    contracts_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    registered_by TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE platform_component_versions (
    id INTEGER PRIMARY KEY,
    component_version_id TEXT NOT NULL UNIQUE,
    component_id TEXT NOT NULL REFERENCES platform_components(component_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    contracts_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    registered_by TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (component_id, version, manifest_sha256)
);

CREATE TABLE platform_links (
    id INTEGER PRIMARY KEY,
    link_id TEXT NOT NULL UNIQUE,
    source_component_id TEXT NOT NULL REFERENCES platform_components(component_id),
    target_component_id TEXT NOT NULL REFERENCES platform_components(component_id),
    relationship TEXT NOT NULL CHECK (relationship IN ('handoff','data-source','analysis','publication','embed','api','federation')),
    capability TEXT NOT NULL,
    contract_id TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','degraded','disabled')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_component_id, target_component_id, relationship, capability)
);

CREATE TABLE platform_release_snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    release_version TEXT NOT NULL,
    repository_id TEXT,
    migration_version INTEGER NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE platform_integrity_checks (
    id INTEGER PRIMARY KEY,
    check_id TEXT NOT NULL UNIQUE,
    snapshot_id TEXT REFERENCES platform_release_snapshots(snapshot_id),
    subsystem TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pass','warning','fail')),
    details_json TEXT NOT NULL DEFAULT '{}',
    checked_by TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE platform_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    component_id TEXT REFERENCES platform_components(component_id),
    link_id TEXT REFERENCES platform_links(link_id),
    snapshot_id TEXT REFERENCES platform_release_snapshots(snapshot_id),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX platform_contracts_contract_idx ON platform_contracts(contract_id, status);
CREATE INDEX platform_components_status_idx ON platform_components(status, component_type);
CREATE INDEX platform_component_versions_component_idx ON platform_component_versions(component_id, id DESC);
CREATE INDEX platform_links_source_idx ON platform_links(source_component_id, status);
CREATE INDEX platform_links_target_idx ON platform_links(target_component_id, status);
CREATE INDEX platform_snapshots_release_idx ON platform_release_snapshots(release_version, id DESC);
CREATE INDEX platform_integrity_status_idx ON platform_integrity_checks(status, subsystem, id DESC);
CREATE INDEX platform_events_component_idx ON platform_events(component_id, id DESC);

CREATE TRIGGER platform_contracts_immutable_update
BEFORE UPDATE ON platform_contracts BEGIN SELECT RAISE(ABORT, 'platform contract registrations are immutable'); END;
CREATE TRIGGER platform_contracts_immutable_delete
BEFORE DELETE ON platform_contracts BEGIN SELECT RAISE(ABORT, 'platform contract registrations are immutable'); END;
CREATE TRIGGER platform_component_versions_immutable_update
BEFORE UPDATE ON platform_component_versions BEGIN SELECT RAISE(ABORT, 'platform component versions are immutable'); END;
CREATE TRIGGER platform_component_versions_immutable_delete
BEFORE DELETE ON platform_component_versions BEGIN SELECT RAISE(ABORT, 'platform component versions are immutable'); END;
CREATE TRIGGER platform_release_snapshots_immutable_update
BEFORE UPDATE ON platform_release_snapshots BEGIN SELECT RAISE(ABORT, 'platform release snapshots are immutable'); END;
CREATE TRIGGER platform_release_snapshots_immutable_delete
BEFORE DELETE ON platform_release_snapshots BEGIN SELECT RAISE(ABORT, 'platform release snapshots are immutable'); END;
CREATE TRIGGER platform_integrity_checks_immutable_update
BEFORE UPDATE ON platform_integrity_checks BEGIN SELECT RAISE(ABORT, 'platform integrity checks are immutable'); END;
CREATE TRIGGER platform_integrity_checks_immutable_delete
BEFORE DELETE ON platform_integrity_checks BEGIN SELECT RAISE(ABORT, 'platform integrity checks are immutable'); END;
CREATE TRIGGER platform_events_immutable_update
BEFORE UPDATE ON platform_events BEGIN SELECT RAISE(ABORT, 'platform events are immutable'); END;
CREATE TRIGGER platform_events_immutable_delete
BEFORE DELETE ON platform_events BEGIN SELECT RAISE(ABORT, 'platform events are immutable'); END;

CREATE VIEW platform_component_status AS
SELECT
    c.component_id,
    c.name,
    c.product_code,
    c.component_type,
    c.status,
    c.current_version,
    c.endpoint,
    c.workspace_id,
    c.capabilities_json,
    c.contracts_json,
    c.updated_at,
    (SELECT COUNT(*) FROM platform_component_versions v WHERE v.component_id=c.component_id) AS version_count,
    (SELECT COUNT(*) FROM platform_links l WHERE l.source_component_id=c.component_id AND l.status='active') AS outbound_link_count,
    (SELECT COUNT(*) FROM platform_links l WHERE l.target_component_id=c.component_id AND l.status='active') AS inbound_link_count
FROM platform_components c;

CREATE VIEW platform_release_readiness AS
SELECT
    (SELECT COUNT(*) FROM platform_components WHERE status='active') AS active_components,
    (SELECT COUNT(*) FROM platform_components WHERE status IN ('degraded','offline')) AS attention_components,
    (SELECT COUNT(*) FROM platform_contracts WHERE status='active') AS active_contracts,
    (SELECT COUNT(*) FROM platform_links WHERE status='active') AS active_links,
    (SELECT COUNT(*) FROM platform_release_snapshots) AS release_snapshots,
    (SELECT COUNT(*) FROM platform_integrity_checks WHERE status='fail') AS failed_checks,
    (SELECT COUNT(*) FROM platform_integrity_checks WHERE status='warning') AS warning_checks;

INSERT INTO platform_components(
    component_id,name,product_code,component_type,status,current_version,endpoint,workspace_id,
    capabilities_json,contracts_json,metadata_json,registered_by
) VALUES (
    'component:catalyst-data','Catalyst Data','catalyst-data','core','active','2.0.0',NULL,'workspace:default',
    '["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","analysis-artifacts","offline-operations","backup-restore","platform-manifest"]',
    '["catalyst-data-record/1.0","catalyst-data-evidence-chain/1.0","catalyst-data-indicator-governance/1.0","catalyst-data-observation-lineage/1.0","catalyst-data-review-workflow/1.0","catalyst-data-query/1.0","catalyst-data-handoff/1.0","catalyst-data-access-governance/1.0","catalyst-data-connector-operations/1.0","catalyst-data-analysis-artifact/1.0","catalyst-data-operational-hardening/1.0","catalyst-data-platform/2.0"]',
    '{"local_first":true,"platform_core_optional":true}',
    'principal:system'
);

INSERT INTO platform_component_versions(
    component_version_id,component_id,version,manifest_sha256,capabilities_json,contracts_json,metadata_json,registered_by
) SELECT
    'component-version:catalyst-data:2.0.0','component:catalyst-data','2.0.0',
    'c5d21eddc957d6a6e6c94fe1e7a85b1ff83445d01160b9c5bb6be3b7e7786abc',
    capabilities_json,contracts_json,metadata_json,'principal:system'
FROM platform_components WHERE component_id='component:catalyst-data';
