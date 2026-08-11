CREATE TABLE internet_archive_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_identifier TEXT NOT NULL UNIQUE,
    title TEXT,
    mediatype TEXT,
    creator_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(creator_json)),
    item_date TEXT,
    description TEXT,
    collection_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(collection_json)),
    subject_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(subject_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    metadata_sha256 TEXT NOT NULL CHECK(length(metadata_sha256)=64),
    source_uri TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_internet_archive_items_title ON internet_archive_items(title);
CREATE INDEX idx_internet_archive_items_mediatype ON internet_archive_items(mediatype,item_date);

CREATE TABLE internet_archive_item_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id TEXT NOT NULL UNIQUE,
    item_id INTEGER NOT NULL,
    metadata_sha256 TEXT NOT NULL CHECK(length(metadata_sha256)=64),
    files_sha256 TEXT NOT NULL CHECK(length(files_sha256)=64),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    files_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(files_json)),
    fetched_at TEXT NOT NULL,
    UNIQUE(item_id,metadata_sha256,files_sha256),
    FOREIGN KEY(item_id) REFERENCES internet_archive_items(id) ON DELETE CASCADE
);
CREATE INDEX idx_internet_archive_item_versions_item ON internet_archive_item_versions(item_id,id DESC);
CREATE TRIGGER internet_archive_item_versions_immutable_update
BEFORE UPDATE ON internet_archive_item_versions BEGIN SELECT RAISE(ABORT, 'internet archive item versions are immutable'); END;
CREATE TRIGGER internet_archive_item_versions_immutable_delete
BEFORE DELETE ON internet_archive_item_versions BEGIN SELECT RAISE(ABORT, 'internet archive item versions are immutable'); END;

CREATE TABLE internet_archive_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    format TEXT,
    source_kind TEXT,
    size_bytes INTEGER,
    md5 TEXT,
    sha1 TEXT,
    crc32 TEXT,
    mtime TEXT,
    private_flag INTEGER NOT NULL DEFAULT 0 CHECK(private_flag IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    source_uri TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(item_id,file_name),
    FOREIGN KEY(item_id) REFERENCES internet_archive_items(id) ON DELETE CASCADE
);
CREATE INDEX idx_internet_archive_files_format ON internet_archive_files(format);

CREATE TABLE internet_archive_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id TEXT NOT NULL UNIQUE,
    query_text TEXT NOT NULL,
    fields_json TEXT NOT NULL CHECK(json_valid(fields_json)),
    sorts_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(sorts_json)),
    page_number INTEGER NOT NULL CHECK(page_number >= 1),
    row_limit INTEGER NOT NULL CHECK(row_limit BETWEEN 1 AND 1000),
    num_found INTEGER NOT NULL DEFAULT 0 CHECK(num_found >= 0),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256)=64),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_internet_archive_searches_query ON internet_archive_searches(query_text,id DESC);
CREATE TRIGGER internet_archive_searches_immutable_update
BEFORE UPDATE ON internet_archive_searches BEGIN SELECT RAISE(ABORT, 'internet archive searches are immutable'); END;
CREATE TRIGGER internet_archive_searches_immutable_delete
BEFORE DELETE ON internet_archive_searches BEGIN SELECT RAISE(ABORT, 'internet archive searches are immutable'); END;

CREATE TABLE internet_archive_search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK(position >= 1),
    item_identifier TEXT NOT NULL,
    document_json TEXT NOT NULL CHECK(json_valid(document_json)),
    UNIQUE(search_id,position),
    FOREIGN KEY(search_id) REFERENCES internet_archive_searches(id) ON DELETE CASCADE
);
CREATE INDEX idx_internet_archive_search_results_identifier ON internet_archive_search_results(item_identifier);
CREATE TRIGGER internet_archive_search_results_immutable_update
BEFORE UPDATE ON internet_archive_search_results BEGIN SELECT RAISE(ABORT, 'internet archive search results are immutable'); END;
CREATE TRIGGER internet_archive_search_results_immutable_delete
BEFORE DELETE ON internet_archive_search_results BEGIN SELECT RAISE(ABORT, 'internet archive search results are immutable'); END;

CREATE TABLE wayback_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL UNIQUE,
    target_url TEXT NOT NULL,
    query_type TEXT NOT NULL CHECK(query_type IN ('availability','cdx')),
    params_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(params_json)),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256)=64),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK(result_count >= 0),
    source_uri TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_wayback_queries_target ON wayback_queries(target_url,id DESC);
CREATE TRIGGER wayback_queries_immutable_update
BEFORE UPDATE ON wayback_queries BEGIN SELECT RAISE(ABORT, 'wayback queries are immutable'); END;
CREATE TRIGGER wayback_queries_immutable_delete
BEFORE DELETE ON wayback_queries BEGIN SELECT RAISE(ABORT, 'wayback queries are immutable'); END;

CREATE TABLE wayback_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL UNIQUE,
    target_url TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    original_url TEXT NOT NULL,
    mimetype TEXT,
    status_code TEXT,
    digest TEXT,
    length_bytes INTEGER,
    replay_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(target_url,timestamp,original_url)
);
CREATE INDEX idx_wayback_captures_target_time ON wayback_captures(target_url,timestamp DESC);
CREATE INDEX idx_wayback_captures_digest ON wayback_captures(digest);

CREATE VIEW internet_archive_catalog_status AS
SELECT
    (SELECT COUNT(*) FROM internet_archive_items) AS item_count,
    (SELECT COUNT(*) FROM internet_archive_files) AS file_count,
    (SELECT COUNT(*) FROM internet_archive_searches) AS search_count,
    (SELECT COUNT(*) FROM wayback_captures) AS wayback_capture_count,
    (SELECT MAX(fetched_at) FROM internet_archive_searches) AS latest_search_at,
    (SELECT MAX(fetched_at) FROM wayback_queries) AS latest_wayback_at;

UPDATE platform_components
SET current_version='2.3.0',
    capabilities_json='["records","evidence","measurements","provenance","indicator-governance","observation-lineage","review-workflow","queries","exports","public-api","typed-handoffs","workspaces","connectors","external-source-adapters","conditional-http","adapter-pagination","internet-archive-catalog","internet-archive-metadata","internet-archive-file-inventory","wayback-availability","wayback-cdx-history","analysis-artifacts","offline-operations","backup-restore","postgresql-production-persistence","sqlite-portable-persistence","wordpress-data-integration","platform-manifest"]',
    updated_at=datetime('now')
WHERE component_id='component:catalyst-data';
