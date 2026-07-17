# Provenance and Immutable History

Catalyst Data v1.3.0 preserves both the current normalized repository state and append-only historical evidence.

## Source versions

Each distinct canonical source payload receives an incrementing version number. Re-importing identical metadata reuses the existing version. Changed citation, publisher, license, retrieval, checksum, URL, or access metadata creates a new immutable version.

## Source snapshots

Snapshots can record retrieval time, content checksum, storage URI, media type, byte size, and metadata. A snapshot may be created automatically from source metadata or explicitly through `CatalystRepository.add_source_snapshot()`.

## Record revisions

Every insert or material update creates an immutable revision containing the full canonical JSON payload and SHA-256 checksum. Duplicate imports create no revision.

## Provenance events

Events form an append-only chain through `previous_event_id`. Supported events include record creation/update, source versioning, source linking, snapshots, transformations, imports, corrections, publication, review, and supersession.

## Current-state tables

`measurement_sources`, `source_relationships`, and `evidence_gaps` expose the current evidence model. Historical record payloads and events remain available even when current source links or gaps change.

## CLI inspection

```bash
catalyst-data sources repository.sqlite3
catalyst-data sources repository.sqlite3 --source-id SOURCE_ID
catalyst-data provenance repository.sqlite3 RECORD_ID
catalyst-data evidence repository.sqlite3 RECORD_ID
```
