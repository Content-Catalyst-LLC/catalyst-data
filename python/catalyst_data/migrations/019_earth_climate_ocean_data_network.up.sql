CREATE TABLE earth_climate_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL CHECK(provider IN ('ncei','erddap')),
    dataset_id TEXT NOT NULL,
    source_native_id TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    period TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    latitude REAL,
    longitude REAL,
    depth REAL,
    station_id TEXT,
    geometry_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(geometry_json)),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider,dataset_id,source_native_id,metric_code,period)
);
CREATE INDEX idx_earth_climate_observations_lookup ON earth_climate_observations(provider,dataset_id,metric_code,period DESC);
CREATE INDEX idx_earth_climate_observations_station ON earth_climate_observations(station_id,period DESC);
CREATE INDEX idx_earth_climate_observations_location ON earth_climate_observations(latitude,longitude,period DESC);

CREATE TABLE erddap_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_key TEXT NOT NULL UNIQUE,
    server_url TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    title TEXT NOT NULL,
    institution TEXT,
    service_kind TEXT NOT NULL DEFAULT 'unknown',
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(server_url,dataset_id)
);
CREATE INDEX idx_erddap_datasets_server ON erddap_datasets(server_url,title);

CREATE TABLE ioos_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL UNIQUE,
    name TEXT,
    title TEXT,
    organization TEXT,
    notes TEXT,
    resources_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(resources_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_ioos_datasets_title ON ioos_datasets(title,name);

CREATE TABLE usgs_earthquakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_time TEXT NOT NULL,
    updated_time TEXT,
    magnitude REAL,
    magnitude_type TEXT,
    place TEXT,
    status TEXT,
    tsunami INTEGER NOT NULL DEFAULT 0 CHECK(tsunami IN (0,1)),
    significance INTEGER NOT NULL DEFAULT 0,
    alert TEXT,
    latitude REAL,
    longitude REAL,
    depth_km REAL,
    geometry_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(geometry_json)),
    properties_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(properties_json)),
    detail_uri TEXT,
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_usgs_earthquakes_time ON usgs_earthquakes(event_time DESC);
CREATE INDEX idx_usgs_earthquakes_magnitude ON usgs_earthquakes(magnitude DESC,event_time DESC);
CREATE INDEX idx_usgs_earthquakes_location ON usgs_earthquakes(latitude,longitude,event_time DESC);

CREATE TABLE earth_climate_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL CHECK(provider IN ('ncei','erddap','ioos','usgs-earthquake')),
    resource_type TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_json)),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK(result_count >= 0),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256)=64),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_earth_climate_fetches_provider ON earth_climate_fetches(provider,resource_type,id DESC);
CREATE TRIGGER earth_climate_fetches_immutable_update BEFORE UPDATE ON earth_climate_fetches BEGIN SELECT RAISE(ABORT, 'Earth/climate/ocean fetch history is immutable'); END;
CREATE TRIGGER earth_climate_fetches_immutable_delete BEFORE DELETE ON earth_climate_fetches BEGIN SELECT RAISE(ABORT, 'Earth/climate/ocean fetch history is immutable'); END;

CREATE VIEW earth_climate_ocean_status AS
SELECT
    (SELECT COUNT(*) FROM earth_climate_observations WHERE provider='ncei') AS ncei_observation_count,
    (SELECT COUNT(*) FROM earth_climate_observations WHERE provider='erddap') AS erddap_observation_count,
    (SELECT COUNT(*) FROM erddap_datasets) AS erddap_dataset_count,
    (SELECT COUNT(*) FROM ioos_datasets) AS ioos_dataset_count,
    (SELECT COUNT(*) FROM usgs_earthquakes) AS usgs_earthquake_count,
    (SELECT MAX(fetched_at) FROM earth_climate_fetches WHERE provider='ncei') AS latest_ncei_fetch_at,
    (SELECT MAX(fetched_at) FROM earth_climate_fetches WHERE provider='erddap') AS latest_erddap_fetch_at,
    (SELECT MAX(fetched_at) FROM earth_climate_fetches WHERE provider='ioos') AS latest_ioos_fetch_at,
    (SELECT MAX(fetched_at) FROM earth_climate_fetches WHERE provider='usgs-earthquake') AS latest_usgs_earthquake_fetch_at;

UPDATE platform_components
SET current_version='2.6.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
