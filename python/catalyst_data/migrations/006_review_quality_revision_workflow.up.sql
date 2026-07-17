PRAGMA foreign_keys = ON;

CREATE TABLE review_cases (
    id INTEGER PRIMARY KEY,
    canonical_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL UNIQUE,
    measurement_id INTEGER NOT NULL UNIQUE,
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
    id INTEGER PRIMARY KEY,
    assignment_id TEXT NOT NULL UNIQUE,
    review_case_id INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('assigned','unassigned')),
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_assignments_case ON review_assignments(review_case_id, id);

CREATE TABLE review_comments (
    id INTEGER PRIMARY KEY,
    comment_id TEXT NOT NULL UNIQUE,
    review_case_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    body TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('internal','public')),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_comments_case ON review_comments(review_case_id, id);

CREATE TABLE review_decisions (
    id INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    review_case_id INTEGER NOT NULL,
    decision_type TEXT NOT NULL CHECK(decision_type IN ('submitted','review_started','changes_requested','approved','rejected','superseded','archived','reopened','quality_assessed','publication_gate_updated','assigned','unassigned','commented')),
    actor TEXT NOT NULL,
    reason TEXT,
    notes TEXT,
    previous_decision_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_decision_id) REFERENCES review_decisions(decision_id) ON DELETE RESTRICT
);
CREATE INDEX idx_review_decisions_case ON review_decisions(review_case_id, id);

CREATE TABLE quality_assessments (
    id INTEGER PRIMARY KEY,
    assessment_id TEXT NOT NULL UNIQUE,
    review_case_id INTEGER NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT,
    UNIQUE(review_case_id, payload_sha256)
);
CREATE INDEX idx_quality_assessments_case ON quality_assessments(review_case_id, assessed_at DESC);

CREATE TABLE approval_snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    review_case_id INTEGER NOT NULL,
    decision_id TEXT NOT NULL,
    record_revision_id INTEGER NOT NULL,
    record_payload_json TEXT NOT NULL,
    record_payload_sha256 TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (review_case_id) REFERENCES review_cases(id) ON DELETE RESTRICT,
    FOREIGN KEY (decision_id) REFERENCES review_decisions(decision_id) ON DELETE RESTRICT,
    FOREIGN KEY (record_revision_id) REFERENCES record_revisions(id) ON DELETE RESTRICT,
    UNIQUE(review_case_id, decision_id)
);
CREATE INDEX idx_approval_snapshots_case ON approval_snapshots(review_case_id, approved_at DESC);

CREATE TABLE revision_diffs (
    id INTEGER PRIMARY KEY,
    diff_id TEXT NOT NULL UNIQUE,
    record_id TEXT NOT NULL,
    from_revision_id INTEGER,
    to_revision_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('inserted','updated','corrected','superseded')),
    change_summary TEXT NOT NULL,
    reason TEXT,
    changed_by TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (record_id) REFERENCES data_records(record_id) ON DELETE RESTRICT,
    FOREIGN KEY (from_revision_id) REFERENCES record_revisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (to_revision_id) REFERENCES record_revisions(id) ON DELETE RESTRICT,
    UNIQUE(record_id, to_revision_id)
);
CREATE INDEX idx_revision_diffs_record ON revision_diffs(record_id, id);

CREATE TRIGGER review_assignments_immutable_update BEFORE UPDATE ON review_assignments BEGIN SELECT RAISE(ABORT, 'review assignments are immutable'); END;
CREATE TRIGGER review_assignments_immutable_delete BEFORE DELETE ON review_assignments BEGIN SELECT RAISE(ABORT, 'review assignments are immutable'); END;
CREATE TRIGGER review_comments_immutable_update BEFORE UPDATE ON review_comments BEGIN SELECT RAISE(ABORT, 'review comments are immutable'); END;
CREATE TRIGGER review_comments_immutable_delete BEFORE DELETE ON review_comments BEGIN SELECT RAISE(ABORT, 'review comments are immutable'); END;
CREATE TRIGGER review_decisions_immutable_update BEFORE UPDATE ON review_decisions BEGIN SELECT RAISE(ABORT, 'review decisions are immutable'); END;
CREATE TRIGGER review_decisions_immutable_delete BEFORE DELETE ON review_decisions BEGIN SELECT RAISE(ABORT, 'review decisions are immutable'); END;
CREATE TRIGGER quality_assessments_immutable_update BEFORE UPDATE ON quality_assessments BEGIN SELECT RAISE(ABORT, 'quality assessments are immutable'); END;
CREATE TRIGGER quality_assessments_immutable_delete BEFORE DELETE ON quality_assessments BEGIN SELECT RAISE(ABORT, 'quality assessments are immutable'); END;
CREATE TRIGGER approval_snapshots_immutable_update BEFORE UPDATE ON approval_snapshots BEGIN SELECT RAISE(ABORT, 'approval snapshots are immutable'); END;
CREATE TRIGGER approval_snapshots_immutable_delete BEFORE DELETE ON approval_snapshots BEGIN SELECT RAISE(ABORT, 'approval snapshots are immutable'); END;
CREATE TRIGGER revision_diffs_immutable_update BEFORE UPDATE ON revision_diffs BEGIN SELECT RAISE(ABORT, 'revision diffs are immutable'); END;
CREATE TRIGGER revision_diffs_immutable_delete BEFORE DELETE ON revision_diffs BEGIN SELECT RAISE(ABORT, 'revision diffs are immutable'); END;

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
