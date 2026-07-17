DROP VIEW IF EXISTS measurement_governance_review;
DROP VIEW IF EXISTS indicator_registry_current;

DROP TRIGGER IF EXISTS governance_events_immutable_delete;
DROP TRIGGER IF EXISTS governance_events_immutable_update;
DROP TRIGGER IF EXISTS methodology_versions_immutable_delete;
DROP TRIGGER IF EXISTS methodology_versions_immutable_update;
DROP TRIGGER IF EXISTS indicator_versions_immutable_delete;
DROP TRIGGER IF EXISTS indicator_versions_immutable_update;

DELETE FROM governance_events;
DELETE FROM framework_mappings;
DELETE FROM indicator_compatibility_rules;
DELETE FROM indicator_unit_assignments;
DELETE FROM indicator_methodologies;
DELETE FROM methodology_versions;
DELETE FROM methodologies;
DELETE FROM indicator_aliases;
DELETE FROM indicator_versions;
DELETE FROM unit_definitions;

DROP TABLE IF EXISTS governance_events;
DROP TABLE IF EXISTS framework_mappings;
DROP TABLE IF EXISTS indicator_compatibility_rules;
DROP TABLE IF EXISTS indicator_unit_assignments;
DROP TABLE IF EXISTS indicator_methodologies;
DROP TABLE IF EXISTS methodology_versions;
DROP TABLE IF EXISTS methodologies;
DROP TABLE IF EXISTS indicator_aliases;
DROP TABLE IF EXISTS indicator_versions;
DROP TABLE IF EXISTS unit_definitions;

ALTER TABLE indicators DROP COLUMN disaggregation_json;
ALTER TABLE indicators DROP COLUMN aggregation;
ALTER TABLE indicators DROP COLUMN frequency;
ALTER TABLE indicators DROP COLUMN definition;
ALTER TABLE indicators DROP COLUMN status;
ALTER TABLE indicators DROP COLUMN custodian;
ALTER TABLE indicators DROP COLUMN domain;
ALTER TABLE indicators DROP COLUMN namespace;
