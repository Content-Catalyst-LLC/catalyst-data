DROP VIEW IF EXISTS instrument_registry_current;
DROP VIEW IF EXISTS dataset_registry_current;
DROP VIEW IF EXISTS observation_lineage_summary;

DROP TRIGGER IF EXISTS lineage_events_immutable_delete;
DROP TRIGGER IF EXISTS lineage_events_immutable_update;
DROP TRIGGER IF EXISTS dataset_versions_immutable_delete;
DROP TRIGGER IF EXISTS dataset_versions_immutable_update;
DROP TRIGGER IF EXISTS instrument_versions_immutable_delete;
DROP TRIGGER IF EXISTS instrument_versions_immutable_update;

UPDATE lineage_events SET previous_event_id = NULL;
DELETE FROM lineage_events;
DROP TABLE IF EXISTS lineage_events;
DROP TABLE IF EXISTS transformation_inputs;
DROP TABLE IF EXISTS observation_transformations;
DROP TABLE IF EXISTS measurement_observations;
DROP TABLE IF EXISTS measurement_questions;
DROP TABLE IF EXISTS observation_dimensions;
DROP TABLE IF EXISTS observations;
DROP TABLE IF EXISTS observation_batches;
DROP TABLE IF EXISTS dataset_fields;
DROP TABLE IF EXISTS instrument_fields;
DROP TABLE IF EXISTS dataset_versions;
DROP TABLE IF EXISTS instrument_versions;
DROP TABLE IF EXISTS datasets;
DROP TABLE IF EXISTS instruments;
DROP TABLE IF EXISTS research_questions;
