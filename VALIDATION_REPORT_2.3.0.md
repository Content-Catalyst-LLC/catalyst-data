# Catalyst Data v2.3.0 Validation Report

## Release

**Catalyst Data v2.3.0 — Internet Archive & Wayback Intelligence**

Validated: 2026-08-11

## Scope

- Migration 016: Internet Archive and Wayback archival catalog persistence
- Internet Archive Advanced Search provider adapter
- Internet Archive Item Metadata and file-inventory adapter
- Wayback snapshot-availability adapter
- Wayback CDX capture-history adapter
- Archive/Wayback CLI acquisition and cached catalog commands
- Public read-only archive catalog and Wayback API endpoints
- Sustainable Catalyst Data WordPress archive and Wayback surfaces
- SQLite and generated PostgreSQL schema parity
- Existing v2.2 external adapter, connector, provenance, workspace, review, analysis, API, and operational contracts

## Automated results

- 176 tests collected across the complete Python matrix
- 175 passed
- 1 skipped: live PostgreSQL integration when `CATALYST_TEST_POSTGRES_URL` is not configured locally
- 0 failed
- Portable release contract: PASS
- Browser contract parity: PASS
- Sustainable Catalyst Data WordPress PHP syntax: PASS
- WordPress JavaScript syntax: PASS
- Generated PostgreSQL schema: PASS
- Migration 016 forward/rollback/reapply coverage: PASS
- Deterministic WordPress distribution build: PASS

## Archive-specific regression coverage

- Provider adapters registered through the v2.2 adapter registry
- Advanced Search query construction and pagination contract
- Archive.org identifier path-injection rejection
- Catalog-first persistence without coercion into measurement records
- Descriptive Catalyst Data automated-request User-Agent
- Item metadata and file inventory persistence
- Immutable item snapshot history, including file-only changes
- Current file-inventory reconciliation
- Wayback availability capture persistence
- CDX enrichment/deduplication of the same capture
- Unsafe target URL rejection
- Public API serves cached archive resources without triggering provider acquisition
- WordPress contains no direct Archive.org/Wayback acquisition endpoint

## Result

Release-ready. Live PostgreSQL execution remains CI-gated exactly as in v2.2.0; SQLite, PostgreSQL schema generation, and all local cross-backend contracts pass.
