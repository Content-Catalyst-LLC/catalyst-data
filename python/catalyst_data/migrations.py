from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterable


MIGRATION_PATTERN = re.compile(r"^(\d{3})_([a-z0-9_]+)\.(up|down)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up_sql: str
    down_sql: str


class MigrationError(RuntimeError):
    pass


def discover_migrations() -> list[Migration]:
    root = files("catalyst_data").joinpath("migrations")
    pairs: dict[tuple[int, str], dict[str, str]] = {}
    for item in root.iterdir():
        match = MIGRATION_PATTERN.match(item.name)
        if not match:
            continue
        version, name, direction = int(match.group(1)), match.group(2), match.group(3)
        pairs.setdefault((version, name), {})[direction] = item.read_text(encoding="utf-8")
    migrations: list[Migration] = []
    for (version, name), scripts in sorted(pairs.items()):
        if set(scripts) != {"up", "down"}:
            raise MigrationError(f"migration {version:03d}_{name} must include up and down SQL")
        migrations.append(Migration(version, name, scripts["up"], scripts["down"]))
    expected = list(range(1, len(migrations) + 1))
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise MigrationError(f"migration versions must be contiguous: expected {expected}, found {actual}")
    return migrations


def ensure_ledger(connection: sqlite3.Connection) -> None:
    already_in_transaction = connection.in_transaction
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    if not already_in_transaction:
        connection.commit()


class MigrationManager:
    def __init__(self, connection: sqlite3.Connection, migrations: Iterable[Migration] | None = None):
        self.connection = connection
        self.migrations = list(migrations or discover_migrations())
        ensure_ledger(connection)

    @property
    def latest_version(self) -> int:
        return self.migrations[-1].version if self.migrations else 0

    @property
    def current_version(self) -> int:
        row = self.connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
        return int(row[0])

    def applied(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY version"))

    def status(self) -> list[dict[str, object]]:
        applied = {int(row["version"]): row["applied_at"] for row in self.applied()}
        return [
            {
                "version": migration.version,
                "name": migration.name,
                "applied": migration.version in applied,
                "applied_at": applied.get(migration.version),
            }
            for migration in self.migrations
        ]

    def migrate(self, target: int | None = None) -> list[int]:
        destination = self.latest_version if target is None else int(target)
        if destination < 0 or destination > self.latest_version:
            raise MigrationError(f"target must be between 0 and {self.latest_version}")
        current = self.current_version
        if destination < current:
            self.rollback(current - destination)
            return []
        applied: list[int] = []
        for migration in self.migrations:
            if current < migration.version <= destination:
                script = (
                    "BEGIN IMMEDIATE;\n"
                    + migration.up_sql
                    + f"\nINSERT INTO schema_migrations(version, name) VALUES ({migration.version}, '{migration.name}');\n"
                    + "COMMIT;"
                )
                try:
                    self.connection.executescript(script)
                except sqlite3.Error as exc:
                    if self.connection.in_transaction:
                        self.connection.rollback()
                    raise MigrationError(f"failed to apply migration {migration.version:03d}_{migration.name}: {exc}") from exc
                applied.append(migration.version)
                current = migration.version
        return applied

    def rollback(self, steps: int = 1) -> list[int]:
        if steps < 1:
            raise MigrationError("rollback steps must be at least 1")
        current = self.current_version
        destination = max(0, current - steps)
        rolled_back: list[int] = []
        by_version = {migration.version: migration for migration in self.migrations}
        for version in range(current, destination, -1):
            migration = by_version.get(version)
            if migration is None:
                raise MigrationError(f"no migration file for applied version {version}")
            script = (
                "BEGIN IMMEDIATE;\n"
                + migration.down_sql
                + f"\nDELETE FROM schema_migrations WHERE version = {version};\n"
                + "COMMIT;"
            )
            try:
                self.connection.executescript(script)
            except sqlite3.Error as exc:
                if self.connection.in_transaction:
                    self.connection.rollback()
                raise MigrationError(f"failed to roll back migration {version:03d}_{migration.name}: {exc}") from exc
            rolled_back.append(version)
        return rolled_back
