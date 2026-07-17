DROP TRIGGER IF EXISTS data_records_assign_default_workspace;
DROP TRIGGER IF EXISTS workspace_transfer_events_no_delete;
DROP TRIGGER IF EXISTS workspace_transfer_events_no_update;
DROP TRIGGER IF EXISTS access_governance_events_no_delete;
DROP TRIGGER IF EXISTS access_governance_events_no_update;
DROP VIEW IF EXISTS workspace_record_access;
DROP VIEW IF EXISTS public_api_records;
DROP INDEX IF EXISTS idx_transfers_record;
DROP INDEX IF EXISTS idx_access_events_workspace;
DROP INDEX IF EXISTS idx_record_access_workspace;
DROP INDEX IF EXISTS idx_workspace_memberships_lookup;
DROP TABLE IF EXISTS workspace_transfer_events;
DROP TABLE IF EXISTS access_governance_events;
DROP TABLE IF EXISTS api_client_workspace_bindings;
DROP TABLE IF EXISTS record_access_governance;
DROP TABLE IF EXISTS role_permissions;
DROP TABLE IF EXISTS workspace_memberships;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS retention_policies;
DROP TABLE IF EXISTS principals;
DROP TABLE IF EXISTS institutions;
CREATE VIEW public_api_records AS
SELECT dr.record_id, dr.payload_sha256, dr.payload_json, dr.created_at, dr.updated_at
FROM data_records dr
JOIN review_cases rc ON rc.record_id = dr.record_id
WHERE rc.current_state = 'approved' AND rc.publication_status = 'external';
