PRAGMA foreign_keys = ON;

CREATE TABLE saved_queries (
    id INTEGER PRIMARY KEY,
    query_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    definition_json TEXT NOT NULL,
    definition_sha256 TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE saved_query_versions (
    id INTEGER PRIMARY KEY,
    query_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    definition_json TEXT NOT NULL,
    definition_sha256 TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (query_id) REFERENCES saved_queries(query_id) ON DELETE RESTRICT,
    UNIQUE(query_id, version_number),
    UNIQUE(query_id, definition_sha256)
);
CREATE INDEX idx_saved_query_versions_query ON saved_query_versions(query_id, version_number DESC);

CREATE TABLE query_runs (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    query_id TEXT,
    query_version_id INTEGER,
    definition_json TEXT NOT NULL,
    definition_sha256 TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK(record_count >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK(warning_count >= 0),
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    FOREIGN KEY (query_id) REFERENCES saved_queries(query_id) ON DELETE RESTRICT,
    FOREIGN KEY (query_version_id) REFERENCES saved_query_versions(id) ON DELETE RESTRICT
);
CREATE INDEX idx_query_runs_query ON query_runs(query_id, completed_at DESC);

CREATE TABLE query_run_records (
    run_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position >= 0),
    record_id TEXT NOT NULL,
    record_payload_sha256 TEXT NOT NULL,
    record_payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, position),
    FOREIGN KEY (run_id) REFERENCES query_runs(run_id) ON DELETE RESTRICT,
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT
);
CREATE INDEX idx_query_run_records_record ON query_run_records(record_id, run_id);

CREATE TABLE query_run_warnings (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    warning_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('info','caution','blocking')),
    record_ids_json TEXT NOT NULL DEFAULT '[]',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES query_runs(run_id) ON DELETE RESTRICT
);
CREATE INDEX idx_query_run_warnings_run ON query_run_warnings(run_id, severity);

CREATE TABLE export_bundles (
    id INTEGER PRIMARY KEY,
    bundle_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    bundle_format TEXT NOT NULL CHECK(bundle_format IN ('zip','directory')),
    output_name TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES query_runs(run_id) ON DELETE RESTRICT,
    UNIQUE(run_id, bundle_format, manifest_sha256)
);
CREATE INDEX idx_export_bundles_run ON export_bundles(run_id, created_at DESC);

CREATE TRIGGER saved_query_versions_immutable_update BEFORE UPDATE ON saved_query_versions BEGIN SELECT RAISE(ABORT, 'saved query versions are immutable'); END;
CREATE TRIGGER saved_query_versions_immutable_delete BEFORE DELETE ON saved_query_versions BEGIN SELECT RAISE(ABORT, 'saved query versions are immutable'); END;
CREATE TRIGGER query_runs_immutable_update BEFORE UPDATE ON query_runs BEGIN SELECT RAISE(ABORT, 'query runs are immutable'); END;
CREATE TRIGGER query_runs_immutable_delete BEFORE DELETE ON query_runs BEGIN SELECT RAISE(ABORT, 'query runs are immutable'); END;
CREATE TRIGGER query_run_records_immutable_update BEFORE UPDATE ON query_run_records BEGIN SELECT RAISE(ABORT, 'query run records are immutable'); END;
CREATE TRIGGER query_run_records_immutable_delete BEFORE DELETE ON query_run_records BEGIN SELECT RAISE(ABORT, 'query run records are immutable'); END;
CREATE TRIGGER query_run_warnings_immutable_update BEFORE UPDATE ON query_run_warnings BEGIN SELECT RAISE(ABORT, 'query run warnings are immutable'); END;
CREATE TRIGGER query_run_warnings_immutable_delete BEFORE DELETE ON query_run_warnings BEGIN SELECT RAISE(ABORT, 'query run warnings are immutable'); END;
CREATE TRIGGER export_bundles_immutable_update BEFORE UPDATE ON export_bundles BEGIN SELECT RAISE(ABORT, 'export bundles are immutable'); END;
CREATE TRIGGER export_bundles_immutable_delete BEFORE DELETE ON export_bundles BEGIN SELECT RAISE(ABORT, 'export bundles are immutable'); END;

CREATE VIEW saved_query_registry AS
SELECT sq.query_id, sq.name, sq.description, sq.definition_sha256,
       sq.created_by, sq.created_at, sq.updated_at,
       (SELECT MAX(sqv.version_number) FROM saved_query_versions sqv WHERE sqv.query_id=sq.query_id) AS version_count,
       (SELECT COUNT(*) FROM query_runs qr WHERE qr.query_id=sq.query_id) AS run_count
FROM saved_queries sq;

CREATE VIEW query_run_summary AS
SELECT qr.run_id, qr.query_id, sq.name AS query_name, qr.record_count, qr.warning_count,
       qr.definition_sha256, qr.result_sha256, qr.started_at, qr.completed_at,
       (SELECT COUNT(*) FROM export_bundles eb WHERE eb.run_id=qr.run_id) AS export_count
FROM query_runs qr
LEFT JOIN saved_queries sq ON sq.query_id=qr.query_id;
