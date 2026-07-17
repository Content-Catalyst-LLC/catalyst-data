PRAGMA foreign_keys = ON;

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
CREATE INDEX idx_source_versions_source ON source_versions(source_id, version_number DESC);

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
CREATE INDEX idx_measurement_sources_source ON measurement_sources(source_id);
CREATE INDEX idx_measurement_sources_role ON measurement_sources(role);

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
CREATE INDEX idx_record_revisions_record ON record_revisions(record_id, revision_number DESC);

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
CREATE INDEX idx_provenance_record ON provenance_events(record_id, id);
CREATE INDEX idx_provenance_source ON provenance_events(source_id, id);

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
CREATE INDEX idx_evidence_gaps_open ON evidence_gaps(resolved_at, severity);

CREATE TRIGGER source_versions_immutable_update BEFORE UPDATE ON source_versions BEGIN SELECT RAISE(ABORT, 'source_versions are immutable'); END;
CREATE TRIGGER source_versions_immutable_delete BEFORE DELETE ON source_versions BEGIN SELECT RAISE(ABORT, 'source_versions are immutable'); END;
CREATE TRIGGER source_snapshots_immutable_update BEFORE UPDATE ON source_snapshots BEGIN SELECT RAISE(ABORT, 'source_snapshots are immutable'); END;
CREATE TRIGGER source_snapshots_immutable_delete BEFORE DELETE ON source_snapshots BEGIN SELECT RAISE(ABORT, 'source_snapshots are immutable'); END;
CREATE TRIGGER record_revisions_immutable_update BEFORE UPDATE ON record_revisions BEGIN SELECT RAISE(ABORT, 'record_revisions are immutable'); END;
CREATE TRIGGER record_revisions_immutable_delete BEFORE DELETE ON record_revisions BEGIN SELECT RAISE(ABORT, 'record_revisions are immutable'); END;
CREATE TRIGGER provenance_events_immutable_update BEFORE UPDATE ON provenance_events BEGIN SELECT RAISE(ABORT, 'provenance_events are immutable'); END;
CREATE TRIGGER provenance_events_immutable_delete BEFORE DELETE ON provenance_events BEGIN SELECT RAISE(ABORT, 'provenance_events are immutable'); END;

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
