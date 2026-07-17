# Relational Schema

Catalyst Data v1.6.0 maintains a normalized SQLite repository alongside the complete canonical JSON record.

## Core tables

- `entities`
- `indicators`
- `periods`
- `sources`
- `measurements`
- `measurement_notes`
- `tags` and tag joins

Each core object can carry a canonical stable ID. `data_records` maps the canonical `record_id` to the normalized entity, indicator, period, source, and measurement rows while preserving the complete validated payload and SHA-256 digest.

## Repository tables

- `schema_migrations` records ordered migration state.
- `repository_metadata` identifies the local repository.
- `data_records` stores canonical JSON and normalized row links.
- `import_runs` records import execution summaries.
- `import_records` records inserted, updated, and skipped records.
- `import_row_errors` records row-level failures.

## Review views

- `measurement_review`
- `provenance_gaps`
- `low_confidence_measurements`

`schema.sql` is a current-schema reference and demo fixture. Applications must initialize repositories through the migration manager rather than treating `schema.sql` as a migration substitute.
