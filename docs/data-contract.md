# Canonical Data Contract

`catalyst-data-record/1.0` is the normative Catalyst Data record shape introduced in v1.1.0.

The JSON Schema in `schemas/catalyst_data_record_1_0.schema.json` is authoritative for structure. Cross-field semantic rules are enforced by `catalyst_data.engine.validate_record_semantics`:

- `measurement.percent_change` must match baseline and current values.
- `review.status` must match source availability and confidence.
- `review.signal_status` must match percent change and indicator direction.
- `updated_at` cannot precede `created_at`.
- a period end date cannot precede its start date.

Canonical records are not auto-repaired. Convert old records first, then validate the resulting canonical output.
