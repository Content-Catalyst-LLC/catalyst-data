PRAGMA foreign_keys = ON;

ALTER TABLE indicators ADD COLUMN namespace TEXT NOT NULL DEFAULT 'sc';
ALTER TABLE indicators ADD COLUMN domain TEXT NOT NULL DEFAULT 'general';
ALTER TABLE indicators ADD COLUMN custodian TEXT NOT NULL DEFAULT 'Content Catalyst LLC';
ALTER TABLE indicators ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE indicators ADD COLUMN definition TEXT;
ALTER TABLE indicators ADD COLUMN frequency TEXT NOT NULL DEFAULT 'annual';
ALTER TABLE indicators ADD COLUMN aggregation TEXT NOT NULL DEFAULT 'point-estimate';
ALTER TABLE indicators ADD COLUMN disaggregation_json TEXT NOT NULL DEFAULT '[]';

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
CREATE INDEX idx_unit_definitions_dimension ON unit_definitions(dimension, canonical_unit_id);

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
CREATE INDEX idx_indicator_versions_indicator ON indicator_versions(indicator_id, version, revision_number DESC);

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
CREATE INDEX idx_methodology_versions_method ON methodology_versions(methodology_id, version, revision_number DESC);

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
CREATE INDEX idx_governance_events_indicator ON governance_events(indicator_id, id);

CREATE TRIGGER indicator_versions_immutable_update BEFORE UPDATE ON indicator_versions BEGIN SELECT RAISE(ABORT, 'indicator_versions are immutable'); END;
CREATE TRIGGER indicator_versions_immutable_delete BEFORE DELETE ON indicator_versions BEGIN SELECT RAISE(ABORT, 'indicator_versions are immutable'); END;
CREATE TRIGGER methodology_versions_immutable_update BEFORE UPDATE ON methodology_versions BEGIN SELECT RAISE(ABORT, 'methodology_versions are immutable'); END;
CREATE TRIGGER methodology_versions_immutable_delete BEFORE DELETE ON methodology_versions BEGIN SELECT RAISE(ABORT, 'methodology_versions are immutable'); END;
CREATE TRIGGER governance_events_immutable_update BEFORE UPDATE ON governance_events BEGIN SELECT RAISE(ABORT, 'governance_events are immutable'); END;
CREATE TRIGGER governance_events_immutable_delete BEFORE DELETE ON governance_events BEGIN SELECT RAISE(ABORT, 'governance_events are immutable'); END;

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
