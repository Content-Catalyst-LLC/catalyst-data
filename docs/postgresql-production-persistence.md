# PostgreSQL Production Persistence

Catalyst Data v2.1.0 adds PostgreSQL as the production persistence backend while preserving SQLite as a fully supported local, offline, test, recovery, and portable backend.

## Backend selection

The repository accepts either a SQLite path or a PostgreSQL URL. When no value is supplied programmatically, `DATABASE_URL` is used when present; otherwise Catalyst Data falls back to `catalyst-data.sqlite3`.

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/catalyst_data?sslmode=require'
catalyst-data init "$DATABASE_URL"
catalyst-data status "$DATABASE_URL"
```

Status and error surfaces redact PostgreSQL usernames, passwords, query parameters, and other credentials. Application services retain the existing `CatalystRepository` contract and do not contain backend-specific branches.

## Production baseline

`python/catalyst_data/postgresql/schema.sql` is generated from the complete ordered migration history. It translates portable SQLite DDL to PostgreSQL types and supplies PostgreSQL trigger functions for the repository's append-only/immutable tables, default Workspace assignment, and analysis invalidation rules.

A fresh PostgreSQL database initializes atomically to the latest supported baseline. `schema_migrations` records every canonical migration represented by that baseline. Migration 014 adds `storage_backend_metadata` and `storage_migration_events`.

PostGIS is not enabled automatically in v2.1.0. PostgreSQL is marked as geospatial-extension-capable so a later geospatial release can add PostGIS deliberately without making it a hidden deployment dependency.

## Promote an existing SQLite repository

```bash
catalyst-data storage-migrate-postgres catalyst-data.sqlite3 "$DATABASE_URL" --actor principal:system
```

The migration workflow:

1. initializes and validates both repositories;
2. copies canonical and normalized tables inside one PostgreSQL transaction;
3. preserves the SQLite repository ID;
4. preserves explicit integer IDs and advances PostgreSQL sequences;
5. temporarily suspends only the default-Workspace insert trigger while copied governance rows are restored;
6. records a completed or failed storage-migration event.

The target database should be dedicated to Catalyst Data. Take a managed backup before re-running a migration against a target that already contains production data.

## Backup boundary

SQLite continues to support Catalyst Data's file-level verified backup and restore commands. PostgreSQL deployments should use the managed provider's backup and point-in-time-recovery facilities. Catalyst Data does not create raw PostgreSQL filesystem backups.

## Application deployment

Keep the database private to the Catalyst application tier where the hosting provider supports private networking. WordPress and other site surfaces should call the Catalyst Data API rather than connect to PostgreSQL directly.

The deployment process needs the PostgreSQL driver declared by the package:

```text
psycopg[binary]>=3.2
```

## Validation

The normal source suite always validates SQLite compatibility and PostgreSQL SQL generation. When `CATALYST_TEST_POSTGRES_URL` is provided, the v2.1 test suite additionally creates a live PostgreSQL baseline, imports canonical records, validates evidence access, and exercises a full SQLite-to-PostgreSQL promotion.
