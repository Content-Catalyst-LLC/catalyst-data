from __future__ import annotations

import contextlib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlparse


POSTGRES_SCHEMES = {"postgres", "postgresql"}


class DatabaseConfigurationError(RuntimeError):
    """Raised when the configured database backend cannot be opened safely."""


@dataclass(frozen=True)
class DatabaseTarget:
    backend: str
    value: str
    display: str

    @property
    def is_sqlite(self) -> bool:
        return self.backend == "sqlite"

    @property
    def is_postgresql(self) -> bool:
        return self.backend == "postgresql"


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
    backend: str = "sqlite"
    server_version: str | None = None

    @property
    def healthy(self) -> bool:
        return self.exists and self.integrity == "ok" and self.foreign_keys and self.migration_version == self.latest_migration


def resolve_database_target(value: str | Path | DatabaseTarget | None) -> DatabaseTarget:
    if isinstance(value, DatabaseTarget):
        return value
    if value is None:
        value = os.environ.get("DATABASE_URL") or "catalyst-data.sqlite3"
    raw = str(value)
    parsed = urlparse(raw)
    if parsed.scheme.lower() in POSTGRES_SCHEMES:
        # Never expose credentials in status/error surfaces.
        host = parsed.hostname or "postgresql"
        port = f":{parsed.port}" if parsed.port else ""
        database = (parsed.path or "/").lstrip("/") or "database"
        return DatabaseTarget("postgresql", raw, f"postgresql://{host}{port}/{database}")
    if parsed.scheme and parsed.scheme.lower() not in {"file"} and "://" in raw:
        raise DatabaseConfigurationError(f"unsupported database URL scheme: {parsed.scheme}")
    return DatabaseTarget("sqlite", raw, str(Path(raw).expanduser()))


def database_url_from_env(*, required: bool = True) -> str | None:
    value = os.environ.get("DATABASE_URL")
    if required and not value:
        raise DatabaseConfigurationError("DATABASE_URL is not set")
    return value


def backend_name(value: str | Path | DatabaseTarget | None) -> str:
    return resolve_database_target(value).backend


class HybridRow(dict[str, Any]):
    """Mapping row with sqlite3.Row-compatible integer access."""

    __slots__ = ("_values",)

    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        super().__init__(zip(keys, values))
        self._values = tuple(values)

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def __iter__(self):
        # sqlite3.Row iterates values; dict(row) still works because Mapping.keys is present.
        return iter(self._values)

    def keys(self):
        return dict.keys(self)


def _hybrid_row_factory(cursor: Any):
    # psycopg may construct the row maker before a result description exists.
    # Resolve column names when a row is actually materialized instead.
    def make_row(values: Sequence[Any]) -> HybridRow:
        description = cursor.description or ()
        columns = [column.name for column in description]
        return HybridRow(columns, values)

    return make_row


def _translate_datetime_now(sql: str) -> str:
    return re.sub(
        r"datetime\(\s*'now'\s*\)",
        "((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::text)",
        sql,
        flags=re.IGNORECASE,
    )


def _translate_transaction_dialect(sql: str) -> str:
    return re.sub(r"^\s*BEGIN\s+IMMEDIATE\s*;?\s*$", "BEGIN", sql, flags=re.IGNORECASE)


def _translate_placeholders(sql: str) -> str:
    # Catalyst SQL uses DB-API qmark placeholders and does not embed literal question
    # marks in executable SQL. Keeping translation here preserves all higher-level APIs.
    return sql.replace("?", "%s")


def _translate_json_extract(sql: str) -> str:
    pattern = re.compile(r"json_extract\(\s*([A-Za-z0-9_.]+)\s*,\s*'\$\.([A-Za-z0-9_]+)'\s*\)")
    return pattern.sub(r"(\1::jsonb -> '\2')", sql)


def _translate_insert_or_ignore(sql: str) -> str:
    if not re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.IGNORECASE):
        return sql
    translated = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE)
    stripped = translated.rstrip()
    semicolon = stripped.endswith(";")
    if semicolon:
        stripped = stripped[:-1].rstrip()
    if " ON CONFLICT " not in stripped.upper():
        stripped += " ON CONFLICT DO NOTHING"
    return stripped + (";" if semicolon else "")


def translate_sql_for_postgresql(sql: str) -> str:
    translated = _translate_transaction_dialect(sql)
    translated = _translate_datetime_now(translated)
    translated = _translate_json_extract(translated)
    translated = _translate_insert_or_ignore(translated)
    translated = _translate_placeholders(translated)
    return translated


class _PostgresCursor:
    def __init__(self, cursor: Any, *, lastrowid: int | None = None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)


class PostgresConnection:
    backend = "postgresql"

    def __init__(self, raw: Any, target: DatabaseTarget):
        self.raw = raw
        self.target = target
        self._transaction_depth = 0

    @property
    def in_transaction(self) -> bool:
        return self._transaction_depth > 0

    def _special_pragma(self, sql: str) -> _PostgresCursor | None:
        normalized = " ".join(sql.strip().rstrip(";").split()).lower()
        queries = {
            "pragma integrity_check": "SELECT 'ok' AS integrity_check",
            "pragma quick_check": "SELECT 'ok' AS quick_check",
            "pragma foreign_keys": "SELECT 1 AS foreign_keys",
            "pragma journal_mode": "SELECT 'postgresql' AS journal_mode",
            "pragma foreign_key_check": "SELECT NULL::text AS table_name WHERE FALSE",
            "pragma wal_checkpoint(passive)": "SELECT 0 AS busy, 0 AS log, 0 AS checkpointed",
        }
        query = queries.get(normalized)
        if query is None:
            return None
        cursor = self.raw.cursor(row_factory=_hybrid_row_factory)
        cursor.execute(query)
        return _PostgresCursor(cursor)

    def execute(self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> _PostgresCursor:
        pragma = self._special_pragma(sql)
        if pragma is not None:
            return pragma
        translated = translate_sql_for_postgresql(sql)
        cursor = self.raw.cursor(row_factory=_hybrid_row_factory)
        cursor.execute(translated, params or ())
        normalized = " ".join(translated.strip().rstrip(";").split()).upper()
        if normalized == "BEGIN":
            self._transaction_depth = max(1, self._transaction_depth)
        elif normalized == "COMMIT" or normalized == "ROLLBACK":
            self._transaction_depth = 0

        lastrowid = None
        insert_match = re.match(r'^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)', translated, flags=re.IGNORECASE)
        if insert_match and cursor.rowcount:
            # sqlite3 exposes cursor.lastrowid for INTEGER PRIMARY KEY tables.
            # Resolve the specific PostgreSQL table sequence instead of LASTVAL(),
            # which could otherwise return a stale sequence from an unrelated insert.
            table = insert_match.group(1)
            try:
                id_cursor = self.raw.cursor(row_factory=_hybrid_row_factory)
                id_cursor.execute("SELECT pg_get_serial_sequence(%s, 'id') AS sequence_name", (table,))
                sequence = id_cursor.fetchone()
                sequence_name = sequence[0] if sequence is not None else None
                if sequence_name:
                    id_cursor.execute("SELECT currval(%s::regclass) AS id", (sequence_name,))
                    row = id_cursor.fetchone()
                    lastrowid = int(row[0]) if row is not None else None
                id_cursor.close()
            except Exception:
                # Inserts into non-sequence tables are valid and simply have no lastrowid.
                lastrowid = None
        return _PostgresCursor(cursor, lastrowid=lastrowid)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> _PostgresCursor:
        cursor = self.raw.cursor(row_factory=_hybrid_row_factory)
        cursor.executemany(translate_sql_for_postgresql(sql), seq_of_params)
        return _PostgresCursor(cursor)

    def executescript(self, sql: str) -> None:
        # psycopg/libpq accepts multi-statement simple queries when no parameters are
        # bound. Wrap the entire script in one PostgreSQL transaction so schema
        # initialization is atomic even when the connection itself is autocommit.
        with self.raw.transaction():
            cursor = self.raw.cursor()
            cursor.execute(sql, prepare=False)
            cursor.close()

    def commit(self) -> None:
        if self._transaction_depth:
            cursor = self.raw.cursor()
            cursor.execute("COMMIT")
            cursor.close()
            self._transaction_depth = 0
        elif not self.raw.autocommit:
            self.raw.commit()

    def rollback(self) -> None:
        if self._transaction_depth:
            cursor = self.raw.cursor()
            cursor.execute("ROLLBACK")
            cursor.close()
            self._transaction_depth = 0
        elif not self.raw.autocommit:
            self.raw.rollback()

    def close(self) -> None:
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and self.in_transaction:
            self.rollback()
        self.close()
        return False


def connect(target_value: str | Path | DatabaseTarget | None, *, readonly: bool = False):
    target = resolve_database_target(target_value)
    if target.is_sqlite:
        database = Path(target.value).expanduser()
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

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DatabaseConfigurationError(
            "PostgreSQL support requires psycopg 3. Install with: pip install 'psycopg[binary]>=3.2'"
        ) from exc
    try:
        # Autocommit keeps read-only service calls lightweight; the transaction()
        # helper creates explicit atomic scopes for all governed writes.
        raw = psycopg.connect(target.value, autocommit=True)
        if readonly:
            with raw.cursor() as cursor:
                cursor.execute("SET default_transaction_read_only = on")
        return PostgresConnection(raw, target)
    except Exception as exc:  # pragma: no cover - requires live PostgreSQL
        message = str(exc).replace(target.value, target.display)
        parsed = urlparse(target.value)
        for secret in (parsed.username, parsed.password):
            if secret:
                message = message.replace(secret, "***")
        raise DatabaseConfigurationError(f"unable to connect to {target.display}: {message}") from exc


@contextlib.contextmanager
def transaction(connection) -> Iterator[Any]:
    if isinstance(connection, sqlite3.Connection):
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
        return

    name = f"catalyst_data_nested_{connection._transaction_depth + 1}"
    if connection._transaction_depth:
        connection.execute(f"SAVEPOINT {name}")
        connection._transaction_depth += 1
        try:
            yield connection
        except Exception:
            connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            connection.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            connection.execute(f"RELEASE SAVEPOINT {name}")
        finally:
            connection._transaction_depth -= 1
        return

    connection.execute("BEGIN")
    connection._transaction_depth = 1
    try:
        yield connection
    except Exception:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")
    finally:
        connection._transaction_depth = 0
