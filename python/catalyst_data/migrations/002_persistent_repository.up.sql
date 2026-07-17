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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO repository_metadata(id, repository_id)
VALUES (1, 'repository:local:' || lower(hex(randomblob(12))));

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
CREATE INDEX idx_data_records_schema ON data_records(schema_version);
CREATE INDEX idx_data_records_updated ON data_records(updated_at);

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
CREATE INDEX idx_import_errors_run ON import_row_errors(import_run_id);

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
WHERE source IS NULL OR confidence < 40 OR method IS NULL OR LENGTH(TRIM(COALESCE(method, ''))) = 0;

CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review WHERE confidence < 70;
