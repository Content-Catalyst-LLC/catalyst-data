# Connectors, Refresh, and Data Operations

Catalyst Data v1.10.0 introduces a governed acquisition layer for recurring external and local data. Connectors remain subordinate to the canonical record, review, provenance, and workspace contracts: a connector may import and refresh evidence, but it cannot silently approve or publish a record.

## Connector registry

Each connector has a stable identifier, workspace and principal ownership, source type, source URI, licensing and freshness policy, authentication reference, capabilities, and operational status. Connector configuration is stored as immutable versions. Activating a new version appends an activation event rather than rewriting previous history.

Supported zero-dependency source types are:

- JSON over HTTP or a local file
- CSV over HTTP or a local file
- Manual payloads
- Immutable payload replay

Credentials are referenced only by environment-variable name. Secret values are never stored in connector definitions, logs, snapshots, exports, or audit records.

## Refresh runs

Runs may be triggered manually, by a governed schedule, as a retry, from an immutable replay snapshot, or while recovering a quarantined row. Every run records its connector version, attempt number, trigger, timing, response metadata, payload checksum, row counts, actions, status, and reconciliation result.

Stable source keys and row checksums make refreshes idempotent. Unchanged records are skipped, changed records are updated through the canonical repository, new records are inserted, and missing source keys are retained in history but marked inactive.

## Snapshots and offline replay

Fetched payloads are stored as append-only snapshots with their source URI, content type, size, and SHA-256 digest. A prior run can be replayed without contacting the original source. This supports debugging, independent review, regression testing, and recovery when an upstream service is unavailable.

## Reconciliation and drift

Each successful or partial run compares the current source-key set with the previous active set. Reports include expected, actual, matched, changed, missing, unexpected, duplicate, failed, and quarantined counts. Schema fingerprints detect field-shape drift, while configurable missing-record ratios identify material population drift.

## Quarantine and dead letters

Rows that fail mapping or canonical validation are quarantined with their raw payload and error reason. After a corrected connector version is activated, a quarantined row can be retried under that version. Fetch or payload failures that exhaust their retry policy create dead letters linked to the failed run and any available payload snapshot.

## Operational governance

Connector state tracks last attempt, last success, active version, source modification time, payload and schema checksums, consecutive failures, rate-limit timing, and health. Alerts cover fetch failures, rate limits, stale data, missing or restricted licenses, schema drift, record drift, reconciliation warnings, quarantine, and dead letters.

Schedules have a minimum hourly frequency. Catalyst Data intentionally does not provide a continuously running proprietary scheduler; `connector-run-due` can be invoked by cron, a system timer, CI, or another open orchestration service.

## CLI examples

```bash
catalyst-data connector-register catalyst-data.sqlite3 examples/connectors/open_metrics_connector.json
catalyst-data connector-run catalyst-data.sqlite3 connector:open-metrics
catalyst-data connector-runs catalyst-data.sqlite3 --connector-id connector:open-metrics
catalyst-data connector-run-show catalyst-data.sqlite3 RUN_ID
catalyst-data connector-replay catalyst-data.sqlite3 RUN_ID
catalyst-data connector-schedule catalyst-data.sqlite3 connector:open-metrics 1440 --enabled
catalyst-data connector-run-due catalyst-data.sqlite3
catalyst-data connector-quarantine catalyst-data.sqlite3 --connector-id connector:open-metrics
catalyst-data connector-alerts catalyst-data.sqlite3 --connector-id connector:open-metrics
```

## Boundaries

Connector success means that retrieval, mapping, canonical validation, persistence, and reconciliation completed under the recorded policy. It does not certify that an upstream source is true, complete, lawful for every use, or suitable for a particular decision. Human review, licensing judgment, and publication approval remain explicit steps.
