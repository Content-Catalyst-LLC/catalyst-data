-- Catalyst Data schema
-- Shared SQL layer for traceable entities, indicators, sources, periods, measurements, confidence, and review notes.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('country','organization','project','program','site','policy','persona','experiment','dataset','other')),
    name TEXT NOT NULL,
    description TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entity_type, name)
);

CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY,
    code TEXT,
    name TEXT NOT NULL,
    framework TEXT,
    unit TEXT,
    direction TEXT NOT NULL DEFAULT 'neutral' CHECK(direction IN ('higher','lower','neutral')),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(framework, code),
    UNIQUE(name, framework)
);

CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    period_type TEXT NOT NULL CHECK(period_type IN ('date','month','quarter','year','custom')),
    start_date TEXT,
    end_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'unspecified',
    url TEXT,
    publisher TEXT,
    license TEXT,
    retrieved_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS measurements (
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
    updated_at TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE RESTRICT,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
    UNIQUE(entity_id, indicator_id, period_id, source_id)
);

CREATE TABLE IF NOT EXISTS measurement_notes (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL,
    note_type TEXT NOT NULL CHECK(note_type IN ('method','assumption','limitation','review','revision')),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS entity_tags (
    entity_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (entity_id, tag_id),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS indicator_tags (
    indicator_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (indicator_id, tag_id),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_measurements_entity ON measurements(entity_id);
CREATE INDEX IF NOT EXISTS idx_measurements_indicator ON measurements(indicator_id);
CREATE INDEX IF NOT EXISTS idx_measurements_period ON measurements(period_id);
CREATE INDEX IF NOT EXISTS idx_measurements_source ON measurements(source_id);
CREATE INDEX IF NOT EXISTS idx_measurements_confidence ON measurements(confidence);

-- BEGIN GENERATED REVIEW CONTRACT
DROP VIEW IF EXISTS low_confidence_measurements;
DROP VIEW IF EXISTS provenance_gaps;
DROP VIEW IF EXISTS measurement_review;

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
        ELSE ROUND(((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0, 2)
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
WHERE source IS NULL
   OR confidence < 40
   OR method IS NULL
   OR LENGTH(TRIM(COALESCE(method, ''))) = 0;

CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review
WHERE confidence < 70;
-- END GENERATED REVIEW CONTRACT
