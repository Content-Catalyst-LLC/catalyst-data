# Public API, Embeds, and Platform Handoffs

Catalyst Data v1.8.0 adds a dependency-light HTTP layer without making remote operation mandatory. The SQLite repository and CLI remain fully usable offline.

## Public read boundary

Only records with an approved review state and an `external` publication gate are returned by `GET /v1/records`. The public projection removes reviewer assignments and decisions, retains only public review comments, clears source access notes, excludes restricted datasets, and removes raw observation payloads.

## Protected writes

`POST /v1/records` requires a bearer token with `records:write`. `POST /v1/handoffs` requires `handoffs:write`. Tokens are generated locally, stored only as SHA-256 digests, individually scoped, auditable, and revocable.

```bash
catalyst-data api-key-create catalyst-data.sqlite3 "Decision Studio" \
  --scope records:write --scope handoffs:write
catalyst-data serve catalyst-data.sqlite3 --host 127.0.0.1 --port 8765
```

## API surfaces

- `GET /health`
- `GET /v1/capabilities`
- `GET /v1/records`
- `GET /v1/records/{record_id}`
- `POST /v1/records`
- `POST /v1/handoffs`
- `GET /v1/openapi.json`

The static OpenAPI 3.1 document is stored at `openapi/catalyst-data-openapi.json`.

## Typed handoffs

`catalyst-data-handoff/1.0` exchanges checksum-bound record references with Knowledge Library, Research Librarian, Site Intelligence, Workbench, Research Lab, Catalyst Analytics R, Catalyst Canvas, Decision Studio, and Platform Core. Platform Core is a supported target, not a runtime dependency.

```bash
catalyst-data handoff-create catalyst-data.sqlite3 handoff.json RECORD_ID \
  --target decision-studio --capability decision-evidence \
  --api-base-url https://data.example.org
catalyst-data handoff-validate handoff.json
```

## WordPress persistent embed

The browser-only `[catalyst_data_demo]` remains available. Persistent public records can be embedded with:

```text
[catalyst_data_embed api_url="https://data.example.org" limit="12"]
```

The embed never accepts a write token. The API must explicitly allow the WordPress origin with `--allow-origin`.
