CREATE TABLE canonical_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    canonical_name_normalized TEXT NOT NULL,
    parent_entity_id TEXT REFERENCES canonical_entities(entity_id),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','historical','provisional','deprecated')),
    source_uri TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(entity_type,canonical_key)
);
CREATE INDEX idx_canonical_entities_lookup ON canonical_entities(entity_type,status,canonical_name_normalized);
CREATE INDEX idx_canonical_entities_parent ON canonical_entities(parent_entity_id);

CREATE TABLE entity_identifiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier_id TEXT NOT NULL UNIQUE,
    entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    identifier TEXT NOT NULL,
    identifier_normalized TEXT NOT NULL,
    identifier_type TEXT NOT NULL DEFAULT 'provider',
    source_uri TEXT,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(namespace,identifier)
);
CREATE INDEX idx_entity_identifiers_entity ON entity_identifiers(entity_id,namespace);
CREATE INDEX idx_entity_identifiers_lookup ON entity_identifiers(namespace,identifier_normalized);

CREATE TABLE entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_id TEXT NOT NULL UNIQUE,
    entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'und',
    alias_type TEXT NOT NULL DEFAULT 'name',
    source_uri TEXT,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(entity_id,alias_normalized,language,alias_type)
);
CREATE INDEX idx_entity_aliases_lookup ON entity_aliases(alias_normalized,language);

CREATE TABLE entity_resolution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    query_value TEXT NOT NULL,
    namespace TEXT,
    entity_type TEXT,
    resolution_status TEXT NOT NULL CHECK(resolution_status IN ('resolved','ambiguous','not-found')),
    resolution_method TEXT NOT NULL,
    selected_entity_id TEXT REFERENCES canonical_entities(entity_id),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count >= 0),
    candidates_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(candidates_json)),
    actor TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
CREATE TRIGGER entity_resolution_events_immutable_update BEFORE UPDATE ON entity_resolution_events BEGIN SELECT RAISE(ABORT, 'Entity resolution history is immutable'); END;
CREATE TRIGGER entity_resolution_events_immutable_delete BEFORE DELETE ON entity_resolution_events BEGIN SELECT RAISE(ABORT, 'Entity resolution history is immutable'); END;

CREATE TABLE entity_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id TEXT NOT NULL UNIQUE,
    entity_count INTEGER NOT NULL CHECK(entity_count >= 0),
    registry_sha256 TEXT NOT NULL CHECK(length(registry_sha256)=64),
    synced_at TEXT NOT NULL
);
CREATE TRIGGER entity_sync_runs_immutable_update BEFORE UPDATE ON entity_sync_runs BEGIN SELECT RAISE(ABORT, 'Entity sync history is immutable'); END;
CREATE TRIGGER entity_sync_runs_immutable_delete BEFORE DELETE ON entity_sync_runs BEGIN SELECT RAISE(ABORT, 'Entity sync history is immutable'); END;

CREATE VIEW entity_registry_status AS
SELECT
  (SELECT COUNT(*) FROM canonical_entities WHERE status='active') AS active_entity_count,
  (SELECT COUNT(*) FROM canonical_entities WHERE entity_type='country-area' AND status='active') AS country_area_count,
  (SELECT COUNT(*) FROM canonical_entities WHERE entity_type='subnational-geography' AND status='active') AS subnational_geography_count,
  (SELECT COUNT(*) FROM entity_identifiers) AS identifier_count,
  (SELECT COUNT(DISTINCT namespace) FROM entity_identifiers) AS namespace_count,
  (SELECT COUNT(*) FROM entity_aliases) AS alias_count,
  (SELECT COUNT(*) FROM entity_resolution_events) AS resolution_event_count,
  (SELECT MAX(synced_at) FROM entity_sync_runs) AS latest_sync_at;

UPDATE platform_components SET current_version='2.9.0', capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","nasa-donki-space-weather","jpl-small-body-database","jpl-close-approaches","nasa-exoplanet-archive","space-science-network","dataset-catalog","dataset-registry","cross-provider-discovery","freshness-index","canonical-entities","identifier-resolution","iso-country-identifiers","un-m49-identifiers","provider-crosswalks","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]', updated_at=datetime('now') WHERE component_id='component:catalyst-data';
