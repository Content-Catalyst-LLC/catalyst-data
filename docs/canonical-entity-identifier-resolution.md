# Canonical Entity & Identifier Resolution

Catalyst Data v2.9.0 adds a governed entity layer above provider-native identifiers. Exact identifiers are authoritative; fuzzy similarity never merges entities automatically.

## Country spine

Country/area bootstrap records carry ISO alpha-2, ISO alpha-3, and UN M49 numeric identifiers. The checked-in bootstrap is refreshable and records the official ISO and UNSD reference pages.

## Provider crosswalks

World Bank country codes and UN SDG GeoArea codes attach only when they resolve through authoritative ISO/M49 identifiers. Census geographies are represented as provider-local subnational entities beneath the United States rather than guessed into unrelated standards.

## Public boundary

`/v1/entities/*` is read-only and resolves only the local registry. Registry synchronization and resolution-event persistence remain backend operations. WordPress never mutates mappings.
