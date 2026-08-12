CREATE TABLE dataset_catalog_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    dataset_key TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    resource_kind TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    license_code TEXT,
    geographic_coverage TEXT,
    temporal_start TEXT,
    temporal_end TEXT,
    update_frequency TEXT,
    freshness_status TEXT NOT NULL DEFAULT 'unknown' CHECK(freshness_status IN ('fresh','aging','stale','unknown')),
    record_count INTEGER NOT NULL DEFAULT 0 CHECK(record_count >= 0),
    tags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_source_fetch_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(provider,dataset_key)
);
CREATE INDEX idx_dataset_catalog_discovery ON dataset_catalog_entries(active,provider,resource_kind,freshness_status,title);
CREATE INDEX idx_dataset_catalog_source_freshness ON dataset_catalog_entries(provider,last_source_fetch_at);

CREATE TABLE dataset_catalog_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id TEXT NOT NULL UNIQUE,
    entry_count INTEGER NOT NULL CHECK(entry_count >= 0),
    catalog_sha256 TEXT NOT NULL CHECK(length(catalog_sha256)=64),
    synced_at TEXT NOT NULL
);
CREATE TRIGGER dataset_catalog_sync_runs_immutable_update BEFORE UPDATE ON dataset_catalog_sync_runs BEGIN SELECT RAISE(ABORT, 'Dataset catalog sync history is immutable'); END;
CREATE TRIGGER dataset_catalog_sync_runs_immutable_delete BEFORE DELETE ON dataset_catalog_sync_runs BEGIN SELECT RAISE(ABORT, 'Dataset catalog sync history is immutable'); END;

CREATE VIEW dataset_catalog_status AS
SELECT
    (SELECT COUNT(*) FROM dataset_catalog_entries WHERE active=1) AS active_dataset_count,
    (SELECT COUNT(DISTINCT provider) FROM dataset_catalog_entries WHERE active=1) AS provider_count,
    (SELECT COUNT(*) FROM dataset_catalog_entries WHERE active=1 AND freshness_status='fresh') AS fresh_count,
    (SELECT COUNT(*) FROM dataset_catalog_entries WHERE active=1 AND freshness_status='aging') AS aging_count,
    (SELECT COUNT(*) FROM dataset_catalog_entries WHERE active=1 AND freshness_status='stale') AS stale_count,
    (SELECT COUNT(*) FROM dataset_catalog_entries WHERE active=1 AND freshness_status='unknown') AS unknown_freshness_count,
    (SELECT COALESCE(SUM(record_count),0) FROM dataset_catalog_entries WHERE active=1) AS indexed_record_count,
    (SELECT MAX(synced_at) FROM dataset_catalog_sync_runs) AS latest_sync_at;

UPDATE platform_components
SET current_version='2.8.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","nasa-donki-space-weather","jpl-small-body-database","jpl-close-approaches","nasa-exoplanet-archive","space-science-network","dataset-catalog","dataset-registry","cross-provider-discovery","freshness-index","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
