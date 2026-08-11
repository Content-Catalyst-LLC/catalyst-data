DROP VIEW IF EXISTS space_science_status;
DROP TRIGGER IF EXISTS space_science_fetches_immutable_delete;
DROP TRIGGER IF EXISTS space_science_fetches_immutable_update;
DROP TABLE IF EXISTS space_science_fetches;
DROP TABLE IF EXISTS nasa_exoplanets;
DROP TABLE IF EXISTS jpl_close_approaches;
DROP TABLE IF EXISTS jpl_small_bodies;
DROP TABLE IF EXISTS nasa_space_weather_events;
UPDATE platform_components
SET current_version='2.6.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
