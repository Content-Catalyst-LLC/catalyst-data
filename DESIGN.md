# Catalyst Data Design Document

Catalyst Data is the persistent evidence and measurement repository for Sustainable Catalyst.

It exists to answer these practical questions:

1. Which entity and indicator are being measured?
2. Which reporting period and measurement values apply?
3. Which source supports the record, under what license and access conditions?
4. Which method, assumptions, limitations, and uncertainty produced the value?
5. How confident is the record, and why?
6. What evidence-readiness and directional judgments have been derived?
7. Which versioned contract and stable identifiers allow the record to move safely between products?
8. Which repository, migration, and import run stored or changed the record?
9. Which governed indicator, unit, methodology version, framework mapping, and compatibility rules define whether records can be compared?

## Contract architecture

- `contracts/review_contract.json` governs confidence thresholds and directional classification.
- `contracts/record_contract.json` governs record types, enums, ID patterns, provenance vocabulary, quality flags, and extension rules.
- `schemas/catalyst_data_record_1_0.schema.json` is the normative exchange schema.
- `schemas/catalyst_data_indicator_governance_1_0.schema.json` governs indicator definitions, units, methodologies, mappings, and comparability metadata.
- Python and browser artifacts are generated from those contracts.
- Cross-field semantic validation verifies derived percentage change and review judgments.

## Persistence architecture

The canonical JSON payload is the contract source of truth. The SQLite repository stores that payload and its SHA-256 digest in `data_records`, then synchronizes searchable fields into normalized entity, indicator, period, source, and measurement tables.

Stable canonical IDs govern idempotent upserts. Re-importing an unchanged record is a skip; changing the payload while retaining the record ID is an update.

## Migration architecture

Ordered `.up.sql` and `.down.sql` files are packaged with the Python distribution. Versions must be contiguous and are recorded in `schema_migrations`. Fresh repositories always migrate from version 0 to the latest supported schema.

## Import architecture

JSON and CSV imports run through the same canonical record builder and validator. Imports support:

- dry-run rollback;
- atomic all-or-nothing operation;
- non-atomic valid-row commits;
- row-level error reports;
- import-run and record-action ledgers; and
- deterministic file-based timestamps when authoring inputs omit timestamps.

## Indicator governance architecture

Migration 004 separates stable indicator identities from immutable indicator and methodology versions. Unit definitions carry dimensions and canonical conversion bases. Framework mappings preserve external relationships without collapsing distinct indicators. Compatibility rules make comparability explicit and the comparison engine returns equivalent, convertible, limited, or incompatible outcomes.

## Extension boundary

The core schema rejects unknown fields. Product-specific metadata belongs under namespaced `extensions` keys so integrations can add context without mutating the canonical meaning of core fields.

## Scope boundary

v1.4.0 supports local persistence, governed ingestion, governed indicator and methodology registries, unit conversion, explicit comparability, multiple evidence sources per measurement, immutable source and record history, provenance events, and evidence-gap review. Institutional authorization, remote APIs, and scheduled connectors remain later roadmap work.
