## Repo hygiene

This repository intentionally does **not** commit the generated SQLite database file (`*.db`).
Recreate the database locally by running:

```sql
.read schema.sql
```

Optionally load demo queries:

```sql
.read queries.sql
```
