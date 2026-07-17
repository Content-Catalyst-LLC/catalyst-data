# Catalyst Data

Catalyst Data is the persistent evidence and measurement repository for Sustainable Catalyst. It connects canonical records, normalized relational tables, provenance, confidence, review logic, migrations, imports, exports, and local analytical workflows without requiring paid infrastructure.

## Current release

**v1.12.0 — Analysis Artifacts and Reproducible Data Packages**

The release freezes exact canonical inputs, parameters, environments, code references, outputs, derived lineage, replication reviews, and invalidation warnings. Deterministic packages preserve the evidence needed to reproduce or independently review an analysis without making Catalyst Data dependent on any single analytical product.

## Core capabilities

- Versioned analysis artifacts with immutable activations and run history.
- Frozen canonical inputs, checksums, parameters, environments, and code references.
- Checksum-bound outputs, derived measurement lineage, and platform artifact links.
- Automatic upstream-change invalidation warnings without rewriting historical results.
- Independent replication reviews and deterministic reproducible data packages.

- Governed file and HTTP connectors for JSON and CSV sources.
- Immutable connector versions with explicit activation history.
- Manual, scheduled, retry, replay, and quarantine-recovery runs.
- Payload snapshots, row checksums, idempotent refresh, and source-key state.
- Freshness, licensing, schema-drift, population-drift, and health alerts.
- Reconciliation reports, quarantine queues, dead letters, and offline replay.
- Workspace-bound connector access and protected API operations.
- Institutional tenants, workspaces, projects, principals, and memberships.
- Viewer, contributor, analyst, reviewer, approver, publisher, and administrator roles.
- Record ownership, stewardship, custodianship, visibility, classification, retention, and legal-hold governance.
- Append-only access decisions and immutable workspace transfer history.
- Workspace-bound API keys and tenant-safe protected record endpoints.
- `catalyst-data-access-governance/1.0` repository access metadata.
- Strict `catalyst-data-record/1.0` validation.
- Backward-compatible `catalyst-data-review-workflow/1.0` records.
- Attributable review states, assignments, comments, decisions, and priorities.
- Explainable six-dimension quality assessments and publication gates.
- Immutable approval snapshots and semantic revision diffs.
- Backward-compatible `catalyst-data-observation-lineage/1.0` records.
- Research, decision, monitoring, and evaluation questions.
- Immutable instrument and dataset versions with governed fields.
- Observation batches, baseline/current observations, dimensions, and quality metadata.
- Explicit observation-to-measurement transformations and append-only lineage events.
- Backward-compatible `catalyst-data-indicator-governance/1.0` records.
- Namespaced indicator registry with lifecycle status, custody, definitions, frequency, aggregation, and disaggregation metadata.
- Immutable indicator and methodology versions with append-only governance events.
- Governed units, conversion bases, framework mappings, and explicit compatibility rules.
- Deterministic equivalent, convertible, limited, and incompatible comparison results.
- Backward-compatible `catalyst-data-evidence-chain/1.0` records.
- Multiple evidence sources with primary, supporting, conflicting, derived, and contextual roles.
- Immutable source versions, snapshots, record revisions, and provenance events.
- Source relationships, evidence locators, supported fields, and transformation lineage.
- Derived evidence gaps and deterministic completeness scoring.
- Stable semantic IDs and payload checksums.
- SQLite persistence with normalized tables and complete canonical JSON records.
- Ordered `.up.sql` and `.down.sql` migrations, including populated evidence-history rollback.
- Automatic evidence-table backfill when an existing v1.2.0 repository reaches migration 003.
- Idempotent inserts, updates, and duplicate skips.
- JSON and CSV imports with dry runs and row-level errors.
- Atomic rollback or controlled partial-import mode.
- Import-run and imported-record ledgers.
- JSON and CSV exports.
- Review queues, repository statistics, integrity checks, and schema-version reporting.
- Versioned saved queries and immutable query-run snapshots.
- Filtered entity, indicator, period, source, framework, quality, evidence, and review queries.
- Consecutive-period comparisons with unit conversion and comparability warnings.
- Reproducible Markdown briefs and deterministic JSON/CSV/provenance/review export bundles.
- Externally approved public-record views with privacy-aware projections.
- Dependency-light HTTP API with health, capabilities, pagination, CORS, and OpenAPI 3.1.
- SHA-256-only bearer-token storage with scopes, revocation, and audit history.
- Protected canonical record writes and typed handoff receipt.
- `catalyst-data-handoff/1.0` for Sustainable Catalyst product exchange.
- Persistent WordPress API embeds while preserving the no-server demo.

## Repository contents

- `python/catalyst_data/migrations/` — ordered, reversible SQL migrations.
- `python/catalyst_data/repository.py` — normalized and canonical record persistence.
- `python/catalyst_data/importer.py` — JSON/CSV ingestion and import reporting.
- `python/catalyst_data/exporter.py` — supported repository exports.
- `python/catalyst_data/service.py` — application service facade.
- `schemas/` and `contracts/` — canonical record and review contracts.
- `examples/imports/` — supported JSON and CSV examples.
- `python/catalyst_data/workspaces.py` — institutions, roles, permissions, retention, transfers, and access auditing.
- `python/catalyst_data/public_api.py` — public-safe HTTP API and protected writes.
- `python/catalyst_data/handoff.py` — typed platform handoff contract and validation.
- `python/catalyst_data/operations.py` — backup, restore, offline synchronization, performance, security, and release attestation.
- `openapi/` — static OpenAPI 3.1 contract.
- `wordpress/catalyst-data-demo/` — browser-only demo and persistent public API embed.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
```

## Persistent repository quick start

```bash
catalyst-data init catalyst-data.sqlite3
catalyst-data status catalyst-data.sqlite3

catalyst-data import catalyst-data.sqlite3 examples/imports/records.json --dry-run
catalyst-data import catalyst-data.sqlite3 examples/imports/records.json
catalyst-data import catalyst-data.sqlite3 examples/imports/measurements.csv

catalyst-data inspect catalyst-data.sqlite3
catalyst-data review catalyst-data.sqlite3
catalyst-data sources catalyst-data.sqlite3
catalyst-data provenance catalyst-data.sqlite3 RECORD_ID
catalyst-data evidence catalyst-data.sqlite3 RECORD_ID
catalyst-data indicators catalyst-data.sqlite3
catalyst-data methods catalyst-data.sqlite3
catalyst-data units catalyst-data.sqlite3
catalyst-data compare catalyst-data.sqlite3 LEFT_RECORD_ID RIGHT_RECORD_ID
catalyst-data governance-events catalyst-data.sqlite3 INDICATOR_ID
catalyst-data questions catalyst-data.sqlite3
catalyst-data instruments catalyst-data.sqlite3
catalyst-data datasets catalyst-data.sqlite3
catalyst-data observations catalyst-data.sqlite3 --record-id RECORD_ID
catalyst-data lineage catalyst-data.sqlite3 RECORD_ID
catalyst-data reviews catalyst-data.sqlite3
catalyst-data review-history catalyst-data.sqlite3 RECORD_ID
catalyst-data review-assign catalyst-data.sqlite3 RECORD_ID reviewer@example.org --actor author@example.org
catalyst-data review-submit catalyst-data.sqlite3 RECORD_ID --actor author@example.org
catalyst-data review-start catalyst-data.sqlite3 RECORD_ID --actor reviewer@example.org
catalyst-data quality-assess catalyst-data.sqlite3 RECORD_ID quality-assessment.json --actor reviewer@example.org
catalyst-data review-decide catalyst-data.sqlite3 RECORD_ID approved --actor reviewer@example.org --reason "Evidence and method are sufficient"
catalyst-data revisions catalyst-data.sqlite3 RECORD_ID
catalyst-data query-save catalyst-data.sqlite3 examples/queries/reviewable_records.json --actor analyst@example.org
catalyst-data queries catalyst-data.sqlite3
catalyst-data query-run catalyst-data.sqlite3 QUERY_ID
catalyst-data query-results catalyst-data.sqlite3 RUN_ID
catalyst-data query-brief catalyst-data.sqlite3 RUN_ID outputs/query-brief.md
catalyst-data export-bundle catalyst-data.sqlite3 RUN_ID outputs/query-bundle.zip

catalyst-data institutions catalyst-data.sqlite3
catalyst-data workspaces catalyst-data.sqlite3
catalyst-data principal-create catalyst-data.sqlite3 "Analyst One" --principal-id principal:analyst-one
catalyst-data workspace-member-add catalyst-data.sqlite3 workspace:default principal:analyst-one analyst --actor principal:system
catalyst-data record-access catalyst-data.sqlite3 RECORD_ID
catalyst-data workspace-records catalyst-data.sqlite3 workspace:default --principal-id principal:analyst-one
catalyst-data legal-hold catalyst-data.sqlite3 RECORD_ID set --actor principal:system --reason "Institutional preservation"
catalyst-data disposition-check catalyst-data.sqlite3 RECORD_ID
catalyst-data access-events catalyst-data.sqlite3 --record-id RECORD_ID

catalyst-data api-key-create catalyst-data.sqlite3 "Decision Studio" --scope records:write --scope handoffs:write
catalyst-data api-keys catalyst-data.sqlite3
catalyst-data serve catalyst-data.sqlite3 --host 127.0.0.1 --port 8765 --allow-origin https://sustainablecatalyst.com
catalyst-data openapi outputs/catalyst-data-openapi.json --base-url https://data.example.org
catalyst-data handoff-create catalyst-data.sqlite3 outputs/handoff.json RECORD_ID --target decision-studio --capability decision-evidence --api-base-url https://data.example.org
catalyst-data handoff-validate outputs/handoff.json
catalyst-data handoff-receive catalyst-data.sqlite3 outputs/handoff.json
catalyst-data handoff-receipts catalyst-data.sqlite3

catalyst-data export catalyst-data.sqlite3 outputs/repository-export.json
catalyst-data export catalyst-data.sqlite3 outputs/repository-export.csv --format csv
```

For a partial CSV import that commits valid rows and reports invalid rows:

```bash
catalyst-data import catalyst-data.sqlite3 records.csv --non-atomic --continue-on-error --summary outputs/import-summary.json
```

## Operational hardening

```bash
catalyst-data backup-create catalyst-data.sqlite3 backups/catalyst-data.sqlite3
catalyst-data backup-verify catalyst-data.sqlite3 backups/catalyst-data.sqlite3
catalyst-data backups catalyst-data.sqlite3

catalyst-data offline-queue catalyst-data.sqlite3 record-upsert queued-record.json
catalyst-data offline-sync catalyst-data.sqlite3
catalyst-data offline-operations catalyst-data.sqlite3

catalyst-data benchmark catalyst-data.sqlite3 --iterations 5
catalyst-data security-audit catalyst-data.sqlite3
catalyst-data operational-readiness catalyst-data.sqlite3
catalyst-data release-attest catalyst-data.sqlite3 . outputs/release-attestation.json
```

Restore a verified backup to a separate repository first:

```bash
catalyst-data restore catalyst-data.sqlite3 backups/catalyst-data.sqlite3 --target restored.sqlite3
```

## Migration operations

```bash
catalyst-data migrate catalyst-data.sqlite3
catalyst-data rollback catalyst-data.sqlite3 --steps 1
catalyst-data migrate catalyst-data.sqlite3
```

Create a verified backup before rolling back a repository containing important data.

## Record utilities

```bash
catalyst-data brief examples/sample_project.json outputs/generated_brief.md
catalyst-data validate outputs/generated_brief.json
catalyst-data upgrade examples/sample_legacy_v1_0_record.json outputs/upgraded_legacy_record.json
```

The legacy two-positional-argument brief command remains supported.

## Python API

```python
from catalyst_data import CatalystDataService

service = CatalystDataService("catalyst-data.sqlite3")
service.initialize()
summary = service.import_file("examples/imports/records.json")
service.export_file("outputs/export.json")
```

## WordPress demo and persistent embed

Install `dist/catalyst-data-demo.zip`. `[catalyst_data_demo]` remains browser-only and does not write to SQLite. `[catalyst_data_embed api_url="https://data.example.org" limit="12"]` reads externally approved records from the public API and never accepts a write token.

## Build and validation

```bash
python3 scripts/build_release.py
python3 scripts/check_release.py
```

The release suite validates generated contracts, schemas, review transitions, quality assessments, immutable approvals, semantic revision history, governed indicator semantics, unit conversion, comparability, migrations, populated rollback/remigration, repository persistence, imports, exports, verified backup/restore, offline synchronization, performance and security checks, release attestations, accessibility markers, SQL/Python/browser parity, PHP and JavaScript syntax, package contents, and deterministic ZIP reproduction.

## Boundary

Catalyst Data preserves validated structure, immutable revisions, provenance history, and controlled exchange. It does not certify truth, compliance, or impact. Remote API operation and Platform Core integration are optional, and v1.12.0 provides governed connector operations and repository-level institutional authorization without claiming legal or regulatory compliance.

## License

MIT — see `LICENSE`.
