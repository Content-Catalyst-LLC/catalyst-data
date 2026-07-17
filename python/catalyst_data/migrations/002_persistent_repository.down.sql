DROP VIEW low_confidence_measurements;
DROP VIEW provenance_gaps;
DROP VIEW measurement_review;
DROP TABLE import_records;
DROP TABLE import_row_errors;
DROP TABLE import_runs;
DROP TABLE data_records;
DROP TABLE repository_metadata;
DROP INDEX ux_measurements_canonical_id;
DROP INDEX ux_sources_canonical_id;
DROP INDEX ux_periods_canonical_id;
DROP INDEX ux_indicators_canonical_id;
DROP INDEX ux_entities_canonical_id;
ALTER TABLE measurements DROP COLUMN reviewer_notes;
ALTER TABLE measurements DROP COLUMN quality_flags;
ALTER TABLE measurements DROP COLUMN uncertainty;
ALTER TABLE measurements DROP COLUMN limitations;
ALTER TABLE measurements DROP COLUMN canonical_id;
ALTER TABLE sources DROP COLUMN access_notes;
ALTER TABLE sources DROP COLUMN checksum;
ALTER TABLE sources DROP COLUMN citation;
ALTER TABLE sources DROP COLUMN canonical_id;
ALTER TABLE periods DROP COLUMN canonical_id;
ALTER TABLE indicators DROP COLUMN version;
ALTER TABLE indicators DROP COLUMN canonical_id;
ALTER TABLE entities DROP COLUMN external_ids_json;
ALTER TABLE entities DROP COLUMN canonical_id;

CREATE VIEW measurement_review AS
SELECT
    m.id AS measurement_id,
    e.name AS entity,
    e.entity_type,
    i.name AS indicator,
    i.framework,
    i.unit,
    i.direction,
    p.label AS period,
    m.baseline_value,
    m.value,
    CASE WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN NULL
         ELSE ROUND(((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0, 2) END AS percent_change,
    s.name AS source,
    s.source_type,
    m.confidence,
    CASE WHEN m.source_id IS NULL THEN 'missing source'
         WHEN m.confidence < 40 THEN 'needs evidence'
         WHEN m.confidence < 70 THEN 'reviewable with caution'
         ELSE 'reviewable' END AS review_status,
    CASE WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN 'indeterminate'
         WHEN m.value = m.baseline_value THEN 'unchanged'
         WHEN i.direction = 'neutral' THEN 'descriptive'
         WHEN i.direction = 'higher' AND m.value > m.baseline_value THEN 'improving'
         WHEN i.direction = 'lower' AND m.value < m.baseline_value THEN 'improving'
         ELSE 'declining' END AS signal_status,
    m.method,
    m.assumptions
FROM measurements m
JOIN entities e ON e.id = m.entity_id
JOIN indicators i ON i.id = m.indicator_id
JOIN periods p ON p.id = m.period_id
LEFT JOIN sources s ON s.id = m.source_id;
CREATE VIEW provenance_gaps AS
SELECT * FROM measurement_review
WHERE source IS NULL OR confidence < 40 OR method IS NULL OR LENGTH(TRIM(COALESCE(method, ''))) = 0;
CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review WHERE confidence < 70;
