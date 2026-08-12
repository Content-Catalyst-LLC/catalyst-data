# Connected Data Graph & Cross-Source Federation

Catalyst Data v3.0.0 adds a rebuildable connected-data layer over the governed caches established in v2.x. The graph is an index and federation surface, not a new acquisition system: provider-native tables, canonical entities, and the dataset catalog remain authoritative.

## Architecture

The graph uses relational tables that work in both SQLite and PostgreSQL:

- `connected_graph_nodes` — stable nodes for canonical entities, datasets, providers, events, and scientific objects.
- `connected_graph_edges` — typed edges with semantic predicate, source namespace, source record, source URI, confidence, evidence, metadata, and active/inactive lifecycle state.
- `connected_graph_edge_events` — immutable added/deactivated edge history.
- `connected_graph_sync_runs` — immutable graph checksums and synchronization counts.
- `connected_graph_status` — operational counts and latest synchronization timestamp.

Stable graph IDs are derived from source namespace and native resource identity. Graph synchronization is deterministic with respect to active nodes and edges; historical change events remain append-only.

## Semantic alignment

Catalyst Data remains a relational application and does not require an RDF database. Its export profile aligns selected graph concepts with established Web vocabularies:

- W3C DCAT 3 `dcat:Dataset` for dataset-catalog nodes.
- W3C PROV-O `prov:Entity` for canonical/scientific resources and `prov:Agent` for data providers.
- Dublin Core Terms `dct:publisher` for dataset/provider edges.
- Catalyst-specific predicates remain under `https://sustainablecatalyst.com/ns/catalyst-data#` when no standard predicate accurately represents the relationship.

The JSON-LD-compatible export is intentionally bounded and descriptive. It does not claim that every provider-native field has been transformed into RDF.

## Graph synchronization

`graph-sync` first rebuilds the local canonical-entity crosswalk and dataset registry, then creates or refreshes graph nodes and edges. It never calls upstream providers.

Current graph families include:

- canonical country/area and Census geography entities;
- dataset catalog entries and provider agents;
- World Bank, UN SDG, and Census entity-to-series anchors with observation counts and temporal evidence;
- JPL small bodies and close-approach events;
- NASA Exoplanet Archive planets and stellar hosts.

Edges are marked inactive when their source-backed relationship disappears from a later synchronization. The change is recorded in the immutable edge event ledger rather than deleting history.

## Cross-source federation

`federate-entity` resolves the provider identifiers attached to a canonical entity and reads cached provider observations without rewriting them. Country/area entities currently federate World Bank and UN SDG observations; Census geography entities federate cached Census observations.

This is intentionally conservative. BEA, EIA, NOAA, ERDDAP, IOOS, and other resources are not attached to a canonical geography simply because labels or codes appear similar. Additional authoritative crosswalks can be added later without changing the graph contract.

## Public API

Cached read endpoints:

- `GET /v1/graph/status`
- `GET /v1/graph/nodes`
- `GET /v1/graph/nodes/{node_id}`
- `GET /v1/graph/neighbors`
- `GET /v1/graph/path`
- `GET /v1/graph/federate`
- `GET /v1/graph/export`

Public requests cannot run `graph-sync`, mutate graph history, acquire provider data, or receive database credentials.

## CLI

```bash
catalyst-data graph-sync catalyst-data.sqlite3
catalyst-data graph-search catalyst-data.sqlite3 --query climate
catalyst-data graph-node catalyst-data.sqlite3 GRAPH_NODE_ID
catalyst-data graph-neighbors catalyst-data.sqlite3 GRAPH_NODE_ID --direction both
catalyst-data graph-path catalyst-data.sqlite3 START_NODE END_NODE --max-depth 4
catalyst-data federate-entity catalyst-data.sqlite3 ENTITY_ID --limit-per-source 100
catalyst-data graph-export catalyst-data.sqlite3 --node-id GRAPH_NODE_ID --limit 500
catalyst-data graph-status catalyst-data.sqlite3
```

## WordPress

`[catalyst_data_graph value="KEN" namespace="iso-alpha3" limit="8"]` renders cached federation results. WordPress remains a public read client of Catalyst Data and never owns provider credentials, PostgreSQL credentials, or graph synchronization.
