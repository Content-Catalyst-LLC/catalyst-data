-- Catalyst Data v1.5.0 current schema snapshot
-- Repository initialization uses ordered migrations in python/catalyst_data/migrations.
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;
CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('country','organization','project','program','site','policy','persona','experiment','dataset','other')),
    name TEXT NOT NULL,
    description TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), canonical_id TEXT, external_ids_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(entity_type, name)
);

CREATE TABLE indicators (
    id INTEGER PRIMARY KEY,
    code TEXT,
    name TEXT NOT NULL,
    framework TEXT,
    unit TEXT,
    direction TEXT NOT NULL DEFAULT 'neutral' CHECK(direction IN ('higher','lower','neutral')),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), canonical_id TEXT, version TEXT NOT NULL DEFAULT '1.0', namespace TEXT NOT NULL DEFAULT 'sc', domain TEXT NOT NULL DEFAULT 'general', custodian TEXT NOT NULL DEFAULT 'Content Catalyst LLC', status TEXT NOT NULL DEFAULT 'active', definition TEXT, frequency TEXT NOT NULL DEFAULT 'annual', aggregation TEXT NOT NULL DEFAULT 'point-estimate', disaggregation_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(framework, code),
    UNIQUE(name, framework)
);

CREATE TABLE periods (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    period_type TEXT NOT NULL CHECK(period_type IN ('date','month','quarter','year','custom')),
    start_date TEXT,
    end_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
, canonical_id TEXT);

CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'unspecified',
    url TEXT,
    publisher TEXT,
    license TEXT,
    retrieved_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
, canonical_id TEXT, citation TEXT, checksum TEXT, access_notes TEXT);

CREATE TABLE measurements (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    indicator_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    source_id INTEGER,
    value REAL NOT NULL,
    baseline_value REAL,
    confidence REAL NOT NULL DEFAULT 0 CHECK(confidence >= 0 AND confidence <= 100),
    method TEXT,
    assumptions TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT, canonical_id TEXT, limitations TEXT NOT NULL DEFAULT '[]', uncertainty TEXT, quality_flags TEXT NOT NULL DEFAULT '[]', reviewer_notes TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
    UNIQUE(entity_id, indicator_id, period_id, source_id)
);

CREATE TABLE measurement_notes (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL,
    note_type TEXT NOT NULL CHECK(note_type IN ('method','assumption','limitation','review','revision')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(kind, name)
);

CREATE TABLE entity_tags (
    entity_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (entity_id, tag_id),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE indicator_tags (
    indicator_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (indicator_id, tag_id),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE repository_metadata (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    repository_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE data_records (
    record_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    record_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    indicator_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    source_id INTEGER,
    measurement_id INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stored_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE RESTRICT,
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE TABLE import_runs (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_format TEXT NOT NULL CHECK(source_format IN ('json','csv')),
    dry_run INTEGER NOT NULL DEFAULT 0 CHECK(dry_run IN (0,1)),
    atomic_mode INTEGER NOT NULL DEFAULT 1 CHECK(atomic_mode IN (0,1)),
    status TEXT NOT NULL CHECK(status IN ('running','completed','completed_with_errors','failed')),
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE import_row_errors (
    id INTEGER PRIMARY KEY,
    import_run_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    error_message TEXT NOT NULL,
    raw_payload TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (import_run_id) REFERENCES import_runs(id) ON DELETE CASCADE
);

CREATE TABLE import_records (
    id INTEGER PRIMARY KEY,
    import_run_id INTEGER NOT NULL,
    row_number INTEGER,
    record_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','skipped')),
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (import_run_id) REFERENCES import_runs(id) ON DELETE CASCADE
);

CREATE TABLE source_versions (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    UNIQUE(source_id, version_number),
    UNIQUE(source_id, payload_sha256)
);

CREATE TABLE source_snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    source_version_id INTEGER NOT NULL,
    retrieved_at TEXT,
    content_sha256 TEXT,
    storage_uri TEXT,
    media_type TEXT,
    byte_size INTEGER CHECK(byte_size IS NULL OR byte_size >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_version_id) REFERENCES source_versions(id) ON DELETE RESTRICT
);

CREATE TABLE measurement_sources (
    measurement_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    source_version_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('primary','supporting','conflicting','derived','contextual')),
    locator_json TEXT NOT NULL DEFAULT '{}',
    supports_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (measurement_id, source_id, role),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_version_id) REFERENCES source_versions(id) ON DELETE RESTRICT
);

CREATE TABLE source_relationships (
    id INTEGER PRIMARY KEY,
    subject_source_id INTEGER NOT NULL,
    predicate TEXT NOT NULL CHECK(predicate IN ('corroborates','conflicts_with','derived_from','supersedes','duplicates','contextualizes')),
    object_source_id INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (subject_source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (object_source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    UNIQUE(subject_source_id, predicate, object_source_id),
    CHECK(subject_source_id <> object_source_id)
);

CREATE TABLE record_revisions (
    id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','corrected','superseded')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    import_run_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (import_run_id) REFERENCES import_runs(id) ON DELETE SET NULL,
    UNIQUE(record_id, revision_number),
    UNIQUE(record_id, payload_sha256)
);

CREATE TABLE provenance_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    measurement_id INTEGER,
    source_id INTEGER,
    event_type TEXT NOT NULL CHECK(event_type IN ('record_created','record_updated','source_versioned','source_snapshot_added','source_linked','source_unlinked','transformed','reviewed','published','corrected','superseded','imported')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    previous_event_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_event_id) REFERENCES provenance_events(event_id) ON DELETE RESTRICT
);

CREATE TABLE evidence_gaps (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL,
    gap_code TEXT NOT NULL CHECK(gap_code IN ('missing-source','missing-citation','missing-license','missing-retrieval-date','missing-checksum','missing-method','low-confidence','conflicting-evidence','restricted-source','stale-source')),
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
    description TEXT NOT NULL,
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE,
    UNIQUE(measurement_id, gap_code, resolved_at)
);

CREATE TABLE unit_definitions (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    dimension TEXT NOT NULL,
    canonical_unit_id TEXT NOT NULL,
    conversion_factor REAL NOT NULL DEFAULT 1 CHECK(conversion_factor > 0),
    conversion_offset REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(dimension, symbol)
);

CREATE TABLE indicator_versions (
    id INTEGER PRIMARY KEY,
    indicator_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','active','deprecated','replaced','archived')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    UNIQUE(indicator_id, version, revision_number),
    UNIQUE(indicator_id, payload_sha256)
);

CREATE TABLE indicator_aliases (
    indicator_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (indicator_id, alias),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE CASCADE
);

CREATE TABLE methodologies (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    current_status TEXT NOT NULL CHECK(current_status IN ('draft','in-review','approved','deprecated','archived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE methodology_versions (
    id INTEGER PRIMARY KEY,
    methodology_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','in-review','approved','deprecated','archived')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (methodology_id) REFERENCES methodologies(id) ON DELETE RESTRICT,
    UNIQUE(methodology_id, version, revision_number),
    UNIQUE(methodology_id, payload_sha256),
    CHECK(status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE TABLE indicator_methodologies (
    indicator_version_id INTEGER NOT NULL,
    methodology_version_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary','alternative','legacy')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (indicator_version_id, methodology_version_id, role),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (methodology_version_id) REFERENCES methodology_versions(id) ON DELETE RESTRICT
);

CREATE TABLE indicator_unit_assignments (
    indicator_version_id INTEGER NOT NULL,
    unit_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'reporting' CHECK(role IN ('reporting','numerator','denominator','conversion')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (indicator_version_id, unit_id, role),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

CREATE TABLE framework_mappings (
    id INTEGER PRIMARY KEY,
    indicator_version_id INTEGER NOT NULL,
    framework TEXT NOT NULL,
    mapping_code TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK(relationship IN ('exactMatch','closeMatch','broaderMatch','narrowerMatch','relatedMatch')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE CASCADE,
    UNIQUE(indicator_version_id, framework, mapping_code, relationship)
);

CREATE TABLE indicator_compatibility_rules (
    id INTEGER PRIMARY KEY,
    indicator_version_id INTEGER NOT NULL,
    comparable_version TEXT NOT NULL,
    required_dimensions_json TEXT NOT NULL DEFAULT '[]',
    methodology_equivalence_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE CASCADE,
    UNIQUE(indicator_version_id, comparable_version)
);

CREATE TABLE governance_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    indicator_id INTEGER NOT NULL,
    indicator_version_id INTEGER,
    methodology_version_id INTEGER,
    unit_id INTEGER,
    event_type TEXT NOT NULL CHECK(event_type IN ('indicator_registered','indicator_versioned','methodology_versioned','unit_registered','framework_mapped','compatibility_rule_added')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (methodology_version_id) REFERENCES methodology_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

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

CREATE INDEX idx_measurements_entity ON measurements(entity_id);

CREATE INDEX idx_measurements_indicator ON measurements(indicator_id);

CREATE INDEX idx_measurements_period ON measurements(period_id);

CREATE INDEX idx_measurements_source ON measurements(source_id);

CREATE INDEX idx_measurements_confidence ON measurements(confidence);

CREATE UNIQUE INDEX ux_entities_canonical_id ON entities(canonical_id);

CREATE UNIQUE INDEX ux_indicators_canonical_id ON indicators(canonical_id);

CREATE UNIQUE INDEX ux_periods_canonical_id ON periods(canonical_id);

CREATE UNIQUE INDEX ux_sources_canonical_id ON sources(canonical_id);

CREATE UNIQUE INDEX ux_measurements_canonical_id ON measurements(canonical_id);

CREATE INDEX idx_data_records_schema ON data_records(schema_version);

CREATE INDEX idx_data_records_updated ON data_records(updated_at);

CREATE INDEX idx_import_errors_run ON import_row_errors(import_run_id);

CREATE INDEX idx_import_records_run ON import_records(import_run_id);

CREATE INDEX idx_import_records_record ON import_records(record_id);

CREATE INDEX idx_source_versions_source ON source_versions(source_id, version_number DESC);

CREATE INDEX idx_measurement_sources_source ON measurement_sources(source_id);

CREATE INDEX idx_measurement_sources_role ON measurement_sources(role);

CREATE INDEX idx_record_revisions_record ON record_revisions(record_id, revision_number DESC);

CREATE INDEX idx_provenance_record ON provenance_events(record_id, id);

CREATE INDEX idx_provenance_source ON provenance_events(source_id, id);

CREATE INDEX idx_evidence_gaps_open ON evidence_gaps(resolved_at, severity);

CREATE INDEX idx_unit_definitions_dimension ON unit_definitions(dimension, canonical_unit_id);

CREATE INDEX idx_indicator_versions_indicator ON indicator_versions(indicator_id, version, revision_number DESC);

CREATE INDEX idx_methodology_versions_method ON methodology_versions(methodology_id, version, revision_number DESC);

CREATE INDEX idx_governance_events_indicator ON governance_events(indicator_id, id);

CREATE INDEX idx_research_questions_status ON research_questions(status, question_type);

CREATE INDEX idx_instrument_versions_current ON instrument_versions(instrument_id, version, revision_number DESC);

CREATE INDEX idx_datasets_access ON datasets(access_classification);

CREATE INDEX idx_dataset_versions_current ON dataset_versions(dataset_id, version, revision_number DESC);

CREATE INDEX idx_observation_batches_dataset ON observation_batches(dataset_version_id, collected_at);

CREATE INDEX idx_observations_batch_role ON observations(batch_id, role, observed_at);

CREATE INDEX idx_observations_quality ON observations(quality_status);

CREATE INDEX idx_observation_transformations_measurement ON observation_transformations(measurement_id, occurred_at);

CREATE INDEX idx_lineage_events_record ON lineage_events(record_id, id);

CREATE TRIGGER source_versions_immutable_update BEFORE UPDATE ON source_versions BEGIN SELECT RAISE(ABORT, 'source_versions are immutable'); END;

CREATE TRIGGER source_versions_immutable_delete BEFORE DELETE ON source_versions BEGIN SELECT RAISE(ABORT, 'source_versions are immutable'); END;

CREATE TRIGGER source_snapshots_immutable_update BEFORE UPDATE ON source_snapshots BEGIN SELECT RAISE(ABORT, 'source_snapshots are immutable'); END;

CREATE TRIGGER source_snapshots_immutable_delete BEFORE DELETE ON source_snapshots BEGIN SELECT RAISE(ABORT, 'source_snapshots are immutable'); END;

CREATE TRIGGER record_revisions_immutable_update BEFORE UPDATE ON record_revisions BEGIN SELECT RAISE(ABORT, 'record_revisions are immutable'); END;

CREATE TRIGGER record_revisions_immutable_delete BEFORE DELETE ON record_revisions BEGIN SELECT RAISE(ABORT, 'record_revisions are immutable'); END;

CREATE TRIGGER provenance_events_immutable_update BEFORE UPDATE ON provenance_events BEGIN SELECT RAISE(ABORT, 'provenance_events are immutable'); END;

CREATE TRIGGER provenance_events_immutable_delete BEFORE DELETE ON provenance_events BEGIN SELECT RAISE(ABORT, 'provenance_events are immutable'); END;

CREATE TRIGGER indicator_versions_immutable_update BEFORE UPDATE ON indicator_versions BEGIN SELECT RAISE(ABORT, 'indicator_versions are immutable'); END;

CREATE TRIGGER indicator_versions_immutable_delete BEFORE DELETE ON indicator_versions BEGIN SELECT RAISE(ABORT, 'indicator_versions are immutable'); END;

CREATE TRIGGER methodology_versions_immutable_update BEFORE UPDATE ON methodology_versions BEGIN SELECT RAISE(ABORT, 'methodology_versions are immutable'); END;

CREATE TRIGGER methodology_versions_immutable_delete BEFORE DELETE ON methodology_versions BEGIN SELECT RAISE(ABORT, 'methodology_versions are immutable'); END;

CREATE TRIGGER governance_events_immutable_update BEFORE UPDATE ON governance_events BEGIN SELECT RAISE(ABORT, 'governance_events are immutable'); END;

CREATE TRIGGER governance_events_immutable_delete BEFORE DELETE ON governance_events BEGIN SELECT RAISE(ABORT, 'governance_events are immutable'); END;

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

CREATE VIEW evidence_chain_summary AS
SELECT
    m.id AS measurement_id,
    m.canonical_id AS record_id,
    COUNT(ms.source_id) AS source_count,
    SUM(CASE WHEN ms.role = 'primary' THEN 1 ELSE 0 END) AS primary_source_count,
    SUM(CASE WHEN ms.role = 'supporting' THEN 1 ELSE 0 END) AS supporting_source_count,
    SUM(CASE WHEN ms.role = 'conflicting' THEN 1 ELSE 0 END) AS conflicting_source_count,
    (SELECT COUNT(*) FROM evidence_gaps eg WHERE eg.measurement_id = m.id AND eg.resolved_at IS NULL) AS open_gap_count,
    (SELECT COUNT(*) FROM record_revisions rr WHERE rr.record_id = m.canonical_id) AS revision_count,
    (SELECT COUNT(*) FROM provenance_events pe WHERE pe.record_id = m.canonical_id) AS provenance_event_count
FROM measurements m
LEFT JOIN measurement_sources ms ON ms.measurement_id = m.id
GROUP BY m.id, m.canonical_id;

CREATE VIEW open_evidence_gaps AS
SELECT eg.*, m.canonical_id AS record_id, e.name AS entity, i.name AS indicator
FROM evidence_gaps eg
JOIN measurements m ON m.id = eg.measurement_id
JOIN entities e ON e.id = m.entity_id
JOIN indicators i ON i.id = m.indicator_id
WHERE eg.resolved_at IS NULL;

CREATE VIEW indicator_registry_current AS
SELECT
    i.id AS indicator_row_id,
    i.canonical_id AS indicator_id,
    i.namespace,
    i.code,
    i.name,
    i.domain,
    i.custodian,
    i.status,
    i.definition,
    i.framework,
    i.unit,
    i.direction,
    i.frequency,
    i.aggregation,
    i.disaggregation_json,
    iv.id AS indicator_version_id,
    iv.version,
    iv.revision_number,
    iv.payload_sha256,
    iv.created_at AS version_created_at
FROM indicators i
JOIN indicator_versions iv ON iv.id = (
    SELECT iv2.id FROM indicator_versions iv2
    WHERE iv2.indicator_id = i.id
    ORDER BY iv2.created_at DESC, iv2.id DESC LIMIT 1
);

CREATE VIEW measurement_governance_review AS
SELECT
    mr.*,
    ir.namespace,
    ir.code AS registry_code,
    ir.domain,
    ir.custodian,
    ir.status AS indicator_status,
    ir.frequency,
    ir.aggregation,
    CASE
        WHEN ir.status IN ('deprecated','replaced','archived') THEN 'governance review required'
        WHEN ir.indicator_version_id IS NULL THEN 'missing governance'
        ELSE 'governed'
    END AS governance_status
FROM measurement_review mr
LEFT JOIN indicator_registry_current ir ON ir.indicator_id = mr.indicator_id;

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
COMMIT;

-- BEGIN GENERATED REVIEW CONTRACT
DROP VIEW IF EXISTS low_confidence_measurements;
DROP VIEW IF EXISTS provenance_gaps;
DROP VIEW IF EXISTS measurement_review;

CREATE VIEW measurement_review AS
SELECT
    m.id AS measurement_id,
    m.canonical_id AS record_id,
    e.canonical_id AS entity_id,
    e.name AS entity,
    e.entity_type,
    i.canonical_id AS indicator_id,
    i.name AS indicator,
    i.framework,
    i.unit,
    i.direction,
    i.version AS indicator_version,
    p.canonical_id AS period_id,
    p.label AS period,
    m.baseline_value,
    m.value,
    CASE
        WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN NULL
        ELSE ROUND(((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0, 2)
    END AS percent_change,
    s.canonical_id AS source_id,
    s.name AS source,
    s.source_type,
    s.publisher,
    s.license,
    m.confidence,
    CASE
        WHEN m.source_id IS NULL THEN 'missing source'
        WHEN m.confidence < 40 THEN 'needs evidence'
        WHEN m.confidence < 70 THEN 'reviewable with caution'
        ELSE 'reviewable'
    END AS review_status,
    CASE
        WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN 'indeterminate'
        WHEN m.value = m.baseline_value THEN 'unchanged'
        WHEN i.direction = 'neutral' THEN 'descriptive'
        WHEN i.direction = 'higher' AND m.value > m.baseline_value THEN 'improving'
        WHEN i.direction = 'lower' AND m.value < m.baseline_value THEN 'improving'
        ELSE 'declining'
    END AS signal_status,
    m.method,
    m.assumptions,
    m.limitations,
    m.uncertainty,
    m.quality_flags,
    m.reviewer_notes
FROM measurements m
JOIN entities e ON e.id = m.entity_id
JOIN indicators i ON i.id = m.indicator_id
JOIN periods p ON p.id = m.period_id
LEFT JOIN sources s ON s.id = m.source_id;

CREATE VIEW provenance_gaps AS
SELECT * FROM measurement_review
WHERE source IS NULL
   OR confidence < 40
   OR method IS NULL
   OR LENGTH(TRIM(COALESCE(method, ''))) = 0;

CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review
WHERE confidence < 70;
-- END GENERATED REVIEW CONTRACT
