# Export Specification

Catalyst Data v1.1.0 exports the canonical `catalyst-data-record/1.0` shape and validates it against `schemas/catalyst_data_record_1_0.schema.json`.

## Required record sections

- schema identity, stable record ID, record type, timestamps, and producer metadata
- identified entity, indicator, and reporting period
- baseline, current value, and derived percentage change
- source name, type, URL, publisher, license, retrieval time, citation, checksum, and access notes
- confidence score, scale, and basis
- evidence-readiness status, directional signal, and reviewer notes
- method notes, assumptions, limitations, uncertainty, and quality flags
- namespaced extensions

`measurement.percent_change` is `null` when the baseline is missing or zero because a percentage change is undefined in those cases.

The compatibility file `schemas/catalyst_data_export.schema.json` describes the same canonical record shape. New integrations should use the record schema filename directly.

Review readiness and signal direction remain separate. An improving measurement can still have missing evidence or require caution.
