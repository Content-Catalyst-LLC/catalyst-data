# Connected Evidence and Measurement Platform

Catalyst Data v2.0.0 is the governed relational backbone for Sustainable Catalyst. It connects records, evidence, methods, observations, review, queries, publication, workspaces, connectors, analyses, and operational history without requiring private database coupling between products.

## Platform contract

`catalyst-data-platform/2.0` describes the running platform rather than replacing `catalyst-data-record/1.0`. A platform manifest contains:

- Runtime and migration versions.
- Repository identity and subsystem counts.
- Registered contract checksums.
- Connected components and their versions.
- Declared capabilities and contracts.
- Supported platform targets and operating boundaries.

## Contract registry

Packaged JSON Schemas are registered by contract ID and SHA-256 checksum. Registrations are immutable. A changed schema is recorded as a new registration rather than rewriting prior history.

## Component registry

Components declare a stable component ID, product code, type, version, endpoint, capabilities, contracts, and metadata. Version registrations are immutable. The current component record may change status or endpoint while historical component versions remain unchanged.

## Capability graph

Platform links describe governed relationships between components, including typed handoffs, APIs, data sources, analysis, publication, embeds, and federation. Links do not grant access by themselves; workspace roles, API scopes, review gates, and publication rules still apply.

## Release snapshots

A platform snapshot freezes the platform manifest and binds it to a SHA-256 checksum. Snapshot verification records append-only integrity results. Repeated snapshots of an unchanged platform produce the same snapshot identifier and manifest checksum.

## Integrated readiness

`platform-integrity` checks database integrity, foreign keys, migration currency, core component identity, contract registration, and record-access coverage. `platform-readiness` combines those checks with backup, offline, benchmark, security, and attestation readiness from the operational layer.

## Local-first boundary

Catalyst Data remains usable with SQLite and the command line alone. Platform Core and remote product endpoints are optional. Registry status describes integration readiness; it does not certify truth, legal compliance, or professional suitability.
