# Changelog

## 1.4.0 — Indicator Registry, Units, and Methodology Governance

- Added the backward-compatible `catalyst-data-indicator-governance/1.0` contract.
- Added migration 004 with immutable indicator and methodology versions, governed units, framework mappings, compatibility rules, and governance events.
- Added automatic v1.3.0 registry backfill.
- Added unit conversion and record comparability services.
- Added indicator, methodology, unit, comparison, conversion, and governance-history CLI commands.
- Added governance-aware JSON and CSV import/export fields.
- Added schema, migration, semantic, repository, CLI, browser, and package validation.

## 1.3.0 — Sources, Provenance, and Evidence Chain

- Added the backward-compatible `catalyst-data-evidence-chain/1.0` contract.
- Added multiple evidence roles, locators, source relationships, transformations, gaps, and completeness scoring.
- Added immutable source versions, source snapshots, record revisions, and provenance events.
- Added migration 003, evidence views, evidence-aware import/export, repository APIs, and CLI inspection commands.
- Added automatic evidence-storage backfill for existing v1.2.0 records and repaired populated migration rollback ordering.
- Expanded release validation and tests for immutability, versioning, lineage, gaps, and upgrade safety.

## 1.2.0 — Persistent Repository, Migrations, and Import Pipeline

- Added a local-first SQLite repository with synchronized normalized tables and canonical JSON records.
- Added ordered, contiguous, reversible SQL migrations and migration status reporting.
- Added repository and application service layers.
- Added stable-ID and payload-checksum based inserts, updates, and duplicate skips.
- Added JSON and CSV imports with deterministic authoring timestamps, dry runs, row-level errors, atomic rollback, and partial-import mode.
- Added import run, imported-record, and import-error ledgers.
- Added JSON and CSV repository exports.
- Added `init`, `migrate`, `rollback`, `status`, `import`, `export`, `inspect`, and `review` CLI commands.
- Added repository health, SQLite integrity, schema-version, statistics, and review-queue checks.
- Packaged migration SQL inside the installable Python distribution.
- Expanded migration, persistence, import, export, CLI, transaction, and release tests.

## 1.1.0 — Canonical Data Contract and Validation Engine

### Installer reliability repair

- Prevented stale v1.0.x Python bytecode from being reused during an in-place v1.1.0 upgrade.
- Isolated release validation bytecode lookups from repository caches.

- Added the canonical `catalyst-data-record/1.0` schema and contract metadata.
- Added strict JSON Schema validation with unknown-field rejection and format checks.
- Added stable semantic IDs, record type, creation/update timestamps, and producer metadata.
- Expanded source provenance with URL, publisher, license, retrieval timestamp, citation, checksum, and access notes.
- Added structured confidence basis, review notes, assumptions, limitations, uncertainty, and quality flags.
- Added namespaced extension rules.
- Added Python TypedDict mappings and packaged schema resources.
- Added legacy v1.0.x conversion through Python and `catalyst-data upgrade`.
- Added `catalyst-data validate` and preserved the legacy brief CLI invocation.
- Updated the WordPress demo to emit the canonical record contract.
- Expanded contract, semantic, CLI, browser, packaging, and release tests.

## 1.0.1 — Repository Integrity and Package Contract Repair

- Added `VERSION` as the canonical release version source.
- Added a canonical review contract and generated Python, SQL, and browser artifacts.
- Synchronized confidence thresholds, missing-source behavior, trace paths, and status labels across runtimes.
- Separated evidence readiness (`review_status`) from measurement direction (`signal_status`).
- Corrected zero-baseline percent change to `null` / indeterminate instead of `0`.
- Added basic input validation for confidence, direction, numeric values, and required identifiers.
- Added `pyproject.toml`, installable package metadata, and the `catalyst-data-brief` CLI.
- Added deterministic WordPress ZIP generation from committed source.
- Added release-contract, SQL parity, browser parity, JSON Schema, syntax, and package-content checks.
- Added unique WordPress field IDs for multiple shortcode instances.
- Expanded CI and release documentation.

## 1.0.0 — Catalyst Data demo and repository upgrade

- Added WordPress shortcode plugin: `[catalyst_data_demo]`.
- Added browser-based Catalyst Data demo for traceable measurement records.
- Added Python Catalyst Data brief generator.
- Added JSON schema for structured exports.
- Added sample data, examples, and outputs.
- Added methodology, provenance, schema, export, review, and WordPress plugin docs.
- Added pytest tests and GitHub Actions workflow.
- Updated SQL schema and queries to align with Sustainable Catalyst methodology.
