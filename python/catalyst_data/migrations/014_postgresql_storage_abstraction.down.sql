UPDATE platform_components
SET current_version='2.0.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","analysis-artifacts","offline-operations","backup-restore","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';

DROP INDEX IF EXISTS idx_storage_migration_events_status;
DROP TABLE IF EXISTS storage_migration_events;
DROP TABLE IF EXISTS storage_backend_metadata;
