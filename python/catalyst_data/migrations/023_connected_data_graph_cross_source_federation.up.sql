CREATE TABLE connected_graph_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    node_type TEXT NOT NULL,
    semantic_type TEXT,
    resource_namespace TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    canonical_entity_id TEXT REFERENCES canonical_entities(entity_id),
    label TEXT NOT NULL,
    provider TEXT,
    source_uri TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(resource_namespace,resource_id)
);
CREATE INDEX idx_connected_graph_nodes_lookup ON connected_graph_nodes(status,node_type,provider,label);
CREATE INDEX idx_connected_graph_nodes_entity ON connected_graph_nodes(canonical_entity_id,status);

CREATE TABLE connected_graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id TEXT NOT NULL UNIQUE,
    subject_node_id TEXT NOT NULL REFERENCES connected_graph_nodes(node_id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,
    semantic_predicate TEXT,
    object_node_id TEXT NOT NULL REFERENCES connected_graph_nodes(node_id) ON DELETE CASCADE,
    source_namespace TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_uri TEXT,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    evidence_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_connected_graph_edges_subject ON connected_graph_edges(status,subject_node_id,predicate);
CREATE INDEX idx_connected_graph_edges_object ON connected_graph_edges(status,object_node_id,predicate);
CREATE INDEX idx_connected_graph_edges_source ON connected_graph_edges(source_namespace,source_record_id);

CREATE TABLE connected_graph_edge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    edge_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('added','deactivated')),
    actor TEXT NOT NULL,
    event_at TEXT NOT NULL
);
CREATE TRIGGER connected_graph_edge_events_immutable_update BEFORE UPDATE ON connected_graph_edge_events BEGIN SELECT RAISE(ABORT, 'Connected graph edge history is immutable'); END;
CREATE TRIGGER connected_graph_edge_events_immutable_delete BEFORE DELETE ON connected_graph_edge_events BEGIN SELECT RAISE(ABORT, 'Connected graph edge history is immutable'); END;

CREATE TABLE connected_graph_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id TEXT NOT NULL UNIQUE,
    node_count INTEGER NOT NULL CHECK(node_count >= 0),
    edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
    added_edge_count INTEGER NOT NULL DEFAULT 0 CHECK(added_edge_count >= 0),
    deactivated_edge_count INTEGER NOT NULL DEFAULT 0 CHECK(deactivated_edge_count >= 0),
    graph_sha256 TEXT NOT NULL CHECK(length(graph_sha256)=64),
    synced_at TEXT NOT NULL
);
CREATE TRIGGER connected_graph_sync_runs_immutable_update BEFORE UPDATE ON connected_graph_sync_runs BEGIN SELECT RAISE(ABORT, 'Connected graph sync history is immutable'); END;
CREATE TRIGGER connected_graph_sync_runs_immutable_delete BEFORE DELETE ON connected_graph_sync_runs BEGIN SELECT RAISE(ABORT, 'Connected graph sync history is immutable'); END;

CREATE VIEW connected_graph_status AS
SELECT
  (SELECT COUNT(*) FROM connected_graph_nodes WHERE status='active') AS active_node_count,
  (SELECT COUNT(*) FROM connected_graph_edges WHERE status='active') AS active_edge_count,
  (SELECT COUNT(DISTINCT node_type) FROM connected_graph_nodes WHERE status='active') AS node_type_count,
  (SELECT COUNT(DISTINCT provider) FROM connected_graph_nodes WHERE status='active' AND provider IS NOT NULL) AS provider_count,
  (SELECT COUNT(*) FROM connected_graph_nodes WHERE status='active' AND canonical_entity_id IS NOT NULL) AS canonical_entity_node_count,
  (SELECT COUNT(*) FROM connected_graph_nodes WHERE status='active' AND node_type='dataset') AS dataset_node_count,
  (SELECT COUNT(*) FROM connected_graph_nodes WHERE status='active' AND node_type IN ('scientific-object','stellar-object','astronomical-body')) AS scientific_object_node_count,
  (SELECT COUNT(*) FROM connected_graph_edge_events) AS edge_event_count,
  (SELECT MAX(synced_at) FROM connected_graph_sync_runs) AS latest_sync_at;

UPDATE platform_components SET current_version='3.0.0', capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","nasa-donki-space-weather","jpl-small-body-database","jpl-close-approaches","nasa-exoplanet-archive","space-science-network","dataset-catalog","dataset-registry","cross-provider-discovery","freshness-index","canonical-entities","identifier-resolution","iso-country-identifiers","un-m49-identifiers","provider-crosswalks","connected-data-graph","typed-graph-edges","cross-source-federation","graph-path-query","jsonld-graph-export","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]', updated_at=datetime('now') WHERE component_id='component:catalyst-data';
