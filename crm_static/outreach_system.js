(() => {
  let data=null, filter='queue', settingsDirty=false, loading=0;
  const form=$('#system-settings');
  const date=s=>s?new Date(s).toLocaleString('en-US',{timeZone:'Etc/GMT+7',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—';
  const link=(text,url)=>{const a=el('a','',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;};
  const fail=message=>{$('#system-error').textContent=message;$('#system-error').hidden=!message;};
  async function load() {
    const ticket=++loading;
    try {const next=await api('/api/outreach-system');if(ticket!==loading)return;data=next;fail('');render();}
    catch(e){fail(e.message);}
  }
  async function write(p){await api('/api/outreach-system',{method:'POST',body:JSON.stringify(p)});await load();}
  function render() {
    const c=data.config,t=data.totals,button=$('#system-toggle');
    $('#system-running').textContent=c.enabled?'Running':'Paused';button.textContent=c.enabled?'Pause outreach':'Start outreach';button.disabled=!c.operator;
    $('#system-worker').textContent=(c.heartbeat?'Mac last connected '+date(c.heartbeat):'Mac worker not connected')+' · '+c.worker_state;
    $('#system-next').textContent=c.enabled?'Next check: '+date(c.next_run):'No messages will be sent while paused.';
    if(!c.operator)fail('This browser can view activity. Connect it using the private Mac worker connection link to control outreach.');
    const cards=$('#system-totals');cards.replaceChildren();
    for(const [value,label] of [[t.sent_today,'Sent today'],[t.confirmed_sent,'Confirmed sends'],[t.replies,'Companies replied'],[t.interested,'Interested / booking requested']]){const card=el('div','stats-card');card.append(el('strong','',value),el('span','',label));cards.append(card);}
    if(!settingsDirty){form.elements.daily_cap.value=c.daily_cap;for(const name of ['Facebook','Instagram','Skool'])form.elements.namedItem(name).checked=c.channels.includes(name);}
    form.querySelector('button').disabled=!c.operator;
    const root=$('#system-records');root.replaceChildren();
    if(filter==='replies') {
      for(const r of data.replies){const box=el('div','system-prospect');box.append(el('h3','',r.company),el('small','system-meta',r.channel+' · '+r.classification+' · detected '+date(r.observed_at)),el('p','system-reply',r.text));if(r.suggested_reply)box.append(el('strong','','Suggested reply'),el('p','system-message',r.suggested_reply));box.append(link('Open conversation ↗',r.source_url));root.append(box);}
      if(!data.replies.length)root.append(el('p','booking-hint','No replies recorded yet.'));
    } else {
      const rows=data.prospects.filter(p=>filter==='all'||(filter==='queue'?p.state==='ready':!!p.sent_at));
      for(const p of rows){const box=el('div','system-prospect');box.append(el('h3','',p.company),el('small','system-meta',`${p.location} · ${p.trade} · ${p.channel} · ${p.state}`),el('p','system-meta',p.source_type==='public_intent'?'Source: Public request for advertising help':'Source: Advertising issue'),el('p','', (p.source_type==='public_intent'?'Need expressed: ':'Observed: ')+p.issue),el('p','','Proposed improvement: '+p.improvement),el('p','system-message',p.message));const links=el('div','system-links');links.append(link(p.source_type==='public_intent'?'Agency post / ad ↗':'Ad evidence ↗',p.ad_url),link('Company website ↗',p.website),link('Profile / conversation ↗',p.profile_url));if(p.source_type==='public_intent'){box.append(el('p','system-reply',p.intent_author+': “'+p.intent_quote+'”'));links.append(link('Original comment ↗',p.intent_url));}box.append(links,el('p','system-meta','Source checked '+date(p.checked_at)+(p.sent_at?' · Sent '+date(p.sent_at):'')));if(p.stop_reason)box.append(el('p','',p.stop_reason));if(p.state==='ready'&&c.operator){const skip=el('button','','Skip this company');skip.onclick=async()=>{try{await write({op:'skip',id:p.id});}catch(e){fail(e.message);}};box.append(skip);}root.append(box);}
      if(!rows.length)root.append(el('p','booking-hint',filter==='queue'?'No qualified prospects waiting. The next run checks replies and researches new advertising opportunities.':'No confirmed sends yet.'));
    }
    const history=$('#system-runs');history.replaceChildren();
    for(const r of data.runs){const box=el('div','system-run');box.append(el('strong','',date(r.started_at)+' · '+r.state),el('p','',r.summary||'Checking replies and researching companies…'));history.append(box);}
    if(!data.runs.length)history.append(el('p','booking-hint','The first run will appear here.'));
  }
  $('#system-toggle').onclick=async()=>{if(!data)return;const b=$('#system-toggle');b.disabled=true;try{await write({op:'settings',enabled:!data.config.enabled});}catch(e){fail(e.message);b.disabled=false;}};
  form.oninput=()=>settingsDirty=true;
  form.onsubmit=async event=>{event.preventDefault();try{await write({op:'settings',daily_cap:Number(form.elements.daily_cap.value),channels:['Facebook','Instagram','Skool'].filter(n=>form.elements.namedItem(n).checked)});settingsDirty=false;$('#system-settings-state').textContent='Settings saved.';}catch(e){$('#system-settings-state').textContent=e.message;}};
  for(const b of $('#system-filters').querySelectorAll('button'))b.onclick=()=>{filter=b.dataset.filter;$('#system-filters').querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===b));if(data)render();};
  $('#system-refresh').onclick=load;document.addEventListener('crm-system-open',load);setInterval(()=>{if(location.hash==='#system')load();},30000);if(location.hash==='#system')load();
})();
