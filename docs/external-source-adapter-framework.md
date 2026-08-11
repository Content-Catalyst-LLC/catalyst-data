# External Source Adapter Framework

Catalyst Data v2.2.0 adds source adapters as a governed layer above the connector engine.

## Boundary

An adapter knows how to request and page through a source API. A connector continues to own authentication references, mapping, payload snapshots, normalization into canonical records, quarantine, reconciliation, and provenance. This prevents source-specific API code from bypassing Catalyst Data governance.

## Built-in adapters

- `generic-http-json`
- `generic-http-csv`

Both support bounded runs, descriptive User-Agent headers, configured headers/query parameters, and no/page/offset pagination. JSON also supports cursor pagination with a configured cursor path.

## Conditional HTTP

For non-paginated sources, successful ETag and Last-Modified responses are retained in adapter state and reused as `If-None-Match` and `If-Modified-Since`. HTTP 304 creates a completed adapter run without creating a duplicate connector ingestion run.

## Secrets

Adapter config is persisted and therefore must be non-secret. Authorization, API-key, cookie, access-token, and client-secret style values must use the connector authentication environment-reference contract instead of adapter headers or query parameters.

## First source-specific adapter

The framework is designed so provider-specific implementations such as Internet Archive/Wayback can declare capabilities and normalization without modifying the core connector engine.
