## Repo hygiene

Generated local databases are not the source of truth. Recreate local SQLite files by running:

```bash
sqlite3 catalyst_data.db < schema.sql
sqlite3 catalyst_data.db < queries.sql
```

The durable source files are the schema, seed queries, sample CSVs, JSON examples, docs, tests, and WordPress plugin source.
