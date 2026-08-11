DROP VIEW IF EXISTS internet_archive_catalog_status;
DROP TRIGGER IF EXISTS wayback_queries_immutable_delete;
DROP TRIGGER IF EXISTS wayback_queries_immutable_update;
DROP TRIGGER IF EXISTS internet_archive_search_results_immutable_delete;
DROP TRIGGER IF EXISTS internet_archive_search_results_immutable_update;
DROP TRIGGER IF EXISTS internet_archive_searches_immutable_delete;
DROP TRIGGER IF EXISTS internet_archive_searches_immutable_update;
DROP TRIGGER IF EXISTS internet_archive_item_versions_immutable_delete;
DROP TRIGGER IF EXISTS internet_archive_item_versions_immutable_update;
DROP TABLE IF EXISTS wayback_captures;
DROP TABLE IF EXISTS wayback_queries;
DROP TABLE IF EXISTS internet_archive_search_results;
DROP TABLE IF EXISTS internet_archive_searches;
DROP TABLE IF EXISTS internet_archive_files;
DROP TABLE IF EXISTS internet_archive_item_versions;
DROP TABLE IF EXISTS internet_archive_items;
UPDATE platform_components
SET current_version='2.2.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
