# Migrating v1.0.x Records

Catalyst Data v1.0.x used an unversioned, flat export. v1.1.0 upgrades that shape into `catalyst-data-record/1.0`.

```bash
catalyst-data upgrade legacy.json canonical.json
catalyst-data validate canonical.json
```

The converter:

- creates stable semantic IDs;
- wraps confidence and review metadata;
- expands source provenance fields with explicit `null` values when unavailable;
- converts method notes into the structured method section;
- recalculates percent change and review/signal statuses;
- assigns migration producer metadata and timestamps.

Legacy derived fields are not trusted. They are recalculated from their source values.
