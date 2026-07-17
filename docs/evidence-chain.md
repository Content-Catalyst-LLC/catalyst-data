# Evidence Chain Contract

Catalyst Data v1.3.0 adds `catalyst-data-evidence-chain/1.0` as an optional, backward-compatible property of `catalyst-data-record/1.0`.

## Structure

An evidence chain contains:

- `sources`: one or more role-bearing source links.
- `relationships`: statements connecting two linked sources.
- `transformations`: documented operations used to derive or combine evidence.
- `gaps`: visible provenance or evidence deficiencies.
- `completeness_score`: a deterministic metadata-completeness score from 0–100.

Every chain must include a `primary` source. Its complete metadata must match the record-level `source` object.

## Evidence roles

- `primary` — the principal evidence used for the measurement.
- `supporting` — evidence that corroborates or supplements the primary source.
- `conflicting` — evidence that materially disagrees with another linked source.
- `derived` — a source produced from another source or transformation.
- `contextual` — background evidence that informs interpretation but does not directly establish the value.

## Source relationships

Supported predicates are:

- `corroborates`
- `conflicts_with`
- `derived_from`
- `supersedes`
- `duplicates`
- `contextualizes`

Relationships can reference only source IDs already linked to the record.

## Completeness scoring

The score rewards the presence of a primary source, citations, licensing, retrieval timestamps, checksums, method notes, sufficient confidence, additional evidence, and the absence of conflicting evidence. It does not assess whether a claim is true.

## Derived gaps

The engine can identify:

- missing source
- missing citation
- missing license
- missing retrieval date
- missing checksum
- missing method
- low confidence
- conflicting evidence
- restricted source
- stale source

User-supplied gaps may be retained, but derived gaps cannot be omitted from a normalized chain.
