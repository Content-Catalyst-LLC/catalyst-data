# Persistent Repository

Catalyst Data v1.11.0 uses SQLite as its zero-cost local repository. The Python service applies ordered migrations from `python/catalyst_data/migrations` and stores each canonical record in two synchronized forms:

1. normalized entity, indicator, period, source, and measurement tables; and
2. the complete validated canonical JSON payload in `data_records`.

The complete payload remains the contract source of truth. The normalized tables provide efficient review and relational queries.

## Initialize

```bash
catalyst-data init catalyst-data.sqlite3
catalyst-data status catalyst-data.sqlite3
```

## Migration behavior

Every migration has matching `.up.sql` and `.down.sql` files. Migration versions must be contiguous. Applied versions are recorded in `schema_migrations`.

```bash
catalyst-data migrate catalyst-data.sqlite3
catalyst-data rollback catalyst-data.sqlite3 --steps 1
catalyst-data migrate catalyst-data.sqlite3
```

Back up production repositories before rollback. Rollback is intended for controlled development and recovery workflows.
