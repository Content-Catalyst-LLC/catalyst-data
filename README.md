# Catalyst Data

Catalyst Data is the canonical evidence and measurement record layer for Sustainable Catalyst. It connects entities, indicators, periods, measurements, sources, confidence, review judgments, and method limitations in a versioned structure that can move safely between applications.

## Current release

**v1.1.0 — Canonical Data Contract and Validation Engine**

The release introduces `catalyst-data-record/1.0`: a strict, versioned JSON contract with stable identifiers, timestamps, producer metadata, complete source provenance, structured uncertainty, and explicit extension rules.

## Canonical record

Every canonical record contains:

- `$schema` and `schema_version`
- stable `record_id`
- record type, creation time, update time, and producer
- identified entity, indicator, and period
- baseline, current value, and derived percentage change
- source URL, publisher, license, retrieval time, citation, checksum, and access notes
- confidence score and basis
- review readiness and signal status
- method notes, assumptions, limitations, uncertainty, and quality flags
- namespaced extensions

Unknown core fields are rejected. Extensions must use a namespaced key such as `org.sustainablecatalyst.project`.

## Repository contents

- `contracts/record_contract.json` — canonical enums, ID rules, and extension policy.
- `contracts/review_contract.json` — canonical confidence and signal rules.
- `schemas/catalyst_data_record_1_0.schema.json` — normative JSON Schema.
- `python/catalyst_data/` — validation, conversion, typed mappings, and brief generation.
- `examples/sample_project.json` — v1.0-style authoring input upgraded during build.
- `examples/sample_legacy_v1_0_record.json` — legacy browser export fixture.
- `outputs/sample_export.json` — canonical validated export.
- `wordpress/catalyst-data-demo/` — browser demo that emits the canonical record.
- `scripts/` — contract generation, deterministic packaging, smoke tests, and release checks.

## Python quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .

catalyst-data brief examples/sample_project.json outputs/generated_brief.md
catalyst-data validate outputs/generated_brief.json
catalyst-data upgrade examples/sample_legacy_v1_0_record.json outputs/upgraded_legacy_record.json
pytest
```

The v1.0.x two-argument brief command remains supported:

```bash
catalyst-data-brief examples/sample_project.json outputs/generated_brief.md
```

## Python API

```python
from catalyst_data import build_record, convert_legacy_record, validate_record

record = build_record(authoring_payload)
validate_record(record)
upgraded = convert_legacy_record(legacy_export)
```

`validate_record` checks the JSON Schema and record formats. `validate_record_semantics` additionally verifies percent change, review readiness, and signal status against their source fields; `build_record` applies both.

## WordPress demo

Install `dist/catalyst-data-demo.zip`, activate it, and add:

```text
[catalyst_data_demo]
```

The demo is local to the browser. It does not send records to a server.

## Build and validation

```bash
python3 scripts/build_release.py
python3 scripts/check_release.py
```

The release suite checks generated contracts, schema parity, canonical exports, legacy upgrades, SQL review logic, Python tests, browser parity, PHP and JavaScript syntax, package contents, and deterministic ZIP reproduction.

## Method path

```text
entity → indicator → period → measurement → source → confidence → review
```

## Boundary

Catalyst Data validates structure, provenance fields, and derived contract logic. It does not certify source truth, regulatory compliance, impact, or professional conclusions.

## License

MIT — see `LICENSE`.
