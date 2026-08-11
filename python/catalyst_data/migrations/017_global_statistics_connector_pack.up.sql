CREATE TABLE world_bank_countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code TEXT NOT NULL UNIQUE,
    iso2_code TEXT,
    name TEXT NOT NULL,
    region_code TEXT,
    region_name TEXT,
    income_level_code TEXT,
    income_level_name TEXT,
    lending_type_code TEXT,
    lending_type_name TEXT,
    capital_city TEXT,
    longitude TEXT,
    latitude TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_world_bank_countries_name ON world_bank_countries(name);
CREATE INDEX idx_world_bank_countries_region ON world_bank_countries(region_code,income_level_code);

CREATE TABLE world_bank_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    unit TEXT,
    source_id TEXT,
    source_note TEXT,
    source_organization TEXT,
    topics_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(topics_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_world_bank_indicators_name ON world_bank_indicators(name);
CREATE INDEX idx_world_bank_indicators_source ON world_bank_indicators(source_id);

CREATE TABLE world_bank_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    country_code TEXT NOT NULL,
    country_name TEXT,
    indicator_code TEXT NOT NULL,
    indicator_name TEXT,
    period TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    decimal_places INTEGER,
    obs_status TEXT,
    footnote TEXT,
    source_id TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(country_code,indicator_code,period,source_id)
);
CREATE INDEX idx_world_bank_observations_lookup ON world_bank_observations(country_code,indicator_code,period DESC);
CREATE INDEX idx_world_bank_observations_indicator ON world_bank_observations(indicator_code,period DESC);

CREATE TABLE un_sdg_geoareas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    geo_area_code TEXT NOT NULL UNIQUE,
    geo_area_name TEXT NOT NULL,
    type_code TEXT,
    parent_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_un_sdg_geoareas_name ON un_sdg_geoareas(geo_area_name);

CREATE TABLE un_sdg_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE un_sdg_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_code TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    goal_code TEXT,
    target_code TEXT,
    series_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(series_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_un_sdg_indicators_goal ON un_sdg_indicators(goal_code,target_code);

CREATE TABLE un_sdg_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    indicator_code TEXT,
    series_code TEXT,
    series_description TEXT,
    geo_area_code TEXT,
    geo_area_name TEXT,
    time_period TEXT,
    value_numeric REAL,
    value_text TEXT,
    units TEXT,
    nature_code TEXT,
    dimensions_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(dimensions_json)),
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(series_code,geo_area_code,time_period,dimensions_json,nature_code)
);
CREATE INDEX idx_un_sdg_observations_lookup ON un_sdg_observations(indicator_code,geo_area_code,time_period DESC);
CREATE INDEX idx_un_sdg_observations_series ON un_sdg_observations(series_code,time_period DESC);

CREATE TABLE global_statistics_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL CHECK(provider IN ('world-bank','un-sdg')),
    resource_type TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_json)),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK(result_count >= 0),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256)=64),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_global_statistics_fetches_provider ON global_statistics_fetches(provider,resource_type,id DESC);
CREATE TRIGGER global_statistics_fetches_immutable_update
BEFORE UPDATE ON global_statistics_fetches BEGIN SELECT RAISE(ABORT, 'global statistics fetch history is immutable'); END;
CREATE TRIGGER global_statistics_fetches_immutable_delete
BEFORE DELETE ON global_statistics_fetches BEGIN SELECT RAISE(ABORT, 'global statistics fetch history is immutable'); END;

CREATE VIEW global_statistics_status AS
SELECT
    (SELECT COUNT(*) FROM world_bank_countries) AS world_bank_country_count,
    (SELECT COUNT(*) FROM world_bank_indicators) AS world_bank_indicator_count,
    (SELECT COUNT(*) FROM world_bank_observations) AS world_bank_observation_count,
    (SELECT COUNT(*) FROM un_sdg_geoareas) AS un_sdg_geoarea_count,
    (SELECT COUNT(*) FROM un_sdg_goals) AS un_sdg_goal_count,
    (SELECT COUNT(*) FROM un_sdg_indicators) AS un_sdg_indicator_count,
    (SELECT COUNT(*) FROM un_sdg_observations) AS un_sdg_observation_count,
    (SELECT MAX(fetched_at) FROM global_statistics_fetches WHERE provider='world-bank') AS latest_world_bank_fetch_at,
    (SELECT MAX(fetched_at) FROM global_statistics_fetches WHERE provider='un-sdg') AS latest_un_sdg_fetch_at;

UPDATE platform_components
SET current_version='2.4.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
