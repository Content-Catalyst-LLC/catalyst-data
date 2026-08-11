DROP VIEW IF EXISTS us_public_data_status;
DROP VIEW IF EXISTS us_public_observations;
DROP TRIGGER IF EXISTS us_public_fetches_immutable_delete;
DROP TRIGGER IF EXISTS us_public_fetches_immutable_update;
DROP TABLE IF EXISTS us_public_fetches;
DROP TABLE IF EXISTS usgs_water_observations;
DROP TABLE IF EXISTS epa_envirofacts_records;
DROP TABLE IF EXISTS eia_observations;
DROP TABLE IF EXISTS bea_observations;
DROP TABLE IF EXISTS bls_observations;
DROP TABLE IF EXISTS bls_series;
DROP TABLE IF EXISTS census_observations;
UPDATE platform_components
SET current_version='2.4.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
