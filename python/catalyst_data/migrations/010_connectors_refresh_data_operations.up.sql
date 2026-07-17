CREATE TABLE connector_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER NOT NULL,
    principal_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    connector_type TEXT NOT NULL CHECK(connector_type IN ('http-json','http-csv','file-json','file-csv','manual','replay')),
    base_uri TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','disabled','archived')),
    license_name TEXT,
    license_url TEXT,
    freshness_sla_seconds INTEGER CHECK(freshness_sla_seconds IS NULL OR freshness_sla_seconds >= 0),
    request_timeout_seconds INTEGER NOT NULL DEFAULT 30 CHECK(request_timeout_seconds BETWEEN 1 AND 300),
    rate_limit_per_hour INTEGER CHECK(rate_limit_per_hour IS NULL OR rate_limit_per_hour > 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts BETWEEN 1 AND 20),
    retry_backoff_seconds INTEGER NOT NULL DEFAULT 30 CHECK(retry_backoff_seconds >= 0),
    credential_env TEXT,
    auth_type TEXT NOT NULL DEFAULT 'none' CHECK(auth_type IN ('none','bearer-env','header-env','query-env')),
    auth_name TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE RESTRICT
);

CREATE TABLE connector_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('draft','active','deprecated','retired')),
    capabilities_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(capabilities_json)),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json)),
    field_mapping_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(field_mapping_json)),
    transformation_profile_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(transformation_profile_json)),
    schema_fingerprint TEXT,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(connector_id, version),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_version_activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activation_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL,
    connector_version_id INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(connector_version_id) REFERENCES connector_versions(id) ON DELETE RESTRICT
);

CREATE INDEX idx_connector_version_activations_current
ON connector_version_activations(connector_id, id DESC);

CREATE TABLE connector_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    frequency_minutes INTEGER NOT NULL CHECK(frequency_minutes >= 60),
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_state (
    connector_id INTEGER PRIMARY KEY,
    health_status TEXT NOT NULL DEFAULT 'unknown' CHECK(health_status IN ('unknown','healthy','degraded','unhealthy','paused')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_run_id TEXT,
    last_payload_sha256 TEXT,
    last_schema_fingerprint TEXT,
    last_source_modified_at TEXT,
    next_allowed_at TEXT,
    cursor_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(cursor_json)),
    etag TEXT,
    last_modified TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL,
    connector_version_id INTEGER NOT NULL,
    parent_run_id INTEGER,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('manual','scheduled','retry','replay','recovery')),
    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','partial','failed','quarantined','dead-letter','cancelled')),
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number >= 1),
    input_uri TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    latency_ms INTEGER CHECK(latency_ms IS NULL OR latency_ms >= 0),
    response_status INTEGER,
    response_headers_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(response_headers_json)),
    source_modified_at TEXT,
    freshness_seconds INTEGER CHECK(freshness_seconds IS NULL OR freshness_seconds >= 0),
    payload_bytes INTEGER NOT NULL DEFAULT 0 CHECK(payload_bytes >= 0),
    payload_sha256 TEXT,
    row_count INTEGER NOT NULL DEFAULT 0 CHECK(row_count >= 0),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK(inserted_count >= 0),
    updated_count INTEGER NOT NULL DEFAULT 0 CHECK(updated_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK(skipped_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
    quarantined_count INTEGER NOT NULL DEFAULT 0 CHECK(quarantined_count >= 0),
    license_status TEXT NOT NULL DEFAULT 'unknown' CHECK(license_status IN ('compliant','missing','restricted','unknown')),
    freshness_status TEXT NOT NULL DEFAULT 'unknown' CHECK(freshness_status IN ('current','stale','unknown')),
    drift_status TEXT NOT NULL DEFAULT 'unknown' CHECK(drift_status IN ('stable','changed','unknown')),
    reconciliation_status TEXT NOT NULL DEFAULT 'pending' CHECK(reconciliation_status IN ('pending','balanced','warning','failed')),
    retry_after_at TEXT,
    error_class TEXT,
    error_message TEXT,
    checkpoint_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(checkpoint_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(connector_version_id) REFERENCES connector_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY(parent_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    level TEXT NOT NULL CHECK(level IN ('debug','info','warning','error')),
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE
);

CREATE TABLE connector_payload_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    encoding TEXT NOT NULL DEFAULT 'utf-8',
    payload_blob BLOB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    payload_bytes INTEGER NOT NULL CHECK(payload_bytes >= 0),
    source_uri TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE
);

CREATE TABLE connector_run_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    source_payload_sha256 TEXT NOT NULL CHECK(length(source_payload_sha256)=64),
    source_payload_json TEXT NOT NULL CHECK(json_valid(source_payload_json)),
    transformed_payload_json TEXT CHECK(transformed_payload_json IS NULL OR json_valid(transformed_payload_json)),
    record_id TEXT,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','skipped','quarantined','failed','not-applied')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, row_number),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE SET NULL
);

CREATE TABLE connector_record_state (
    connector_id INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    source_payload_sha256 TEXT NOT NULL CHECK(length(source_payload_sha256)=64),
    record_id TEXT,
    first_seen_run_id INTEGER NOT NULL,
    last_seen_run_id INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    PRIMARY KEY(connector_id, source_key),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE SET NULL,
    FOREIGN KEY(first_seen_run_id) REFERENCES connector_runs(id) ON DELETE RESTRICT,
    FOREIGN KEY(last_seen_run_id) REFERENCES connector_runs(id) ON DELETE RESTRICT
);

CREATE TABLE connector_quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quarantine_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL CHECK(json_valid(raw_payload_json)),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','released','discarded','resolved')),
    resolution_notes TEXT,
    recovered_run_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(recovered_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dead_letter_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL,
    run_id INTEGER NOT NULL UNIQUE,
    payload_snapshot_id INTEGER,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','replayed','resolved','discarded')),
    replay_run_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(payload_snapshot_id) REFERENCES connector_payload_snapshots(id) ON DELETE SET NULL,
    FOREIGN KEY(replay_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reconciliation_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL UNIQUE,
    previous_run_id INTEGER,
    expected_count INTEGER NOT NULL DEFAULT 0,
    actual_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    missing_count INTEGER NOT NULL DEFAULT 0,
    unexpected_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    missing_keys_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(missing_keys_json)),
    unexpected_keys_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(unexpected_keys_json)),
    duplicate_keys_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(duplicate_keys_json)),
    status TEXT NOT NULL CHECK(status IN ('balanced','warning','failed')),
    summary_sha256 TEXT NOT NULL CHECK(length(summary_sha256)=64),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(previous_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL,
    run_id INTEGER,
    alert_type TEXT NOT NULL CHECK(alert_type IN ('fetch-failure','rate-limit','freshness','license','schema-drift','record-drift','reconciliation','quarantine','dead-letter','health')),
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged','resolved')),
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged_at TEXT,
    resolved_at TEXT,
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

INSERT OR IGNORE INTO role_permissions(role,permission) VALUES
('analyst','connectors:read'),
('analyst','connectors:run'),
('publisher','connectors:read');

CREATE VIEW connector_operational_status AS
SELECT cd.connector_id, cd.name, cd.connector_type, cd.status,
       w.workspace_id, p.principal_id,
       cv.version AS active_version,
       cs.health_status, cs.consecutive_failures, cs.last_attempt_at, cs.last_success_at,
       cs.last_run_id, cs.next_allowed_at, cs.last_schema_fingerprint,
       sch.enabled AS schedule_enabled, sch.frequency_minutes, sch.next_run_at,
       (SELECT COUNT(*) FROM connector_alerts ca WHERE ca.connector_id=cd.id AND ca.status='open') AS open_alert_count,
       (SELECT COUNT(*) FROM connector_quarantine cq JOIN connector_runs cr ON cr.id=cq.run_id WHERE cr.connector_id=cd.id AND cq.status='open') AS open_quarantine_count,
       (SELECT COUNT(*) FROM connector_dead_letters dl WHERE dl.connector_id=cd.id AND dl.status='open') AS open_dead_letter_count
FROM connector_definitions cd
JOIN workspaces w ON w.id=cd.workspace_id
JOIN principals p ON p.id=cd.principal_id
LEFT JOIN connector_version_activations cva ON cva.id=(SELECT MAX(a.id) FROM connector_version_activations a WHERE a.connector_id=cd.id)
LEFT JOIN connector_versions cv ON cv.id=cva.connector_version_id
LEFT JOIN connector_state cs ON cs.connector_id=cd.id
LEFT JOIN connector_schedules sch ON sch.connector_id=cd.id;

CREATE VIEW connector_run_summary AS
SELECT cr.run_id, cd.connector_id, cv.version AS connector_version, cr.trigger_type, cr.status,
       cr.attempt_number, cr.started_at, cr.finished_at, cr.latency_ms, cr.response_status,
       cr.row_count, cr.inserted_count, cr.updated_count, cr.skipped_count, cr.failed_count,
       cr.quarantined_count, cr.license_status, cr.freshness_status, cr.drift_status,
       cr.reconciliation_status, cr.error_class, cr.error_message,
       rec.expected_count, rec.actual_count, rec.matched_count, rec.changed_count,
       rec.missing_count, rec.unexpected_count, rec.duplicate_count
FROM connector_runs cr
JOIN connector_definitions cd ON cd.id=cr.connector_id
JOIN connector_versions cv ON cv.id=cr.connector_version_id
LEFT JOIN connector_reconciliations rec ON rec.run_id=cr.id;

CREATE VIEW open_connector_alerts AS
SELECT ca.alert_id, cd.connector_id, cr.run_id, ca.alert_type, ca.severity, ca.message,
       ca.details_json, ca.created_at
FROM connector_alerts ca
JOIN connector_definitions cd ON cd.id=ca.connector_id
LEFT JOIN connector_runs cr ON cr.id=ca.run_id
WHERE ca.status='open';

CREATE INDEX idx_connector_runs_connector ON connector_runs(connector_id, started_at DESC, id DESC);
CREATE INDEX idx_connector_run_records_run ON connector_run_records(run_id, row_number);
CREATE INDEX idx_connector_record_state_active ON connector_record_state(connector_id, active, source_key);
CREATE INDEX idx_connector_quarantine_status ON connector_quarantine(status, created_at);
CREATE INDEX idx_connector_alerts_status ON connector_alerts(connector_id, status, created_at);
CREATE INDEX idx_connector_schedules_due ON connector_schedules(enabled, next_run_at);

CREATE TRIGGER connector_version_activations_no_update BEFORE UPDATE ON connector_version_activations
BEGIN SELECT RAISE(ABORT, 'connector version activations are append-only'); END;
CREATE TRIGGER connector_version_activations_no_delete BEFORE DELETE ON connector_version_activations
BEGIN SELECT RAISE(ABORT, 'connector version activations are append-only'); END;
CREATE TRIGGER connector_versions_no_update BEFORE UPDATE ON connector_versions
BEGIN SELECT RAISE(ABORT, 'connector versions are append-only'); END;
CREATE TRIGGER connector_versions_no_delete BEFORE DELETE ON connector_versions
BEGIN SELECT RAISE(ABORT, 'connector versions are append-only'); END;
CREATE TRIGGER connector_run_logs_no_update BEFORE UPDATE ON connector_run_logs
BEGIN SELECT RAISE(ABORT, 'connector run logs are append-only'); END;
CREATE TRIGGER connector_run_logs_no_delete BEFORE DELETE ON connector_run_logs
BEGIN SELECT RAISE(ABORT, 'connector run logs are append-only'); END;
CREATE TRIGGER connector_payload_snapshots_no_update BEFORE UPDATE ON connector_payload_snapshots
BEGIN SELECT RAISE(ABORT, 'connector payload snapshots are append-only'); END;
CREATE TRIGGER connector_payload_snapshots_no_delete BEFORE DELETE ON connector_payload_snapshots
BEGIN SELECT RAISE(ABORT, 'connector payload snapshots are append-only'); END;
CREATE TRIGGER connector_run_records_no_update BEFORE UPDATE ON connector_run_records
BEGIN SELECT RAISE(ABORT, 'connector run records are append-only'); END;
CREATE TRIGGER connector_run_records_no_delete BEFORE DELETE ON connector_run_records
BEGIN SELECT RAISE(ABORT, 'connector run records are append-only'); END;
CREATE TRIGGER connector_reconciliations_no_update BEFORE UPDATE ON connector_reconciliations
BEGIN SELECT RAISE(ABORT, 'connector reconciliations are append-only'); END;
CREATE TRIGGER connector_reconciliations_no_delete BEFORE DELETE ON connector_reconciliations
BEGIN SELECT RAISE(ABORT, 'connector reconciliations are append-only'); END;
