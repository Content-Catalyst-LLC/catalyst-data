DROP VIEW IF EXISTS earth_climate_ocean_status;
DROP TRIGGER IF EXISTS earth_climate_fetches_immutable_delete;
DROP TRIGGER IF EXISTS earth_climate_fetches_immutable_update;
DROP TABLE IF EXISTS earth_climate_fetches;
DROP TABLE IF EXISTS usgs_earthquakes;
DROP TABLE IF EXISTS ioos_datasets;
DROP TABLE IF EXISTS erddap_datasets;
DROP TABLE IF EXISTS earth_climate_observations;
UPDATE platform_components
SET current_version='2.5.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
