#!/usr/bin/env python3
"""Generate the PostgreSQL v2.1 schema from canonical Catalyst migrations.

SQLite remains the reference migration history. This generator translates the
portable DDL and replaces SQLite trigger syntax with PostgreSQL trigger
functions so both backends implement the same repository contracts.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from catalyst_data.migrations import discover_migrations

OUTPUT = ROOT / "python" / "catalyst_data" / "postgresql" / "schema.sql"

IMMUTABLE_TABLES = [
    "source_versions", "source_snapshots", "record_revisions", "provenance_events",
    "indicator_versions", "methodology_versions", "governance_events",
    "instrument_versions", "dataset_versions", "lineage_events",
    "review_assignments", "review_comments", "review_decisions", "quality_assessments",
    "approval_snapshots", "revision_diffs", "saved_query_versions", "query_runs",
    "query_run_records", "query_run_warnings", "export_bundles", "api_audit_events",
    "access_governance_events", "workspace_transfer_events", "connector_version_activations",
    "connector_versions", "connector_run_logs", "connector_payload_snapshots",
    "connector_run_records", "connector_reconciliations", "analysis_versions",
    "analysis_version_activations", "analysis_run_inputs", "analysis_outputs",
    "derived_measurement_lineage", "analysis_replication_reviews", "analysis_invalidation_events",
    "analysis_package_exports", "operational_backups", "restore_events", "offline_sync_runs",
    "offline_sync_items", "performance_benchmarks", "security_audit_events",
    "release_attestations", "platform_contracts", "platform_component_versions",
    "platform_release_snapshots", "platform_integrity_checks", "platform_events",
]

NO_DELETE_TABLES = ["handoff_receipts"]


def strip_sqlite_triggers(sql: str) -> str:
    return re.sub(r"\n?CREATE\s+TRIGGER\b.*?\bEND;\s*", "\n", sql, flags=re.IGNORECASE | re.DOTALL)


def translate_insert_or_ignore(sql: str) -> str:
    pattern = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO\s+(.*?);", re.IGNORECASE | re.DOTALL)
    return pattern.sub(lambda m: "INSERT INTO " + m.group(1).rstrip() + " ON CONFLICT DO NOTHING;", sql)


def translate(sql: str) -> str:
    sql = strip_sqlite_triggers(sql)
    sql = re.sub(r"^\s*PRAGMA\s+foreign_keys\s*=\s*ON;\s*$", "", sql, flags=re.IGNORECASE | re.MULTILINE)
    sql = re.sub(r"\bid\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "id BIGSERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bid\s+INTEGER\s+PRIMARY\s+KEY(?!\s+CHECK)\b", "id BIGSERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*_id)\s+INTEGER\b", r"\1 BIGINT", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.IGNORECASE)
    sql = sql.replace("DEFAULT (datetime('now'))", "DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)")
    sql = sql.replace("datetime('now')", "((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)")
    sql = sql.replace("'repository:local:' || lower(hex(randomblob(12)))", "'repository:postgresql:' || md5(random()::text || clock_timestamp()::text)")
    sql = re.sub(
        r"ROUND\(\(\(m\.value - m\.baseline_value\) / ABS\(m\.baseline_value\)\) \* 100\.0, 2\)",
        "ROUND((((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0)::numeric, 2)::double precision",
        sql,
    )
    sql = translate_insert_or_ignore(sql)
    return sql.strip()


def trigger_sql() -> str:
    immutable = "\n".join(
        f"DROP TRIGGER IF EXISTS catalyst_immutable_{table} ON {table};\n"
        f"CREATE TRIGGER catalyst_immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();"
        for table in IMMUTABLE_TABLES
    )
    no_delete = "\n".join(
        f"DROP TRIGGER IF EXISTS catalyst_no_delete_{table} ON {table};\n"
        f"CREATE TRIGGER catalyst_no_delete_{table} BEFORE DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION catalyst_reject_mutation();"
        for table in NO_DELETE_TABLES
    )
    return f"""

CREATE OR REPLACE FUNCTION catalyst_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Catalyst append-only/immutable table % cannot be mutated', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

{immutable}
{no_delete}

CREATE OR REPLACE FUNCTION catalyst_assign_default_workspace() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM record_access_governance WHERE record_id=NEW.record_id) THEN
        INSERT INTO record_access_governance(
            record_id,workspace_id,owner_principal_id,steward_principal_id,custodian_principal_id,
            visibility,classification,retention_policy_id
        )
        SELECT NEW.record_id,w.id,p.id,p.id,p.id,'private','internal',r.id
        FROM workspaces w
        JOIN principals p ON p.principal_id='principal:system'
        JOIN retention_policies r ON r.policy_id='retention:default'
        WHERE w.workspace_id='workspace:default';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS data_records_assign_default_workspace ON data_records;
CREATE TRIGGER data_records_assign_default_workspace AFTER INSERT ON data_records
FOR EACH ROW EXECUTE FUNCTION catalyst_assign_default_workspace();

CREATE OR REPLACE FUNCTION catalyst_analysis_invalidation() RETURNS trigger AS $$
BEGIN
    IF OLD.payload_sha256 IS DISTINCT FROM NEW.payload_sha256 THEN
        INSERT INTO analysis_invalidation_events(
            invalidation_id,run_id,record_id,frozen_sha256,current_sha256,reason,severity,detected_at,details_json
        )
        SELECT 'invalidation:' || substr(md5(random()::text || clock_timestamp()::text),1,24), ari.run_id, NEW.record_id,
               ari.payload_sha256, NEW.payload_sha256, 'upstream-record-changed', 'warning',
               ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text),
               json_build_object('previous_record_sha256',OLD.payload_sha256,'current_record_sha256',NEW.payload_sha256)::text
        FROM analysis_run_inputs ari
        WHERE ari.record_id=NEW.record_id AND ari.payload_sha256<>NEW.payload_sha256
          AND NOT EXISTS (
              SELECT 1 FROM analysis_invalidation_events aie
              WHERE aie.run_id=ari.run_id AND aie.record_id=NEW.record_id
                AND COALESCE(aie.current_sha256,'')=NEW.payload_sha256
          );
        UPDATE analysis_runs SET reproducibility_status='invalidated'
        WHERE id IN (
            SELECT run_id FROM analysis_run_inputs
            WHERE record_id=NEW.record_id AND payload_sha256<>NEW.payload_sha256
        );
        UPDATE analysis_artifacts SET status='invalidated',updated_at=((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)
        WHERE id IN (
            SELECT ar.artifact_id FROM analysis_runs ar
            JOIN analysis_run_inputs ari ON ari.run_id=ar.id
            WHERE ari.record_id=NEW.record_id AND ari.payload_sha256<>NEW.payload_sha256
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS data_records_analysis_invalidation ON data_records;
CREATE TRIGGER data_records_analysis_invalidation AFTER UPDATE OF payload_sha256 ON data_records
FOR EACH ROW EXECUTE FUNCTION catalyst_analysis_invalidation();
""".strip()


def main() -> int:
    release_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    blocks = [
        f"-- Catalyst Data v{release_version} PostgreSQL schema",
        "-- Generated from canonical ordered migrations. Do not edit by hand.",
        """CREATE OR REPLACE FUNCTION json_valid(value TEXT) RETURNS BOOLEAN AS $$
BEGIN
    PERFORM value::jsonb;
    RETURN TRUE;
EXCEPTION WHEN others THEN
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;""",
    ]
    for migration in discover_migrations():
        blocks.append(f"\n-- migration {migration.version:03d}_{migration.name}\n{translate(migration.up_sql)}")
    blocks.append("\n-- PostgreSQL equivalents for canonical SQLite governance triggers\n" + trigger_sql())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    print(f"generated {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
