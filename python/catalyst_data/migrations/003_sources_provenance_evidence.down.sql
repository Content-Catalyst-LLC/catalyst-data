DROP VIEW IF EXISTS open_evidence_gaps;
DROP VIEW IF EXISTS evidence_chain_summary;

DROP TRIGGER IF EXISTS provenance_events_immutable_delete;
DROP TRIGGER IF EXISTS provenance_events_immutable_update;
DROP TRIGGER IF EXISTS record_revisions_immutable_delete;
DROP TRIGGER IF EXISTS record_revisions_immutable_update;
DROP TRIGGER IF EXISTS source_snapshots_immutable_delete;
DROP TRIGGER IF EXISTS source_snapshots_immutable_update;
DROP TRIGGER IF EXISTS source_versions_immutable_delete;
DROP TRIGGER IF EXISTS source_versions_immutable_update;

-- Break the append-only event chain before removing its rows. SQLite enforces
-- the self-referential previous_event_id foreign key during DROP TABLE when
-- populated, so a data-bearing rollback must dismantle children explicitly.
UPDATE provenance_events SET previous_event_id = NULL;
DELETE FROM evidence_gaps;
DELETE FROM provenance_events;
DELETE FROM record_revisions;
DELETE FROM source_relationships;
DELETE FROM measurement_sources;
DELETE FROM source_snapshots;
DELETE FROM source_versions;

DROP TABLE IF EXISTS evidence_gaps;
DROP TABLE IF EXISTS provenance_events;
DROP TABLE IF EXISTS record_revisions;
DROP TABLE IF EXISTS source_relationships;
DROP TABLE IF EXISTS measurement_sources;
DROP TABLE IF EXISTS source_snapshots;
DROP TABLE IF EXISTS source_versions;
