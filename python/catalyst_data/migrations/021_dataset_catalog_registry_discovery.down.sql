DROP VIEW IF EXISTS dataset_catalog_status;
DROP TRIGGER IF EXISTS dataset_catalog_sync_runs_immutable_delete;
DROP TRIGGER IF EXISTS dataset_catalog_sync_runs_immutable_update;
DROP TABLE IF EXISTS dataset_catalog_sync_runs;
DROP TABLE IF EXISTS dataset_catalog_entries;
UPDATE platform_components
SET current_version='2.7.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","nasa-donki-space-weather","jpl-small-body-database","jpl-close-approaches","nasa-exoplanet-archive","space-science-network","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
