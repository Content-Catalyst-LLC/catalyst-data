(function(root){
  'use strict';

  var contract = root.CatalystDataReviewContract;
  if (!contract) {
    throw new Error('Catalyst Data review contract was not loaded.');
  }

  function numberValue(value){
    var result = Number(value);
    return Number.isFinite(result) ? result : 0;
  }

  function percentChange(baseline, current){
    var baselineValue = numberValue(baseline);
    var currentValue = numberValue(current);
    if (baselineValue === 0) return null;
    return Number((((currentValue - baselineValue) / Math.abs(baselineValue)) * 100).toFixed(2));
  }

  function sourceIsMissing(sourceName){
    var normalized = sourceName == null ? '' : String(sourceName).trim();
    return contract.missing_source_names.indexOf(normalized) !== -1;
  }

  function classifyReview(confidence, sourceName){
    var value = numberValue(confidence);
    if (sourceIsMissing(sourceName)) return 'missing source';
    if (value < contract.confidence.needs_evidence_below) return 'needs evidence';
    if (value < contract.confidence.caution_below) return 'reviewable with caution';
    return 'reviewable';
  }

  function classifySignal(change, direction){
    if (change === null) return 'indeterminate';
    if (change === 0) return 'unchanged';
    if (direction === 'neutral') return 'descriptive';
    var improving = direction === 'higher' ? change > 0 : change < 0;
    return improving ? 'improving' : 'declining';
  }

  function formatPercent(value){
    if (value === null || !Number.isFinite(value)) return '—';
    return (value > 0 ? '+' : '') + value.toFixed(1) + '%';
  }

  function escapeHtml(value){
    return String(value).replace(/[&<>"]/g, function(character){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[character];
    });
  }

  function buildRecord(container){
    var indicator = container.querySelector('[name="indicator"]');
    var selected = indicator.options[indicator.selectedIndex];
    var baseline = numberValue(container.querySelector('[name="baseline"]').value);
    var current = numberValue(container.querySelector('[name="current"]').value);
    var change = percentChange(baseline, current);
    var confidence = numberValue(container.querySelector('[name="confidence"]').value);
    var direction = container.querySelector('[name="direction"]').value;
    var sourceName = container.querySelector('[name="source"]').value.trim() || 'Unspecified source';

    return {
      entity: {
        name: container.querySelector('[name="entity"]').value.trim() || 'Unnamed entity',
        type: container.querySelector('[name="entityType"]').value
      },
      indicator: {
        name: indicator.value,
        unit: container.querySelector('[name="unit"]').value.trim() || selected.getAttribute('data-unit') || 'unit',
        direction: direction
      },
      period: container.querySelector('[name="period"]').value,
      values: {
        baseline: baseline,
        current: current,
        percent_change: change
      },
      source: {
        name: sourceName,
        type: container.querySelector('[name="sourceType"]').value
      },
      confidence: confidence,
      review_status: classifyReview(confidence, sourceName),
      signal_status: classifySignal(change, direction),
      method_notes: container.querySelector('[name="notes"]').value.trim(),
      trace_path: contract.trace_path.slice()
    };
  }

  function update(container){
    var record = buildRecord(container);
    container.querySelector('[data-confidence-output]').textContent = record.confidence + '%';
    container.querySelector('[data-cdata-title]').textContent = record.entity.name;
    container.querySelector('[data-cdata-change]').textContent = formatPercent(record.values.percent_change);
    container.querySelector('[data-cdata-confidence]').textContent = record.confidence + '%';
    container.querySelector('[data-cdata-status]').textContent = record.review_status;
    container.querySelector('[data-cdata-signal]').textContent = record.signal_status;
    container.querySelector('[data-cdata-trace]').textContent = record.trace_path.join(' → ');

    var changeSentence = record.values.percent_change === null
      ? 'Percent change is indeterminate because the baseline is zero.'
      : 'The calculated change is <strong>' + escapeHtml(formatPercent(record.values.percent_change)) + '</strong>.';

    container.querySelector('[data-cdata-brief]').innerHTML =
      '<p><strong>' + escapeHtml(record.indicator.name) + '</strong> for <strong>' +
      escapeHtml(record.entity.name) + '</strong> moved from ' + record.values.baseline + ' to ' +
      record.values.current + ' ' + escapeHtml(record.indicator.unit) + ' during ' +
      escapeHtml(record.period) + '. ' + changeSentence + '</p><p>The record is tied to <strong>' +
      escapeHtml(record.source.name) + '</strong> with confidence of <strong>' + record.confidence +
      '%</strong>. Review status: <strong>' + escapeHtml(record.review_status) +
      '</strong>. Signal status: <strong>' + escapeHtml(record.signal_status) + '</strong>.</p>';

    container.querySelector('[data-cdata-json]').value = JSON.stringify(record, null, 2);
  }

  function setSample(container){
    container.querySelector('[name="entity"]').value = 'Supplier Energy Transition Program';
    container.querySelector('[name="entityType"]').value = 'program';
    container.querySelector('[name="indicator"]').value = 'Estimated CO2e avoided';
    container.querySelector('[name="period"]').value = '2026-Q3';
    container.querySelector('[name="baseline"]').value = '120';
    container.querySelector('[name="current"]').value = '168';
    container.querySelector('[name="unit"]').value = 'tCO2e';
    container.querySelector('[name="direction"]').value = 'higher';
    container.querySelector('[name="source"]').value = 'Supplier energy reports + procurement audit sample';
    container.querySelector('[name="sourceType"]').value = 'internal record';
    container.querySelector('[name="confidence"]').value = '68';
    container.querySelector('[name="notes"]').value = 'Reported supplier data was sampled against procurement records. Confidence remains moderate until broader third-party verification is available.';
    update(container);
  }

  function copyJson(container){
    var area = container.querySelector('[data-cdata-json]');
    var text = area.value;
    if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) {
      root.navigator.clipboard.writeText(text);
    } else if (root.document) {
      area.focus();
      area.select();
      root.document.execCommand('copy');
    }
  }

  function downloadJson(container){
    if (!root.document) return;
    var blob = new Blob([container.querySelector('[data-cdata-json]').value], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var anchor = root.document.createElement('a');
    anchor.href = url;
    anchor.download = 'catalyst-data-record.json';
    root.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function initialize(){
    root.document.querySelectorAll('[data-catalyst-data-demo]').forEach(function(container){
      container.querySelectorAll('input, select, textarea').forEach(function(element){
        element.addEventListener('input', function(){ update(container); });
        element.addEventListener('change', function(){
          if (element.name === 'indicator') {
            container.querySelector('[name="unit"]').value = element.options[element.selectedIndex].getAttribute('data-unit') || '';
          }
          update(container);
        });
      });
      container.querySelector('[data-cdata-sample]').addEventListener('click', function(){ setSample(container); });
      container.querySelector('[data-cdata-copy]').addEventListener('click', function(){ copyJson(container); });
      container.querySelector('[data-cdata-download]').addEventListener('click', function(){ downloadJson(container); });
      update(container);
    });
  }

  root.CatalystDataDemoEngine = Object.freeze({
    percentChange: percentChange,
    sourceIsMissing: sourceIsMissing,
    classifyReview: classifyReview,
    classifySignal: classifySignal
  });

  if (root.document) {
    root.document.addEventListener('DOMContentLoaded', initialize);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
