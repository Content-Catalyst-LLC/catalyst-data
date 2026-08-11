UPDATE platform_components
SET current_version='2.1.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';

DROP VIEW IF EXISTS connector_adapter_operational_status;
DROP TRIGGER IF EXISTS connector_adapter_pages_immutable_delete;
DROP TRIGGER IF EXISTS connector_adapter_pages_immutable_update;
DROP TABLE IF EXISTS connector_adapter_pages;
DROP TABLE IF EXISTS connector_adapter_runs;
DROP TABLE IF EXISTS connector_adapter_state;
DROP INDEX IF EXISTS idx_connector_adapter_bindings_adapter;
DROP TABLE IF EXISTS connector_adapter_bindings;
