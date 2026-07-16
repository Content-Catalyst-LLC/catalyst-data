# Export Specification

Catalyst Data exports preserve the trace path from entity to review and validate against `schemas/catalyst_data_export.schema.json`.

## v1.0.1 fields

The export contains:

- entity name and type
- indicator name, unit, and direction
- reporting period
- baseline, current value, and percent change
- source name and type
- confidence
- evidence `review_status`
- directional `signal_status`
- method notes
- canonical trace path

`values.percent_change` is `null` when the baseline is zero because a percentage change is mathematically undefined in that case.

`review_status` and `signal_status` must not be conflated. An improving measurement can still be `needs evidence` or `reviewable with caution`.
