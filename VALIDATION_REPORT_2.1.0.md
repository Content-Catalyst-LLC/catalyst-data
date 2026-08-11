# Catalyst Data v2.1.0 Validation Report

## Release

**v2.1.0 — PostgreSQL Production Persistence & Storage Abstraction**

## Validation summary

- Python tests collected: **161**
- Python tests passed locally: **160**
- Python tests skipped locally: **1**
- Failed Python tests: **0**
- Portable release contract: **PASS**
- Portable smoke suite: **PASS**
- Browser JavaScript contract parity: **PASS**
- WordPress PHP syntax: **PASS**
- Deterministic WordPress distribution build: **PASS**

The single skipped test is `test_live_postgresql_baseline_import_and_sqlite_migration`. The local build container does not provide a PostgreSQL server. `.github/workflows/tests.yml` now provisions PostgreSQL 16 and sets `CATALYST_TEST_POSTGRES_URL`, so the live baseline/import/backend-migration contract runs in CI.

## v2.1.0 release gates exercised

- SQLite migration 001 → 014 and populated rollback/remigration.
- SQLite backward compatibility across records, evidence, governance, observation lineage, review, queries, API, workspaces, connectors, analyses, operations, and platform registry.
- PostgreSQL URL recognition and credential-safe display identity.
- PostgreSQL runtime SQL translation for qmark parameters, SQLite transaction syntax, current timestamps, JSON extraction, and idempotent inserts.
- Generated PostgreSQL schema contains migration 014 and PostgreSQL governance triggers and contains no gated SQLite-only DDL tokens.
- Storage-backend metadata is persisted for SQLite and prepared for PostgreSQL.
- SQLite-to-PostgreSQL migration code preserves repository identity, copied IDs, governance rows, and sequence repair within one target transaction.
- PostgreSQL file-level backup is blocked in favor of managed provider backup/PITR; SQLite verified file backup remains intact.
- Package metadata includes `psycopg[binary]>=3.2`, `rfc3986-validator>=0.1.1`, and PostgreSQL schema resources.
- Canonical source and evidence-source URIs are rejected deterministically even when optional `jsonschema` format extras are absent.
- Release tests run through the project virtual environment rather than ambient Homebrew/system Python.
- Release version, manifest, OpenAPI, WordPress plugin, generated contracts, and release documentation are synchronized to v2.1.0.

## Live PostgreSQL CI contract

The live test resets an isolated CI database, initializes the complete PostgreSQL production baseline, validates health/version reporting, imports canonical records, verifies evidence retrieval, creates a populated SQLite repository, promotes it into PostgreSQL, and verifies repository identity plus canonical record count after migration.
