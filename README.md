# Catalyst Data

Catalyst Data is the persistent evidence and measurement repository for Sustainable Catalyst. It connects canonical records, normalized relational tables, provenance, confidence, review logic, migrations, imports, exports, and local analytical workflows without requiring paid infrastructure.

## Current release

**v1.7.0 — Query, Comparison, and Export Studio**

The release adds versioned saved queries, immutable query runs, frozen record snapshots, governed comparisons, warnings, reproducible briefs, and deterministic export bundles without weakening the review, provenance, or lineage contracts.

## Core capabilities

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

## Repository contents

- `python/catalyst_data/migrations/` — ordered, reversible SQL migrations.
- `python/catalyst_data/repository.py` — normalized and canonical record persistence.
- `python/catalyst_data/importer.py` — JSON/CSV ingestion and import reporting.
- `python/catalyst_data/exporter.py` — supported repository exports.
- `python/catalyst_data/service.py` — application service facade.
- `schemas/` and `contracts/` — canonical record and review contracts.
- `examples/imports/` — supported JSON and CSV examples.
- `wordpress/catalyst-data-demo/` — browser-only canonical-record demonstration.

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

catalyst-data export catalyst-data.sqlite3 outputs/repository-export.json
catalyst-data export catalyst-data.sqlite3 outputs/repository-export.csv --format csv
```

For a partial CSV import that commits valid rows and reports invalid rows:

```bash
catalyst-data import catalyst-data.sqlite3 records.csv --non-atomic --continue-on-error --summary outputs/import-summary.json
```

## Migration operations

```bash
catalyst-data migrate catalyst-data.sqlite3
catalyst-data rollback catalyst-data.sqlite3 --steps 1
catalyst-data migrate catalyst-data.sqlite3
```

Create a backup before rolling back a repository containing important data.

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

## WordPress demo

Install `dist/catalyst-data-demo.zip`, activate it, and add `[catalyst_data_demo]`. The demo remains browser-only and does not write to the SQLite repository.

## Build and validation

```bash
python3 scripts/build_release.py
python3 scripts/check_release.py
```

The release suite validates generated contracts, schemas, review transitions, quality assessments, immutable approvals, semantic revision history, governed indicator semantics, unit conversion, comparability, migrations, rollback/remigration, repository persistence, imports, exports, SQL/Python/browser parity, PHP and JavaScript syntax, package contents, and deterministic ZIP reproduction.

## Boundary

Catalyst Data preserves validated structure, immutable revisions, and provenance history. It does not certify truth, compliance, or impact, and v1.7.0 does not yet provide institutional authorization or remote APIs.

## License

MIT — see `LICENSE`.
