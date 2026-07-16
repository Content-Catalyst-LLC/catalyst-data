'use strict';
const fs = require('fs');
const vm = require('vm');

function load(path) {
  vm.runInThisContext(fs.readFileSync(path, 'utf8'), { filename: path });
}
load('wordpress/catalyst-data-demo/assets/catalyst-data-contract.js');
load('wordpress/catalyst-data-demo/assets/catalyst-data-demo.js');

const engine = globalThis.CatalystDataDemoEngine;
function equal(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
}
equal(engine.percentChange(100, 125), 25, 'positive change');
equal(engine.percentChange(100, 80), -20, 'negative change');
equal(engine.percentChange(0, 50), null, 'zero baseline');
equal(engine.classifyReview(72, 'Source'), 'reviewable', 'reviewable');
equal(engine.classifyReview(68, 'Source'), 'reviewable with caution', 'caution');
equal(engine.classifyReview(30, 'Source'), 'needs evidence', 'needs evidence');
equal(engine.classifyReview(90, ''), 'missing source', 'missing source precedence');
equal(engine.classifySignal(12, 'higher'), 'improving', 'higher improving');
equal(engine.classifySignal(-12, 'lower'), 'improving', 'lower improving');
equal(engine.classifySignal(null, 'higher'), 'indeterminate', 'indeterminate');
console.log('Browser contract parity passed.');
