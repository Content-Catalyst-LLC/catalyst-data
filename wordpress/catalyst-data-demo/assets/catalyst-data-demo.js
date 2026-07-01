(function(){
  function n(value){ var x = Number(value); return Number.isFinite(x) ? x : 0; }
  function pct(x){ if (!Number.isFinite(x)) return '—'; return (x > 0 ? '+' : '') + x.toFixed(1) + '%'; }
  function classify(confidence, change, direction){
    if (confidence < 40) return 'Needs evidence';
    if (direction === 'neutral') return confidence >= 70 ? 'Reviewable' : 'Caution';
    var improving = direction === 'higher' ? change >= 0 : change <= 0;
    if (confidence >= 70 && improving) return 'Strong signal';
    if (confidence >= 55) return 'Reviewable';
    return 'Caution';
  }
  function esc(str){ return String(str).replace(/[&<>"]/g, function(ch){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]; }); }
  function build(root){
    var indicator = root.querySelector('[name="indicator"]');
    var selected = indicator.options[indicator.selectedIndex];
    var baseline = n(root.querySelector('[name="baseline"]').value);
    var current = n(root.querySelector('[name="current"]').value);
    var change = baseline === 0 ? 0 : ((current - baseline) / Math.abs(baseline)) * 100;
    var confidence = n(root.querySelector('[name="confidence"]').value);
    var direction = root.querySelector('[name="direction"]').value;
    return {
      entity: { name: root.querySelector('[name="entity"]').value.trim() || 'Unnamed entity', type: root.querySelector('[name="entityType"]').value },
      indicator: { name: indicator.value, unit: root.querySelector('[name="unit"]').value.trim() || selected.getAttribute('data-unit') || 'unit', direction: direction },
      period: root.querySelector('[name="period"]').value,
      values: { baseline: baseline, current: current, percent_change: Number(change.toFixed(2)) },
      source: { name: root.querySelector('[name="source"]').value.trim() || 'Unspecified source', type: root.querySelector('[name="sourceType"]').value },
      confidence: confidence,
      review_status: classify(confidence, change, direction),
      method_notes: root.querySelector('[name="notes"]').value.trim(),
      trace_path: ['entity','indicator','period','measurement','source','confidence','review']
    };
  }
  function update(root){
    var r = build(root);
    root.querySelector('[data-confidence-output]').textContent = r.confidence + '%';
    root.querySelector('[data-cdata-title]').textContent = r.entity.name;
    root.querySelector('[data-cdata-change]').textContent = pct(r.values.percent_change);
    root.querySelector('[data-cdata-confidence]').textContent = r.confidence + '%';
    root.querySelector('[data-cdata-status]').textContent = r.review_status;
    root.querySelector('[data-cdata-trace]').textContent = r.trace_path.join(' → ');
    root.querySelector('[data-cdata-brief]').innerHTML = '<p><strong>' + esc(r.indicator.name) + '</strong> for <strong>' + esc(r.entity.name) + '</strong> moved from ' + r.values.baseline + ' to ' + r.values.current + ' ' + esc(r.indicator.unit) + ' during ' + esc(r.period) + '.</p><p>The record is tied to <strong>' + esc(r.source.name) + '</strong> with confidence of <strong>' + r.confidence + '%</strong>. Review status: <strong>' + esc(r.review_status) + '</strong>.</p>';
    root.querySelector('[data-cdata-json]').value = JSON.stringify(r, null, 2);
  }
  function setSample(root){
    root.querySelector('[name="entity"]').value = 'Supplier Energy Transition Program';
    root.querySelector('[name="entityType"]').value = 'program';
    root.querySelector('[name="indicator"]').value = 'Estimated CO2e avoided';
    root.querySelector('[name="period"]').value = '2026-Q3';
    root.querySelector('[name="baseline"]').value = '120';
    root.querySelector('[name="current"]').value = '168';
    root.querySelector('[name="unit"]').value = 'tCO2e';
    root.querySelector('[name="direction"]').value = 'higher';
    root.querySelector('[name="source"]').value = 'Supplier energy reports + procurement audit sample';
    root.querySelector('[name="sourceType"]').value = 'internal record';
    root.querySelector('[name="confidence"]').value = '68';
    root.querySelector('[name="notes"]').value = 'Reported supplier data was sampled against procurement records. Confidence remains moderate until broader third-party verification is available.';
    update(root);
  }
  function copyJson(root){
    var text = root.querySelector('[data-cdata-json]').value;
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text);
    else { var area = root.querySelector('[data-cdata-json]'); area.focus(); area.select(); document.execCommand('copy'); }
  }
  function downloadJson(root){
    var blob = new Blob([root.querySelector('[data-cdata-json]').value], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'catalyst-data-record.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }
  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('[data-catalyst-data-demo]').forEach(function(root){
      root.querySelectorAll('input, select, textarea').forEach(function(el){
        el.addEventListener('input', function(){ update(root); });
        el.addEventListener('change', function(){
          if (el.name === 'indicator') {
            root.querySelector('[name="unit"]').value = el.options[el.selectedIndex].getAttribute('data-unit') || '';
          }
          update(root);
        });
      });
      root.querySelector('[data-cdata-sample]').addEventListener('click', function(){ setSample(root); });
      root.querySelector('[data-cdata-copy]').addEventListener('click', function(){ copyJson(root); });
      root.querySelector('[data-cdata-download]').addEventListener('click', function(){ downloadJson(root); });
      update(root);
    });
  });
})();
