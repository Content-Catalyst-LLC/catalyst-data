'use strict';
const fs = require('fs');
const vm = require('vm');

function load(path) {
  vm.runInThisContext(fs.readFileSync(path, 'utf8'), { filename: path });
}
load('wordpress/catalyst-data-demo/assets/catalyst-data-contract.js');
load('wordpress/catalyst-data-demo/assets/catalyst-data-record-contract.js');
load('wordpress/catalyst-data-demo/assets/catalyst-data-demo.js');

const engine = globalThis.CatalystDataDemoEngine;
function equal(actual, expected, label) {
  if (actual !== expected) throw new Error(`${label}: expected ${expected}, got ${actual}`);
}
function truthy(actual, label) {
  if (!actual) throw new Error(`${label}: expected a truthy value`);
}

equal(engine.percentChange(100, 125), 25, 'positive change');
equal(engine.percentChange(100, 80), -20, 'negative change');
equal(engine.percentChange(0, 50), null, 'zero baseline');
equal(engine.percentChange(null, 50), null, 'missing baseline');
equal(engine.classifyReview(72, 'Source'), 'reviewable', 'reviewable');
equal(engine.classifyReview(68, 'Source'), 'reviewable with caution', 'caution');
equal(engine.classifyReview(30, 'Source'), 'needs evidence', 'needs evidence');
equal(engine.classifyReview(90, ''), 'missing source', 'missing source precedence');
equal(engine.classifySignal(12, 'higher'), 'improving', 'higher improving');
equal(engine.classifySignal(-12, 'lower'), 'improving', 'lower improving');
equal(engine.classifySignal(null, 'higher'), 'indeterminate', 'indeterminate');

const values = {
  entity: 'Browser Test Project', entityType: 'project', externalId: 'browser-test',
  indicator: 'Coverage score', unit: 'score', direction: 'higher', framework: 'Test framework', indicatorVersion: '1.0',
  period: '2026-Q2', periodStart: '2026-04-01', periodEnd: '2026-06-30',
  baseline: 40, current: 50,
  source: 'Browser fixture', sourceType: 'internal record', sourceUrl: 'https://example.com/source',
  sourcePublisher: 'Example Publisher', sourceLicense: 'CC BY 4.0', retrievedAt: '2026-07-16T12:00:00Z',
  citation: 'Example Publisher. Browser fixture.', checksum: 'sha256:' + 'a'.repeat(64), accessNotes: 'Public fixture.',
  confidence: 72, confidenceBasis: 'Fixture basis', reviewerNotes: 'Fixture review',
  notes: 'Fixture method', assumptions: 'Stable rubric', limitations: 'Synthetic data', uncertainty: 'Low', qualityFlags: 'estimated',
  createdAt: '2026-07-16T12:00:00Z', sample: true
};
const first = engine.buildRecord(values, '2026-07-16T12:00:00Z');
const second = engine.buildRecord(values, '2026-07-16T12:00:00Z');
equal(first.schema_version, 'catalyst-data-record/1.0', 'record contract');
equal(first.producer.version, '1.9.0', 'producer version');
equal(first.measurement.percent_change, 25, 'record percent change');
equal(first.review.status, 'reviewable', 'record review status');
equal(first.review.signal_status, 'improving', 'record signal status');
equal(first.record_id, second.record_id, 'stable record id');
truthy(first.record_id.startsWith('measurement:'), 'record id prefix');
equal(first.method.quality_flags[0], 'estimated', 'quality flag');
equal(first.source.checksum, 'sha256:' + 'a'.repeat(64), 'checksum');
equal(first.evidence_chain.schema_version, 'catalyst-data-evidence-chain/1.0', 'evidence contract');
equal(first.evidence_chain.sources.length, 1, 'browser evidence sources');
equal(first.evidence_chain.completeness_score, 95, 'browser evidence completeness');
equal(first.indicator_governance.schema_version, 'catalyst-data-indicator-governance/1.0', 'indicator governance contract');
equal(first.indicator_governance.status, 'active', 'indicator governance status');
equal(first.indicator_governance.unit.symbol, 'score', 'governed unit');
equal(first.indicator_governance.methodology.version, '1.0', 'governed methodology version');
equal(first.observation_lineage.schema_version, 'catalyst-data-observation-lineage/1.0', 'observation lineage contract');
equal(first.observation_lineage.questions.length, 1, 'browser questions');
equal(first.observation_lineage.observations.length, 2, 'browser observations');
equal(first.observation_lineage.completeness_score, 100, 'browser lineage completeness');
equal(first.review_workflow.schema_version, 'catalyst-data-review-workflow/1.0', 'review workflow contract');
equal(first.review_workflow.state, 'draft', 'review workflow state');
equal(first.review_workflow.quality.overall, 91, 'review workflow quality');
equal(first.review_workflow.publication_gate.status, 'blocked', 'publication gate');

console.log('Browser contract parity passed.');
