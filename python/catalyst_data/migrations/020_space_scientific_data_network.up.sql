CREATE TABLE nasa_space_weather_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    source_native_id TEXT NOT NULL,
    event_time TEXT,
    end_time TEXT,
    title TEXT,
    status TEXT,
    location TEXT,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(event_type,source_native_id)
);
CREATE INDEX idx_nasa_space_weather_events_type_time ON nasa_space_weather_events(event_type,event_time DESC);

CREATE TABLE jpl_small_bodies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id TEXT NOT NULL UNIQUE,
    spkid TEXT,
    designation TEXT,
    full_name TEXT,
    name TEXT,
    kind TEXT,
    orbit_class TEXT,
    is_neo INTEGER NOT NULL DEFAULT 0 CHECK(is_neo IN (0,1)),
    is_pha INTEGER NOT NULL DEFAULT 0 CHECK(is_pha IN (0,1)),
    absolute_magnitude REAL,
    diameter_km REAL,
    semimajor_axis_au REAL,
    eccentricity REAL,
    inclination_deg REAL,
    moid_au REAL,
    epoch TEXT,
    orbit_id TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_jpl_small_bodies_spkid ON jpl_small_bodies(spkid) WHERE spkid IS NOT NULL;
CREATE INDEX idx_jpl_small_bodies_lookup ON jpl_small_bodies(is_neo,is_pha,orbit_class,name,designation);

CREATE TABLE jpl_close_approaches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    approach_id TEXT NOT NULL UNIQUE,
    designation TEXT NOT NULL,
    full_name TEXT,
    orbit_id TEXT,
    close_approach_time TEXT NOT NULL,
    julian_date TEXT,
    body TEXT NOT NULL,
    distance_au REAL,
    distance_min_au REAL,
    distance_max_au REAL,
    relative_velocity_km_s REAL,
    infinity_velocity_km_s REAL,
    time_uncertainty TEXT,
    absolute_magnitude REAL,
    diameter_km REAL,
    diameter_sigma_km REAL,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_jpl_close_approaches_time ON jpl_close_approaches(close_approach_time,body);
CREATE INDEX idx_jpl_close_approaches_distance ON jpl_close_approaches(distance_au,close_approach_time);

CREATE TABLE nasa_exoplanets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exoplanet_id TEXT NOT NULL UNIQUE,
    table_name TEXT NOT NULL,
    planet_name TEXT NOT NULL,
    host_name TEXT,
    discovery_method TEXT,
    discovery_year INTEGER,
    orbital_period_days REAL,
    radius_earth REAL,
    mass_earth REAL,
    stellar_temperature_k REAL,
    stellar_radius_solar REAL,
    distance_pc REAL,
    ra_deg REAL,
    dec_deg REAL,
    raw_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(raw_json)),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_nasa_exoplanets_name ON nasa_exoplanets(planet_name,host_name);
CREATE INDEX idx_nasa_exoplanets_discovery ON nasa_exoplanets(discovery_method,discovery_year);
CREATE INDEX idx_nasa_exoplanets_radius ON nasa_exoplanets(radius_earth);

CREATE TABLE space_science_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL CHECK(provider IN ('nasa-donki','jpl-sbdb','jpl-cneos','nasa-exoplanet-archive')),
    resource_type TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_json)),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK(result_count >= 0),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256)=64),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_space_science_fetches_provider ON space_science_fetches(provider,resource_type,id DESC);
CREATE TRIGGER space_science_fetches_immutable_update BEFORE UPDATE ON space_science_fetches BEGIN SELECT RAISE(ABORT, 'Space/science fetch history is immutable'); END;
CREATE TRIGGER space_science_fetches_immutable_delete BEFORE DELETE ON space_science_fetches BEGIN SELECT RAISE(ABORT, 'Space/science fetch history is immutable'); END;

CREATE VIEW space_science_status AS
SELECT
    (SELECT COUNT(*) FROM nasa_space_weather_events) AS nasa_space_weather_event_count,
    (SELECT COUNT(*) FROM jpl_small_bodies) AS jpl_small_body_count,
    (SELECT COUNT(*) FROM jpl_small_bodies WHERE is_neo=1) AS jpl_neo_count,
    (SELECT COUNT(*) FROM jpl_small_bodies WHERE is_pha=1) AS jpl_pha_count,
    (SELECT COUNT(*) FROM jpl_close_approaches) AS jpl_close_approach_count,
    (SELECT COUNT(*) FROM nasa_exoplanets) AS nasa_exoplanet_count,
    (SELECT MAX(fetched_at) FROM space_science_fetches WHERE provider='nasa-donki') AS latest_nasa_donki_fetch_at,
    (SELECT MAX(fetched_at) FROM space_science_fetches WHERE provider='jpl-sbdb') AS latest_jpl_sbdb_fetch_at,
    (SELECT MAX(fetched_at) FROM space_science_fetches WHERE provider='jpl-cneos') AS latest_jpl_cneos_fetch_at,
    (SELECT MAX(fetched_at) FROM space_science_fetches WHERE provider='nasa-exoplanet-archive') AS latest_exoplanet_fetch_at;

UPDATE platform_components
SET current_version='2.7.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","world-bank-statistics","un-sdg-statistics","global-statistics-catalog","us-census-data","us-bls-data","us-bea-data","us-eia-data","us-epa-envirofacts","us-usgs-water-data","us-public-data-catalog","noaa-ncei-climate-data","erddap-dataset-catalog","erddap-ocean-observations","ioos-data-catalog","usgs-earthquake-events","earth-climate-ocean-network","nasa-donki-space-weather","jpl-small-body-database","jpl-close-approaches","nasa-exoplanet-archive","space-science-network","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
