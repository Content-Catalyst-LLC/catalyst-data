(function(root){
  'use strict';

  var reviewContract = root.CatalystDataReviewContract;
  var recordContract = root.CatalystDataRecordContract;
  if (!reviewContract || !recordContract) {
    throw new Error('Catalyst Data contracts were not loaded.');
  }

  function numberValue(value, field){
    var result = Number(value);
    if (!Number.isFinite(result)) throw new Error(field + ' must be a finite number.');
    return result;
  }

  function nullableNumber(value, field){
    if (value === '' || value === null || typeof value === 'undefined') return null;
    return numberValue(value, field);
  }

  function percentChange(baseline, current){
    var baselineValue = nullableNumber(baseline, 'measurement.baseline');
    var currentValue = numberValue(current, 'measurement.current');
    if (baselineValue === null || baselineValue === 0) return null;
    return Math.round((((currentValue - baselineValue) / Math.abs(baselineValue)) * 100) * 100) / 100;
  }

  function sourceIsMissing(sourceName){
    var normalized = String(sourceName || '').trim();
    return reviewContract.missing_source_names.indexOf(normalized) !== -1;
  }

  function classifyReview(confidence, sourceName){
    var value = numberValue(confidence, 'confidence.score');
    if (value < reviewContract.confidence.minimum || value > reviewContract.confidence.maximum) {
      throw new Error('Confidence must be between 0 and 100.');
    }
    if (sourceIsMissing(sourceName)) return 'missing source';
    if (value < reviewContract.confidence.needs_evidence_below) return 'needs evidence';
    if (value < reviewContract.confidence.caution_below) return 'reviewable with caution';
    return 'reviewable';
  }

  function classifySignal(change, direction){
    if (reviewContract.directions.indexOf(direction) === -1) throw new Error('Indicator direction is invalid.');
    if (change === null) return 'indeterminate';
    if (change === 0) return 'unchanged';
    if (direction === 'neutral') return 'descriptive';
    var improving = direction === 'higher' ? change > 0 : change < 0;
    return improving ? 'improving' : 'declining';
  }

  function slug(value){
    var normalized = String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return (normalized || 'unspecified').slice(0, 64);
  }

  function hashText(value){
    var hash = 2166136261;
    for (var i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return ('00000000' + (hash >>> 0).toString(16)).slice(-8);
  }

  function stableId(kind){
    var parts = Array.prototype.slice.call(arguments, 1).map(function(part){ return String(part || '').trim().toLowerCase(); });
    var anchor = parts.filter(Boolean)[0] || kind;
    return slug(kind) + ':' + slug(anchor) + ':' + hashText(JSON.stringify(parts));
  }

  function nullableText(value){
    var text = String(value || '').trim();
    return text || null;
  }

  function textList(value){
    if (Array.isArray(value)) return value.map(String).map(function(item){ return item.trim(); }).filter(Boolean);
    return String(value || '').split(/\n|,/).map(function(item){ return item.trim(); }).filter(Boolean).filter(function(item, index, all){ return all.indexOf(item) === index; });
  }

  function isoDateTime(value){
    if (!value) return null;
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) throw new Error('A provenance date-time is invalid.');
    return date.toISOString().replace('.000Z', 'Z');
  }

  function validateUrl(value){
    if (!value) return null;
    try { return new URL(value).toString(); }
    catch (error) { throw new Error('Source URL must be an absolute URL.'); }
  }

  function validateChecksum(value){
    if (!value) return null;
    var normalized = String(value).trim().toLowerCase();
    if (!/^sha256:[0-9a-f]{64}$/.test(normalized)) throw new Error('Checksum must use sha256 followed by 64 hexadecimal characters.');
    return normalized;
  }

  function qualityFlags(value){
    var flags = textList(value);
    flags.forEach(function(flag){
      if (recordContract.quality_flags.indexOf(flag) === -1) throw new Error('Unsupported quality flag: ' + flag);
    });
    return flags;
  }

  function buildRecord(values, now){
    var entityName = String(values.entity || '').trim() || 'Unnamed entity';
    var entityType = values.entityType || 'other';
    var indicatorName = String(values.indicator || '').trim();
    var unit = String(values.unit || '').trim();
    var direction = values.direction || 'neutral';
    var periodLabel = String(values.period || '').trim();
    if (!indicatorName || !unit || !periodLabel) throw new Error('Indicator, unit, and reporting period are required.');
    if (recordContract.entity_types.indexOf(entityType) === -1) throw new Error('Entity type is invalid.');
    if (recordContract.source_types.indexOf(values.sourceType || 'unspecified') === -1) throw new Error('Source type is invalid.');

    var baseline = nullableNumber(values.baseline, 'measurement.baseline');
    var current = numberValue(values.current, 'measurement.current');
    var change = percentChange(baseline, current);
    var sourceName = String(values.source || '').trim() || 'Unspecified source';
    var sourceUrl = validateUrl(nullableText(values.sourceUrl));
    var sourcePublisher = nullableText(values.sourcePublisher);
    var sourceId = stableId('source', sourceName, sourcePublisher || '', sourceUrl || '');
    var entityId = stableId('entity', entityType, entityName);
    var indicatorId = stableId('indicator', indicatorName, unit, direction);
    var periodId = stableId('period', periodLabel);
    var timestamp = isoDateTime(now || new Date()) || new Date().toISOString().replace('.000Z', 'Z');
    var createdAt = isoDateTime(values.createdAt || timestamp);
    var confidence = numberValue(values.confidence, 'confidence.score');

    return {
      '$schema': recordContract.schema_uri,
      schema_version: recordContract.contract,
      record_id: stableId('measurement', entityId, indicatorId, periodId, sourceId),
      record_type: 'measurement',
      created_at: createdAt,
      updated_at: timestamp,
      producer: {
        name: 'Catalyst Data',
        version: recordContract.release_version,
        component: 'browser-demo'
      },
      entity: {
        id: entityId,
        name: entityName,
        type: entityType,
        external_ids: values.externalId ? {'org.sustainablecatalyst.demo': String(values.externalId).trim()} : {}
      },
      indicator: {
        id: indicatorId,
        name: indicatorName,
        unit: unit,
        direction: direction,
        framework: nullableText(values.framework),
        version: String(values.indicatorVersion || '1.0').trim() || '1.0'
      },
      period: {
        id: periodId,
        label: periodLabel,
        start_date: nullableText(values.periodStart),
        end_date: nullableText(values.periodEnd)
      },
      measurement: {
        baseline: baseline,
        current: current,
        percent_change: change
      },
      source: {
        id: sourceId,
        name: sourceName,
        type: values.sourceType || 'unspecified',
        url: sourceUrl,
        publisher: sourcePublisher,
        license: nullableText(values.sourceLicense),
        retrieved_at: isoDateTime(values.retrievedAt),
        citation: nullableText(values.citation),
        checksum: validateChecksum(nullableText(values.checksum)),
        access_notes: nullableText(values.accessNotes)
      },
      confidence: {
        score: confidence,
        scale: '0-100',
        basis: nullableText(values.confidenceBasis)
      },
      review: {
        status: classifyReview(confidence, sourceName),
        signal_status: classifySignal(change, direction),
        reviewer_notes: String(values.reviewerNotes || '').trim()
      },
      method: {
        notes: String(values.notes || '').trim(),
        assumptions: textList(values.assumptions),
        limitations: textList(values.limitations),
        uncertainty: nullableText(values.uncertainty),
        quality_flags: qualityFlags(values.qualityFlags)
      },
      extensions: {
        'org.sustainablecatalyst.demo': {sample: Boolean(values.sample)}
      }
    };
  }

  function formatPercent(value){
    if (value === null || !Number.isFinite(value)) return '—';
    return (value > 0 ? '+' : '') + value.toFixed(2).replace(/\.00$/, '') + '%';
  }

  function escapeHtml(value){
    return String(value).replace(/[&<>"']/g, function(character){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[character];
    });
  }

  function valuesFromContainer(container){
    function value(name){
      var element = container.querySelector('[name="' + name + '"]');
      return element ? element.value : '';
    }
    return {
      createdAt: container.dataset.createdAt,
      entity: value('entity'), entityType: value('entityType'), externalId: value('externalId'),
      indicator: value('indicator'), unit: value('unit'), direction: value('direction'), framework: value('framework'), indicatorVersion: value('indicatorVersion'),
      period: value('period'), periodStart: value('periodStart'), periodEnd: value('periodEnd'),
      baseline: value('baseline'), current: value('current'),
      source: value('source'), sourceType: value('sourceType'), sourceUrl: value('sourceUrl'), sourcePublisher: value('sourcePublisher'),
      sourceLicense: value('sourceLicense'), retrievedAt: value('retrievedAt'), citation: value('citation'), checksum: value('checksum'), accessNotes: value('accessNotes'),
      confidence: value('confidence'), confidenceBasis: value('confidenceBasis'), reviewerNotes: value('reviewerNotes'),
      notes: value('notes'), assumptions: value('assumptions'), limitations: value('limitations'), uncertainty: value('uncertainty'), qualityFlags: value('qualityFlags'),
      sample: container.dataset.sample === '1'
    };
  }

  function update(container){
    var error = container.querySelector('[data-cdata-error]');
    try {
      var record = buildRecord(valuesFromContainer(container), new Date());
      error.textContent = '';
      error.hidden = true;
      container.querySelector('[data-confidence-output]').textContent = record.confidence.score + '%';
      container.querySelector('[data-cdata-title]').textContent = record.entity.name;
      container.querySelector('[data-cdata-record-id]').textContent = record.record_id;
      container.querySelector('[data-cdata-change]').textContent = formatPercent(record.measurement.percent_change);
      container.querySelector('[data-cdata-confidence]').textContent = record.confidence.score + '%';
      container.querySelector('[data-cdata-status]').textContent = record.review.status;
      container.querySelector('[data-cdata-signal]').textContent = record.review.signal_status;

      var changeSentence = record.measurement.percent_change === null
        ? 'Percent change is indeterminate because the baseline is missing or zero.'
        : 'The calculated change is <strong>' + escapeHtml(formatPercent(record.measurement.percent_change)) + '</strong>.';

      container.querySelector('[data-cdata-brief]').innerHTML =
        '<p><strong>' + escapeHtml(record.indicator.name) + '</strong> for <strong>' +
        escapeHtml(record.entity.name) + '</strong> moved from ' + escapeHtml(record.measurement.baseline) + ' to ' +
        escapeHtml(record.measurement.current) + ' ' + escapeHtml(record.indicator.unit) + ' during ' +
        escapeHtml(record.period.label) + '. ' + changeSentence + '</p><p>The record is tied to <strong>' +
        escapeHtml(record.source.name) + '</strong> with confidence of <strong>' + record.confidence.score +
        '%</strong>. Review status: <strong>' + escapeHtml(record.review.status) +
        '</strong>. Signal status: <strong>' + escapeHtml(record.review.signal_status) + '</strong>.</p>';

      container.querySelector('[data-cdata-json]').value = JSON.stringify(record, null, 2);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      container.querySelector('[data-cdata-json]').value = '';
    }
  }

  function setSample(container){
    container.dataset.sample = '1';
    var sample = {
      entity:'Supplier Energy Transition Program', entityType:'program', externalId:'supplier-energy-transition',
      indicator:'Estimated CO2e avoided', unit:'tCO2e', direction:'higher', framework:'Sustainable Catalyst Measurement Framework', indicatorVersion:'1.0',
      period:'2026-Q3', periodStart:'2026-07-01', periodEnd:'2026-09-30', baseline:'120', current:'168',
      source:'Supplier energy reports + procurement audit sample', sourceType:'internal record',
      sourceUrl:'https://sustainablecatalyst.com/records/supplier-energy-transition-2026-q3', sourcePublisher:'Content Catalyst LLC',
      sourceLicense:'Internal review record', retrievedAt:'2026-07-16T12:00',
      citation:'Content Catalyst LLC. Supplier Energy Transition Program evidence record, 2026-Q3.',
      checksum:'sha256:7c7d2ab0857f139ee840678101daa9baaaae77f0e5aa7adf9f6ca5ac2e8f1f4a',
      accessNotes:'Public demonstration record.', confidence:'68', confidenceBasis:'Supplier reports checked against a procurement sample.',
      notes:'Reported supplier data was sampled against procurement records.',
      assumptions:'Supplier reporting uses the same emissions boundary as the baseline.',
      limitations:'Only a sample of procurement records has been independently checked.',
      uncertainty:'Moderate uncertainty remains until broader verification is complete.', qualityFlags:'unverified',
      reviewerNotes:'Appropriate for internal review with the verification limitation visible.'
    };
    Object.keys(sample).forEach(function(name){
      var element = container.querySelector('[name="' + name + '"]');
      if (element) element.value = sample[name];
    });
    update(container);
  }

  function copyJson(container){
    var area = container.querySelector('[data-cdata-json]');
    if (!area.value) return;
    if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) root.navigator.clipboard.writeText(area.value);
    else if (root.document) { area.focus(); area.select(); root.document.execCommand('copy'); }
  }

  function downloadJson(container){
    if (!root.document) return;
    var text = container.querySelector('[data-cdata-json]').value;
    if (!text) return;
    var blob = new Blob([text], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var anchor = root.document.createElement('a');
    anchor.href = url;
    anchor.download = 'catalyst-data-record-1.0.json';
    root.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function initialize(){
    root.document.querySelectorAll('[data-catalyst-data-demo]').forEach(function(container){
      container.dataset.createdAt = new Date().toISOString().replace('.000Z', 'Z');
      container.querySelectorAll('input, select, textarea').forEach(function(element){
        element.addEventListener('input', function(){ update(container); });
        element.addEventListener('change', function(){
          if (element.name === 'indicator') container.querySelector('[name="unit"]').value = element.options[element.selectedIndex].getAttribute('data-unit') || '';
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
    classifySignal: classifySignal,
    stableId: stableId,
    buildRecord: buildRecord
  });

  if (root.document) root.document.addEventListener('DOMContentLoaded', initialize);
})(typeof globalThis !== 'undefined' ? globalThis : this);
