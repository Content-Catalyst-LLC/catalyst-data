(function(){
  'use strict';
  function text(value){ return value == null ? '' : String(value); }
  function element(name, className, content){
    var node=document.createElement(name); if(className) node.className=className;
    if(content !== undefined) node.textContent=text(content); return node;
  }
  function cacheKey(api,limit){ return 'catalyst-data-embed:v1:'+api+':'+limit; }
  function readCache(key){
    try { var value=JSON.parse(localStorage.getItem(key)||'null'); return value && Array.isArray(value.records) ? value : null; }
    catch(error){ return null; }
  }
  function writeCache(key,payload){
    try { localStorage.setItem(key,JSON.stringify({cached_at:new Date().toISOString(),records:payload.records||[]})); }
    catch(error){ /* Browser storage is optional. */ }
  }
  function recordCard(record,index){
    var card=element('article','cdata-embed__card'); card.setAttribute('role','listitem');
    var headingId='cdata-embed-record-'+index+'-'+Math.random().toString(36).slice(2,8);
    card.setAttribute('aria-labelledby',headingId);
    card.appendChild(element('p','cdata-embed__eyebrow',record.period && record.period.label));
    var heading=element('h3','',record.entity && record.entity.name); heading.id=headingId; card.appendChild(heading);
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
    if(source.url){ var link=element('a','cdata-embed__source','View source for '+text(record.entity && record.entity.name)); link.href=source.url; link.rel='noopener noreferrer'; card.appendChild(link); }
    return card;
  }
  function setBusy(root,busy){ root.setAttribute('aria-busy',busy?'true':'false'); }
  function renderRecords(root,records,message,cached){
    var status=root.querySelector('[data-cdata-embed-status]');
    var grid=root.querySelector('[data-cdata-embed-grid]');
    grid.innerHTML='';
    records.forEach(function(record,index){ grid.appendChild(recordCard(record,index)); });
    status.textContent=message;
    root.classList.toggle('cdata-embed--cached',!!cached);
    setBusy(root,false);
  }
  function load(root){
    var api=(root.getAttribute('data-api-url') || '').replace(/\/$/,'');
    var limit=Math.min(100,Math.max(1,parseInt(root.getAttribute('data-limit') || '12',10)));
    var status=root.querySelector('[data-cdata-embed-status]');
    var key=cacheKey(api,limit);
    if(!api){ status.textContent='A Catalyst Data API URL is required.'; setBusy(root,false); return; }
    setBusy(root,true); status.textContent='Loading approved records…'; root.classList.remove('cdata-embed--cached');
    fetch(api+'/v1/records?limit='+encodeURIComponent(limit),{headers:{'Accept':'application/json'},cache:'no-store'})
      .then(function(response){ if(!response.ok) throw new Error('API returned '+response.status); return response.json(); })
      .then(function(payload){
        var records=Array.isArray(payload.records) ? payload.records : [];
        writeCache(key,{records:records});
        if(!records.length){ renderRecords(root,[],'No externally approved records are available.',false); return; }
        renderRecords(root,records,records.length+' approved record'+(records.length===1?'':'s')+' loaded.',false);
      })
      .catch(function(error){
        var cached=readCache(key);
        if(cached && cached.records.length){
          var when=cached.cached_at ? new Date(cached.cached_at).toLocaleString() : 'an earlier session';
          renderRecords(root,cached.records,'Offline fallback: showing '+cached.records.length+' cached public record'+(cached.records.length===1?'':'s')+' saved '+when+'.',true);
          return;
        }
        status.textContent='Catalyst Data is temporarily unavailable. '+error.message+' Use Retry to try again.'; setBusy(root,false);
      });
  }
  function render(root){
    var retry=root.querySelector('[data-cdata-embed-retry]');
    if(retry){ retry.addEventListener('click',function(){ load(root); }); }
    load(root);
  }
  function boot(){ document.querySelectorAll('[data-catalyst-data-embed]').forEach(render); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
