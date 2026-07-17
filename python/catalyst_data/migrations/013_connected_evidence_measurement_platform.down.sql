DROP VIEW IF EXISTS platform_release_readiness;
DROP VIEW IF EXISTS platform_component_status;

DROP TRIGGER IF EXISTS platform_events_immutable_delete;
DROP TRIGGER IF EXISTS platform_events_immutable_update;
DROP TRIGGER IF EXISTS platform_integrity_checks_immutable_delete;
DROP TRIGGER IF EXISTS platform_integrity_checks_immutable_update;
DROP TRIGGER IF EXISTS platform_release_snapshots_immutable_delete;
DROP TRIGGER IF EXISTS platform_release_snapshots_immutable_update;
DROP TRIGGER IF EXISTS platform_component_versions_immutable_delete;
DROP TRIGGER IF EXISTS platform_component_versions_immutable_update;
DROP TRIGGER IF EXISTS platform_contracts_immutable_delete;
DROP TRIGGER IF EXISTS platform_contracts_immutable_update;

DROP TABLE IF EXISTS platform_events;
DROP TABLE IF EXISTS platform_integrity_checks;
DROP TABLE IF EXISTS platform_release_snapshots;
DROP TABLE IF EXISTS platform_links;
DROP TABLE IF EXISTS platform_component_versions;
DROP TABLE IF EXISTS platform_components;
DROP TABLE IF EXISTS platform_contracts;
