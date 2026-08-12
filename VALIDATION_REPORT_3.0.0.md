# Catalyst Data v3.0.0 Validation Report

## Release

**Catalyst Data v3.0.0 — Connected Data Graph & Cross-Source Federation**

## Scope validated

- Migration 023 connected graph schema, rollback, and reapply behavior.
- Relational property-graph node/edge storage and immutable graph event/sync history.
- Rebuildable graph synchronization from Catalyst Data's governed local caches.
- Canonical-entity, dataset-catalog, provider, statistical-series, and scientific-object federation.
- Bounded graph search, neighborhood, shortest-path, entity federation, and JSON-LD-compatible export.
- Cache-only public API and WordPress graph surfaces; no upstream acquisition from public reads.
- SQLite local/offline behavior and generated PostgreSQL production-schema parity.
- Existing Catalyst Data archive, statistics, U.S. public data, earth/ocean, space/science, entity, platform, governance, query, review, lineage, import/export, and operational-hardening contracts.

## Python test inventory

Final collection: **219 tests**.

Validated in bounded groups because the container execution window terminates the repository's one-shot per-module release script before completion:

- **218 passed**
- **1 skipped** — the expected live PostgreSQL integration test when `CATALYST_TEST_POSTGRES_URL` is not configured
- **0 functional failures**

The exact `scripts/test_release.sh` command was also started. Its first five modules completed successfully before the container command reached its 120-second execution limit. The complete test inventory above was then covered by bounded pytest groups.

## Release gates

Passed:

- `scripts/smoke_test.py`
- `scripts/check_release.py --portable`
- full `scripts/check_release.py`
- generated contract synchronization
- generated record-contract synchronization
- migration sequence 1–23
- migration 023 rollback/reapply
- generated PostgreSQL schema
- static OpenAPI parity
- browser contract parity
- JavaScript syntax checks
- PHP syntax checks for both WordPress plugins
- deterministic Sustainable Catalyst Data WordPress ZIP reproduction
- runtime/package version-source contract (`catalyst_data._version.__version__`)

## Packaging hardening

The macOS installer retains the v2.8/v2.9 recovery hardening:

- content-checksum source overlay (`rsync --checksum`)
- `.git`, `.venv`, `.env`, and local SQLite/database preservation
- explicit `setuptools.build_meta` and wheel preparation
- stale editable-package removal before reinstall
- runtime version, installed distribution version, and import-path verification before release validation
- Git commit/push only after the complete project release suite passes on the target Mac

## Provider boundary

Connected-graph synchronization reads only Catalyst Data's locally persisted provider caches and derived registries. Public API and WordPress graph reads do not invoke upstream provider acquisition and do not require provider credentials.

## Environment limitation

No live PostgreSQL URL was supplied in the build environment. The generated PostgreSQL production baseline and SQL-parity checks pass, but a live PostgreSQL integration run remains the expected skipped test.
