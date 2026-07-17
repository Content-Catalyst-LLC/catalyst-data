CREATE TABLE api_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE CHECK(length(token_sha256)=64),
    scopes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(scopes_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);

CREATE TABLE api_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(key_id) REFERENCES api_clients(key_id) ON DELETE SET NULL
);

CREATE TABLE embed_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    api_base_url TEXT NOT NULL,
    default_limit INTEGER NOT NULL DEFAULT 20 CHECK(default_limit BETWEEN 1 AND 100),
    filters_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(filters_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE handoff_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
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

CREATE TRIGGER api_audit_events_no_update BEFORE UPDATE ON api_audit_events
BEGIN SELECT RAISE(ABORT, 'api audit events are append-only'); END;
CREATE TRIGGER api_audit_events_no_delete BEFORE DELETE ON api_audit_events
BEGIN SELECT RAISE(ABORT, 'api audit events are append-only'); END;
CREATE TRIGGER handoff_receipts_no_delete BEFORE DELETE ON handoff_receipts
BEGIN SELECT RAISE(ABORT, 'handoff receipts cannot be deleted'); END;
