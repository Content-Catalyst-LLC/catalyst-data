-- Catalyst Core DB (CS50 SQL Final Project)
-- Purpose: One database layer that can support the Catalyst Suite:
--   - Canvas (design thinking: personas → hypotheses → experiments)
--   - Grit (setbacks/recoveries + deliberate-practice signals)
--   - Finance (microeconomics: demand, elasticity, MR/TR)
--   - Analytics (scenario runs + SDG/ESG indicators)
--   - Narrative Risk (events + scores)
--   - International Law (instruments linked to topics + metrics)

PRAGMA foreign_keys = ON;

-- -----------------------------
-- Core dimensions
-- -----------------------------

-- Entities are anything you measure or attach evidence to (countries, orgs, projects, personas, etc.)
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN (
        'country','organization','project','persona','experiment','dataset','other'
    )),
    name TEXT NOT NULL,
    iso2 TEXT CHECK (iso2 IS NULL OR length(iso2) = 2),
    iso3 TEXT CHECK (iso3 IS NULL OR length(iso3) = 3),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entity_type, name)
);

-- Frameworks group metrics (SDG, ESG, Resilience, Microeconomics, NarrativeRisk, etc.)
CREATE TABLE IF NOT EXISTS frameworks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

-- Metrics are any measurable concept; values are stored in measurements.
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY,
    framework_id INTEGER NOT NULL,
    code TEXT, -- e.g., '13.2.1', 'DPR', 'PRICE_ELAST', 'NR_SCORE'
    name TEXT NOT NULL,
    unit TEXT,
    direction INTEGER CHECK(direction IN (-1, 0, 1)) DEFAULT 0, -- -1 = lower is better, +1 = higher is better
    description TEXT,
    FOREIGN KEY (framework_id) REFERENCES frameworks(id) ON DELETE RESTRICT,
    UNIQUE(framework_id, code),
    UNIQUE(framework_id, name)
);

-- Provenance: where a measurement or document came from.
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT,
    license TEXT,
    retrieved_at TEXT,
    note TEXT
);

-- Periods unify different time representations:
--   - 'date': date_value = 'YYYY-MM-DD'
--   - 'year': year_value = 2024
--   - 'time': time_value = numeric time (e.g., model t)
CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('date','year','time')),
    date_value TEXT,
    year_value INTEGER,
    time_value REAL,
    CHECK (
        (kind = 'date' AND date_value IS NOT NULL AND year_value IS NULL AND time_value IS NULL) OR
        (kind = 'year' AND year_value IS NOT NULL AND date_value IS NULL AND time_value IS NULL) OR
        (kind = 'time' AND time_value IS NOT NULL AND date_value IS NULL AND year_value IS NULL)
    ),
    UNIQUE(kind, date_value, year_value, time_value)
);

-- The universal fact table. Nearly every downstream module can write here.
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    metric_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    value REAL NOT NULL,
    source_id INTEGER,
    confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES metrics(id) ON DELETE RESTRICT,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL,
    UNIQUE(entity_id, metric_id, period_id)
);

-- Tags provide your cause taxonomy (Human Rights, Environment, etc.) and other classifications.
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('cause','topic','esg','sdg','keyword')),
    name TEXT NOT NULL,
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS entity_tags (
    entity_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (entity_id, tag_id),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metric_tags (
    metric_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (metric_id, tag_id),
    FOREIGN KEY (metric_id) REFERENCES metrics(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

-- -----------------------------
-- SDG module (semantic layer)
-- -----------------------------

CREATE TABLE IF NOT EXISTS sdg_goals (
    id INTEGER PRIMARY KEY,
    goal_number INTEGER NOT NULL CHECK(goal_number BETWEEN 1 AND 17),
    title TEXT NOT NULL,
    UNIQUE(goal_number)
);

CREATE TABLE IF NOT EXISTS sdg_targets (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL,
    target_code TEXT NOT NULL, -- e.g., '13.2'
    title TEXT NOT NULL,
    FOREIGN KEY (goal_id) REFERENCES sdg_goals(id) ON DELETE CASCADE,
    UNIQUE(target_code)
);

CREATE TABLE IF NOT EXISTS sdg_indicators (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL,
    indicator_code TEXT NOT NULL, -- e.g., '13.2.1'
    description TEXT NOT NULL,
    unit TEXT,
    FOREIGN KEY (target_id) REFERENCES sdg_targets(id) ON DELETE CASCADE,
    UNIQUE(indicator_code)
);

-- Map an SDG indicator to a metric in the core measurement system.
CREATE TABLE IF NOT EXISTS sdg_indicator_metric (
    sdg_indicator_id INTEGER PRIMARY KEY,
    metric_id INTEGER NOT NULL UNIQUE,
    FOREIGN KEY (sdg_indicator_id) REFERENCES sdg_indicators(id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES metrics(id) ON DELETE RESTRICT
);

-- -----------------------------
-- International Law module
-- -----------------------------

CREATE TABLE IF NOT EXISTS legal_instruments (
    id INTEGER PRIMARY KEY,
    instrument_type TEXT NOT NULL CHECK(instrument_type IN ('treaty','case','resolution','report','policy','other')),
    title TEXT NOT NULL,
    short_citation TEXT,
    adopted_on TEXT,
    url TEXT,
    source_id INTEGER,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS instrument_topics (
    instrument_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (instrument_id, tag_id),
    FOREIGN KEY (instrument_id) REFERENCES legal_instruments(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

-- Instruments can be associated with entities (e.g., country party, respondent state).
CREATE TABLE IF NOT EXISTS instrument_entities (
    instrument_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    role TEXT,
    PRIMARY KEY (instrument_id, entity_id, role),
    FOREIGN KEY (instrument_id) REFERENCES legal_instruments(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

-- Instruments can justify or constrain metrics (e.g., a right-to-water treaty linked to SDG 6 indicators).
CREATE TABLE IF NOT EXISTS instrument_metrics (
    instrument_id INTEGER NOT NULL,
    metric_id INTEGER NOT NULL,
    PRIMARY KEY (instrument_id, metric_id),
    FOREIGN KEY (instrument_id) REFERENCES legal_instruments(id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES metrics(id) ON DELETE CASCADE
);

-- -----------------------------
-- Catalyst Canvas module (design thinking)
-- -----------------------------

CREATE TABLE IF NOT EXISTS canvases (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    owner TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY,
    canvas_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    segment TEXT,
    needs TEXT,
    pains TEXT,
    gains TEXT,
    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE,
    UNIQUE(canvas_id, name)
);

CREATE TABLE IF NOT EXISTS povs (
    id INTEGER PRIMARY KEY,
    persona_id INTEGER NOT NULL,
    user_statement TEXT NOT NULL,
    need_statement TEXT NOT NULL,
    insight_statement TEXT NOT NULL,
    pov_statement TEXT NOT NULL,
    FOREIGN KEY (persona_id) REFERENCES personas(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hmw_questions (
    id INTEGER PRIMARY KEY,
    pov_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    FOREIGN KEY (pov_id) REFERENCES povs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    canvas_id INTEGER NOT NULL,
    statement TEXT NOT NULL,
    assumptions TEXT,
    impact INTEGER CHECK(impact BETWEEN 1 AND 10),
    confidence INTEGER CHECK(confidence BETWEEN 1 AND 10),
    effort INTEGER CHECK(effort BETWEEN 1 AND 10),
    rice_reach INTEGER,
    rice_impact REAL,
    rice_confidence REAL,
    rice_effort REAL,
    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    canvas_id INTEGER NOT NULL,
    opportunity_id INTEGER,
    hypothesis TEXT NOT NULL,
    design TEXT,
    owner TEXT,
    status TEXT NOT NULL CHECK(status IN ('queued','running','paused','completed','killed')) DEFAULT 'queued',
    started_on TEXT,
    ended_on TEXT,
    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE SET NULL
);

-- Which metrics matter for an experiment (success / guardrail / diagnostic).
CREATE TABLE IF NOT EXISTS experiment_metrics (
    experiment_id INTEGER NOT NULL,
    metric_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('success','guardrail','diagnostic')),
    PRIMARY KEY (experiment_id, metric_id, role),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES metrics(id) ON DELETE CASCADE
);

-- Evidence ties an experiment to specific measurements.
CREATE TABLE IF NOT EXISTS experiment_evidence (
    experiment_id INTEGER NOT NULL,
    measurement_id INTEGER NOT NULL,
    note TEXT,
    PRIMARY KEY (experiment_id, measurement_id),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
    FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

-- -----------------------------
-- Catalyst Grit module (resilience signals)
-- -----------------------------

-- Mirrors the lightweight table in catalyst-grit (kind = setback/recovery), but links to an entity.
CREATE TABLE IF NOT EXISTS grit_events (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('setback','recovery')),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

-- Practice blocks power Deliberate Practice Ratio (DPR).
CREATE TABLE IF NOT EXISTS practice_blocks (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL, -- usually kind='date'
    minutes REAL NOT NULL CHECK(minutes >= 0),
    deliberate INTEGER NOT NULL CHECK(deliberate IN (0,1)),
    note TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE CASCADE
);

-- Topic minutes power Consistency of Interests.
CREATE TABLE IF NOT EXISTS topic_minutes (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    minutes REAL NOT NULL CHECK(minutes >= 0),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE CASCADE
);

-- -----------------------------
-- Catalyst Finance module (microeconomics: demand & elasticity)
-- -----------------------------

CREATE TABLE IF NOT EXISTS demand_series (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL, -- who/what the series belongs to
    label TEXT NOT NULL,
    currency TEXT,
    unit_quantity TEXT,
    source_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);

-- Observed demand points (Price, Quantity), optionally segmented by Group.
CREATE TABLE IF NOT EXISTS demand_points (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL,
    group_name TEXT,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    observed_on TEXT,
    FOREIGN KEY (series_id) REFERENCES demand_series(id) ON DELETE CASCADE
);

-- A run captures how results were computed (observed midpoint vs linear point elasticity).
CREATE TABLE IF NOT EXISTS econ_runs (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('observed','linear')),
    a REAL, -- for linear: Q = a - bP
    b REAL,
    price_start REAL,
    price_end REAL,
    price_step REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (series_id) REFERENCES demand_series(id) ON DELETE CASCADE
);

-- Per-price outputs (matches the CSVs in catalyst-finance data/).
CREATE TABLE IF NOT EXISTS econ_results (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    group_name TEXT,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    revenue REAL NOT NULL,
    elasticity REAL,
    abs_elasticity REAL,
    elasticity_type TEXT CHECK(elasticity_type IN ('elastic','inelastic','unit elastic')),
    marginal_revenue REAL,
    is_rev_max INTEGER NOT NULL CHECK(is_rev_max IN (0,1)) DEFAULT 0,
    is_unit_elastic INTEGER NOT NULL CHECK(is_unit_elastic IN (0,1)) DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES econ_runs(id) ON DELETE CASCADE
);

-- -----------------------------
-- Narrative Risk module
-- -----------------------------

CREATE TABLE IF NOT EXISTS narratives (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS narrative_events (
    id INTEGER PRIMARY KEY,
    narrative_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    source_id INTEGER,
    FOREIGN KEY (narrative_id) REFERENCES narratives(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS narrative_scores (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    metric_id INTEGER NOT NULL, -- framework likely 'NarrativeRisk'
    score REAL NOT NULL,
    confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    note TEXT,
    FOREIGN KEY (event_id) REFERENCES narrative_events(id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES metrics(id) ON DELETE RESTRICT
);

-- -----------------------------
-- Optimizations
-- -----------------------------

CREATE INDEX IF NOT EXISTS idx_measurements_entity_metric ON measurements(entity_id, metric_id);
CREATE INDEX IF NOT EXISTS idx_measurements_metric_period ON measurements(metric_id, period_id);
CREATE INDEX IF NOT EXISTS idx_periods_kind_year ON periods(kind, year_value);
CREATE INDEX IF NOT EXISTS idx_periods_kind_date ON periods(kind, date_value);

CREATE INDEX IF NOT EXISTS idx_experiments_canvas_status ON experiments(canvas_id, status);
CREATE INDEX IF NOT EXISTS idx_experiment_evidence_measurement ON experiment_evidence(measurement_id);

CREATE INDEX IF NOT EXISTS idx_grit_events_entity_kind_time ON grit_events(entity_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_practice_blocks_entity_period ON practice_blocks(entity_id, period_id);
CREATE INDEX IF NOT EXISTS idx_topic_minutes_entity_period ON topic_minutes(entity_id, period_id);

CREATE INDEX IF NOT EXISTS idx_demand_points_series_group_price ON demand_points(series_id, group_name, price);
CREATE INDEX IF NOT EXISTS idx_econ_results_run_group_price ON econ_results(run_id, group_name, price);

CREATE INDEX IF NOT EXISTS idx_instrument_topics_tag ON instrument_topics(tag_id);
CREATE INDEX IF NOT EXISTS idx_instrument_metrics_metric ON instrument_metrics(metric_id);

-- A convenience view to read measurements with human-friendly labels.
CREATE VIEW IF NOT EXISTS v_measurements_flat AS
SELECT
    m.id AS measurement_id,
    e.entity_type,
    e.name AS entity_name,
    f.name AS framework,
    mt.code AS metric_code,
    mt.name AS metric_name,
    p.kind AS period_kind,
    COALESCE(p.date_value, CAST(p.year_value AS TEXT), CAST(p.time_value AS TEXT)) AS period_value,
    m.value,
    mt.unit,
    s.name AS source_name,
    s.url AS source_url,
    m.confidence,
    m.note,
    m.created_at
FROM measurements m
JOIN entities e ON e.id = m.entity_id
JOIN metrics mt ON mt.id = m.metric_id
JOIN frameworks f ON f.id = mt.framework_id
JOIN periods p ON p.id = m.period_id
LEFT JOIN sources s ON s.id = m.source_id;

-- -----------------------------
-- Catalyst Analytics module (scenario runs + trajectories)
-- -----------------------------

-- Captures a scenario run (e.g., produced by catalystanalyticsr) and links it to an entity.
CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    scenario TEXT NOT NULL DEFAULT 'baseline',
    method TEXT NOT NULL DEFAULT 'rk4' CHECK(method IN ('rk4','euler')),
    package_name TEXT NOT NULL DEFAULT 'catalystanalyticsr',
    package_version TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

-- Key/value parameter store for the run (keeps DESIGN.md honest about reproducibility).
CREATE TABLE IF NOT EXISTS analysis_params (
    run_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (run_id, key),
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

-- Long-format time series (t, variable, value) for trajectories.
CREATE TABLE IF NOT EXISTS analysis_series (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL, -- kind='time'
    variable TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE RESTRICT
);

-- Optional pointer list to exported bundle files (CSV/PNG/manifest.json/zip).
CREATE TABLE IF NOT EXISTS run_artifacts (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    artifact_type TEXT NOT NULL CHECK(artifact_type IN ('csv','png','json','zip','other')),
    filename TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_entity_time ON analysis_runs(entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_series_run_var_time ON analysis_series(run_id, variable, period_id);
CREATE INDEX IF NOT EXISTS idx_run_artifacts_run ON run_artifacts(run_id);

-- Latest YEAR measurements per (entity, metric): handy for SDG/ESG dashboards.
CREATE VIEW IF NOT EXISTS v_latest_year_measurements AS
WITH year_meas AS (
    SELECT
        m.entity_id,
        m.metric_id,
        p.year_value AS year,
        m.value,
        m.source_id,
        m.id AS measurement_id,
        ROW_NUMBER() OVER (
            PARTITION BY m.entity_id, m.metric_id
            ORDER BY p.year_value DESC, m.created_at DESC
        ) AS rn
    FROM measurements m
    JOIN periods p ON p.id = m.period_id
    WHERE p.kind = 'year'
)
SELECT entity_id, metric_id, year, value, source_id, measurement_id
FROM year_meas
WHERE rn = 1;