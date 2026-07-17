# Import Pipeline

The v2.0.0 import pipeline accepts JSON and CSV files.

## JSON forms

Supported JSON input may be:

- one canonical or authoring record;
- an array of records; or
- an object containing a `records` array.

## CSV form

CSV imports use flattened fields such as `entity_name`, `indicator_name`, `period_label`, `current`, `source_name`, and `confidence`. Optional provenance, method, quality, stable ID, and timestamp fields are supported. See `examples/imports/measurements.csv`.

## Safety modes

```bash
catalyst-data import data.sqlite3 records.json --dry-run
catalyst-data import data.sqlite3 records.json
catalyst-data import data.sqlite3 records.csv --non-atomic --continue-on-error
```

- Dry runs execute validation and database writes inside a transaction and then roll everything back.
- Atomic imports roll back all records when any row fails.
- Non-atomic imports commit valid rows and preserve row-level error reports.
- Re-importing an unchanged file skips records with matching stable IDs and payload checksums.

## Observation lineage

JSON records may include `observation_lineage`. CSV rows may include a complete `observation_lineage_json` object. When absent, the canonical builder creates a conservative default lineage from the record entity, indicator, source, period, method, baseline, and current value.
