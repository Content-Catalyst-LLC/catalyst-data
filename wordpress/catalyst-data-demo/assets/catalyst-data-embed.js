(function(){
  'use strict';
  function text(value){ return value == null ? '' : String(value); }
  function element(name, className, content){
    var node=document.createElement(name); if(className) node.className=className;
    if(content !== undefined) node.textContent=text(content); return node;
  }
  function recordCard(record){
    var card=element('article','cdata-embed__card');
    card.appendChild(element('p','cdata-embed__eyebrow',record.period && record.period.label));
    card.appendChild(element('h3','',record.entity && record.entity.name));
    card.appendChild(element('p','cdata-embed__indicator',record.indicator && record.indicator.name));
    var value=element('p','cdata-embed__value');
    value.textContent=text(record.measurement && record.measurement.current)+' '+text(record.indicator && record.indicator.unit);
    card.appendChild(value);
    var meta=element('dl','cdata-embed__meta');
    [['Confidence', record.confidence && record.confidence.score],['Quality', record.review_workflow && record.review_workflow.quality && record.review_workflow.quality.overall],['Review', record.review && record.review.status]].forEach(function(pair){
      var dt=element('dt','',pair[0]); var dd=element('dd','',pair[1]); meta.appendChild(dt); meta.appendChild(dd);
    });
    card.appendChild(meta);
    var source=record.source || {};
    if(source.url){ var link=element('a','cdata-embed__source','View source'); link.href=source.url; link.rel='noopener noreferrer'; card.appendChild(link); }
    return card;
  }
  function render(root){
    var api=(root.getAttribute('data-api-url') || '').replace(/\/$/,'');
    var limit=Math.min(100,Math.max(1,parseInt(root.getAttribute('data-limit') || '12',10)));
    var status=root.querySelector('[data-cdata-embed-status]');
    var grid=root.querySelector('[data-cdata-embed-grid]');
    if(!api){ status.textContent='A Catalyst Data API URL is required.'; return; }
    status.textContent='Loading approved records…';
    fetch(api+'/v1/records?limit='+encodeURIComponent(limit),{headers:{'Accept':'application/json'}})
      .then(function(response){ if(!response.ok) throw new Error('API returned '+response.status); return response.json(); })
      .then(function(payload){
        grid.innerHTML=''; var records=Array.isArray(payload.records) ? payload.records : [];
        if(!records.length){ status.textContent='No externally approved records are available.'; return; }
        records.forEach(function(record){ grid.appendChild(recordCard(record)); });
        status.textContent=records.length+' approved record'+(records.length===1?'':'s')+' loaded.';
      })
      .catch(function(error){ status.textContent='Catalyst Data is temporarily unavailable. '+error.message; });
  }
  function boot(){ document.querySelectorAll('[data-catalyst-data-embed]').forEach(render); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
