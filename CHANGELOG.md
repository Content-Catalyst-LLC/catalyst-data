# Changelog

## 1.0.1 — Repository Integrity and Package Contract Repair

- Added `VERSION` as the canonical release version source.
- Added a canonical review contract and generated Python, SQL, and browser artifacts.
- Synchronized confidence thresholds, missing-source behavior, trace paths, and status labels across runtimes.
- Separated evidence readiness (`review_status`) from measurement direction (`signal_status`).
- Corrected zero-baseline percent change to `null` / indeterminate instead of `0`.
- Added basic input validation for confidence, direction, numeric values, and required identifiers.
- Added `pyproject.toml`, installable package metadata, and the `catalyst-data-brief` CLI.
- Added deterministic WordPress ZIP generation from committed source.
- Added release-contract, SQL parity, browser parity, JSON Schema, syntax, and package-content checks.
- Added unique WordPress field IDs for multiple shortcode instances.
- Expanded CI and release documentation.

## 1.0.0 — Catalyst Data demo and repository upgrade

- Added WordPress shortcode plugin: `[catalyst_data_demo]`.
- Added browser-based Catalyst Data demo for traceable measurement records.
- Added Python Catalyst Data brief generator.
- Added JSON schema for structured exports.
- Added sample data, examples, and outputs.
- Added methodology, provenance, schema, export, review, and WordPress plugin docs.
- Added pytest tests and GitHub Actions workflow.
- Updated SQL schema and queries to align with Sustainable Catalyst methodology.
