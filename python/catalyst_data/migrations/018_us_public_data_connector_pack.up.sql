CREATE TABLE census_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    dataset TEXT NOT NULL,
    year INTEGER NOT NULL,
    geography_id TEXT NOT NULL,
    geography_name TEXT,
    geography_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(geography_json)),
    variable_code TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(dataset,year,geography_json,variable_code)
);
CREATE INDEX idx_census_observations_lookup ON census_observations(dataset,variable_code,year DESC);
CREATE INDEX idx_census_observations_geography ON census_observations(geography_id,year DESC);

CREATE TABLE bls_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL UNIQUE,
    title TEXT,
    survey_name TEXT,
    survey_abbreviation TEXT,
    seasonality TEXT,
    catalog_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(catalog_json)),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE bls_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    series_id TEXT NOT NULL,
    year TEXT NOT NULL,
    period TEXT NOT NULL,
    period_name TEXT,
    value_numeric REAL,
    value_text TEXT,
    latest INTEGER NOT NULL DEFAULT 0 CHECK(latest IN (0,1)),
    footnotes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(footnotes_json)),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(series_id,year,period)
);
CREATE INDEX idx_bls_observations_lookup ON bls_observations(series_id,year DESC,period DESC);

CREATE TABLE bea_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    dataset TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    metric_name TEXT,
    geography_id TEXT NOT NULL,
    geography_name TEXT,
    period TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    unit_multiplier INTEGER,
    dimensions_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(dimensions_json)),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(dataset,metric_code,geography_id,period,dimensions_json)
);
CREATE INDEX idx_bea_observations_lookup ON bea_observations(dataset,metric_code,period DESC);
CREATE INDEX idx_bea_observations_geography ON bea_observations(geography_id,period DESC);

CREATE TABLE eia_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    route TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    period TEXT NOT NULL,
    geography_id TEXT,
    geography_name TEXT,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    dimensions_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(dimensions_json)),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(route,metric_code,period,dimensions_json)
);
CREATE INDEX idx_eia_observations_lookup ON eia_observations(route,metric_code,period DESC);
CREATE INDEX idx_eia_observations_geography ON eia_observations(geography_id,period DESC);

CREATE TABLE epa_envirofacts_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    table_name TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(filters_json)),
    record_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(record_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_epa_envirofacts_table ON epa_envirofacts_records(table_name,id DESC);

CREATE TABLE usgs_water_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    collection_name TEXT NOT NULL,
    feature_id TEXT NOT NULL,
    monitoring_location_id TEXT,
    parameter_code TEXT,
    statistic_id TEXT,
    period TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    qualifier_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(qualifier_json)),
    geometry_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(geometry_json)),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(collection_name,feature_id)
);
CREATE INDEX idx_usgs_water_lookup ON usgs_water_observations(monitoring_location_id,parameter_code,period DESC);
CREATE INDEX idx_usgs_water_collection ON usgs_water_observations(collection_name,period DESC);

CREATE TABLE us_public_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL CHECK(provider IN ('census','bls','bea','eia','epa','usgs')),
    resource_type TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_json)),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK(result_count >= 0),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256)=64),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_us_public_fetches_provider ON us_public_fetches(provider,resource_type,id DESC);
CREATE TRIGGER us_public_fetches_immutable_update
BEFORE UPDATE ON us_public_fetches BEGIN SELECT RAISE(ABORT, 'U.S. public data fetch history is immutable'); END;
CREATE TRIGGER us_public_fetches_immutable_delete
BEFORE DELETE ON us_public_fetches BEGIN SELECT RAISE(ABORT, 'U.S. public data fetch history is immutable'); END;

CREATE VIEW us_public_observations AS
SELECT 'census' AS provider, observation_id, dataset AS dataset_or_route, geography_id, geography_name,
       variable_code AS metric_code, NULL AS metric_name, CAST(year AS TEXT) AS period,
       value_numeric, value_text, NULL AS unit, source_uri, fetched_at
FROM census_observations
UNION ALL
SELECT 'bls', bo.observation_id, bs.survey_abbreviation, NULL, NULL,
       bo.series_id, bs.title, bo.year || '-' || bo.period,
       bo.value_numeric, bo.value_text, NULL, bo.source_uri, bo.fetched_at
FROM bls_observations bo LEFT JOIN bls_series bs ON bs.series_id=bo.series_id
UNION ALL
SELECT 'bea', observation_id, dataset, geography_id, geography_name,
       metric_code, metric_name, period, value_numeric, value_text, unit, source_uri, fetched_at
FROM bea_observations
UNION ALL
SELECT 'eia', observation_id, route, geography_id, geography_name,
       metric_code, NULL, period, value_numeric, value_text, unit, source_uri, fetched_at
FROM eia_observations
UNION ALL
SELECT 'usgs', observation_id, collection_name, monitoring_location_id, monitoring_location_id,
       parameter_code, statistic_id, period, value_numeric, value_text, unit, source_uri, fetched_at
FROM usgs_water_observations;

CREATE VIEW us_public_data_status AS
SELECT
    (SELECT COUNT(*) FROM census_observations) AS census_observation_count,
    (SELECT COUNT(*) FROM bls_series) AS bls_series_count,
    (SELECT COUNT(*) FROM bls_observations) AS bls_observation_count,
    (SELECT COUNT(*) FROM bea_observations) AS bea_observation_count,
    (SELECT COUNT(*) FROM eia_observations) AS eia_observation_count,
    (SELECT COUNT(*) FROM epa_envirofacts_records) AS epa_record_count,
    (SELECT COUNT(*) FROM usgs_water_observations) AS usgs_observation_count,
    (SELECT MAX(fetched_at) FROM us_public_fetches WHERE provider='census') AS latest_census_fetch_at,
    (SELECT MAX(fetched_at) FROM us_public_fetches WHERE provider='bls') AS latest_bls_fetch_at,
    (SELECT MAX(fetched_at) FROM us_public_fetches WHERE provider='bea') AS latest_bea_fetch_at,
    (SELECT MAX(fetched_at) FROM us_public_fetches WHERE provider='eia') AS latest_eia_fetch_at,
    (SELECT MAX(fetched_at) FROM us_public_fetches WHERE provider='epa') AS latest_epa_fetch_at,
    (SELECT MAX(fetched_at) FROM us_public_fetches WHERE provider='usgs') AS latest_usgs_fetch_at;

UPDATE platform_components
SET current_version='2.5.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
