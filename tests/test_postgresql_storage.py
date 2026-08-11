from __future__ import annotations

import os
from pathlib import Path

import pytest

from catalyst_data.database import (
    DatabaseConfigurationError,
    backend_name,
    resolve_database_target,
    translate_sql_for_postgresql,
)
from catalyst_data.importer import ImportService
from catalyst_data.repository import CatalystRepository
from catalyst_data.storage_migration import migrate_sqlite_to_postgresql

ROOT = Path(__file__).resolve().parents[1]


def test_database_target_detection_and_redaction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sqlite_path = tmp_path / "data.sqlite3"
    sqlite_target = resolve_database_target(sqlite_path)
    assert sqlite_target.backend == "sqlite"
    assert backend_name(sqlite_path) == "sqlite"

    url = "postgresql://catalyst:secret@example.org:5432/catalyst_data?sslmode=require"
    target = resolve_database_target(url)
    assert target.backend == "postgresql"
    assert target.value == url
    assert target.display == "postgresql://example.org:5432/catalyst_data"
    assert "secret" not in target.display
    assert "catalyst@" not in target.display

    monkeypatch.setenv("DATABASE_URL", url)
    env_repository = CatalystRepository()
    assert env_repository.backend == "postgresql"
    assert env_repository.database_display == target.display

    with pytest.raises(DatabaseConfigurationError, match="unsupported database URL scheme"):
        resolve_database_target("mysql://localhost/catalyst")


def test_postgresql_runtime_sql_translation_preserves_repository_contract() -> None:
    sql = """INSERT OR IGNORE INTO source_snapshots(snapshot_id, metadata_json)
             VALUES (?, ?);"""
    translated = translate_sql_for_postgresql(sql)
    assert "INSERT INTO source_snapshots" in translated
    assert "ON CONFLICT DO NOTHING" in translated
    assert translated.count("%s") == 2

    assert translate_sql_for_postgresql("BEGIN IMMEDIATE") == "BEGIN"
    timestamp_sql = translate_sql_for_postgresql(
        "UPDATE import_runs SET finished_at=datetime('now') WHERE id=?"
    )
    assert "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'" in timestamp_sql
    assert "WHERE id=%s" in timestamp_sql

    json_sql = translate_sql_for_postgresql(
        "SELECT record_id FROM data_records WHERE json_extract(payload_json, '$.review_workflow') IS NULL"
    )
    assert "payload_json::jsonb -> 'review_workflow'" in json_sql


def test_sqlite_v21_storage_metadata_and_backward_compatibility(tmp_path: Path) -> None:
    repository = CatalystRepository(tmp_path / "catalyst.sqlite3")
    assert repository.initialize() == list(range(1, 17))
    health = repository.health()
    assert health.healthy
    assert health.backend == "sqlite"
    assert health.migration_version == 16

    ImportService(repository).run(ROOT / "examples/imports/records.json")
    assert repository.stats()["records"] == 2

    from catalyst_data.database import connect
    from contextlib import closing
    import json

    with closing(connect(repository.path, readonly=True)) as connection:
        metadata = connection.execute(
            "SELECT backend,database_identity,feature_flags_json FROM storage_backend_metadata WHERE id=1"
        ).fetchone()
    features = json.loads(metadata["feature_flags_json"])
    assert metadata["backend"] == "sqlite"
    assert features["sqlite_portable"] is True
    assert features["postgis_enabled"] is False


def test_generated_postgresql_schema_is_packaged_and_free_of_sqlite_only_ddl() -> None:
    schema_path = ROOT / "python/catalyst_data/postgresql/schema.sql"
    text = schema_path.read_text(encoding="utf-8")
    assert "Catalyst Data v2.3.0 PostgreSQL schema" in text
    assert "CREATE OR REPLACE FUNCTION json_valid" in text
    assert "CREATE TRIGGER data_records_assign_default_workspace" in text
    assert "CREATE TABLE storage_backend_metadata" in text
    assert "CREATE TABLE storage_migration_events" in text
    for forbidden in (
        "PRAGMA ",
        "AUTOINCREMENT",
        "randomblob(",
        "datetime('now')",
        "INSERT OR IGNORE",
    ):
        assert forbidden not in text


@pytest.mark.skipif(not os.environ.get("CATALYST_TEST_POSTGRES_URL"), reason="live PostgreSQL URL not configured")
def test_live_postgresql_baseline_import_and_sqlite_migration(tmp_path: Path) -> None:
    url = os.environ["CATALYST_TEST_POSTGRES_URL"]
    # CI supplies an isolated database. Reset public so this test is repeatable.
    from catalyst_data.database import connect
    from contextlib import closing

    with closing(connect(url)) as connection:
        connection.executescript("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")

    postgres_repository = CatalystRepository(url)
    assert postgres_repository.initialize() == list(range(1, 17))
    health = postgres_repository.health()
    assert health.healthy
    assert health.backend == "postgresql"
    assert health.server_version

    ImportService(postgres_repository).run(ROOT / "examples/imports/records.json")
    assert postgres_repository.stats()["records"] == 2
    first = postgres_repository.list_records(limit=1)[0]
    assert postgres_repository.evidence(first["record_id"])["chain"]

    # Prove that an existing local repository can be promoted without changing
    # repository identity or canonical record count.
    sqlite_repository = CatalystRepository(tmp_path / "source.sqlite3")
    sqlite_repository.initialize()
    ImportService(sqlite_repository).run(ROOT / "examples/imports/records.json")
    source_id = sqlite_repository.health().repository_id

    result = migrate_sqlite_to_postgresql(sqlite_repository.path, url, actor="principal:test")
    assert result["status"] == "completed"
    assert result["row_count"] > 0
    migrated = CatalystRepository(url)
    assert migrated.health().repository_id == source_id
    assert migrated.stats()["records"] == 2
