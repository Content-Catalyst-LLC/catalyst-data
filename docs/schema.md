# Schema Guide

Catalyst Data has two complementary schemas.

## Canonical record schema

`schemas/catalyst_data_record_1_0.schema.json` governs records exchanged between applications. It uses strict objects, complete provenance fields, stable identifiers, structured review and method metadata, and namespaced extensions.

The same schema is packaged at `python/catalyst_data/schemas/` for installed Python validation. Both copies are generated from `contracts/record_contract.json` and must remain byte-identical.

## Relational SQLite schema

`schema.sql` provides the local normalized storage demonstration centered on measurements. Core tables include entities, indicators, periods, sources, measurements, notes, and tags. Review views include `measurement_review`, `provenance_gaps`, and `low_confidence_measurements`.

The relational schema remains a local prototype in v1.1.0. Database migrations and a persistent repository service are scheduled for v1.2.0.
