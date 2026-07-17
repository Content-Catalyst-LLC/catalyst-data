PRAGMA foreign_keys = ON;

CREATE TABLE research_questions (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK(question_type IN ('research','decision','monitoring','evaluation')),
    decision_context TEXT,
    status TEXT NOT NULL CHECK(status IN ('draft','active','answered','archived')),
    owner TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_research_questions_status ON research_questions(status, question_type);

CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    instrument_type TEXT NOT NULL CHECK(instrument_type IN ('survey','sensor','form','api','administrative','model','manual','other')),
    current_version TEXT NOT NULL,
    description TEXT,
    provider TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE instrument_versions (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    UNIQUE(instrument_id, version, revision_number),
    UNIQUE(instrument_id, payload_sha256)
);
CREATE INDEX idx_instrument_versions_current ON instrument_versions(instrument_id, version, revision_number DESC);

CREATE TABLE instrument_fields (
    instrument_version_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('string','number','integer','boolean','date','datetime','object','array')),
    unit_id INTEGER,
    description TEXT,
    required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0,1)),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_version_id, field_name),
    FOREIGN KEY (instrument_version_id) REFERENCES instrument_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

CREATE TABLE datasets (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    current_version TEXT NOT NULL,
    description TEXT,
    license TEXT,
    access_classification TEXT NOT NULL CHECK(access_classification IN ('public','internal','restricted','confidential')),
    checksum TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_datasets_access ON datasets(access_classification);

CREATE TABLE dataset_versions (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE RESTRICT,
    UNIQUE(dataset_id, version, revision_number),
    UNIQUE(dataset_id, payload_sha256)
);
CREATE INDEX idx_dataset_versions_current ON dataset_versions(dataset_id, version, revision_number DESC);

CREATE TABLE dataset_fields (
    dataset_version_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('string','number','integer','boolean','date','datetime','object','array')),
    unit_id INTEGER,
    description TEXT,
    nullable INTEGER NOT NULL DEFAULT 1 CHECK(nullable IN (0,1)),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dataset_version_id, field_name),
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

CREATE TABLE observation_batches (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    dataset_version_id INTEGER NOT NULL,
    instrument_version_id INTEGER NOT NULL,
    collected_at TEXT,
    received_at TEXT,
    collector TEXT,
    protocol TEXT,
    record_count INTEGER NOT NULL DEFAULT 0 CHECK(record_count >= 0),
    notes TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (instrument_version_id) REFERENCES instrument_versions(id) ON DELETE RESTRICT
);
CREATE INDEX idx_observation_batches_dataset ON observation_batches(dataset_version_id, collected_at);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    batch_id INTEGER NOT NULL,
    observed_at TEXT,
    role TEXT NOT NULL CHECK(role IN ('baseline','current','supporting','derived')),
    value_numeric REAL,
    value_text TEXT,
    unit_id INTEGER,
    quality_status TEXT NOT NULL CHECK(quality_status IN ('valid','missing','censored','outlier','imputed','rejected')),
    missing_reason TEXT,
    censoring TEXT,
    outlier INTEGER NOT NULL DEFAULT 0 CHECK(outlier IN (0,1)),
    imputation TEXT,
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (batch_id) REFERENCES observation_batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT,
    CHECK(value_numeric IS NOT NULL OR value_text IS NOT NULL OR quality_status = 'missing'),
    CHECK(quality_status <> 'missing' OR missing_reason IS NOT NULL)
);
CREATE INDEX idx_observations_batch_role ON observations(batch_id, role, observed_at);
CREATE INDEX idx_observations_quality ON observations(quality_status);

CREATE TABLE observation_dimensions (
    observation_id INTEGER NOT NULL,
    dimension_name TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    PRIMARY KEY (observation_id, dimension_name),
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE RESTRICT
);

CREATE TABLE measurement_questions (
    measurement_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary','supporting','contextual')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (measurement_id, question_id, role),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (question_id) REFERENCES research_questions(id) ON DELETE RESTRICT
);

CREATE TABLE measurement_observations (
    measurement_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('baseline','current','supporting','derived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (measurement_id, observation_id, role),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE RESTRICT
);

CREATE TABLE observation_transformations (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    measurement_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    description TEXT NOT NULL,
    software TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    output_fields_json TEXT NOT NULL DEFAULT '[]',
    occurred_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT
);
CREATE INDEX idx_observation_transformations_measurement ON observation_transformations(measurement_id, occurred_at);

CREATE TABLE transformation_inputs (
    transformation_id INTEGER NOT NULL,
    observation_id INTEGER NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (transformation_id, observation_id),
    FOREIGN KEY (transformation_id) REFERENCES observation_transformations(id) ON DELETE RESTRICT,
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE RESTRICT
);

CREATE TABLE lineage_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    measurement_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('question_linked','instrument_versioned','dataset_versioned','batch_registered','observation_recorded','observation_linked','transformation_recorded')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    previous_event_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_event_id) REFERENCES lineage_events(event_id) ON DELETE RESTRICT
);
CREATE INDEX idx_lineage_events_record ON lineage_events(record_id, id);

CREATE TRIGGER instrument_versions_immutable_update BEFORE UPDATE ON instrument_versions
BEGIN SELECT RAISE(ABORT, 'instrument versions are immutable'); END;
CREATE TRIGGER instrument_versions_immutable_delete BEFORE DELETE ON instrument_versions
BEGIN SELECT RAISE(ABORT, 'instrument versions are immutable'); END;
CREATE TRIGGER dataset_versions_immutable_update BEFORE UPDATE ON dataset_versions
BEGIN SELECT RAISE(ABORT, 'dataset versions are immutable'); END;
CREATE TRIGGER dataset_versions_immutable_delete BEFORE DELETE ON dataset_versions
BEGIN SELECT RAISE(ABORT, 'dataset versions are immutable'); END;
CREATE TRIGGER lineage_events_immutable_update BEFORE UPDATE ON lineage_events
BEGIN SELECT RAISE(ABORT, 'lineage events are immutable'); END;
CREATE TRIGGER lineage_events_immutable_delete BEFORE DELETE ON lineage_events
BEGIN SELECT RAISE(ABORT, 'lineage events are immutable'); END;

CREATE VIEW observation_lineage_summary AS
SELECT
    dr.record_id,
    COUNT(DISTINCT mq.question_id) AS question_count,
    COUNT(DISTINCT ob.instrument_version_id) AS instrument_version_count,
    COUNT(DISTINCT ob.dataset_version_id) AS dataset_version_count,
    COUNT(DISTINCT ob.id) AS batch_count,
    COUNT(DISTINCT mo.observation_id) AS observation_count,
    COUNT(DISTINCT ot.id) AS transformation_count,
    SUM(CASE WHEN o.quality_status = 'missing' THEN 1 ELSE 0 END) AS missing_observation_count,
    SUM(CASE WHEN o.quality_status IN ('outlier','rejected') THEN 1 ELSE 0 END) AS flagged_observation_count
FROM data_records dr
JOIN measurements m ON m.id = dr.measurement_id
LEFT JOIN measurement_questions mq ON mq.measurement_id = m.id
LEFT JOIN measurement_observations mo ON mo.measurement_id = m.id
LEFT JOIN observations o ON o.id = mo.observation_id
LEFT JOIN observation_batches ob ON ob.id = o.batch_id
LEFT JOIN observation_transformations ot ON ot.measurement_id = m.id
GROUP BY dr.record_id;

CREATE VIEW dataset_registry_current AS
SELECT d.canonical_id AS dataset_id, d.name, d.current_version, d.description, d.license,
       d.access_classification, d.checksum, dv.revision_number, dv.payload_sha256, dv.created_at
FROM datasets d
JOIN dataset_versions dv ON dv.id = (
    SELECT dv2.id FROM dataset_versions dv2 WHERE dv2.dataset_id=d.id ORDER BY dv2.id DESC LIMIT 1
);

CREATE VIEW instrument_registry_current AS
SELECT i.canonical_id AS instrument_id, i.name, i.instrument_type, i.current_version,
       i.description, i.provider, iv.revision_number, iv.payload_sha256, iv.created_at
FROM instruments i
JOIN instrument_versions iv ON iv.id = (
    SELECT iv2.id FROM instrument_versions iv2 WHERE iv2.instrument_id=i.id ORDER BY iv2.id DESC LIMIT 1
);
