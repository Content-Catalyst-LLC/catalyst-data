(function(){
  'use strict';
  function text(value){ return value === null || value === undefined || value === '' ? '—' : String(value); }
  function sourceUrl(record){ return record && record.source && record.source.url ? String(record.source.url) : ''; }
  function valueLabel(record){
    if(!record || !record.measurement) return '—';
    var value = record.measurement.current_value;
    var unit = record.indicator && record.indicator.unit ? ' ' + record.indicator.unit : '';
    return text(value) + unit;
  }
  function card(record){
    var article=document.createElement('article'); article.className='scd__card'; article.setAttribute('role','listitem');
    var eyebrow=document.createElement('p'); eyebrow.className='scd__card-eyebrow'; eyebrow.textContent=text(record.entity && record.entity.type || 'record');
    var title=document.createElement('h3'); title.textContent=text(record.entity && record.entity.name || record.record_id);
    var indicator=document.createElement('p'); indicator.className='scd__indicator'; indicator.textContent=text(record.indicator && record.indicator.name);
    var value=document.createElement('p'); value.className='scd__value'; value.textContent=valueLabel(record);
    var meta=document.createElement('dl'); meta.className='scd__meta';
    [['Period',record.period && record.period.label],['Review',record.review && record.review.status],['Confidence',record.confidence && record.confidence.score !== undefined ? record.confidence.score + '%' : null],['Source',record.source && record.source.name]].forEach(function(pair){ var dt=document.createElement('dt');dt.textContent=pair[0];var dd=document.createElement('dd');dd.textContent=text(pair[1]);meta.appendChild(dt);meta.appendChild(dd); });
    article.appendChild(eyebrow);article.appendChild(title);article.appendChild(indicator);article.appendChild(value);article.appendChild(meta);
    var url=sourceUrl(record); if(url){ var a=document.createElement('a');a.className='scd__source';a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='View source';article.appendChild(a); }
    return article;
  }
  function render(root,records,message){
    var grid=root.querySelector('[data-scd-grid]'), status=root.querySelector('[data-scd-status]'); grid.innerHTML=''; records.forEach(function(record){grid.appendChild(card(record));}); status.textContent=message; root.setAttribute('aria-busy','false');
  }
  function load(root){
    var config=window.SustainableCatalystData||{}; var status=root.querySelector('[data-scd-status]'); var limit=parseInt(root.getAttribute('data-limit')||'12',10); root.setAttribute('aria-busy','true'); status.textContent='Connecting to Catalyst Data…';
    var url=(config.recordsUrl||'') + '?limit=' + encodeURIComponent(limit);
    fetch(url,{credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(response){ if(!response.ok) return response.json().catch(function(){return {};}).then(function(payload){throw new Error(payload.message||('HTTP '+response.status));}); return response.json(); }).then(function(payload){ var records=Array.isArray(payload.records)?payload.records:[]; render(root,records,records.length ? records.length+' approved record'+(records.length===1?'':'s')+' loaded.' : 'No approved public records are available.'); }).catch(function(error){ render(root,[],'Catalyst Data is unavailable. '+error.message); });
  }
  function boot(){ document.querySelectorAll('[data-sustainable-catalyst-data]').forEach(function(root){ var retry=root.querySelector('[data-scd-retry]'); if(retry) retry.addEventListener('click',function(){load(root);}); load(root); }); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
