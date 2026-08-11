CREATE TABLE storage_backend_metadata (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    backend TEXT NOT NULL CHECK(backend IN ('sqlite','postgresql')),
    database_identity TEXT NOT NULL,
    feature_flags_json TEXT NOT NULL DEFAULT '{}',
    initialized_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE storage_migration_events (
    id INTEGER PRIMARY KEY,
    migration_id TEXT NOT NULL UNIQUE,
    source_backend TEXT NOT NULL,
    target_backend TEXT NOT NULL,
    source_identity TEXT,
    target_identity TEXT,
    status TEXT NOT NULL CHECK(status IN ('started','completed','failed')),
    table_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX idx_storage_migration_events_status ON storage_migration_events(status, id);

UPDATE platform_components
SET current_version='2.1.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
