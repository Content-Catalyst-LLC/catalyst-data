from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect, resolve_database_target, transaction
from .repository import CatalystRepository, canonical_json


class StorageMigrationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise StorageMigrationError(f"unsafe database identifier: {value!r}")
    return value


def _sqlite_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rootpage"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _sqlite_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({_safe_identifier(table)})").fetchall()]


def migrate_sqlite_to_postgresql(source: str | Path, target_url: str, *, actor: str = "principal:system") -> dict[str, Any]:
    source_target = resolve_database_target(source)
    target = resolve_database_target(target_url)
    if not source_target.is_sqlite:
        raise StorageMigrationError("source must be a SQLite repository path")
    if not target.is_postgresql:
        raise StorageMigrationError("target must be a postgresql:// or postgres:// DATABASE_URL")

    source_path = Path(source_target.value).expanduser().resolve()
    if not source_path.is_file():
        raise StorageMigrationError(f"SQLite source repository not found: {source_path}")

    source_repository = CatalystRepository(source_path)
    source_repository.initialize()
    target_repository = CatalystRepository(target.value)
    target_repository.initialize()

    migration_id = "storage-migration:" + uuid.uuid4().hex[:24]
    started_at = _now()
    copied_tables: list[dict[str, Any]] = []
    total_rows = 0

    with closing(sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)) as source_db:
        source_db.row_factory = sqlite3.Row
        tables = [
            table for table in _sqlite_tables(source_db)
            if table not in {"schema_migrations", "storage_backend_metadata", "storage_migration_events"}
        ]
        for table in tables:
            _safe_identifier(table)

        with closing(connect(target.value)) as target_db:
            try:
                with transaction(target_db):
                    # The PostgreSQL compatibility trigger automatically creates default
                    # workspace governance rows for newly inserted data_records. During a
                    # backend migration those rows are copied explicitly from SQLite, so
                    # suspend only that trigger to avoid duplicate governance records.
                    if "data_records" in tables:
                        target_db.execute("ALTER TABLE data_records DISABLE TRIGGER data_records_assign_default_workspace")
                    if tables:
                        target_db.execute(
                            "TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"
                        )
                    for table in tables:
                        columns = _sqlite_columns(source_db, table)
                        if not columns:
                            continue
                        column_sql = ",".join(_safe_identifier(column) for column in columns)
                        placeholders = ",".join("?" for _ in columns)
                        rows = source_db.execute(f"SELECT {column_sql} FROM {table}").fetchall()
                        if rows:
                            target_db.executemany(
                                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                                [tuple(row[column] for column in columns) for row in rows],
                            )
                        count = len(rows)
                        total_rows += count
                        copied_tables.append({"table": table, "rows": count})

                    # Preserve repository identity across backend migration.
                    repository_row = source_db.execute(
                        "SELECT repository_id,created_at,updated_at FROM repository_metadata WHERE id=1"
                    ).fetchone()
                    if repository_row:
                        target_db.execute(
                            "UPDATE repository_metadata SET repository_id=?,created_at=?,updated_at=? WHERE id=1",
                            tuple(repository_row),
                        )

                    if "data_records" in tables:
                        target_db.execute("ALTER TABLE data_records ENABLE TRIGGER data_records_assign_default_workspace")

                    # Explicit integer IDs were copied; advance every PostgreSQL sequence.
                    for table in tables:
                        columns = _sqlite_columns(source_db, table)
                        if "id" not in columns:
                            continue
                        sequence_row = target_db.execute(
                            "SELECT pg_get_serial_sequence(?, 'id') AS sequence_name", (table,)
                        ).fetchone()
                        sequence_name = sequence_row[0] if sequence_row else None
                        if not sequence_name:
                            continue
                        max_row = source_db.execute(f"SELECT COALESCE(MAX(id),0) FROM {table}").fetchone()
                        maximum = int(max_row[0]) if max_row else 0
                        if maximum > 0:
                            target_db.execute("SELECT setval(?::regclass, ?, true)", (sequence_name, maximum))
                        else:
                            target_db.execute("SELECT setval(?::regclass, 1, false)", (sequence_name,))
            except Exception as exc:
                try:
                    with transaction(target_db):
                        target_db.execute(
                            """INSERT INTO storage_migration_events(
                                migration_id,source_backend,target_backend,source_identity,target_identity,status,
                                table_count,row_count,details_json,started_at,finished_at
                            ) VALUES (?,?,?,?,?,'failed',0,0,?,?,?)""",
                            (
                                migration_id, "sqlite", "postgresql", str(source_path), target.display,
                                canonical_json({"error": str(exc), "actor": actor}), started_at, _now(),
                            ),
                        )
                except Exception:
                    pass
                raise StorageMigrationError(f"SQLite to PostgreSQL migration failed: {exc}") from exc

    # Reassert target backend metadata after copying source data.
    target_repository._record_storage_backend()
    finished_at = _now()
    details = {
        "source_migration_version": source_repository.health().migration_version,
        "target_migration_version": target_repository.health().migration_version,
        "tables": copied_tables,
        "actor": actor,
    }
    with closing(connect(target.value)) as connection, transaction(connection):
        connection.execute(
            """INSERT INTO storage_migration_events(
                migration_id,source_backend,target_backend,source_identity,target_identity,status,
                table_count,row_count,details_json,started_at,finished_at
            ) VALUES (?,?,?,?,?,'completed',?,?,?,?,?)""",
            (
                migration_id, "sqlite", "postgresql", str(source_path), target.display,
                len(copied_tables), total_rows, canonical_json(details), started_at, finished_at,
            ),
        )

    return {
        "migration_id": migration_id,
        "status": "completed",
        "source": str(source_path),
        "target": target.display,
        "table_count": len(copied_tables),
        "row_count": total_rows,
        "tables": copied_tables,
        "started_at": started_at,
        "finished_at": finished_at,
    }
