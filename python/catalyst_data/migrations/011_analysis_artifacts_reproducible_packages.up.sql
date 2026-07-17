CREATE TABLE analysis_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL UNIQUE,
    workspace_id INTEGER NOT NULL,
    project_id INTEGER,
    name TEXT NOT NULL,
    analysis_type TEXT NOT NULL CHECK(analysis_type IN ('analysis','model','scenario','forecast','sensitivity','replication')),
    description TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','completed','failed','invalidated','superseded','archived')),
    target_product TEXT,
    target_uri TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE analysis_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)),
    environment_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(environment_json)),
    code_reference_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(code_reference_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(artifact_id, version),
    UNIQUE(artifact_id, payload_sha256),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE
);

CREATE TABLE analysis_version_activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activation_id TEXT NOT NULL UNIQUE,
    artifact_id INTEGER NOT NULL,
    analysis_version_id INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE,
    FOREIGN KEY(analysis_version_id) REFERENCES analysis_versions(id) ON DELETE RESTRICT
);

CREATE TABLE analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    artifact_id INTEGER NOT NULL,
    analysis_version_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','invalidated','superseded','cancelled')),
    executed_by TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(parameters_json)),
    environment_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(environment_json)),
    input_manifest_sha256 TEXT CHECK(input_manifest_sha256 IS NULL OR length(input_manifest_sha256)=64),
    output_manifest_sha256 TEXT CHECK(output_manifest_sha256 IS NULL OR length(output_manifest_sha256)=64),
    reproducibility_status TEXT NOT NULL DEFAULT 'pending' CHECK(reproducibility_status IN ('pending','reproducible','warning','invalidated','failed')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE,
    FOREIGN KEY(analysis_version_id) REFERENCES analysis_versions(id) ON DELETE RESTRICT
);

CREATE TABLE analysis_run_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    record_id TEXT,
    role TEXT NOT NULL DEFAULT 'input' CHECK(role IN ('input','baseline','reference','training','validation','comparison')),
    ordinal INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    frozen_at TEXT NOT NULL,
    UNIQUE(run_id, record_id, role, ordinal),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE SET NULL
);

CREATE TABLE analysis_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    output_type TEXT NOT NULL CHECK(output_type IN ('table','figure','model','scenario','forecast','sensitivity','document','dataset','metric','log','other')),
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    content_blob BLOB,
    external_uri TEXT,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE TABLE derived_measurement_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lineage_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    output_id INTEGER,
    derived_record_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    transformation_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(transformation_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, derived_record_id, source_record_id),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(output_id) REFERENCES analysis_outputs(id) ON DELETE SET NULL,
    FOREIGN KEY(derived_record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY(source_record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT
);

CREATE TABLE analysis_platform_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id TEXT NOT NULL UNIQUE,
    artifact_id INTEGER NOT NULL,
    product TEXT NOT NULL,
    capability TEXT,
    external_artifact_id TEXT,
    uri TEXT,
    relation TEXT NOT NULL DEFAULT 'related' CHECK(relation IN ('produced-by','consumed-by','published-to','reviewed-in','related')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE
);

CREATE TABLE analysis_replication_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    replication_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','partial','failed','not-reproducible')),
    reviewer TEXT NOT NULL,
    reproduced_run_id INTEGER,
    notes TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_json)),
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(reproduced_run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL
);

CREATE TABLE analysis_invalidation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invalidation_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    record_id TEXT NOT NULL,
    frozen_sha256 TEXT NOT NULL CHECK(length(frozen_sha256)=64),
    current_sha256 TEXT,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning' CHECK(severity IN ('info','warning','blocking')),
    detected_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE CASCADE
);

CREATE TABLE analysis_invalidation_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resolution_id TEXT NOT NULL UNIQUE,
    invalidation_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('acknowledged','rerun','accepted','resolved')),
    actor TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(invalidation_id) REFERENCES analysis_invalidation_events(id) ON DELETE CASCADE
);

CREATE TABLE analysis_package_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL,
    schema_version TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    package_sha256 TEXT NOT NULL CHECK(length(package_sha256)=64),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    format TEXT NOT NULL DEFAULT 'zip' CHECK(format IN ('zip','directory')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO role_permissions(role,permission) VALUES
('analyst','analyses:read'),
('analyst','analyses:write'),
('analyst','analyses:run'),
('reviewer','analyses:read'),
('reviewer','analyses:review'),
('approver','analyses:read'),
('approver','analyses:review'),
('publisher','analyses:read'),
('publisher','analyses:publish');

CREATE VIEW analysis_artifact_status AS
SELECT aa.artifact_id, aa.name, aa.analysis_type, aa.status, w.workspace_id, p.project_id,
       av.version AS active_version,
       ar.run_id AS latest_run_id, ar.status AS latest_run_status,
       ar.reproducibility_status, ar.started_at AS latest_run_started_at,
       (SELECT COUNT(*) FROM analysis_invalidation_events aie
          LEFT JOIN analysis_invalidation_resolutions air ON air.invalidation_id=aie.id
         WHERE aie.run_id=ar.id AND air.id IS NULL) AS open_invalidation_count,
       (SELECT COUNT(*) FROM analysis_runs r WHERE r.artifact_id=aa.id) AS run_count
FROM analysis_artifacts aa
JOIN workspaces w ON w.id=aa.workspace_id
LEFT JOIN projects p ON p.id=aa.project_id
LEFT JOIN analysis_version_activations ava ON ava.id=(SELECT MAX(x.id) FROM analysis_version_activations x WHERE x.artifact_id=aa.id)
LEFT JOIN analysis_versions av ON av.id=ava.analysis_version_id
LEFT JOIN analysis_runs ar ON ar.id=(SELECT MAX(r.id) FROM analysis_runs r WHERE r.artifact_id=aa.id);

CREATE VIEW analysis_input_integrity AS
SELECT ar.run_id, aa.artifact_id, ari.record_id, ari.role, ari.payload_sha256 AS frozen_sha256,
       dr.payload_sha256 AS current_sha256,
       CASE WHEN dr.record_id IS NULL THEN 'missing'
            WHEN dr.payload_sha256=ari.payload_sha256 THEN 'current'
            ELSE 'changed' END AS integrity_status,
       ari.frozen_at
FROM analysis_run_inputs ari
JOIN analysis_runs ar ON ar.id=ari.run_id
JOIN analysis_artifacts aa ON aa.id=ar.artifact_id
LEFT JOIN data_records dr ON dr.record_id=ari.record_id;

CREATE INDEX idx_analysis_artifacts_workspace ON analysis_artifacts(workspace_id, status, updated_at);
CREATE INDEX idx_analysis_versions_artifact ON analysis_versions(artifact_id, id DESC);
CREATE INDEX idx_analysis_runs_artifact ON analysis_runs(artifact_id, started_at DESC, id DESC);
CREATE INDEX idx_analysis_run_inputs_run ON analysis_run_inputs(run_id, ordinal);
CREATE INDEX idx_analysis_outputs_run ON analysis_outputs(run_id, id);
CREATE INDEX idx_analysis_invalidations_run ON analysis_invalidation_events(run_id, detected_at);
CREATE INDEX idx_derived_lineage_derived ON derived_measurement_lineage(derived_record_id);
CREATE INDEX idx_derived_lineage_source ON derived_measurement_lineage(source_record_id);

CREATE TRIGGER analysis_versions_no_update BEFORE UPDATE ON analysis_versions
BEGIN SELECT RAISE(ABORT, 'analysis versions are append-only'); END;
CREATE TRIGGER analysis_versions_no_delete BEFORE DELETE ON analysis_versions
BEGIN SELECT RAISE(ABORT, 'analysis versions are append-only'); END;
CREATE TRIGGER analysis_activations_no_update BEFORE UPDATE ON analysis_version_activations
BEGIN SELECT RAISE(ABORT, 'analysis version activations are append-only'); END;
CREATE TRIGGER analysis_activations_no_delete BEFORE DELETE ON analysis_version_activations
BEGIN SELECT RAISE(ABORT, 'analysis version activations are append-only'); END;
CREATE TRIGGER analysis_inputs_no_update BEFORE UPDATE ON analysis_run_inputs
BEGIN SELECT RAISE(ABORT, 'analysis inputs are immutable'); END;
CREATE TRIGGER analysis_inputs_no_delete BEFORE DELETE ON analysis_run_inputs
BEGIN SELECT RAISE(ABORT, 'analysis inputs are immutable'); END;
CREATE TRIGGER analysis_outputs_no_update BEFORE UPDATE ON analysis_outputs
BEGIN SELECT RAISE(ABORT, 'analysis outputs are immutable'); END;
CREATE TRIGGER analysis_outputs_no_delete BEFORE DELETE ON analysis_outputs
BEGIN SELECT RAISE(ABORT, 'analysis outputs are immutable'); END;
CREATE TRIGGER derived_lineage_no_update BEFORE UPDATE ON derived_measurement_lineage
BEGIN SELECT RAISE(ABORT, 'derived measurement lineage is append-only'); END;
CREATE TRIGGER derived_lineage_no_delete BEFORE DELETE ON derived_measurement_lineage
BEGIN SELECT RAISE(ABORT, 'derived measurement lineage is append-only'); END;
CREATE TRIGGER replication_reviews_no_update BEFORE UPDATE ON analysis_replication_reviews
BEGIN SELECT RAISE(ABORT, 'replication reviews are append-only'); END;
CREATE TRIGGER replication_reviews_no_delete BEFORE DELETE ON analysis_replication_reviews
BEGIN SELECT RAISE(ABORT, 'replication reviews are append-only'); END;
CREATE TRIGGER invalidation_events_no_update BEFORE UPDATE ON analysis_invalidation_events
BEGIN SELECT RAISE(ABORT, 'analysis invalidation events are append-only'); END;
CREATE TRIGGER invalidation_events_no_delete BEFORE DELETE ON analysis_invalidation_events
BEGIN SELECT RAISE(ABORT, 'analysis invalidation events are append-only'); END;

CREATE TRIGGER data_records_analysis_invalidation AFTER UPDATE OF payload_sha256 ON data_records
WHEN OLD.payload_sha256 <> NEW.payload_sha256
BEGIN
    INSERT INTO analysis_invalidation_events(
        invalidation_id,run_id,record_id,frozen_sha256,current_sha256,reason,severity,detected_at,details_json
    )
    SELECT 'invalidation:' || lower(hex(randomblob(12))), ari.run_id, NEW.record_id,
           ari.payload_sha256, NEW.payload_sha256, 'upstream-record-changed', 'warning', datetime('now'),
           json_object('previous_record_sha256',OLD.payload_sha256,'current_record_sha256',NEW.payload_sha256)
    FROM analysis_run_inputs ari
    WHERE ari.record_id=NEW.record_id AND ari.payload_sha256<>NEW.payload_sha256
      AND NOT EXISTS (
          SELECT 1 FROM analysis_invalidation_events aie
          WHERE aie.run_id=ari.run_id AND aie.record_id=NEW.record_id
            AND COALESCE(aie.current_sha256,'')=NEW.payload_sha256
      );
    UPDATE analysis_runs SET reproducibility_status='invalidated'
    WHERE id IN (SELECT run_id FROM analysis_run_inputs WHERE record_id=NEW.record_id AND payload_sha256<>NEW.payload_sha256);
    UPDATE analysis_artifacts SET status='invalidated',updated_at=datetime('now')
    WHERE id IN (
        SELECT ar.artifact_id FROM analysis_runs ar
        JOIN analysis_run_inputs ari ON ari.run_id=ar.id
        WHERE ari.record_id=NEW.record_id AND ari.payload_sha256<>NEW.payload_sha256
    );
END;

CREATE TRIGGER package_exports_no_update BEFORE UPDATE ON analysis_package_exports
BEGIN SELECT RAISE(ABORT, 'analysis package exports are append-only'); END;
CREATE TRIGGER package_exports_no_delete BEFORE DELETE ON analysis_package_exports
BEGIN SELECT RAISE(ABORT, 'analysis package exports are append-only'); END;
