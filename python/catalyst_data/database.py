from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class DatabaseHealth:
    path: str
    exists: bool
    integrity: str
    foreign_keys: bool
    migration_version: int
    latest_migration: int
    repository_id: str | None
    record_count: int
    import_run_count: int

    @property
    def healthy(self) -> bool:
        return self.exists and self.integrity == "ok" and self.foreign_keys and self.migration_version == self.latest_migration


def connect(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    database = Path(path)
    if readonly:
        uri = f"file:{database.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextlib.contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    if connection.in_transaction:
        name = "catalyst_data_nested"
        connection.execute(f"SAVEPOINT {name}")
        try:
            yield connection
        except Exception:
            connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            connection.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            connection.execute(f"RELEASE SAVEPOINT {name}")
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
