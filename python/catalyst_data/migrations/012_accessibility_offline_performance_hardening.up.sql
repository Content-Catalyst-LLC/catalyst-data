CREATE TABLE operational_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_id TEXT NOT NULL UNIQUE,
    repository_id TEXT,
    source_path TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    database_sha256 TEXT NOT NULL CHECK(length(database_sha256)=64),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    schema_version INTEGER NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0 CHECK(record_count >= 0),
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    status TEXT NOT NULL DEFAULT 'verified' CHECK(status IN ('created','verified','failed','superseded')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    verified_at TEXT
);

CREATE TABLE restore_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restore_id TEXT NOT NULL UNIQUE,
    backup_id TEXT,
    backup_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    pre_restore_sha256 TEXT,
    post_restore_sha256 TEXT NOT NULL CHECK(length(post_restore_sha256)=64),
    schema_version INTEGER NOT NULL,
    actor TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('completed','failed')),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE offline_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('record-upsert','connector-run','query-run','analysis-run','handoff-receive','custom')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts >= 1),
    queued_by TEXT NOT NULL,
    queued_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
);

CREATE TABLE offline_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER,
    status TEXT NOT NULL CHECK(status IN ('running','completed','partial','failed')),
    queued_count INTEGER NOT NULL DEFAULT 0,
    succeeded_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    actor TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(summary_json)),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
);

CREATE TABLE offline_sync_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id INTEGER NOT NULL,
    operation_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('succeeded','failed','skipped')),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(sync_id, operation_id),
    FOREIGN KEY(sync_id) REFERENCES offline_sync_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(operation_id) REFERENCES offline_operations(id) ON DELETE RESTRICT
);

CREATE TABLE performance_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    benchmark_id TEXT NOT NULL UNIQUE,
    benchmark_name TEXT NOT NULL,
    repository_id TEXT,
    schema_version INTEGER NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT NOT NULL CHECK(json_valid(metrics_json)),
    environment_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(environment_json)),
    status TEXT NOT NULL CHECK(status IN ('pass','warning','fail')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE security_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL UNIQUE,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pass','warning','fail')),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE release_attestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attestation_id TEXT NOT NULL UNIQUE,
    release_version TEXT NOT NULL,
    repository_sha256 TEXT NOT NULL CHECK(length(repository_sha256)=64),
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    sbom_json TEXT NOT NULL CHECK(json_valid(sbom_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_operational_backups_created ON operational_backups(created_at DESC);
CREATE INDEX idx_restore_events_created ON restore_events(created_at DESC);
CREATE INDEX idx_offline_operations_status ON offline_operations(status, queued_at, id);
CREATE INDEX idx_offline_operations_workspace ON offline_operations(workspace_id, status);
CREATE INDEX idx_offline_sync_runs_started ON offline_sync_runs(started_at DESC);
CREATE INDEX idx_performance_benchmarks_created ON performance_benchmarks(created_at DESC);
CREATE INDEX idx_security_audit_events_created ON security_audit_events(created_at DESC);
CREATE INDEX idx_release_attestations_version ON release_attestations(release_version, created_at DESC);

CREATE VIEW operational_readiness AS
SELECT
    (SELECT COUNT(*) FROM operational_backups WHERE status='verified') AS verified_backup_count,
    (SELECT COUNT(*) FROM restore_events WHERE status='completed') AS completed_restore_count,
    (SELECT COUNT(*) FROM offline_operations WHERE status='queued') AS queued_offline_operation_count,
    (SELECT COUNT(*) FROM offline_operations WHERE status='failed') AS failed_offline_operation_count,
    (SELECT COUNT(*) FROM performance_benchmarks WHERE status='fail') AS failed_benchmark_count,
    (SELECT COUNT(*) FROM security_audit_events WHERE status='fail') AS failed_security_check_count,
    (SELECT COUNT(*) FROM release_attestations) AS release_attestation_count;

CREATE TRIGGER operational_backups_no_update BEFORE UPDATE ON operational_backups
BEGIN SELECT RAISE(ABORT, 'backup history is append-only'); END;
CREATE TRIGGER operational_backups_no_delete BEFORE DELETE ON operational_backups
BEGIN SELECT RAISE(ABORT, 'backup history is append-only'); END;
CREATE TRIGGER restore_events_no_update BEFORE UPDATE ON restore_events
BEGIN SELECT RAISE(ABORT, 'restore events are append-only'); END;
CREATE TRIGGER restore_events_no_delete BEFORE DELETE ON restore_events
BEGIN SELECT RAISE(ABORT, 'restore events are append-only'); END;
CREATE TRIGGER offline_sync_runs_no_update BEFORE UPDATE ON offline_sync_runs
BEGIN SELECT RAISE(ABORT, 'offline sync runs are append-only after completion'); END;
CREATE TRIGGER offline_sync_runs_no_delete BEFORE DELETE ON offline_sync_runs
BEGIN SELECT RAISE(ABORT, 'offline sync runs are append-only'); END;
CREATE TRIGGER offline_sync_items_no_update BEFORE UPDATE ON offline_sync_items
BEGIN SELECT RAISE(ABORT, 'offline sync items are append-only'); END;
CREATE TRIGGER offline_sync_items_no_delete BEFORE DELETE ON offline_sync_items
BEGIN SELECT RAISE(ABORT, 'offline sync items are append-only'); END;
CREATE TRIGGER performance_benchmarks_no_update BEFORE UPDATE ON performance_benchmarks
BEGIN SELECT RAISE(ABORT, 'performance benchmarks are append-only'); END;
CREATE TRIGGER performance_benchmarks_no_delete BEFORE DELETE ON performance_benchmarks
BEGIN SELECT RAISE(ABORT, 'performance benchmarks are append-only'); END;
CREATE TRIGGER security_audit_events_no_update BEFORE UPDATE ON security_audit_events
BEGIN SELECT RAISE(ABORT, 'security audit events are append-only'); END;
CREATE TRIGGER security_audit_events_no_delete BEFORE DELETE ON security_audit_events
BEGIN SELECT RAISE(ABORT, 'security audit events are append-only'); END;
CREATE TRIGGER release_attestations_no_update BEFORE UPDATE ON release_attestations
BEGIN SELECT RAISE(ABORT, 'release attestations are append-only'); END;
CREATE TRIGGER release_attestations_no_delete BEFORE DELETE ON release_attestations
BEGIN SELECT RAISE(ABORT, 'release attestations are append-only'); END;
