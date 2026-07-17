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

  function evidenceChain(source, method, confidence){
    var gaps = [];
    function gap(code, severity, description){ gaps.push({code: code, severity: severity, description: description}); }
    if (!source.citation) gap('missing-citation', 'warning', 'The linked source lacks a citation.');
    if (!source.license) gap('missing-license', 'warning', 'The linked source lacks license metadata.');
    if (!source.retrieved_at) gap('missing-retrieval-date', 'warning', 'The linked source lacks a retrieval timestamp.');
    if (!source.checksum) gap('missing-checksum', 'info', 'The linked source lacks a content checksum.');
    if (!method.notes) gap('missing-method', 'warning', 'The measurement has no method description.');
    if (confidence.score < 40) gap('low-confidence', 'warning', 'Confidence is below the evidence-readiness threshold.');
    var score = 20;
    if (source.citation) score += 15;
    if (source.license) score += 10;
    if (source.retrieved_at) score += 10;
    if (source.checksum) score += 10;
    if (method.notes) score += 15;
    if (confidence.score >= 40) score += 10;
    score += 5;
    return {
      schema_version: recordContract.evidence_contract,
      sources: [{role: 'primary', source: source, locator: {page: null, section: null, quote: null, fragment: null}, supports: ['measurement.baseline', 'measurement.current'], notes: null}],
      relationships: [],
      transformations: [],
      gaps: gaps,
      completeness_score: Math.min(score, 100)
    };
  }


  function indicatorGovernance(indicator, method){
    var dimension = slug(indicator.unit) || 'unspecified';
    var unitId = stableId('unit', dimension, indicator.unit);
    var methodId = stableId('method', indicator.id, indicator.name + ' methodology');
    return {
      schema_version: recordContract.indicator_governance_contract,
      namespace: 'sc',
      code: indicator.id.split(':').slice(1).join(':'),
      domain: indicator.framework || 'general',
      custodian: 'Content Catalyst LLC',
      status: 'active',
      aliases: [],
      definition: indicator.name,
      frequency: 'annual',
      aggregation: 'point-estimate',
      disaggregation_dimensions: [],
      numerator: null,
      denominator: null,
      unit: {
        id: unitId, symbol: indicator.unit, name: indicator.unit, dimension: dimension,
        canonical_unit_id: unitId, conversion_factor: 1, conversion_offset: 0
      },
      methodology: {
        id: methodId, version: indicator.version, title: indicator.name + ' methodology',
        description: method.notes || '', formula: null, references: [], status: 'draft',
        approved_by: null, approved_at: null, revision_notes: null
      },
      framework_mappings: indicator.framework ? [{framework: indicator.framework, code: indicator.id.split(':').slice(1).join(':'), relationship: 'exactMatch', notes: null}] : [],
      compatibility: {
        comparable_versions: [indicator.version], required_dimensions: [],
        methodology_equivalence: [methodId], notes: null
      }
    };
  }

  function observationLineage(record){
    var questionId = stableId('question', record.entity.id, record.indicator.id);
    var instrumentId = stableId('instrument', record.source.id, record.source.type);
    var datasetId = stableId('dataset', record.source.id, record.indicator.id);
    var batchId = stableId('batch', record.record_id, record.updated_at);
    var unitId = record.indicator_governance.unit.id;
    var observations = [];
    if (record.measurement.baseline !== null) {
      observations.push({
        id: stableId('observation', record.record_id, 'baseline'), batch_id: batchId, role: 'baseline',
        observed_at: record.period.start_date ? record.period.start_date + 'T00:00:00Z' : record.updated_at,
        value: record.measurement.baseline, value_text: null, unit_id: unitId, quality_status: 'valid',
        missing_reason: null, censoring: null, outlier: false, imputation: null,
        dimensions: {entity_id: record.entity.id, period_id: record.period.id}, raw_payload: {}
      });
    }
    observations.push({
      id: stableId('observation', record.record_id, 'current'), batch_id: batchId, role: 'current',
      observed_at: record.period.end_date ? record.period.end_date + 'T00:00:00Z' : record.updated_at,
      value: record.measurement.current, value_text: null, unit_id: unitId, quality_status: 'valid',
      missing_reason: null, censoring: null, outlier: false, imputation: null,
      dimensions: {entity_id: record.entity.id, period_id: record.period.id}, raw_payload: {}
    });
    var transformationId = stableId('transformation', record.record_id, record.indicator_governance.methodology.id, record.indicator_governance.methodology.version);
    return {
      schema_version: recordContract.observation_lineage_contract,
      questions: [{
        id: questionId,
        text: 'What is the value of ' + record.indicator.name + ' for ' + record.entity.name + ' during ' + record.period.label + '?',
        type: 'monitoring', decision_context: null, status: 'active', owner: record.producer.name
      }],
      instruments: [{
        id: instrumentId, name: record.source.name + ' collection instrument',
        type: record.source.type === 'survey' ? 'survey' : (record.source.type === 'sensor' ? 'sensor' : (record.source.type === 'api' ? 'api' : 'administrative')),
        version: '1.0', description: record.source.access_notes || null,
        protocol: record.method.notes || null, provider: record.source.publisher || null, calibration: null,
        fields: [
          {name:'value', data_type:'number', unit_id:unitId, description:record.indicator.name, required:true},
          {name:'observed_at', data_type:'datetime', unit_id:null, description:'Observation timestamp', required:true}
        ]
      }],
      datasets: [{
        id: datasetId, name: record.source.name, version: record.source.checksum || record.source.retrieved_at || '1.0',
        description: record.source.citation || null, license: record.source.license || null,
        access: record.method.quality_flags.indexOf('restricted') !== -1 ? 'restricted' : 'public',
        checksum: record.source.checksum || null,
        fields: [
          {name:'value', data_type:'number', unit_id:unitId, description:record.indicator.name, nullable:false},
          {name:'entity_id', data_type:'string', unit_id:null, description:'Canonical entity identifier', nullable:false},
          {name:'period_id', data_type:'string', unit_id:null, description:'Canonical period identifier', nullable:false}
        ]
      }],
      batches: [{
        id: batchId, dataset_id: datasetId, instrument_id: instrumentId,
        collected_at: record.period.end_date ? record.period.end_date + 'T00:00:00Z' : record.updated_at,
        received_at: record.source.retrieved_at || record.updated_at, collector: record.source.publisher || record.producer.name,
        protocol: record.method.notes || null, record_count: observations.length, notes: null
      }],
      observations: observations,
      transformations: [{
        id: transformationId, operation: observations.length === 1 ? 'identity' : 'baseline-current comparison',
        description: record.method.notes || 'Map governed observations to the canonical measurement.',
        software: record.producer.name,
        parameters: {methodology_id:record.indicator_governance.methodology.id, methodology_version:record.indicator_governance.methodology.version},
        input_observation_ids: observations.map(function(item){ return item.id; }),
        output_measurement_fields: ['measurement.baseline','measurement.current','measurement.percent_change'],
        occurred_at: record.updated_at
      }],
      completeness_score: 100
    };
  }

  function reviewWorkflow(record){
    var evidence = record.evidence_chain.completeness_score;
    var lineage = record.observation_lineage.completeness_score;
    var flags = record.method.quality_flags || [];
    var observations = record.observation_lineage.observations || [];
    var flagged = observations.filter(function(item){ return item.quality_status === 'outlier' || item.quality_status === 'rejected'; }).length;
    var missing = observations.filter(function(item){ return item.quality_status === 'missing'; }).length;
    var completeness = Math.max(0, Math.min(100, Math.round((evidence + lineage) / 2)));
    var validity = Math.max(25, 100 - (12 * flags.length) - (12 * flagged) - (5 * missing));
    var consistency = 92 - (flags.indexOf('conflicting') >= 0 ? 35 : 0) - (record.indicator_governance.status !== 'active' ? 15 : 0);
    consistency = Math.max(25, consistency);
    var timeliness = flags.indexOf('stale') >= 0 ? 45 : 85;
    var provenance = evidence;
    var uncertainty = record.method.uncertainty ? 85 : 55;
    if (record.method.limitations.length) uncertainty = Math.min(100, uncertainty + 5);
    var overall = Math.round((completeness + validity + consistency + timeliness + provenance + uncertainty) / 6);
    return {
      schema_version: recordContract.review_workflow_contract,
      state: 'draft',
      priority: 'normal',
      assigned_reviewers: [],
      quality: {
        completeness: completeness, validity: validity, consistency: consistency, timeliness: timeliness,
        provenance: provenance, uncertainty: uncertainty, overall: overall,
        basis: {
          completeness: 'Average of evidence-chain and observation-lineage completeness.',
          validity: 'Derived from method quality flags and observation quality states.',
          consistency: 'Derived from indicator governance status and conflicting-data flags.',
          timeliness: 'Reduced when the record is explicitly marked stale.',
          provenance: 'Equal to evidence-chain completeness.',
          uncertainty: 'Higher when uncertainty and limitations are explicitly documented.'
        },
        assessed_by: 'browser-demo',
        assessed_at: record.updated_at
      },
      publication_gate: {status: 'blocked', reasons: ['record has not been approved'], approved_by: null, approved_at: null},
      revision: {number: 1, action: 'inserted', change_summary: 'Initial governed record revision.', reason: 'Initial repository registration.', changed_by: 'browser-demo', compared_to_sha256: null},
      decisions: [],
      comments: []
    };
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
    var confidenceValue = numberValue(values.confidence, 'confidence.score');
    var sourceRecord = {
      id: sourceId, name: sourceName, type: values.sourceType || 'unspecified', url: sourceUrl,
      publisher: sourcePublisher, license: nullableText(values.sourceLicense), retrieved_at: isoDateTime(values.retrievedAt),
      citation: nullableText(values.citation), checksum: validateChecksum(nullableText(values.checksum)), access_notes: nullableText(values.accessNotes)
    };
    var confidenceRecord = {score: confidenceValue, scale: '0-100', basis: nullableText(values.confidenceBasis)};
    var methodRecord = {
      notes: String(values.notes || '').trim(), assumptions: textList(values.assumptions), limitations: textList(values.limitations),
      uncertainty: nullableText(values.uncertainty), quality_flags: qualityFlags(values.qualityFlags)
    };
    var indicatorRecord = {
      id: indicatorId, name: indicatorName, unit: unit, direction: direction,
      framework: nullableText(values.framework), version: String(values.indicatorVersion || '1.0').trim() || '1.0'
    };

    var record = {
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
      indicator: indicatorRecord,
      indicator_governance: indicatorGovernance(indicatorRecord, methodRecord),
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
      source: sourceRecord,
      evidence_chain: evidenceChain(sourceRecord, methodRecord, confidenceRecord),
      confidence: confidenceRecord,
      review: {
        status: classifyReview(confidenceValue, sourceName),
        signal_status: classifySignal(change, direction),
        reviewer_notes: String(values.reviewerNotes || '').trim()
      },
      method: methodRecord,
      extensions: {
        'org.sustainablecatalyst.demo': {sample: Boolean(values.sample)}
      }
    };
    record.observation_lineage = observationLineage(record);
    record.review_workflow = reviewWorkflow(record);
    return record;
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
