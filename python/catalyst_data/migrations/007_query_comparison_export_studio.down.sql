DROP VIEW IF EXISTS query_run_summary;
DROP VIEW IF EXISTS saved_query_registry;

DROP TRIGGER IF EXISTS export_bundles_immutable_delete;
DROP TRIGGER IF EXISTS export_bundles_immutable_update;
DROP TRIGGER IF EXISTS query_run_warnings_immutable_delete;
DROP TRIGGER IF EXISTS query_run_warnings_immutable_update;
DROP TRIGGER IF EXISTS query_run_records_immutable_delete;
DROP TRIGGER IF EXISTS query_run_records_immutable_update;
DROP TRIGGER IF EXISTS query_runs_immutable_delete;
DROP TRIGGER IF EXISTS query_runs_immutable_update;
DROP TRIGGER IF EXISTS saved_query_versions_immutable_delete;
DROP TRIGGER IF EXISTS saved_query_versions_immutable_update;

DELETE FROM export_bundles;
DELETE FROM query_run_warnings;
DELETE FROM query_run_records;
DELETE FROM query_runs;
DELETE FROM saved_query_versions;
DELETE FROM saved_queries;
DROP TABLE IF EXISTS export_bundles;
DROP TABLE IF EXISTS query_run_warnings;
DROP TABLE IF EXISTS query_run_records;
DROP TABLE IF EXISTS query_runs;
DROP TABLE IF EXISTS saved_query_versions;
DROP TABLE IF EXISTS saved_queries;
