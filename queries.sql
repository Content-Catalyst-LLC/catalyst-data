-- Catalyst Data demo seed and review queries

PRAGMA foreign_keys = ON;

INSERT OR IGNORE INTO entities (entity_type, name, description) VALUES
  ('project', 'Urban Tree Canopy Program', 'Demo program tracking urban greening and implementation evidence.'),
  ('program', 'Supplier Energy Transition Program', 'Demo supplier engagement and emissions-reduction program.'),
  ('organization', 'Catalyst Demo Organization', 'Synthetic organization used for examples.');

INSERT OR IGNORE INTO indicators (code, name, framework, unit, direction, description) VALUES
  ('DATA-COMPLETE', 'Data completeness score', 'Catalyst', 'score', 'higher', 'Completeness of required records, provenance, and method notes.'),
  ('CO2E-AVOIDED', 'Estimated CO2e avoided', 'Impact', 'tCO2e', 'higher', 'Estimated avoided emissions, subject to method assumptions.'),
  ('ENERGY-INTENSITY', 'Energy intensity', 'Energy', 'kWh / sq ft', 'lower', 'Energy consumed per square foot.'),
  ('PARTICIPATION', 'Participation rate', 'Program', '%', 'higher', 'Percentage of eligible participants engaged.');

INSERT OR IGNORE INTO periods (label, period_type, start_date, end_date) VALUES
  ('2026-Q1', 'quarter', '2026-01-01', '2026-03-31'),
  ('2026-Q2', 'quarter', '2026-04-01', '2026-06-30'),
  ('2026-Q3', 'quarter', '2026-07-01', '2026-09-30'),
  ('2026', 'year', '2026-01-01', '2026-12-31');

INSERT OR IGNORE INTO sources (name, source_type, url, publisher, license, retrieved_at, notes) VALUES
  ('Internal program tracker + field verification notes', 'internal record', NULL, 'Catalyst Demo Organization', NULL, '2026-07-01', 'Synthetic example source.'),
  ('Supplier energy reports + procurement audit sample', 'internal record', NULL, 'Catalyst Demo Organization', NULL, '2026-07-01', 'Synthetic example source.'),
  ('Public energy benchmark dataset', 'third-party dataset', 'https://example.org/energy-benchmark', 'Example Publisher', 'Example license', '2026-07-01', 'Placeholder URL for demo purposes.');

INSERT OR IGNORE INTO measurements (entity_id, indicator_id, period_id, source_id, value, baseline_value, confidence, method, assumptions)
SELECT e.id, i.id, p.id, s.id, 78, 62, 72,
       'Current value combines verified site records with program-reported updates.',
       'Not all locations have third-party verification.'
FROM entities e, indicators i, periods p, sources s
WHERE e.name='Urban Tree Canopy Program'
  AND i.name='Data completeness score'
  AND p.label='2026-Q2'
  AND s.name='Internal program tracker + field verification notes';

INSERT OR IGNORE INTO measurements (entity_id, indicator_id, period_id, source_id, value, baseline_value, confidence, method, assumptions)
SELECT e.id, i.id, p.id, s.id, 168, 120, 68,
       'Supplier reported values sampled against procurement records.',
       'Estimates require broader third-party verification before external claims.'
FROM entities e, indicators i, periods p, sources s
WHERE e.name='Supplier Energy Transition Program'
  AND i.name='Estimated CO2e avoided'
  AND p.label='2026-Q3'
  AND s.name='Supplier energy reports + procurement audit sample';

SELECT * FROM measurement_review;
SELECT * FROM provenance_gaps;
SELECT * FROM low_confidence_measurements;
