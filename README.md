# Catalyst Data

Catalyst Data is the shared SQL and evidence layer for Sustainable Catalyst. It connects entities, indicators, sources, periods, measurements, confidence levels, method notes, and review states so sustainability and systems work can remain traceable over time.

The module is designed for auditable work: what was measured, where it came from, when it applied, how confident the record is, what direction the result indicates, and what assumptions still need review.

## Current release

**v1.0.1 — Repository Integrity and Package Contract Repair**

This release establishes one reproducible package and review contract across SQLite, Python, JSON, JavaScript, and the WordPress demo.

## Repository contents

- `VERSION` — canonical repository version.
- `contracts/review_contract.json` — canonical evidence-readiness and signal contract.
- `schema.sql` — SQLite schema and generated review views.
- `queries.sql` — sample seed data and example review queries.
- `python/catalyst_data/` — installable Python package and brief generator.
- `data/` — sample CSV inputs.
- `examples/` — sample project-level JSON input.
- `outputs/` — generated JSON and Markdown examples.
- `schemas/` — JSON Schema for Catalyst Data exports.
- `wordpress/catalyst-data-demo/` — committed WordPress shortcode source.
- `dist/catalyst-data-demo.zip` — deterministic WordPress plugin distribution.
- `scripts/` — contract synchronization, release building, and release validation.
- `release/` — release-specific implementation notes.
- `docs/` — methodology, schema, provenance, export, review, and WordPress documentation.
- `tests/` — Python, SQL, package, and cross-runtime contract tests.

## Canonical review model

Catalyst Data keeps two judgments separate:

- `review_status` describes whether the evidence is ready for review: `missing source`, `needs evidence`, `reviewable with caution`, or `reviewable`.
- `signal_status` describes measurement direction: `improving`, `declining`, `unchanged`, `descriptive`, or `indeterminate`.

A measurement can therefore be improving while still needing evidence. Direction never overrides weak provenance.

A zero baseline does not produce a meaningful percentage change. In that case, `percent_change` is `null` and `signal_status` is `indeterminate`.

## WordPress demo

Install `dist/catalyst-data-demo.zip` and add:

```text
[catalyst_data_demo]
```

The demo is browser-based. It does not send records to a server. It creates a structured evidence record that can be copied or downloaded as JSON.

## Quick start: SQLite

```bash
sqlite3 catalyst_data.db < schema.sql
sqlite3 catalyst_data.db < queries.sql
sqlite3 catalyst_data.db "SELECT * FROM measurement_review;"
```

## Quick start: Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
catalyst-data-brief examples/sample_project.json outputs/generated_brief.md
pytest
```

The compatibility script remains available:

```bash
python3 python/generate_data_brief.py examples/sample_project.json outputs/generated_brief.md
```

## Build and validation

```bash
python3 scripts/build_release.py
python3 scripts/check_release.py
```

`build_release.py` synchronizes generated contract artifacts, regenerates examples, and creates a deterministic WordPress ZIP. `check_release.py` verifies version alignment, JSON exports, SQLite views, Python tests, browser parity, PHP and JavaScript syntax, and distribution contents.

## Method path

```text
entity → indicator → period → measurement → source → confidence → review
```

## Boundary

Catalyst Data is an open-source data and provenance layer. It does not certify compliance, verify impact, guarantee outcomes, or replace qualified professional review.

## License

MIT — see `LICENSE`.
