DROP VIEW IF EXISTS global_statistics_status;
DROP TRIGGER IF EXISTS global_statistics_fetches_immutable_delete;
DROP TRIGGER IF EXISTS global_statistics_fetches_immutable_update;
DROP TABLE IF EXISTS global_statistics_fetches;
DROP TABLE IF EXISTS un_sdg_observations;
DROP TABLE IF EXISTS un_sdg_indicators;
DROP TABLE IF EXISTS un_sdg_goals;
DROP TABLE IF EXISTS un_sdg_geoareas;
DROP TABLE IF EXISTS world_bank_observations;
DROP TABLE IF EXISTS world_bank_indicators;
DROP TABLE IF EXISTS world_bank_countries;
UPDATE platform_components
SET current_version='2.3.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
