CREATE TABLE connector_adapter_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    binding_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL UNIQUE,
    adapter_id TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','disabled')),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);
CREATE INDEX idx_connector_adapter_bindings_adapter ON connector_adapter_bindings(adapter_id,status);

CREATE TABLE connector_adapter_state (
    connector_id INTEGER PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(state_json)),
    etag TEXT,
    last_modified TEXT,
    last_request_uri TEXT,
    last_success_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_adapter_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter_run_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL,
    adapter_id TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','cancelled')),
    page_count INTEGER NOT NULL DEFAULT 0 CHECK(page_count >= 0),
    row_count INTEGER NOT NULL DEFAULT 0 CHECK(row_count >= 0),
    connector_run_id INTEGER,
    last_request_uri TEXT,
    checkpoint_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(checkpoint_json)),
    error_class TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(connector_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_connector_adapter_runs_connector ON connector_adapter_runs(connector_id,id DESC);
CREATE INDEX idx_connector_adapter_runs_status ON connector_adapter_runs(status,id DESC);

CREATE TABLE connector_adapter_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id TEXT NOT NULL UNIQUE,
    adapter_run_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL CHECK(page_number >= 1),
    request_uri TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_headers_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(response_headers_json)),
    content_type TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    payload_bytes INTEGER NOT NULL CHECK(payload_bytes >= 0),
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    etag TEXT,
    last_modified TEXT,
    next_cursor_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(next_cursor_json)),
    fetched_at TEXT NOT NULL,
    UNIQUE(adapter_run_id,page_number),
    FOREIGN KEY(adapter_run_id) REFERENCES connector_adapter_runs(id) ON DELETE CASCADE
);

CREATE TRIGGER connector_adapter_pages_immutable_update
BEFORE UPDATE ON connector_adapter_pages
BEGIN
    SELECT RAISE(ABORT, 'connector adapter pages are immutable');
END;

CREATE TRIGGER connector_adapter_pages_immutable_delete
BEFORE DELETE ON connector_adapter_pages
BEGIN
    SELECT RAISE(ABORT, 'connector adapter pages are immutable');
END;

CREATE VIEW connector_adapter_operational_status AS
SELECT
    cab.binding_id,
    cd.connector_id,
    cd.name AS connector_name,
    cab.adapter_id,
    cab.adapter_version,
    cab.status,
    cas.last_request_uri,
    cas.last_success_at,
    car.adapter_run_id AS latest_adapter_run_id,
    car.status AS latest_adapter_run_status,
    car.page_count AS latest_page_count,
    car.row_count AS latest_row_count,
    car.finished_at AS latest_finished_at
FROM connector_adapter_bindings cab
JOIN connector_definitions cd ON cd.id=cab.connector_id
LEFT JOIN connector_adapter_state cas ON cas.connector_id=cab.connector_id
LEFT JOIN connector_adapter_runs car ON car.id=(
    SELECT r.id FROM connector_adapter_runs r WHERE r.connector_id=cab.connector_id ORDER BY r.id DESC LIMIT 1
);

UPDATE platform_components
SET current_version='2.2.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
