/* Daily reports use immutable call timestamps, not the resettable header counter. */
(() => {
  const outreach = $('#stats-outreach'), discovery = $('#stats-discovery');
  const f = (form, name) => form.elements.namedItem(name);
  const money = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
  const dayLabel = d => new Date(d+'T12:00:00Z').toLocaleDateString('en-US',{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'});
  let report = null, outreachRevision = 0, outreachReady = false, outreachLoading = 0, discoveryId = null, discoveryRevision = 0;
  let reportLoading = 0;
  const status = (id, text) => { $('#'+id).textContent=text; };
  function row(root, values) { const tr=el('tr',''); for(const value of values)tr.append(el('td','',String(value)));root.append(tr); }
  async function loadStats() {
    const ticket=++reportLoading;
    try {
      status('stats-state','Loading…');
      const data=await api('/api/stats?'+new URLSearchParams({start:$('#stats-start').value,end:$('#stats-end').value}));
      if(ticket!==reportLoading)return;
      report=data; renderStats(); $('#stats-error').hidden=true; status('stats-state','Saved results · '+data.timezone);
    } catch(e) { if(ticket===reportLoading){$('#stats-error').textContent=e.message;$('#stats-error').hidden=false;status('stats-state','Could not load stats.');} }
  }
  function renderStats() {
    const t=report.totals, cards=$('#stats-cards');cards.replaceChildren();
    const rate=(a,b)=>b?Math.round(a/b*100)+'%':'—';
    for(const [value,label] of [[t.calls,'Cold calls'],[t.answered,'Answered · '+rate(t.answered,t.calls)+' of calls'],[t.no_answer,'No answer'],[t.meetings_booked,'CRM meetings booked'],[t.discoveries,'Discovery calls held'],[t.closes,'Discovery closes · '+rate(t.closes,t.discoveries)+' of held calls'],[t.discoveries?Math.round(t.minutes/t.discoveries)+' min':'—','Average discovery duration'],[money(t.collected_usd),'Management fees logged as collected']]) {
      const card=el('div','stats-card');card.append(el('strong','',value),el('span','',label));cards.append(card);
    }
    const days=$('#stats-days');days.replaceChildren();
    for(const d of report.days)row(days,[dayLabel(d.day),d.calls,d.answered,d.no_answer,d.not_interested,d.follow_up,d.booking_outcomes,d.meetings_booked,d.unknown,d.discoveries,d.closes,money(d.collected_usd)]);
    const auto=$('#stats-auto-outreach');auto.replaceChildren();
    for(const d of report.automatic_outreach||[])row(auto,[dayLabel(d.day),d.channel,d.sent,d.replies,d.interested,d.booked]);
    if(!(report.automatic_outreach||[]).length)row(auto,['No automated outreach in this range.','','','','','']);
    const out=$('#stats-outreach-rows');out.replaceChildren();
    for(const d of report.outreach)row(out,[dayLabel(d.day),d.channel,d.sent,d.replies,d.booked,d.notes]);
    if(!report.outreach.length)row(out,['No manual outreach entries in this range.','','','','','']);
    const root=$('#stats-discovery-rows');root.replaceChildren();
    for(const d of report.discovery) {
      const box=el('div','stats-discovery-row'), info=el('div','');
      info.append(el('strong','',d.company+' · '+d.outcome),el('p','',`${dayLabel(d.day)} · ${d.minutes} min · ${d.rating?'Self-rating '+d.rating+'/5':'Not rated'} · ${d.offer_presented?'Offer presented':'Offer not presented'} · ${money(d.collected_usd)} collected`));
      if(d.notes)info.append(el('p','',d.notes));
      const edit=el('button','','Edit');edit.type='button';edit.onclick=()=>editDiscovery(d);box.append(info,edit);root.append(box);
    }
    if(!report.discovery.length)root.append(el('p','booking-hint','No discovery calls logged in this range.'));
  }
  async function loadOutreach() {
    const ticket=++outreachLoading;outreachReady=false;outreach.querySelector('button[type=submit]').disabled=true;
    for(const k of ['sent','replies','booked','notes'])f(outreach,k).disabled=true;
    try {
      const d=await api('/api/stats/outreach?'+new URLSearchParams({day:f(outreach,'day').value,channel:f(outreach,'channel').value}));
      if(ticket!==outreachLoading)return;
      outreachRevision=d.revision;
      for(const name of ['sent','replies','booked','notes'])f(outreach,name).value=d[name];
      outreachReady=true;status('stats-outreach-state',d.revision?'Loaded saved daily totals.':'No entry yet.');
    } catch(e) { if(ticket===outreachLoading)status('stats-outreach-state',e.message); }
    finally { if(ticket===outreachLoading)outreach.querySelector('button[type=submit]').disabled=!outreachReady;
      if(ticket===outreachLoading)for(const k of ['sent','replies','booked','notes'])f(outreach,k).disabled=!outreachReady; }
  }
  outreach.onsubmit=async event=>{
    event.preventDefault();if(!outreachReady)return;
    const button=outreach.querySelector('button[type=submit]');button.disabled=true;outreach.inert=true;
    const p={day:f(outreach,'day').value,channel:f(outreach,'channel').value,notes:f(outreach,'notes').value,revision:outreachRevision};
    for(const k of ['sent','replies','booked'])p[k]=Number(f(outreach,k).value);
    try { const d=await api('/api/stats/outreach',{method:'POST',body:JSON.stringify(p)});outreachRevision=d.revision;status('stats-outreach-state','Saved daily outreach.');await loadStats(); }
    catch(e){status('stats-outreach-state',e.message);}finally{button.disabled=false;outreach.inert=false;}
  };
  f(outreach,'day').onchange=loadOutreach;f(outreach,'channel').onchange=loadOutreach;
  function resetDiscovery() { discovery.reset();f(discovery,'day').value=today();discoveryId=null;discoveryRevision=0;$('#stats-discovery-cancel').hidden=true;$('#stats-discovery-save').textContent='Log discovery call';status('stats-discovery-state',''); }
  function editDiscovery(d) {
    discoveryId=d.id;discoveryRevision=d.revision;
    for(const k of ['day','company','minutes','outcome','collected_usd','notes'])f(discovery,k).value=d[k];
    f(discovery,'rating').value=d.rating||'';f(discovery,'offer_presented').checked=!!d.offer_presented;
    $('#stats-discovery-cancel').hidden=false;$('#stats-discovery-save').textContent='Save discovery changes';status('stats-discovery-state','Editing '+d.company);discovery.scrollIntoView({behavior:'smooth',block:'start'});
  }
  discovery.onsubmit=async event=>{
    event.preventDefault();const button=$('#stats-discovery-save');button.disabled=true;discovery.inert=true;
    if(!discoveryId)discoveryId=crypto.randomUUID();
    const p={id:discoveryId,revision:discoveryRevision};
    for(const k of ['day','company','outcome','notes'])p[k]=f(discovery,k).value;
    p.minutes=Number(f(discovery,'minutes').value);p.collected_usd=Number(f(discovery,'collected_usd').value);p.rating=f(discovery,'rating').value?Number(f(discovery,'rating').value):null;p.offer_presented=f(discovery,'offer_presented').checked;
    try {const d=await api('/api/stats/discovery',{method:'POST',body:JSON.stringify(p)});discoveryRevision=d.revision;resetDiscovery();status('stats-discovery-state','Discovery call saved.');await loadStats();}
    catch(e){status('stats-discovery-state',e.message);}finally{button.disabled=false;discovery.inert=false;}
  };
  $('#stats-discovery-cancel').onclick=resetDiscovery;
  f(discovery,'outcome').onchange=()=>{if(f(discovery,'outcome').value==='No-show')f(discovery,'minutes').value=0;};
  $('#stats-range').onsubmit=event=>{event.preventDefault();loadStats();};$('#stats-refresh').onclick=loadStats;
  const now=today(), first=new Date(now+'T12:00:00Z');first.setUTCDate(first.getUTCDate()-29);
  $('#stats-start').value=first.toISOString().slice(0,10);$('#stats-end').value=now;f(outreach,'day').value=now;resetDiscovery();
  document.addEventListener('crm-stats-open',()=>{loadStats();if(!outreachReady)loadOutreach();});
  setInterval(()=>{if(location.hash==='#stats')loadStats();},60000);
  if(location.hash==='#stats'){loadStats();loadOutreach();}
})();
