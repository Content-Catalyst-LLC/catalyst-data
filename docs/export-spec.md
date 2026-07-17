# Export Specification

Catalyst Data v1.4.0 supports repository exports in JSON and CSV.

## JSON repository export

The JSON export envelope contains:

- `schema_version`: `catalyst-data-export/1.0`
- `record_count`
- `records`: complete `catalyst-data-record/1.0` objects

```bash
catalyst-data export catalyst-data.sqlite3 export.json
```

## CSV repository export

CSV exports flatten the canonical records while preserving stable IDs, provenance, confidence, review status, method fields, and timestamps.

```bash
catalyst-data export catalyst-data.sqlite3 export.csv --format csv
```

The complete canonical JSON record remains authoritative when a flattened CSV cannot preserve nested extension metadata.
