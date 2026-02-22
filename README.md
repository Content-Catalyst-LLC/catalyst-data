# Catalyst Data

An open-source SQL data layer for connecting, tracing, and analyzing the Catalyst Suite.

Catalyst Data is the shared relational layer for the Catalyst Suite. It models **entities**, **metrics**, **time periods**, and **provenance** (sources), and provides queryable views for traceable, auditable analysis.

## What’s included

- `schema.sql` — SQLite schema (tables, constraints, indexes, and views)
- `queries.sql` — demo queries (and optional seed data, if included)
- `DESIGN.md` — CS50 SQL design document
- `docs/erd.svg` — ER diagram (rendered)
- `docs/erd.mmd` — ER diagram source (Mermaid)

## Quick start (SQLite)

```bash
sqlite3 catalyst_data.db
.read schema.sql
-- optionally:
-- .read queries.sql
```

## License

MIT — see `LICENSE`.
