-- Catalyst Data (CS50 SQL Final Project)
-- queries.sql
-- Purpose: seed a small demo dataset + provide example queries that demonstrate
-- how the Catalyst Suite can share a single SQL backbone.
--
-- Usage (sqlite3 shell):
--   .read schema.sql
--   .read queries.sql

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 0) Seed frameworks
-- ------------------------------------------------------------
INSERT OR IGNORE INTO frameworks (name, description) VALUES
  ('SDG', 'UN Sustainable Development Goal indicators'),
  ('ESG', 'Environmental, Social, and Governance metrics'),
  ('Resilience', 'Resilience & grit signals'),
  ('Microeconomics', 'Demand / elasticity / revenue analysis'),
  ('NarrativeRisk', 'Narrative / event-driven risk scoring');

-- ------------------------------------------------------------
-- 1) Seed tags (topics + causes)
-- ------------------------------------------------------------
INSERT OR IGNORE INTO tags (kind, name) VALUES
  ('topic', 'Climate change'),
  ('topic', 'Energy transition'),
  ('cause', 'Sustainability');

-- ------------------------------------------------------------
-- 2) Seed entities
-- ------------------------------------------------------------
INSERT OR IGNORE INTO entities (entity_type, name, iso2, iso3) VALUES
  ('country', 'United States', 'US', 'USA');

INSERT OR IGNORE INTO entities (entity_type, name) VALUES
  ('project', 'Content Catalyst Suite'),
  ('organization', 'Catalyst Demo Co');

-- ------------------------------------------------------------
-- 3) Seed periods
-- ------------------------------------------------------------
INSERT OR IGNORE INTO periods (kind, year_value) VALUES ('year', 2024);
INSERT OR IGNORE INTO periods (kind, date_value) VALUES ('date', '2024-12-31');
INSERT OR IGNORE INTO periods (kind, time_value) VALUES ('time', 0.0), ('time', 1.0), ('time', 2.0);

-- ------------------------------------------------------------
-- 4) Seed sources
-- ------------------------------------------------------------
INSERT OR IGNORE INTO sources (name, url, note) VALUES
  ('UNFCCC', 'https://unfccc.int/', 'UN Framework Convention on Climate Change'),
  ('Internal demo', NULL, 'Synthetic / placeholder data for demo purposes');

-- ------------------------------------------------------------
-- 5) SDG structure: Goal → Target → Indicator
-- ------------------------------------------------------------
INSERT OR IGNORE INTO sdg_goals (goal_number, title)
VALUES (13, 'Climate Action');

INSERT OR IGNORE INTO sdg_targets (goal_id, target_code, title)
SELECT g.id, '13.2', 'Integrate climate change measures into policies, strategies and planning'
FROM sdg_goals g
WHERE g.goal_number = 13;

INSERT OR IGNORE INTO sdg_indicators (target_id, indicator_code, description, unit)
SELECT t.id, '13.2.1', 'Number of countries with nationally determined contributions, long-term strategies, etc. (illustrative)', 'index'
FROM sdg_targets t
WHERE t.target_code = '13.2';

-- ------------------------------------------------------------
-- 6) Metrics + mapping to SDG indicator
-- ------------------------------------------------------------
-- Create the metric in the SDG framework.
INSERT OR IGNORE INTO metrics (framework_id, code, name, unit, direction, description)
SELECT f.id, '13.2.1', 'Climate policy integration (demo)', 'index', 1,
       'Demo metric standing in for SDG 13.2.1-style policy integration tracking.'
FROM frameworks f
WHERE f.name = 'SDG';

-- Map the SDG indicator to the metric.
INSERT OR IGNORE INTO sdg_indicator_metric (sdg_indicator_id, metric_id)
SELECT si.id, m.id
FROM sdg_indicators si
JOIN metrics m ON m.code = si.indicator_code
JOIN frameworks f ON f.id = m.framework_id AND f.name = 'SDG'
WHERE si.indicator_code = '13.2.1';

-- ------------------------------------------------------------
-- 7) Measurements (entity × metric × period)
-- ------------------------------------------------------------
INSERT INTO measurements (entity_id, metric_id, period_id, value, source_id, confidence, note)
SELECT e.id, m.id, p.id,
       0.62,
       s.id,
       0.80,
       'Demo measurement for illustration only.'
FROM entities e, metrics m, periods p, sources s, frameworks f
WHERE e.entity_type='country' AND e.iso3='USA'
  AND f.name='SDG' AND m.framework_id=f.id AND m.code='13.2.1'
  AND p.kind='year' AND p.year_value=2024
  AND s.name='Internal demo';

-- ------------------------------------------------------------
-- 8) Legal instrument linked to topic + metric + entity
-- ------------------------------------------------------------
INSERT OR IGNORE INTO legal_instruments (instrument_type, title, short_citation, adopted_on, url, source_id)
SELECT 'treaty',
       'Paris Agreement',
       'UNFCCC, Paris Agreement (2015)',
       '2015-12-12',
       'https://unfccc.int/process-and-meetings/the-paris-agreement/the-paris-agreement',
       s.id
FROM sources s
WHERE s.name='UNFCCC';

-- Link instrument → topic tag
INSERT OR IGNORE INTO instrument_topics (instrument_id, tag_id)
SELECT li.id, t.id
FROM legal_instruments li
JOIN tags t ON t.kind='topic' AND t.name='Climate change'
WHERE li.title='Paris Agreement';

-- Link instrument → metric
INSERT OR IGNORE INTO instrument_metrics (instrument_id, metric_id)
SELECT li.id, m.id
FROM legal_instruments li
JOIN metrics m ON m.code='13.2.1'
JOIN frameworks f ON f.id=m.framework_id AND f.name='SDG'
WHERE li.title='Paris Agreement';

-- Link instrument → entity (role: signatory)
INSERT OR IGNORE INTO instrument_entities (instrument_id, entity_id, role)
SELECT li.id, e.id, 'signatory'
FROM legal_instruments li
JOIN entities e ON e.entity_type='country' AND e.iso3='USA'
WHERE li.title='Paris Agreement';

-- ------------------------------------------------------------
-- 9) Narrative risk: metric + narrative event + score
-- ------------------------------------------------------------
INSERT OR IGNORE INTO metrics (framework_id, code, name, unit, direction, description)
SELECT f.id, 'NR_CRED', 'Commitment credibility score', 'score', 1,
       'NarrativeRisk score reflecting whether commitments are likely to hold.'
FROM frameworks f
WHERE f.name='NarrativeRisk';

INSERT OR IGNORE INTO narratives (title, description)
VALUES ('Climate commitment credibility', 'Narrative tracking credibility of policy commitments over time.');

INSERT OR IGNORE INTO narrative_events (narrative_id, entity_id, period_id, summary, source_id)
SELECT n.id, e.id, p.id,
       'Policy signal: updated climate plan announced; credibility debated.',
       s.id
FROM narratives n, entities e, periods p, sources s
WHERE n.title='Climate commitment credibility'
  AND e.entity_type='country' AND e.iso3='USA'
  AND p.kind='year' AND p.year_value=2024
  AND s.name='Internal demo';

INSERT OR IGNORE INTO narrative_scores (event_id, metric_id, score, confidence, note)
SELECT ne.id, m.id,
       0.55, 0.70,
       'Demo narrative score (illustrative).'
FROM narrative_events ne
JOIN narratives n ON n.id=ne.narrative_id AND n.title='Climate commitment credibility'
JOIN metrics m ON m.code='NR_CRED'
JOIN frameworks f ON f.id=m.framework_id AND f.name='NarrativeRisk'
WHERE ne.summary LIKE 'Policy signal:%';

-- ------------------------------------------------------------
-- 10) Design thinking: Canvas → Persona → POV → HMW → Opportunity → Experiment
-- ------------------------------------------------------------
INSERT OR IGNORE INTO canvases (title, description, owner)
VALUES ('Catalyst SDG Explorer', 'Design-thinking workspace for connecting causes, law, and measurement.', 'Tariq');

INSERT OR IGNORE INTO personas (canvas_id, name, segment, needs, pains, gains)
SELECT c.id,
       'Policy Analyst',
       'Public-sector / NGO',
       'Reliable indicators with legal context and provenance',
       'Data scattered across sources; weak comparability',
       'One place to go from topic → instrument → indicator → evidence'
FROM canvases c
WHERE c.title='Catalyst SDG Explorer';

INSERT OR IGNORE INTO povs (persona_id, user_statement, need_statement, insight_statement, pov_statement)
SELECT p.id,
       'A policy analyst trying to evaluate climate commitments',
       'needs trustworthy measurements tied to evidence and legal context',
       'because credibility depends on linking data to instruments and narratives',
       'A policy analyst needs a single evidence trail from topic → law → metric → measurement.'
FROM personas p
JOIN canvases c ON c.id=p.canvas_id
WHERE c.title='Catalyst SDG Explorer' AND p.name='Policy Analyst';

INSERT OR IGNORE INTO hmw_questions (pov_id, question)
SELECT pv.id,
       'How might we help analysts compare countries while preserving provenance and legal context?'
FROM povs pv
JOIN personas p ON p.id=pv.persona_id
WHERE p.name='Policy Analyst';

INSERT OR IGNORE INTO opportunities (canvas_id, statement, assumptions, impact, confidence, effort)
SELECT c.id,
       'Unified evidence trail from topic to measurement',
       'Users will trust dashboards more when sources and instruments are visible.',
       8, 7, 5
FROM canvases c
WHERE c.title='Catalyst SDG Explorer';

INSERT OR IGNORE INTO experiments (canvas_id, opportunity_id, hypothesis, design, owner, status, started_on, ended_on)
SELECT c.id, o.id,
       'Showing sources + legal instruments next to metrics increases user trust.',
       'A/B test: control dashboard vs dashboard with instrument + source panel; measure task completion + trust survey.',
       'Tariq',
       'completed',
       '2024-11-01',
       '2024-12-15'
FROM canvases c
JOIN opportunities o ON o.canvas_id=c.id
WHERE c.title='Catalyst SDG Explorer'
  AND o.statement='Unified evidence trail from topic to measurement';

-- Link the experiment to a success metric (SDG) and a diagnostic metric (NarrativeRisk).
INSERT OR IGNORE INTO experiment_metrics (experiment_id, metric_id, role)
SELECT ex.id, m.id, 'success'
FROM experiments ex
JOIN metrics m ON m.code='13.2.1'
JOIN frameworks f ON f.id=m.framework_id AND f.name='SDG'
WHERE ex.hypothesis LIKE 'Showing sources%';

INSERT OR IGNORE INTO experiment_metrics (experiment_id, metric_id, role)
SELECT ex.id, m.id, 'diagnostic'
FROM experiments ex
JOIN metrics m ON m.code='NR_CRED'
JOIN frameworks f ON f.id=m.framework_id AND f.name='NarrativeRisk'
WHERE ex.hypothesis LIKE 'Showing sources%';

-- Tie the SDG measurement to the experiment as evidence.
INSERT OR IGNORE INTO experiment_evidence (experiment_id, measurement_id, note)
SELECT ex.id, me.id,
       'Evidence record used in the experiment evaluation.'
FROM experiments ex
JOIN measurements me ON 1=1
JOIN entities e ON e.id=me.entity_id AND e.iso3='USA'
JOIN metrics m ON m.id=me.metric_id AND m.code='13.2.1'
JOIN periods p ON p.id=me.period_id AND p.kind='year' AND p.year_value=2024
WHERE ex.hypothesis LIKE 'Showing sources%';

-- ------------------------------------------------------------
-- 11) Grit: setbacks/recoveries + deliberate practice blocks
-- ------------------------------------------------------------
-- Use the project entity for resilience logging.
INSERT INTO grit_events (entity_id, kind, note)
SELECT e.id, 'setback', 'Demo setback: timeline slipped due to schema changes.'
FROM entities e
WHERE e.entity_type='project' AND e.name='Content Catalyst Suite';

INSERT INTO grit_events (entity_id, kind, note)
SELECT e.id, 'recovery', 'Demo recovery: refactored schema + re-ran tests.'
FROM entities e
WHERE e.entity_type='project' AND e.name='Content Catalyst Suite';

-- Practice block (deliberate)
INSERT INTO practice_blocks (entity_id, period_id, minutes, deliberate, note)
SELECT e.id, p.id, 90, 1, 'Deliberate practice: SQL schema normalization.'
FROM entities e, periods p
WHERE e.entity_type='project' AND e.name='Content Catalyst Suite'
  AND p.kind='date' AND p.date_value='2024-12-31';

-- ------------------------------------------------------------
-- 12) Finance: demand series + observed points (demo)
-- ------------------------------------------------------------
INSERT OR IGNORE INTO demand_series (entity_id, label, currency, unit_quantity, source_id)
SELECT e.id, 'Demo product demand', 'USD', 'units', s.id
FROM entities e, sources s
WHERE e.entity_type='organization' AND e.name='Catalyst Demo Co'
  AND s.name='Internal demo';

INSERT INTO demand_points (series_id, group_name, price, quantity, observed_on)
SELECT ds.id, 'all', 10, 120, '2024-10-01'
FROM demand_series ds
WHERE ds.label='Demo product demand';

INSERT INTO demand_points (series_id, group_name, price, quantity, observed_on)
SELECT ds.id, 'all', 15, 90, '2024-10-15'
FROM demand_series ds
WHERE ds.label='Demo product demand';

INSERT INTO demand_points (series_id, group_name, price, quantity, observed_on)
SELECT ds.id, 'all', 20, 70, '2024-11-01'
FROM demand_series ds
WHERE ds.label='Demo product demand';

-- ------------------------------------------------------------
-- 13) Analysis runs: time series (demo)
-- ------------------------------------------------------------
INSERT OR IGNORE INTO analysis_runs (entity_id, scenario, method, package_name, package_version)
SELECT e.id, 'baseline', 'rk4', 'catalystanalyticsr', '0.1.0'
FROM entities e
WHERE e.entity_type='country' AND e.iso3='USA';

INSERT OR IGNORE INTO analysis_params (run_id, key, value)
SELECT ar.id, 'discount_rate', '0.03'
FROM analysis_runs ar
JOIN entities e ON e.id=ar.entity_id AND e.iso3='USA'
WHERE ar.scenario='baseline';

INSERT OR IGNORE INTO analysis_series (run_id, period_id, variable, value, unit)
SELECT ar.id, p.id, 'inclusive_wealth_index', v.val, 'index'
FROM analysis_runs ar
JOIN entities e ON e.id=ar.entity_id AND e.iso3='USA'
JOIN periods p ON p.kind='time'
JOIN (SELECT 0.0 AS t, 100.0 AS val UNION ALL SELECT 1.0, 101.5 UNION ALL SELECT 2.0, 103.0) v
  ON v.t = p.time_value
WHERE ar.scenario='baseline';

-- ------------------------------------------------------------
-- Example queries (SELECT only)
-- ------------------------------------------------------------

-- Q1) For an SDG metric, show measurement + linked legal instruments + narrative score context.
SELECT
  m.code AS metric_code,
  m.name AS metric_name,
  e.name AS entity,
  p.year_value AS year,
  me.value,
  me.confidence,
  GROUP_CONCAT(DISTINCT li.short_citation) AS linked_instruments,
  ns.score AS narrative_score,
  ns.confidence AS narrative_confidence
FROM measurements me
JOIN metrics m ON m.id=me.metric_id
JOIN entities e ON e.id=me.entity_id
JOIN periods p ON p.id=me.period_id
LEFT JOIN instrument_metrics im ON im.metric_id=m.id
LEFT JOIN legal_instruments li ON li.id=im.instrument_id
LEFT JOIN narrative_events ne ON ne.entity_id=e.id AND ne.period_id=p.id
LEFT JOIN narrative_scores ns ON ns.event_id=ne.id
LEFT JOIN metrics nm ON nm.id=ns.metric_id
WHERE m.code='13.2.1' AND p.kind='year' AND p.year_value=2024
GROUP BY m.code, m.name, e.name, p.year_value, me.value, me.confidence, ns.score, ns.confidence;

-- Q2) List experiments on a canvas and which metrics they track.
SELECT
  c.title AS canvas,
  ex.id AS experiment_id,
  ex.status,
  ex.hypothesis,
  em.role,
  m.code AS metric_code,
  m.name AS metric_name
FROM canvases c
JOIN experiments ex ON ex.canvas_id=c.id
JOIN experiment_metrics em ON em.experiment_id=ex.id
JOIN metrics m ON m.id=em.metric_id
WHERE c.title='Catalyst SDG Explorer'
ORDER BY ex.id, em.role;

-- Q3) Compute revenue per demand point (no stored econ_results needed).
SELECT
  ds.label AS series,
  dp.observed_on,
  dp.price,
  dp.quantity,
  ROUND(dp.price * dp.quantity, 2) AS revenue
FROM demand_series ds
JOIN demand_points dp ON dp.series_id=ds.id
WHERE ds.label='Demo product demand'
ORDER BY dp.observed_on;

-- Q4) Resilience snapshot: setbacks/recoveries and deliberate minutes.
SELECT
  e.name AS entity,
  SUM(CASE WHEN ge.kind='setback' THEN 1 ELSE 0 END) AS setbacks,
  SUM(CASE WHEN ge.kind='recovery' THEN 1 ELSE 0 END) AS recoveries,
  SUM(CASE WHEN pb.deliberate=1 THEN pb.minutes ELSE 0 END) AS deliberate_minutes
FROM entities e
LEFT JOIN grit_events ge ON ge.entity_id=e.id
LEFT JOIN practice_blocks pb ON pb.entity_id=e.id
WHERE e.entity_type='project' AND e.name='Content Catalyst Suite'
GROUP BY e.name;

-- Q5) Analysis run series (time-indexed).
SELECT
  e.iso3 AS entity,
  ar.scenario,
  p.time_value AS t,
  asr.variable,
  asr.value,
  asr.unit
FROM analysis_series asr
JOIN analysis_runs ar ON ar.id=asr.run_id
JOIN entities e ON e.id=ar.entity_id
JOIN periods p ON p.id=asr.period_id
WHERE e.iso3='USA' AND ar.scenario='baseline'
ORDER BY p.time_value;