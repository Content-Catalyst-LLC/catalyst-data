# Query, Comparison, and Export Studio

Catalyst Data v1.7.0 introduced a local-first analytical layer over the governed repository. It does not bypass canonical validation, provenance, indicator governance, observation lineage, or review controls.

## Saved queries

A query uses `catalyst-data-query/1.0`. Filters cover record, entity, indicator, period, source, framework, evidence status, review state, publication gate, confidence, quality, tags, and text search. Saving a changed definition appends an immutable version while retaining the stable query identity.

## Frozen runs

Every execution stores the exact query definition, definition checksum, selected canonical payloads, record checksums, result checksum, warnings, and completion time. Later repository changes do not alter the historical run.

## Comparisons

Records are grouped by entity and indicator and compared across consecutive periods. Governed indicator and methodology compatibility determine whether the result is equivalent, convertible, limited, or incompatible. Compatible unit conversions are applied before change calculations. Limited and incompatible comparisons remain visible with explicit warnings.

## Export bundles

A bundle contains:

- `manifest.json`
- `records.json`
- `records.csv`
- `comparisons.json`
- `warnings.json`
- `provenance.json`
- `review.json`
- `data-dictionary.json`
- `brief.md`

ZIP metadata and file ordering are deterministic. Rebuilding a bundle from the same immutable run yields the same archive bytes.
