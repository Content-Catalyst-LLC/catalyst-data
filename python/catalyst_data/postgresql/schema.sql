-- Catalyst Data v2.1.0 PostgreSQL schema

-- Generated from canonical ordered migrations. Do not edit by hand.

CREATE OR REPLACE FUNCTION json_valid(value TEXT) RETURNS BOOLEAN AS $$
BEGIN
    PERFORM value::jsonb;
    RETURN TRUE;
EXCEPTION WHEN others THEN
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- migration 001_core_schema
CREATE TABLE entities (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('country','organization','project','program','site','policy','persona','experiment','dataset','other')),
    name TEXT NOT NULL,
    description TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(entity_type, name)
);

CREATE TABLE indicators (
    id BIGSERIAL PRIMARY KEY,
    code TEXT,
    name TEXT NOT NULL,
    framework TEXT,
    unit TEXT,
    direction TEXT NOT NULL DEFAULT 'neutral' CHECK(direction IN ('higher','lower','neutral')),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(framework, code),
    UNIQUE(name, framework)
);

CREATE TABLE periods (
    id BIGSERIAL PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    period_type TEXT NOT NULL CHECK(period_type IN ('date','month','quarter','year','custom')),
    start_date TEXT,
    end_date TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE sources (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'unspecified',
    url TEXT,
    publisher TEXT,
    license TEXT,
    retrieved_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE measurements (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL,
    indicator_id BIGINT NOT NULL,
    period_id BIGINT NOT NULL,
    source_id BIGINT,
    value DOUBLE PRECISION NOT NULL,
    baseline_value DOUBLE PRECISION,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(confidence >= 0 AND confidence <= 100),
    method TEXT,
    assumptions TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
    UNIQUE(entity_id, indicator_id, period_id, source_id)
);

CREATE TABLE measurement_notes (
    id BIGSERIAL PRIMARY KEY,
    measurement_id BIGINT NOT NULL,
    note_type TEXT NOT NULL CHECK(note_type IN ('method','assumption','limitation','review','revision')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE TABLE tags (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(kind, name)
);

CREATE TABLE entity_tags (
    entity_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    PRIMARY KEY (entity_id, tag_id),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE indicator_tags (
    indicator_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    PRIMARY KEY (indicator_id, tag_id),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_measurements_entity ON measurements(entity_id);
CREATE INDEX idx_measurements_indicator ON measurements(indicator_id);
CREATE INDEX idx_measurements_period ON measurements(period_id);
CREATE INDEX idx_measurements_source ON measurements(source_id);
CREATE INDEX idx_measurements_confidence ON measurements(confidence);

CREATE VIEW measurement_review AS
SELECT
    m.id AS measurement_id,
    e.name AS entity,
    e.entity_type,
    i.name AS indicator,
    i.framework,
    i.unit,
    i.direction,
    p.label AS period,
    m.baseline_value,
    m.value,
    CASE
        WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN NULL
        ELSE ROUND((((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0)::numeric, 2)::double precision
    END AS percent_change,
    s.name AS source,
    s.source_type,
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
    m.assumptions
FROM measurements m
JOIN entities e ON e.id = m.entity_id
JOIN indicators i ON i.id = m.indicator_id
JOIN periods p ON p.id = m.period_id
LEFT JOIN sources s ON s.id = m.source_id;

CREATE VIEW provenance_gaps AS
SELECT * FROM measurement_review
WHERE source IS NULL OR confidence < 40 OR method IS NULL OR LENGTH(TRIM(COALESCE(method, ''))) = 0;

CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review WHERE confidence < 70;


-- migration 002_persistent_repository
DROP VIEW low_confidence_measurements;
DROP VIEW provenance_gaps;
DROP VIEW measurement_review;

ALTER TABLE entities ADD COLUMN canonical_id TEXT;
ALTER TABLE entities ADD COLUMN external_ids_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE indicators ADD COLUMN canonical_id TEXT;
ALTER TABLE indicators ADD COLUMN version TEXT NOT NULL DEFAULT '1.0';
ALTER TABLE periods ADD COLUMN canonical_id TEXT;
ALTER TABLE sources ADD COLUMN canonical_id TEXT;
ALTER TABLE sources ADD COLUMN citation TEXT;
ALTER TABLE sources ADD COLUMN checksum TEXT;
ALTER TABLE sources ADD COLUMN access_notes TEXT;
ALTER TABLE measurements ADD COLUMN canonical_id TEXT;
ALTER TABLE measurements ADD COLUMN limitations TEXT NOT NULL DEFAULT '[]';
ALTER TABLE measurements ADD COLUMN uncertainty TEXT;
ALTER TABLE measurements ADD COLUMN quality_flags TEXT NOT NULL DEFAULT '[]';
ALTER TABLE measurements ADD COLUMN reviewer_notes TEXT;

CREATE UNIQUE INDEX ux_entities_canonical_id ON entities(canonical_id);
CREATE UNIQUE INDEX ux_indicators_canonical_id ON indicators(canonical_id);
CREATE UNIQUE INDEX ux_periods_canonical_id ON periods(canonical_id);
CREATE UNIQUE INDEX ux_sources_canonical_id ON sources(canonical_id);
CREATE UNIQUE INDEX ux_measurements_canonical_id ON measurements(canonical_id);

CREATE TABLE repository_metadata (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    repository_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);
INSERT INTO repository_metadata(id, repository_id)
VALUES (1, 'repository:postgresql:' || md5(random()::text || clock_timestamp()::text));

CREATE TABLE data_records (
    record_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    record_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    entity_id BIGINT NOT NULL,
    indicator_id BIGINT NOT NULL,
    period_id BIGINT NOT NULL,
    source_id BIGINT,
    measurement_id BIGINT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stored_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE RESTRICT,
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);
CREATE INDEX idx_data_records_schema ON data_records(schema_version);
CREATE INDEX idx_data_records_updated ON data_records(updated_at);

CREATE TABLE import_runs (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_format TEXT NOT NULL CHECK(source_format IN ('json','csv')),
    dry_run INTEGER NOT NULL DEFAULT 0 CHECK(dry_run IN (0,1)),
    atomic_mode INTEGER NOT NULL DEFAULT 1 CHECK(atomic_mode IN (0,1)),
    status TEXT NOT NULL CHECK(status IN ('running','completed','completed_with_errors','failed')),
    started_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    finished_at TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE import_row_errors (
    id BIGSERIAL PRIMARY KEY,
    import_run_id BIGINT NOT NULL,
    row_number INTEGER NOT NULL,
    error_message TEXT NOT NULL,
    raw_payload TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (import_run_id) REFERENCES import_runs(id) ON DELETE CASCADE
);
CREATE INDEX idx_import_errors_run ON import_row_errors(import_run_id);

CREATE TABLE import_records (
    id BIGSERIAL PRIMARY KEY,
    import_run_id BIGINT NOT NULL,
    row_number INTEGER,
    record_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','skipped')),
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (import_run_id) REFERENCES import_runs(id) ON DELETE CASCADE
);
CREATE INDEX idx_import_records_run ON import_records(import_run_id);
CREATE INDEX idx_import_records_record ON import_records(record_id);

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
        ELSE ROUND((((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0)::numeric, 2)::double precision
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
WHERE source IS NULL OR confidence < 40 OR method IS NULL OR LENGTH(TRIM(COALESCE(method, ''))) = 0;

CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review WHERE confidence < 70;


-- migration 003_sources_provenance_evidence
CREATE TABLE source_versions (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL,
    version_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    UNIQUE(source_id, version_number),
    UNIQUE(source_id, payload_sha256)
);
CREATE INDEX idx_source_versions_source ON source_versions(source_id, version_number DESC);

CREATE TABLE source_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    source_version_id BIGINT NOT NULL,
    retrieved_at TEXT,
    content_sha256 TEXT,
    storage_uri TEXT,
    media_type TEXT,
    byte_size INTEGER CHECK(byte_size IS NULL OR byte_size >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (source_version_id) REFERENCES source_versions(id) ON DELETE RESTRICT
);

CREATE TABLE measurement_sources (
    measurement_id BIGINT NOT NULL,
    source_id BIGINT NOT NULL,
    source_version_id BIGINT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('primary','supporting','conflicting','derived','contextual')),
    locator_json TEXT NOT NULL DEFAULT '{}',
    supports_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    PRIMARY KEY (measurement_id, source_id, role),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_version_id) REFERENCES source_versions(id) ON DELETE RESTRICT
);
CREATE INDEX idx_measurement_sources_source ON measurement_sources(source_id);
CREATE INDEX idx_measurement_sources_role ON measurement_sources(role);

CREATE TABLE source_relationships (
    id BIGSERIAL PRIMARY KEY,
    subject_source_id BIGINT NOT NULL,
    predicate TEXT NOT NULL CHECK(predicate IN ('corroborates','conflicts_with','derived_from','supersedes','duplicates','contextualizes')),
    object_source_id BIGINT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (subject_source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (object_source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    UNIQUE(subject_source_id, predicate, object_source_id),
    CHECK(subject_source_id <> object_source_id)
);

CREATE TABLE record_revisions (
    id BIGSERIAL PRIMARY KEY,
    record_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','corrected','superseded')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    import_run_id BIGINT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (import_run_id) REFERENCES import_runs(id) ON DELETE SET NULL,
    UNIQUE(record_id, revision_number),
    UNIQUE(record_id, payload_sha256)
);
CREATE INDEX idx_record_revisions_record ON record_revisions(record_id, revision_number DESC);

CREATE TABLE provenance_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    measurement_id BIGINT,
    source_id BIGINT,
    event_type TEXT NOT NULL CHECK(event_type IN ('record_created','record_updated','source_versioned','source_snapshot_added','source_linked','source_unlinked','transformed','reviewed','published','corrected','superseded','imported')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    previous_event_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_event_id) REFERENCES provenance_events(event_id) ON DELETE RESTRICT
);
CREATE INDEX idx_provenance_record ON provenance_events(record_id, id);
CREATE INDEX idx_provenance_source ON provenance_events(source_id, id);

CREATE TABLE evidence_gaps (
    id BIGSERIAL PRIMARY KEY,
    measurement_id BIGINT NOT NULL,
    gap_code TEXT NOT NULL CHECK(gap_code IN ('missing-source','missing-citation','missing-license','missing-retrieval-date','missing-checksum','missing-method','low-confidence','conflicting-evidence','restricted-source','stale-source')),
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
    description TEXT NOT NULL,
    detected_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    resolved_at TEXT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE,
    UNIQUE(measurement_id, gap_code, resolved_at)
);
CREATE INDEX idx_evidence_gaps_open ON evidence_gaps(resolved_at, severity);








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


-- migration 004_indicator_units_methodology
ALTER TABLE indicators ADD COLUMN namespace TEXT NOT NULL DEFAULT 'sc';
ALTER TABLE indicators ADD COLUMN domain TEXT NOT NULL DEFAULT 'general';
ALTER TABLE indicators ADD COLUMN custodian TEXT NOT NULL DEFAULT 'Content Catalyst LLC';
ALTER TABLE indicators ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE indicators ADD COLUMN definition TEXT;
ALTER TABLE indicators ADD COLUMN frequency TEXT NOT NULL DEFAULT 'annual';
ALTER TABLE indicators ADD COLUMN aggregation TEXT NOT NULL DEFAULT 'point-estimate';
ALTER TABLE indicators ADD COLUMN disaggregation_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE unit_definitions (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    dimension TEXT NOT NULL,
    canonical_unit_id TEXT NOT NULL,
    conversion_factor DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK(conversion_factor > 0),
    conversion_offset DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(dimension, symbol)
);
CREATE INDEX idx_unit_definitions_dimension ON unit_definitions(dimension, canonical_unit_id);

CREATE TABLE indicator_versions (
    id BIGSERIAL PRIMARY KEY,
    indicator_id BIGINT NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','active','deprecated','replaced','archived')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    UNIQUE(indicator_id, version, revision_number),
    UNIQUE(indicator_id, payload_sha256)
);
CREATE INDEX idx_indicator_versions_indicator ON indicator_versions(indicator_id, version, revision_number DESC);

CREATE TABLE indicator_aliases (
    indicator_id BIGINT NOT NULL,
    alias TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    PRIMARY KEY (indicator_id, alias),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE CASCADE
);

CREATE TABLE methodologies (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    current_status TEXT NOT NULL CHECK(current_status IN ('draft','in-review','approved','deprecated','archived')),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE methodology_versions (
    id BIGSERIAL PRIMARY KEY,
    methodology_id BIGINT NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','in-review','approved','deprecated','archived')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (methodology_id) REFERENCES methodologies(id) ON DELETE RESTRICT,
    UNIQUE(methodology_id, version, revision_number),
    UNIQUE(methodology_id, payload_sha256),
    CHECK(status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE INDEX idx_methodology_versions_method ON methodology_versions(methodology_id, version, revision_number DESC);

CREATE TABLE indicator_methodologies (
    indicator_version_id BIGINT NOT NULL,
    methodology_version_id BIGINT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary','alternative','legacy')),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    PRIMARY KEY (indicator_version_id, methodology_version_id, role),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (methodology_version_id) REFERENCES methodology_versions(id) ON DELETE RESTRICT
);

CREATE TABLE indicator_unit_assignments (
    indicator_version_id BIGINT NOT NULL,
    unit_id BIGINT NOT NULL,
    role TEXT NOT NULL DEFAULT 'reporting' CHECK(role IN ('reporting','numerator','denominator','conversion')),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    PRIMARY KEY (indicator_version_id, unit_id, role),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

CREATE TABLE framework_mappings (
    id BIGSERIAL PRIMARY KEY,
    indicator_version_id BIGINT NOT NULL,
    framework TEXT NOT NULL,
    mapping_code TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK(relationship IN ('exactMatch','closeMatch','broaderMatch','narrowerMatch','relatedMatch')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE CASCADE,
    UNIQUE(indicator_version_id, framework, mapping_code, relationship)
);

CREATE TABLE indicator_compatibility_rules (
    id BIGSERIAL PRIMARY KEY,
    indicator_version_id BIGINT NOT NULL,
    comparable_version TEXT NOT NULL,
    required_dimensions_json TEXT NOT NULL DEFAULT '[]',
    methodology_equivalence_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE CASCADE,
    UNIQUE(indicator_version_id, comparable_version)
);

CREATE TABLE governance_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    indicator_id BIGINT NOT NULL,
    indicator_version_id BIGINT,
    methodology_version_id BIGINT,
    unit_id BIGINT,
    event_type TEXT NOT NULL CHECK(event_type IN ('indicator_registered','indicator_versioned','methodology_versioned','unit_registered','framework_mapped','compatibility_rule_added')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (indicator_version_id) REFERENCES indicator_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (methodology_version_id) REFERENCES methodology_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);
CREATE INDEX idx_governance_events_indicator ON governance_events(indicator_id, id);






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


-- migration 005_questions_instruments_datasets_observations
CREATE TABLE research_questions (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK(question_type IN ('research','decision','monitoring','evaluation')),
    decision_context TEXT,
    status TEXT NOT NULL CHECK(status IN ('draft','active','answered','archived')),
    owner TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);
CREATE INDEX idx_research_questions_status ON research_questions(status, question_type);

CREATE TABLE instruments (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    instrument_type TEXT NOT NULL CHECK(instrument_type IN ('survey','sensor','form','api','administrative','model','manual','other')),
    current_version TEXT NOT NULL,
    description TEXT,
    provider TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE instrument_versions (
    id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    UNIQUE(instrument_id, version, revision_number),
    UNIQUE(instrument_id, payload_sha256)
);
CREATE INDEX idx_instrument_versions_current ON instrument_versions(instrument_id, version, revision_number DESC);

CREATE TABLE instrument_fields (
    instrument_version_id BIGINT NOT NULL,
    field_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('string','number','integer','boolean','date','datetime','object','array')),
    unit_id BIGINT,
    description TEXT,
    required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0,1)),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_version_id, field_name),
    FOREIGN KEY (instrument_version_id) REFERENCES instrument_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

CREATE TABLE datasets (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    current_version TEXT NOT NULL,
    description TEXT,
    license TEXT,
    access_classification TEXT NOT NULL CHECK(access_classification IN ('public','internal','restricted','confidential')),
    checksum TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);
CREATE INDEX idx_datasets_access ON datasets(access_classification);

CREATE TABLE dataset_versions (
    id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL,
    version TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE RESTRICT,
    UNIQUE(dataset_id, version, revision_number),
    UNIQUE(dataset_id, payload_sha256)
);
CREATE INDEX idx_dataset_versions_current ON dataset_versions(dataset_id, version, revision_number DESC);

CREATE TABLE dataset_fields (
    dataset_version_id BIGINT NOT NULL,
    field_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('string','number','integer','boolean','date','datetime','object','array')),
    unit_id BIGINT,
    description TEXT,
    nullable INTEGER NOT NULL DEFAULT 1 CHECK(nullable IN (0,1)),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dataset_version_id, field_name),
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT
);

CREATE TABLE observation_batches (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    dataset_version_id BIGINT NOT NULL,
    instrument_version_id BIGINT NOT NULL,
    collected_at TEXT,
    received_at TEXT,
    collector TEXT,
    protocol TEXT,
    record_count INTEGER NOT NULL DEFAULT 0 CHECK(record_count >= 0),
    notes TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (instrument_version_id) REFERENCES instrument_versions(id) ON DELETE RESTRICT
);
CREATE INDEX idx_observation_batches_dataset ON observation_batches(dataset_version_id, collected_at);

CREATE TABLE observations (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    batch_id BIGINT NOT NULL,
    observed_at TEXT,
    role TEXT NOT NULL CHECK(role IN ('baseline','current','supporting','derived')),
    value_numeric DOUBLE PRECISION,
    value_text TEXT,
    unit_id BIGINT,
    quality_status TEXT NOT NULL CHECK(quality_status IN ('valid','missing','censored','outlier','imputed','rejected')),
    missing_reason TEXT,
    censoring TEXT,
    outlier INTEGER NOT NULL DEFAULT 0 CHECK(outlier IN (0,1)),
    imputation TEXT,
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (batch_id) REFERENCES observation_batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES unit_definitions(id) ON DELETE RESTRICT,
    CHECK(value_numeric IS NOT NULL OR value_text IS NOT NULL OR quality_status = 'missing'),
    CHECK(quality_status <> 'missing' OR missing_reason IS NOT NULL)
);
CREATE INDEX idx_observations_batch_role ON observations(batch_id, role, observed_at);
CREATE INDEX idx_observations_quality ON observations(quality_status);

CREATE TABLE observation_dimensions (
    observation_id BIGINT NOT NULL,
    dimension_name TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    PRIMARY KEY (observation_id, dimension_name),
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE RESTRICT
);

CREATE TABLE measurement_questions (
    measurement_id BIGINT NOT NULL,
    question_id BIGINT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary','supporting','contextual')),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    PRIMARY KEY (measurement_id, question_id, role),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (question_id) REFERENCES research_questions(id) ON DELETE RESTRICT
);

CREATE TABLE measurement_observations (
    measurement_id BIGINT NOT NULL,
    observation_id BIGINT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('baseline','current','supporting','derived')),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    PRIMARY KEY (measurement_id, observation_id, role),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE RESTRICT
);

CREATE TABLE observation_transformations (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    measurement_id BIGINT NOT NULL,
    operation TEXT NOT NULL,
    description TEXT NOT NULL,
    software TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    output_fields_json TEXT NOT NULL DEFAULT '[]',
    occurred_at TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT
);
CREATE INDEX idx_observation_transformations_measurement ON observation_transformations(measurement_id, occurred_at);

CREATE TABLE transformation_inputs (
    transformation_id BIGINT NOT NULL,
    observation_id BIGINT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (transformation_id, observation_id),
    FOREIGN KEY (transformation_id) REFERENCES observation_transformations(id) ON DELETE RESTRICT,
    FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE RESTRICT
);

CREATE TABLE lineage_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    measurement_id BIGINT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('question_linked','instrument_versioned','dataset_versioned','batch_registered','observation_recorded','observation_linked','transformation_recorded')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    previous_event_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_event_id) REFERENCES lineage_events(event_id) ON DELETE RESTRICT
);
CREATE INDEX idx_lineage_events_record ON lineage_events(record_id, id);






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


-- migration 006_review_quality_revision_workflow
CREATE TABLE review_cases (
    id BIGSERIAL PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL UNIQUE,
    measurement_id BIGINT NOT NULL UNIQUE,
    current_state TEXT NOT NULL CHECK(current_state IN ('draft','submitted','in-review','changes-requested','approved','rejected','superseded','archived')),
    priority TEXT NOT NULL CHECK(priority IN ('low','normal','high','critical')),
    assigned_reviewers_json TEXT NOT NULL DEFAULT '[]',
    publication_status TEXT NOT NULL CHECK(publication_status IN ('blocked','internal','external')),
    publication_reasons_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_cases_queue ON review_cases(current_state, priority, updated_at);

CREATE TABLE review_assignments (
    id BIGSERIAL PRIMARY KEY,
    assignment_id TEXT NOT NULL UNIQUE,
    review_case_id BIGINT NOT NULL,
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('assigned','unassigned')),
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_assignments_case ON review_assignments(review_case_id, id);

CREATE TABLE review_comments (
    id BIGSERIAL PRIMARY KEY,
    comment_id TEXT NOT NULL UNIQUE,
    review_case_id BIGINT NOT NULL,
    actor TEXT NOT NULL,
    body TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('internal','public')),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_comments_case ON review_comments(review_case_id, id);

CREATE TABLE review_decisions (
    id BIGSERIAL PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    review_case_id BIGINT NOT NULL,
    decision_type TEXT NOT NULL CHECK(decision_type IN ('submitted','review_started','changes_requested','approved','rejected','superseded','archived','reopened','quality_assessed','publication_gate_updated','assigned','unassigned','commented')),
    actor TEXT NOT NULL,
    reason TEXT,
    notes TEXT,
    previous_decision_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_decision_id) REFERENCES review_decisions(decision_id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_decisions_case ON review_decisions(review_case_id, id);

CREATE TABLE quality_assessments (
    id BIGSERIAL PRIMARY KEY,
    assessment_id TEXT NOT NULL UNIQUE,
    review_case_id BIGINT NOT NULL,
    completeness INTEGER NOT NULL CHECK(completeness BETWEEN 0 AND 100),
    validity INTEGER NOT NULL CHECK(validity BETWEEN 0 AND 100),
    consistency INTEGER NOT NULL CHECK(consistency BETWEEN 0 AND 100),
    timeliness INTEGER NOT NULL CHECK(timeliness BETWEEN 0 AND 100),
    provenance INTEGER NOT NULL CHECK(provenance BETWEEN 0 AND 100),
    uncertainty INTEGER NOT NULL CHECK(uncertainty BETWEEN 0 AND 100),
    overall INTEGER NOT NULL CHECK(overall BETWEEN 0 AND 100),
    basis_json TEXT NOT NULL DEFAULT '{}',
    assessed_by TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT,
    UNIQUE(review_case_id, payload_sha256)
);
CREATE INDEX idx_quality_assessments_case ON quality_assessments(review_case_id, assessed_at DESC);

CREATE TABLE approval_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    review_case_id BIGINT NOT NULL,
    decision_id TEXT NOT NULL,
    record_revision_id BIGINT NOT NULL,
    record_payload_json TEXT NOT NULL,
    record_payload_sha256 TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT,
    FOREIGN KEY (decision_id) REFERENCES review_decisions(decision_id) ON DELETE RESTRICT,
    FOREIGN KEY (record_revision_id) REFERENCES record_revisions(id) ON DELETE RESTRICT,
    UNIQUE(review_case_id, decision_id)
);
CREATE INDEX idx_approval_snapshots_case ON approval_snapshots(review_case_id, approved_at DESC);

CREATE TABLE revision_diffs (
    id BIGSERIAL PRIMARY KEY,
    diff_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    from_revision_id BIGINT,
    to_revision_id BIGINT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','corrected','superseded')),
    change_summary TEXT NOT NULL,
    reason TEXT,
    changed_by TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (from_revision_id) REFERENCES record_revisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (to_revision_id) REFERENCES record_revisions(id) ON DELETE RESTRICT,
    UNIQUE(record_id, to_revision_id)
);
CREATE INDEX idx_revision_diffs_record ON revision_diffs(record_id, id);












CREATE VIEW review_queue_current AS
SELECT rc.canonical_id AS review_case_id, rc.record_id, rc.current_state, rc.priority,
       rc.assigned_reviewers_json, rc.publication_status, rc.publication_reasons_json,
       qa.overall AS quality_score, qa.assessed_at, rc.updated_at,
       e.name AS entity_name, i.name AS indicator_name, p.label AS period_label
FROM review_cases rc
JOIN measurements m ON m.id=rc.measurement_id
JOIN entities e ON e.id=m.entity_id
JOIN indicators i ON i.id=m.indicator_id
JOIN periods p ON p.id=m.period_id
LEFT JOIN quality_assessments qa ON qa.id=(
    SELECT qa2.id FROM quality_assessments qa2 WHERE qa2.review_case_id=rc.id ORDER BY qa2.id DESC LIMIT 1
);

CREATE VIEW record_revision_history AS
SELECT rr.record_id, rr.revision_number, rr.action, rr.payload_sha256, rr.created_at,
       rd.diff_id, rd.change_summary, rd.reason, rd.changed_by, rd.changes_json
FROM record_revisions rr
LEFT JOIN revision_diffs rd ON rd.to_revision_id=rr.id;


-- migration 007_query_comparison_export_studio
CREATE TABLE saved_queries (
    id BIGSERIAL PRIMARY KEY,
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
    id BIGSERIAL PRIMARY KEY,
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
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    query_id TEXT,
    query_version_id BIGINT,
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
    id BIGSERIAL PRIMARY KEY,
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
    id BIGSERIAL PRIMARY KEY,
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


-- migration 008_public_api_embeds_handoffs
CREATE TABLE api_clients (
    id BIGSERIAL PRIMARY KEY,
    key_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE CHECK(length(token_sha256)=64),
    scopes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(scopes_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    last_used_at TEXT
);

CREATE TABLE api_audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    key_id TEXT,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    scope TEXT,
    record_id TEXT,
    handoff_id TEXT,
    remote_address TEXT,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    occurred_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(key_id) REFERENCES api_clients(key_id) ON DELETE SET NULL
);

CREATE TABLE embed_profiles (
    id BIGSERIAL PRIMARY KEY,
    profile_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    api_base_url TEXT NOT NULL,
    default_limit INTEGER NOT NULL DEFAULT 20 CHECK(default_limit BETWEEN 1 AND 100),
    filters_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(filters_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE handoff_receipts (
    id BIGSERIAL PRIMARY KEY,
    handoff_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    source_product TEXT NOT NULL,
    source_version TEXT NOT NULL,
    target_product TEXT NOT NULL,
    capability TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    envelope_json TEXT NOT NULL CHECK(json_valid(envelope_json)),
    status TEXT NOT NULL DEFAULT 'accepted' CHECK(status IN ('accepted','rejected','processed')),
    received_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    processed_at TEXT
);

CREATE VIEW public_api_records AS
SELECT dr.record_id, dr.payload_sha256, dr.payload_json, dr.created_at, dr.updated_at
FROM data_records dr
JOIN review_cases rc ON rc.record_id = dr.record_id
WHERE rc.current_state = 'approved' AND rc.publication_status = 'external';

CREATE INDEX idx_api_clients_active ON api_clients(active, key_id);
CREATE INDEX idx_api_audit_occurred ON api_audit_events(occurred_at, id);
CREATE INDEX idx_handoff_receipts_target ON handoff_receipts(target_product, capability, received_at);


-- migration 009_institutional_workspaces_access_governance
CREATE TABLE institutions (
    id BIGSERIAL PRIMARY KEY,
    institution_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE principals (
    id BIGSERIAL PRIMARY KEY,
    principal_id TEXT NOT NULL UNIQUE,
    principal_type TEXT NOT NULL CHECK(principal_type IN ('user','service','group')),
    display_name TEXT NOT NULL,
    email TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE retention_policies (
    id BIGSERIAL PRIMARY KEY,
    policy_id TEXT NOT NULL UNIQUE,
    institution_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    retention_days INTEGER CHECK(retention_days IS NULL OR retention_days >= 0),
    disposition_action TEXT NOT NULL DEFAULT 'review' CHECK(disposition_action IN ('review','archive','delete')),
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(institution_id) REFERENCES institutions(id) ON DELETE CASCADE
);

CREATE TABLE workspaces (
    id BIGSERIAL PRIMARY KEY,
    workspace_id TEXT NOT NULL UNIQUE,
    institution_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','shared','institutional','public')),
    classification TEXT NOT NULL DEFAULT 'internal' CHECK(classification IN ('public','internal','restricted','confidential')),
    default_retention_policy_id BIGINT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(institution_id, slug),
    FOREIGN KEY(institution_id) REFERENCES institutions(id) ON DELETE CASCADE,
    FOREIGN KEY(default_retention_policy_id) REFERENCES retention_policies(id) ON DELETE SET NULL
);

CREATE TABLE projects (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(workspace_id, slug),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE workspace_memberships (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    principal_id BIGINT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('viewer','contributor','analyst','reviewer','approver','publisher','administrator')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','invited','suspended','expired','revoked')),
    joined_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
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
    id BIGSERIAL PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT NOT NULL,
    project_id BIGINT,
    owner_principal_id BIGINT,
    steward_principal_id BIGINT,
    custodian_principal_id BIGINT,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','shared','institutional','public')),
    classification TEXT NOT NULL DEFAULT 'internal' CHECK(classification IN ('public','internal','restricted','confidential')),
    retention_policy_id BIGINT,
    legal_hold INTEGER NOT NULL DEFAULT 0 CHECK(legal_hold IN (0,1)),
    disposition_due_at TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY(owner_principal_id) REFERENCES principals(id) ON DELETE SET NULL,
    FOREIGN KEY(steward_principal_id) REFERENCES principals(id) ON DELETE SET NULL,
    FOREIGN KEY(custodian_principal_id) REFERENCES principals(id) ON DELETE SET NULL,
    FOREIGN KEY(retention_policy_id) REFERENCES retention_policies(id) ON DELETE SET NULL
);

CREATE TABLE api_client_workspace_bindings (
    id BIGSERIAL PRIMARY KEY,
    key_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT NOT NULL,
    principal_id BIGINT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(key_id) REFERENCES api_clients(key_id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE CASCADE
);

CREATE TABLE access_governance_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT,
    record_id TEXT,
    principal_id BIGINT,
    event_type TEXT NOT NULL CHECK(event_type IN ('institution_created','workspace_created','project_created','principal_created','membership_granted','membership_changed','record_assigned','visibility_changed','classification_changed','retention_assigned','legal_hold_set','legal_hold_released','record_transferred','access_allowed','access_denied','workspace_exported')),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    occurred_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE SET NULL,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE SET NULL
);

CREATE TABLE workspace_transfer_events (
    id BIGSERIAL PRIMARY KEY,
    transfer_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    from_workspace_id BIGINT,
    to_workspace_id BIGINT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    occurred_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
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


-- migration 010_connectors_refresh_data_operations
CREATE TABLE connector_definitions (
    id BIGSERIAL PRIMARY KEY,
    connector_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT NOT NULL,
    principal_id BIGINT NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(principal_id) REFERENCES principals(id) ON DELETE RESTRICT
);

CREATE TABLE connector_versions (
    id BIGSERIAL PRIMARY KEY,
    connector_id BIGINT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('draft','active','deprecated','retired')),
    capabilities_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(capabilities_json)),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json)),
    field_mapping_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(field_mapping_json)),
    transformation_profile_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(transformation_profile_json)),
    schema_fingerprint TEXT,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(connector_id, version),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_version_activations (
    id BIGSERIAL PRIMARY KEY,
    activation_id TEXT NOT NULL UNIQUE,
    connector_id BIGINT NOT NULL,
    connector_version_id BIGINT NOT NULL,
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(connector_version_id) REFERENCES connector_versions(id) ON DELETE RESTRICT
);

CREATE INDEX idx_connector_version_activations_current
ON connector_version_activations(connector_id, id DESC);

CREATE TABLE connector_schedules (
    id BIGSERIAL PRIMARY KEY,
    schedule_id TEXT NOT NULL UNIQUE,
    connector_id BIGINT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    frequency_minutes INTEGER NOT NULL CHECK(frequency_minutes >= 60),
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_state (
    connector_id BIGINT PRIMARY KEY,
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
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE
);

CREATE TABLE connector_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    connector_id BIGINT NOT NULL,
    connector_version_id BIGINT NOT NULL,
    parent_run_id BIGINT,
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
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(connector_version_id) REFERENCES connector_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY(parent_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_run_logs (
    id BIGSERIAL PRIMARY KEY,
    log_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
    level TEXT NOT NULL CHECK(level IN ('debug','info','warning','error')),
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    occurred_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE
);

CREATE TABLE connector_payload_snapshots (
    id BIGSERIAL PRIMARY KEY,
    payload_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    encoding TEXT NOT NULL DEFAULT 'utf-8',
    payload_blob BYTEA NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    payload_bytes INTEGER NOT NULL CHECK(payload_bytes >= 0),
    source_uri TEXT,
    captured_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE
);

CREATE TABLE connector_run_records (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    row_number INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    source_payload_sha256 TEXT NOT NULL CHECK(length(source_payload_sha256)=64),
    source_payload_json TEXT NOT NULL CHECK(json_valid(source_payload_json)),
    transformed_payload_json TEXT CHECK(transformed_payload_json IS NULL OR json_valid(transformed_payload_json)),
    record_id TEXT,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','skipped','quarantined','failed','not-applied')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(run_id, row_number),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(record_id) REFERENCES data_records(record_id) ON DELETE SET NULL
);

CREATE TABLE connector_record_state (
    connector_id BIGINT NOT NULL,
    source_key TEXT NOT NULL,
    source_payload_sha256 TEXT NOT NULL CHECK(length(source_payload_sha256)=64),
    record_id TEXT,
    first_seen_run_id BIGINT NOT NULL,
    last_seen_run_id BIGINT NOT NULL,
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
    id BIGSERIAL PRIMARY KEY,
    quarantine_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
    row_number INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL CHECK(json_valid(raw_payload_json)),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','released','discarded','resolved')),
    resolution_notes TEXT,
    recovered_run_id BIGINT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    resolved_at TEXT,
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(recovered_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_dead_letters (
    id BIGSERIAL PRIMARY KEY,
    dead_letter_id TEXT NOT NULL UNIQUE,
    connector_id BIGINT NOT NULL,
    run_id BIGINT NOT NULL UNIQUE,
    payload_snapshot_id BIGINT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','replayed','resolved','discarded')),
    replay_run_id BIGINT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    resolved_at TEXT,
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(payload_snapshot_id) REFERENCES connector_payload_snapshots(id) ON DELETE SET NULL,
    FOREIGN KEY(replay_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_reconciliations (
    id BIGSERIAL PRIMARY KEY,
    reconciliation_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL UNIQUE,
    previous_run_id BIGINT,
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
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(previous_run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

CREATE TABLE connector_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_id TEXT NOT NULL UNIQUE,
    connector_id BIGINT NOT NULL,
    run_id BIGINT,
    alert_type TEXT NOT NULL CHECK(alert_type IN ('fetch-failure','rate-limit','freshness','license','schema-drift','record-drift','reconciliation','quarantine','dead-letter','health')),
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged','resolved')),
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    acknowledged_at TEXT,
    resolved_at TEXT,
    FOREIGN KEY(connector_id) REFERENCES connector_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES connector_runs(id) ON DELETE SET NULL
);

INSERT INTO role_permissions(role,permission) VALUES
('analyst','connectors:read'),
('analyst','connectors:run'),
('publisher','connectors:read') ON CONFLICT DO NOTHING;

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


-- migration 011_analysis_artifacts_reproducible_packages
CREATE TABLE analysis_artifacts (
    id BIGSERIAL PRIMARY KEY,
    artifact_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT NOT NULL,
    project_id BIGINT,
    name TEXT NOT NULL,
    analysis_type TEXT NOT NULL CHECK(analysis_type IN ('analysis','model','scenario','forecast','sensitivity','replication')),
    description TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','completed','failed','invalidated','superseded','archived')),
    target_product TEXT,
    target_uri TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE analysis_versions (
    id BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT NOT NULL,
    version TEXT NOT NULL,
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)),
    environment_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(environment_json)),
    code_reference_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(code_reference_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(artifact_id, version),
    UNIQUE(artifact_id, payload_sha256),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE
);

CREATE TABLE analysis_version_activations (
    id BIGSERIAL PRIMARY KEY,
    activation_id TEXT NOT NULL UNIQUE,
    artifact_id BIGINT NOT NULL,
    analysis_version_id BIGINT NOT NULL,
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE,
    FOREIGN KEY(analysis_version_id) REFERENCES analysis_versions(id) ON DELETE RESTRICT
);

CREATE TABLE analysis_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    artifact_id BIGINT NOT NULL,
    analysis_version_id BIGINT NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE,
    FOREIGN KEY(analysis_version_id) REFERENCES analysis_versions(id) ON DELETE RESTRICT
);

CREATE TABLE analysis_run_inputs (
    id BIGSERIAL PRIMARY KEY,
    input_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
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
    id BIGSERIAL PRIMARY KEY,
    output_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
    output_type TEXT NOT NULL CHECK(output_type IN ('table','figure','model','scenario','forecast','sensitivity','document','dataset','metric','log','other')),
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    content_blob BYTEA,
    external_uri TEXT,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE TABLE derived_measurement_lineage (
    id BIGSERIAL PRIMARY KEY,
    lineage_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
    output_id BIGINT,
    derived_record_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    transformation_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(transformation_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(run_id, derived_record_id, source_record_id),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(output_id) REFERENCES analysis_outputs(id) ON DELETE SET NULL,
    FOREIGN KEY(derived_record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY(source_record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT
);

CREATE TABLE analysis_platform_links (
    id BIGSERIAL PRIMARY KEY,
    link_id TEXT NOT NULL UNIQUE,
    artifact_id BIGINT NOT NULL,
    product TEXT NOT NULL,
    capability TEXT,
    external_artifact_id TEXT,
    uri TEXT,
    relation TEXT NOT NULL DEFAULT 'related' CHECK(relation IN ('produced-by','consumed-by','published-to','reviewed-in','related')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(artifact_id) REFERENCES analysis_artifacts(id) ON DELETE CASCADE
);

CREATE TABLE analysis_replication_reviews (
    id BIGSERIAL PRIMARY KEY,
    replication_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','partial','failed','not-reproducible')),
    reviewer TEXT NOT NULL,
    reproduced_run_id BIGINT,
    notes TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_json)),
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(reproduced_run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL
);

CREATE TABLE analysis_invalidation_events (
    id BIGSERIAL PRIMARY KEY,
    invalidation_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
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
    id BIGSERIAL PRIMARY KEY,
    resolution_id TEXT NOT NULL UNIQUE,
    invalidation_id BIGINT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('acknowledged','rerun','accepted','resolved')),
    actor TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(invalidation_id) REFERENCES analysis_invalidation_events(id) ON DELETE CASCADE
);

CREATE TABLE analysis_package_exports (
    id BIGSERIAL PRIMARY KEY,
    package_id TEXT NOT NULL UNIQUE,
    run_id BIGINT NOT NULL,
    schema_version TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    package_sha256 TEXT NOT NULL CHECK(length(package_sha256)=64),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    format TEXT NOT NULL DEFAULT 'zip' CHECK(format IN ('zip','directory')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

INSERT INTO role_permissions(role,permission) VALUES
('analyst','analyses:read'),
('analyst','analyses:write'),
('analyst','analyses:run'),
('reviewer','analyses:read'),
('reviewer','analyses:review'),
('approver','analyses:read'),
('approver','analyses:review'),
('publisher','analyses:read'),
('publisher','analyses:publish') ON CONFLICT DO NOTHING;

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


-- migration 012_accessibility_offline_performance_hardening
CREATE TABLE operational_backups (
    id BIGSERIAL PRIMARY KEY,
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
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    verified_at TEXT
);

CREATE TABLE restore_events (
    id BIGSERIAL PRIMARY KEY,
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
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE offline_operations (
    id BIGSERIAL PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('record-upsert','connector-run','query-run','analysis-run','handoff-receive','custom')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts >= 1),
    queued_by TEXT NOT NULL,
    queued_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
);

CREATE TABLE offline_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    sync_id TEXT NOT NULL UNIQUE,
    workspace_id BIGINT,
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
    id BIGSERIAL PRIMARY KEY,
    sync_id BIGINT NOT NULL,
    operation_id BIGINT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('succeeded','failed','skipped')),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE(sync_id, operation_id),
    FOREIGN KEY(sync_id) REFERENCES offline_sync_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(operation_id) REFERENCES offline_operations(id) ON DELETE RESTRICT
);

CREATE TABLE performance_benchmarks (
    id BIGSERIAL PRIMARY KEY,
    benchmark_id TEXT NOT NULL UNIQUE,
    benchmark_name TEXT NOT NULL,
    repository_id TEXT,
    schema_version INTEGER NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT NOT NULL CHECK(json_valid(metrics_json)),
    environment_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(environment_json)),
    status TEXT NOT NULL CHECK(status IN ('pass','warning','fail')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE security_audit_events (
    id BIGSERIAL PRIMARY KEY,
    audit_id TEXT NOT NULL UNIQUE,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pass','warning','fail')),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE release_attestations (
    id BIGSERIAL PRIMARY KEY,
    attestation_id TEXT NOT NULL UNIQUE,
    release_version TEXT NOT NULL,
    repository_sha256 TEXT NOT NULL CHECK(length(repository_sha256)=64),
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    sbom_json TEXT NOT NULL CHECK(json_valid(sbom_json)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
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


-- migration 013_connected_evidence_measurement_platform
-- Catalyst Data v2.0.0 connected evidence and measurement platform.

CREATE TABLE platform_contracts (
    id BIGSERIAL PRIMARY KEY,
    contract_registration_id TEXT NOT NULL UNIQUE,
    contract_id TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    schema_uri TEXT,
    schema_path TEXT,
    schema_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deprecated','retired')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    registered_by TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE (contract_id, schema_sha256)
);

CREATE TABLE platform_components (
    id BIGSERIAL PRIMARY KEY,
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
    registered_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    updated_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE platform_component_versions (
    id BIGSERIAL PRIMARY KEY,
    component_version_id TEXT NOT NULL UNIQUE,
    component_id TEXT NOT NULL REFERENCES platform_components(component_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    contracts_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    registered_by TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE (component_id, version, manifest_sha256)
);

CREATE TABLE platform_links (
    id BIGSERIAL PRIMARY KEY,
    link_id TEXT NOT NULL UNIQUE,
    source_component_id TEXT NOT NULL REFERENCES platform_components(component_id),
    target_component_id TEXT NOT NULL REFERENCES platform_components(component_id),
    relationship TEXT NOT NULL CHECK (relationship IN ('handoff','data-source','analysis','publication','embed','api','federation')),
    capability TEXT NOT NULL,
    contract_id TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','degraded','disabled')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
    UNIQUE (source_component_id, target_component_id, relationship, capability)
);

CREATE TABLE platform_release_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    release_version TEXT NOT NULL,
    repository_id TEXT,
    migration_version INTEGER NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE platform_integrity_checks (
    id BIGSERIAL PRIMARY KEY,
    check_id TEXT NOT NULL UNIQUE,
    snapshot_id TEXT REFERENCES platform_release_snapshots(snapshot_id),
    subsystem TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pass','warning','fail')),
    details_json TEXT NOT NULL DEFAULT '{}',
    checked_by TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE TABLE platform_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    component_id TEXT REFERENCES platform_components(component_id),
    link_id TEXT REFERENCES platform_links(link_id),
    snapshot_id TEXT REFERENCES platform_release_snapshots(snapshot_id),
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
);

CREATE INDEX platform_contracts_contract_idx ON platform_contracts(contract_id, status);
CREATE INDEX platform_components_status_idx ON platform_components(status, component_type);
CREATE INDEX platform_component_versions_component_idx ON platform_component_versions(component_id, id DESC);
CREATE INDEX platform_links_source_idx ON platform_links(source_component_id, status);
CREATE INDEX platform_links_target_idx ON platform_links(target_component_id, status);
CREATE INDEX platform_snapshots_release_idx ON platform_release_snapshots(release_version, id DESC);
CREATE INDEX platform_integrity_status_idx ON platform_integrity_checks(status, subsystem, id DESC);
CREATE INDEX platform_events_component_idx ON platform_events(component_id, id DESC);










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


-- migration 014_postgresql_storage_abstraction
CREATE TABLE storage_backend_metadata (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    backend TEXT NOT NULL CHECK(backend IN ('sqlite','postgresql')),
    database_identity TEXT NOT NULL,
    feature_flags_json TEXT NOT NULL DEFAULT '{}',
    initialized_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE storage_migration_events (
    id BIGSERIAL PRIMARY KEY,
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
    updated_at=((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
WHERE component_id='component:catalyst-data';


-- PostgreSQL equivalents for canonical SQLite governance triggers
CREATE OR REPLACE FUNCTION catalyst_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Catalyst append-only/immutable table % cannot be mutated', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS catalyst_immutable_source_versions ON source_versions;
CREATE TRIGGER catalyst_immutable_source_versions BEFORE UPDATE OR DELETE ON source_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_source_snapshots ON source_snapshots;
CREATE TRIGGER catalyst_immutable_source_snapshots BEFORE UPDATE OR DELETE ON source_snapshots FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_record_revisions ON record_revisions;
CREATE TRIGGER catalyst_immutable_record_revisions BEFORE UPDATE OR DELETE ON record_revisions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_provenance_events ON provenance_events;
CREATE TRIGGER catalyst_immutable_provenance_events BEFORE UPDATE OR DELETE ON provenance_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_indicator_versions ON indicator_versions;
CREATE TRIGGER catalyst_immutable_indicator_versions BEFORE UPDATE OR DELETE ON indicator_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_methodology_versions ON methodology_versions;
CREATE TRIGGER catalyst_immutable_methodology_versions BEFORE UPDATE OR DELETE ON methodology_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_governance_events ON governance_events;
CREATE TRIGGER catalyst_immutable_governance_events BEFORE UPDATE OR DELETE ON governance_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_instrument_versions ON instrument_versions;
CREATE TRIGGER catalyst_immutable_instrument_versions BEFORE UPDATE OR DELETE ON instrument_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_dataset_versions ON dataset_versions;
CREATE TRIGGER catalyst_immutable_dataset_versions BEFORE UPDATE OR DELETE ON dataset_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_lineage_events ON lineage_events;
CREATE TRIGGER catalyst_immutable_lineage_events BEFORE UPDATE OR DELETE ON lineage_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_review_assignments ON review_assignments;
CREATE TRIGGER catalyst_immutable_review_assignments BEFORE UPDATE OR DELETE ON review_assignments FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_review_comments ON review_comments;
CREATE TRIGGER catalyst_immutable_review_comments BEFORE UPDATE OR DELETE ON review_comments FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_review_decisions ON review_decisions;
CREATE TRIGGER catalyst_immutable_review_decisions BEFORE UPDATE OR DELETE ON review_decisions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_quality_assessments ON quality_assessments;
CREATE TRIGGER catalyst_immutable_quality_assessments BEFORE UPDATE OR DELETE ON quality_assessments FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_approval_snapshots ON approval_snapshots;
CREATE TRIGGER catalyst_immutable_approval_snapshots BEFORE UPDATE OR DELETE ON approval_snapshots FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_revision_diffs ON revision_diffs;
CREATE TRIGGER catalyst_immutable_revision_diffs BEFORE UPDATE OR DELETE ON revision_diffs FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_saved_query_versions ON saved_query_versions;
CREATE TRIGGER catalyst_immutable_saved_query_versions BEFORE UPDATE OR DELETE ON saved_query_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_query_runs ON query_runs;
CREATE TRIGGER catalyst_immutable_query_runs BEFORE UPDATE OR DELETE ON query_runs FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_query_run_records ON query_run_records;
CREATE TRIGGER catalyst_immutable_query_run_records BEFORE UPDATE OR DELETE ON query_run_records FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_query_run_warnings ON query_run_warnings;
CREATE TRIGGER catalyst_immutable_query_run_warnings BEFORE UPDATE OR DELETE ON query_run_warnings FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_export_bundles ON export_bundles;
CREATE TRIGGER catalyst_immutable_export_bundles BEFORE UPDATE OR DELETE ON export_bundles FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_api_audit_events ON api_audit_events;
CREATE TRIGGER catalyst_immutable_api_audit_events BEFORE UPDATE OR DELETE ON api_audit_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_access_governance_events ON access_governance_events;
CREATE TRIGGER catalyst_immutable_access_governance_events BEFORE UPDATE OR DELETE ON access_governance_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_workspace_transfer_events ON workspace_transfer_events;
CREATE TRIGGER catalyst_immutable_workspace_transfer_events BEFORE UPDATE OR DELETE ON workspace_transfer_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_connector_version_activations ON connector_version_activations;
CREATE TRIGGER catalyst_immutable_connector_version_activations BEFORE UPDATE OR DELETE ON connector_version_activations FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_connector_versions ON connector_versions;
CREATE TRIGGER catalyst_immutable_connector_versions BEFORE UPDATE OR DELETE ON connector_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_connector_run_logs ON connector_run_logs;
CREATE TRIGGER catalyst_immutable_connector_run_logs BEFORE UPDATE OR DELETE ON connector_run_logs FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_connector_payload_snapshots ON connector_payload_snapshots;
CREATE TRIGGER catalyst_immutable_connector_payload_snapshots BEFORE UPDATE OR DELETE ON connector_payload_snapshots FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_connector_run_records ON connector_run_records;
CREATE TRIGGER catalyst_immutable_connector_run_records BEFORE UPDATE OR DELETE ON connector_run_records FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_connector_reconciliations ON connector_reconciliations;
CREATE TRIGGER catalyst_immutable_connector_reconciliations BEFORE UPDATE OR DELETE ON connector_reconciliations FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_versions ON analysis_versions;
CREATE TRIGGER catalyst_immutable_analysis_versions BEFORE UPDATE OR DELETE ON analysis_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_version_activations ON analysis_version_activations;
CREATE TRIGGER catalyst_immutable_analysis_version_activations BEFORE UPDATE OR DELETE ON analysis_version_activations FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_run_inputs ON analysis_run_inputs;
CREATE TRIGGER catalyst_immutable_analysis_run_inputs BEFORE UPDATE OR DELETE ON analysis_run_inputs FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_outputs ON analysis_outputs;
CREATE TRIGGER catalyst_immutable_analysis_outputs BEFORE UPDATE OR DELETE ON analysis_outputs FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_derived_measurement_lineage ON derived_measurement_lineage;
CREATE TRIGGER catalyst_immutable_derived_measurement_lineage BEFORE UPDATE OR DELETE ON derived_measurement_lineage FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_replication_reviews ON analysis_replication_reviews;
CREATE TRIGGER catalyst_immutable_analysis_replication_reviews BEFORE UPDATE OR DELETE ON analysis_replication_reviews FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_invalidation_events ON analysis_invalidation_events;
CREATE TRIGGER catalyst_immutable_analysis_invalidation_events BEFORE UPDATE OR DELETE ON analysis_invalidation_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_analysis_package_exports ON analysis_package_exports;
CREATE TRIGGER catalyst_immutable_analysis_package_exports BEFORE UPDATE OR DELETE ON analysis_package_exports FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_operational_backups ON operational_backups;
CREATE TRIGGER catalyst_immutable_operational_backups BEFORE UPDATE OR DELETE ON operational_backups FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_restore_events ON restore_events;
CREATE TRIGGER catalyst_immutable_restore_events BEFORE UPDATE OR DELETE ON restore_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_offline_sync_runs ON offline_sync_runs;
CREATE TRIGGER catalyst_immutable_offline_sync_runs BEFORE UPDATE OR DELETE ON offline_sync_runs FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_offline_sync_items ON offline_sync_items;
CREATE TRIGGER catalyst_immutable_offline_sync_items BEFORE UPDATE OR DELETE ON offline_sync_items FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_performance_benchmarks ON performance_benchmarks;
CREATE TRIGGER catalyst_immutable_performance_benchmarks BEFORE UPDATE OR DELETE ON performance_benchmarks FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_security_audit_events ON security_audit_events;
CREATE TRIGGER catalyst_immutable_security_audit_events BEFORE UPDATE OR DELETE ON security_audit_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_release_attestations ON release_attestations;
CREATE TRIGGER catalyst_immutable_release_attestations BEFORE UPDATE OR DELETE ON release_attestations FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_platform_contracts ON platform_contracts;
CREATE TRIGGER catalyst_immutable_platform_contracts BEFORE UPDATE OR DELETE ON platform_contracts FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_platform_component_versions ON platform_component_versions;
CREATE TRIGGER catalyst_immutable_platform_component_versions BEFORE UPDATE OR DELETE ON platform_component_versions FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_platform_release_snapshots ON platform_release_snapshots;
CREATE TRIGGER catalyst_immutable_platform_release_snapshots BEFORE UPDATE OR DELETE ON platform_release_snapshots FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_platform_integrity_checks ON platform_integrity_checks;
CREATE TRIGGER catalyst_immutable_platform_integrity_checks BEFORE UPDATE OR DELETE ON platform_integrity_checks FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_immutable_platform_events ON platform_events;
CREATE TRIGGER catalyst_immutable_platform_events BEFORE UPDATE OR DELETE ON platform_events FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();
DROP TRIGGER IF EXISTS catalyst_no_delete_handoff_receipts ON handoff_receipts;
CREATE TRIGGER catalyst_no_delete_handoff_receipts BEFORE DELETE ON handoff_receipts FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();

CREATE OR REPLACE FUNCTION catalyst_assign_default_workspace() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM record_access_governance WHERE record_id=NEW.record_id) THEN
        INSERT INTO record_access_governance(
            record_id,workspace_id,owner_principal_id,steward_principal_id,custodian_principal_id,
            visibility,classification,retention_policy_id
        )
        SELECT NEW.record_id,w.id,p.id,p.id,p.id,'private','internal',r.id
        FROM workspaces w
        JOIN principals p ON p.principal_id='principal:system'
        JOIN retention_policies r ON r.policy_id='retention:default'
        WHERE w.workspace_id='workspace:default';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS data_records_assign_default_workspace ON data_records;
CREATE TRIGGER data_records_assign_default_workspace AFTER INSERT ON data_records
FOR EACH ROW EXECUTE FUNCTION catalyst_assign_default_workspace();

CREATE OR REPLACE FUNCTION catalyst_analysis_invalidation() RETURNS trigger AS $$
BEGIN
    IF OLD.payload_sha256 IS DISTINCT FROM NEW.payload_sha256 THEN
        INSERT INTO analysis_invalidation_events(
            invalidation_id,run_id,record_id,frozen_sha256,current_sha256,reason,severity,detected_at,details_json
        )
        SELECT 'invalidation:' || substr(md5(random()::text || clock_timestamp()::text),1,24), ari.run_id, NEW.record_id,
               ari.payload_sha256, NEW.payload_sha256, 'upstream-record-changed', 'warning',
               ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
               json_build_object('previous_record_sha256',OLD.payload_sha256,'current_record_sha256',NEW.payload_sha256)::text
        FROM analysis_run_inputs ari
        WHERE ari.record_id=NEW.record_id AND ari.payload_sha256<>NEW.payload_sha256
          AND NOT EXISTS (
              SELECT 1 FROM analysis_invalidation_events aie
              WHERE aie.run_id=ari.run_id AND aie.record_id=NEW.record_id
                AND COALESCE(aie.current_sha256,'')=NEW.payload_sha256
          );
        UPDATE analysis_runs SET reproducibility_status='invalidated'
        WHERE id IN (
            SELECT run_id FROM analysis_run_inputs
            WHERE record_id=NEW.record_id AND payload_sha256<>NEW.payload_sha256
        );
        UPDATE analysis_artifacts SET status='invalidated',updated_at=((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
        WHERE id IN (
            SELECT ar.artifact_id FROM analysis_runs ar
            JOIN analysis_run_inputs ari ON ari.run_id=ar.id
            WHERE ari.record_id=NEW.record_id AND ari.payload_sha256<>NEW.payload_sha256
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS data_records_analysis_invalidation ON data_records;
CREATE TRIGGER data_records_analysis_invalidation AFTER UPDATE OF payload_sha256 ON data_records
FOR EACH ROW EXECUTE FUNCTION catalyst_analysis_invalidation();
