(() => {
  let data=null, filter='queue', settingsDirty=false, loading=0, hadIssues=false;
  const drafts=new Map(),clearedDrafts=new Set();
  function draftForm(form,key){form.dataset.draftKey=key;return form;}
  function captureDrafts(){for(const f of document.querySelectorAll('form[data-draft-key]')){const key=f.dataset.draftKey;if(clearedDrafts.has(key)){drafts.delete(key);continue;}const fields=[...f.querySelectorAll('input,select,textarea')];drafts.set(key,{values:fields.map(x=>x.value),open:f.closest('details')?.open,focus:fields.indexOf(document.activeElement),start:document.activeElement?.selectionStart,end:document.activeElement?.selectionEnd});}}
  function restoreDrafts(){for(const f of document.querySelectorAll('form[data-draft-key]')){const d=drafts.get(f.dataset.draftKey);if(!d)continue;const fields=[...f.querySelectorAll('input,select,textarea')];fields.forEach((x,n)=>{if(d.values[n]!==undefined)x.value=d.values[n];});const details=f.closest('details');if(details&&d.open!==undefined)details.open=d.open;if(d.focus>=0){const active=fields[d.focus];active?.focus({preventScroll:true});if(active&&d.start!=null&&active.setSelectionRange)active.setSelectionRange(d.start,d.end);}}clearedDrafts.clear();}
  const form=$('#system-settings');
  const date=s=>s?new Date(s).toLocaleString('en-US',{timeZone:'Etc/GMT+7',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—';
  const link=(text,url)=>{const a=el('a','',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;};
  const fail=message=>{$('#system-error').textContent=message;$('#system-error').hidden=!message;};
  async function load() {
    const ticket=++loading;
    try {const next=await api('/api/outreach-system');if(ticket!==loading)return;data=next;fail('');render();}
    catch(e){fail(e.message);const b=$('#outreach-health-banner');b.hidden=false;b.className='outreach-alert-banner needs-attention';b.textContent='Outreach status unavailable. The CRM connection could not be checked; do not assume messages are being sent.';}
  }
  async function write(p){await api('/api/outreach-system',{method:'POST',body:JSON.stringify(p)});const prefix={'outcome':'outcome:','release-handoff':'handoff:','resolve-alert':'alert:','review-delivery':'delivery:'}[p.op];if(prefix)clearedDrafts.add(prefix+p.id);await load();}
  function table(headers,rows){const t=el('table',''),head=el('tr','');for(const h of headers)head.append(el('th','',h));t.append(head);for(const values of rows){const tr=el('tr','');for(const v of values)tr.append(el('td','',v??'—'));t.append(tr);}return t;}
  function outcomeForm(p){
    const details=el('details',''),form=el('form','');details.append(el('summary','','Log actual meeting / sales outcome'));draftForm(form,'outcome:'+p.id);
    const label=el('label','','Outcome'),select=el('select','');for(const name of ['Held','Closed','Lost','No-show']){const o=el('option','',name);o.value=name;select.append(o);}label.append(select);
    const timeLabel=el('label','','When it happened (your local time)'),time=el('input','');time.type='datetime-local';time.required=true;const now=new Date();time.value=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);timeLabel.append(time);
    const proofLabel=el('label','','Actual meeting / payment evidence'),proof=el('textarea','');proof.required=true;proof.minLength=20;proof.maxLength=4000;proofLabel.append(proof);
    const save=el('button','','Save outcome'),status=el('p','');save.type='submit';form.append(label,timeLabel,proofLabel,save,status);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await write({op:'outcome',id:p.id,outcome:select.value,occurred_at:new Date(time.value).toISOString(),proof:proof.value});}catch(e){status.textContent=e.message;save.disabled=false;}};details.append(form);return details;
  }
  function handoffForm(p){
    const details=el('details',''),form=el('form','');details.append(el('summary','','Resolve human handoff'));draftForm(form,'handoff:'+p.id);
    const label=el('label','','What did you resolve?'),proof=el('textarea','');proof.required=true;proof.minLength=20;label.append(proof);
    const save=el('button','','Record resolution and allow replies'),status=el('p','');save.type='submit';form.append(label,save,el('p','booking-hint','Records your resolution. A reply still requires a new unanswered inbound message and the normal checks.'),status);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await write({op:'release-handoff',id:p.id,proof:proof.value});}catch(e){status.textContent=e.message;save.disabled=false;}};details.append(form);return details;
  }
  function deliveryForm(p){
    const box=el('div','system-warning'),form=draftForm(el('form',''),'delivery:'+p.id);
    box.append(el('h3','','Review delivery · '+p.company+' · '+p.channel),el('p','system-message',p.text),link('Inspect recipient conversation ↗',p.profile_url));
    const select=el('select','');select.required=true;for(const [value,label] of [['','Choose what you verified'],['sent','Exact message is visible as sent'],['not_sent','Not sent — retire without retry']]){const o=el('option','',label);o.value=value;select.append(o);}
    const proof=el('textarea','');proof.required=true;proof.minLength=20;proof.maxLength=4000;proof.placeholder='Exact conversation link and what you verified. If delivery is still unclear, leave this unresolved.';
    const button=el('button','','Record delivery review'),status=el('p','');button.type='submit';form.append(select,proof,el('p','booking-hint','Records evidence only. This never sends a message or automatically resumes outreach.'),button,status);
    form.onsubmit=async e=>{e.preventDefault();button.disabled=true;try{await write({op:'review-delivery',kind:p.kind,id:p.id,verdict:select.value,proof:proof.value});}catch(error){status.textContent=error.message;button.disabled=false;}};box.append(form);return box;
  }
  function intelligenceView(root){
    const i=data.intelligence||{},list=i.conversations||[];
    if(filter==='conversations'||filter==='needs-reply'||filter==='conversation-archive'){
      const pending=i.needs_reply||[],ids=new Set(pending.map(x=>x.prospect_id));
      const rows=(filter==='conversation-archive'?(i.conversation_archive||[]):list).filter(p=>filter!=='needs-reply'||ids.has(p.id)||p.conversation_stage==='Human needed').sort((a,b)=>Number(ids.has(b.id))-Number(ids.has(a.id))||b.conversation_score-a.conversation_score);
      for(const p of rows){const box=el('div','system-prospect');box.append(el('h3','',p.company),el('p','system-meta',p.channel+' · '+p.conversation_stage+' · Conversation priority '+p.conversation_score+'/100 · Prospect fit '+p.priority_score+'/100'),el('p','',p.conversation_summary||'No substantive dialogue assessed yet.'),el('p','system-meta','Last thread checked '+date(p.last_thread_check)));
        const waiting=pending.filter(x=>x.prospect_id===p.id);if(waiting.length)box.append(el('strong','','Needs reply · '+waiting.length+' new message(s)'));
        const history=el('details','');history.append(el('summary','','Conversation & ranking history'),el('p','system-message','Michael · original introduction · '+date(p.sent_at)+'\n'+p.message));
        for(const message of (i.messages||[]).filter(x=>x.prospect_id===p.id))history.append(el('p',message.direction==='inbound'?'system-reply':'system-message',(message.direction==='inbound'?'Company':'Michael')+' · '+date(message.observed_at)+' · '+message.state+'\n'+message.text));
        for(const a of (i.assessments||[]).filter(x=>x.prospect_id===p.id)){history.append(el('strong','',date(a.created_at)+' · '+a.stage+' · '+a.score+'/100'),el('p','',a.summary));try{const e=JSON.parse(a.evidence);for(const [key,v] of Object.entries(e.insights||{}))if(v)history.append(el('p','',key.replaceAll('_',' ')+': '+v));for(const [key,v] of Object.entries(e.factors||{}))history.append(el('p','system-meta',key.replaceAll('_',' ')+': '+v.points+'/3 — '+v.evidence));}catch(e){}}
        box.append(history,link('Open conversation ↗',p.profile_url));if(data.config.operator){if(p.conversation_stage==='Human needed')box.append(handoffForm(p));box.append(outcomeForm(p));}root.append(box);
      }
      if(!rows.length)root.append(el('p','booking-hint',filter==='needs-reply'?'No unanswered messages or human handoffs.':'No open tracked advertising conversations yet.'));return true;
    }
    if(filter==='research'){
      for(const r of i.research||[]){const b=el('div','system-prospect');b.append(el('h3','',r.company),el('p','system-meta',r.decision+' · '+r.trade+' · '+date(r.checked_at)),el('p','',r.reason),el('p','system-meta','Review again after '+date(r.next_review)),link('Evidence ↗',r.source_url));root.append(b);}if(!(i.research||[]).length)root.append(el('p','booking-hint','Screened companies and rejection reasons will appear here.'));return true;
    }
    if(filter==='sources'){
      for(const r of i.sources||[]){const b=el('div','system-prospect');b.append(el('h3','',r.label),el('p','system-meta',r.channel+' · checked '+date(r.last_checked)),el('p','',r.notes),el('p','',r.qualified+' qualified · '+r.sent+' sent · '+r.replied+' replied · '+r.booked+' booked'),link('Open source ↗',r.url));root.append(b);}if(!(i.sources||[]).length)root.append(el('p','booking-hint','Useful agency posts and communities will be saved here.'));return true;
    }
    if(filter==='performance'){
      const f=i.funnel||{};root.append(el('h3','','All-time outreach funnel'),el('p','',`${f.screened||0} screened · ${f.rejected||0} rejected · ${f.deferred||0} need more evidence · ${f.qualified||0} qualified`),el('p','booking-hint','Rankings are evidence-based priorities, not conversion probabilities. Outcome counts are observed records; small samples do not prove a targeting rule works. Replies, imported historical conversations and new introductions are tracked separately.'));
      const wrapper=el('div','system-table-scroll');wrapper.append(table(['Source','Trade','Message','Qualified','Imported','Attempted','New intros sent','Replied','Interested','Booked','Held','Closed'],(f.segments||[]).map(r=>[r.source,r.trade,r.variant,r.qualified,r.imported||0,r.attempted,r.sent,r.replied,r.interested,r.booked,r.held,r.closed])));root.append(table(['Source','Trade','Screened','Rejected','More evidence','Qualified'],(f.screening_segments||[]).map(r=>[r.source,r.trade,r.screened,r.rejected,r.deferred,r.qualified])),wrapper,el('h3','','Observed needs & objections'),table(['Marker','Companies','Meeting interest now','Booked','Closed'],(i.marker_stats||[]).map(r=>[r.marker.replaceAll('_',' '),r.companies,r.interested,r.booked,r.closed])));
      const outbound=(i.messages||[]).filter(x=>x.direction==='outbound');root.append(el('p','',outbound.filter(x=>x.state==='sent').length+' confirmed conversation replies · '+outbound.filter(x=>x.state==='unconfirmed'||x.state==='blocked').length+' replies needing delivery review'));return true;
    }
    return false;
  }
  function renderHealth(){
    const h=data.health||{},banner=$('#outreach-health-banner'),root=$('#system-health');
    banner.replaceChildren();banner.hidden=false;banner.append(el('strong','','Outreach: '+(h.mode||'Status unknown')));
    const alerts=h.alerts||[];if(alerts.length){banner.className='outreach-alert-banner needs-attention';banner.append(el('span','',alerts.length+' issue'+(alerts.length===1?'':'s')+' need attention'),link('View issues ↗','/#system'));}else{banner.className='outreach-alert-banner';banner.append(el('span','',data.config.enabled?'Next check '+date(data.config.next_run):'Sending is paused.'));}
    root.replaceChildren();if(h.cold_outreach_held)root.append(el('p','system-warning','New introductions are held while cross-platform contact history is unavailable. Verified existing conversations on other available platforms can continue.'));
    for(const c of h.channels||[]){const box=el('div','system-prospect');box.append(el('h3','',c.channel+' · '+c.state.replaceAll('_',' ')),el('p','',c.reason),el('p','system-meta','Last checked '+date(c.checked_at)));if(c.action)box.append(el('p','','Needed: '+c.action));if(c.next_check)box.append(el('p','system-meta','Next connection check no earlier than '+date(c.next_check)));if(data.config.operator&&c.state!=='ready'){const b=el('button','','Check next run');b.onclick=async()=>{b.disabled=true;try{await write({op:'retry-channel',channel:c.channel});}catch(e){fail(e.message);b.disabled=false;}};box.append(b);}root.append(box);}
    for(const a of alerts){const box=el('div','system-warning');box.append(el('strong','',a.scope+' needs attention'),el('p','',a.reason),el('p','','Next step: '+a.action));if(a.updated_at)box.append(el('small','','Last observed '+date(a.updated_at)));if(data.config.operator&&a.scope==='System'){const form=el('form',''),input=el('textarea',''),button=el('button','','Record repair'),status=el('p','');draftForm(form,'alert:'+a.id);input.required=true;input.placeholder='What was fixed and verified?';button.type='submit';form.append(input,button,status);form.onsubmit=async e=>{e.preventDefault();try{await write({op:'resolve-alert',id:a.id,proof:input.value});}catch(error){status.textContent=error.message;}};box.append(form);}root.append(box);}
    if(data.config.operator)for(const p of data.delivery_reviews||[])root.append(deliveryForm(p));
    const issues=alerts.length+(data.delivery_reviews||[]).length;$('#system-health-count').textContent=issues?' · '+issues+' need attention':' · '+(h.available_channels||[]).length+' connected';
    if(issues&&!hadIssues)$('#system-health-details').open=true;hadIssues=issues>0;
  }
  function render() {
    captureDrafts();
    const c=data.config,t=data.totals,button=$('#system-toggle');
    renderHealth();button.textContent=c.enabled?'Pause outreach':'Start outreach';button.disabled=!c.operator;
    $('#system-worker').textContent=c.heartbeat?'Mac last connected '+date(c.heartbeat):'Mac not connected yet';
    if(!c.operator)fail('This browser can view activity. Use your existing owner browser session to control outreach. If access was lost, recover it through your authenticated Render administrator account.');
    const cards=$('#system-totals');cards.replaceChildren();
    for(const [value,label] of [[t.sent_today,'New intros today'],[t.confirmed_sent,'New intros sent'],[t.replies,'Companies replied'],[t.booked||0,'Meetings booked']]){const card=el('div','stats-card');card.append(el('strong','',value),el('span','',label));cards.append(card);}
    if(!settingsDirty){form.elements.daily_cap.value=c.daily_cap;for(const name of ['Facebook','Instagram','Skool'])form.elements.namedItem(name).checked=c.channels.includes(name);}
    form.querySelector('button').disabled=!c.operator;
    const root=$('#system-records');root.replaceChildren();
    if(intelligenceView(root)) {
    } else {
      const rows=data.prospects.filter(p=>filter==='all'||p.state==='ready').sort((a,b)=>(b.priority_score||0)-(a.priority_score||0));
      for(const p of rows){const box=el('div','system-prospect');box.append(el('h3','',p.company),el('small','system-meta',`${p.location} · ${p.trade} · ${p.channel} · ${p.state} · Fit ${p.priority_score||0}/100`),el('p','system-meta',p.source_type==='existing_conversation'?'Source: Imported advertising conversation':p.source_type==='public_intent'?'Source: Public request for advertising help':'Source: Advertising issue'),el('p','', (p.source_type==='public_intent'?'Need expressed: ':'Observed: ')+p.issue),el('p','','Proposed improvement: '+p.improvement),el('p','system-message',p.message));const links=el('div','system-links');links.append(link(p.source_type==='existing_conversation'?'Historical source / thread ↗':p.source_type==='public_intent'?'Source post / ad ↗':'Ad evidence ↗',p.ad_url),link('Company website ↗',p.website),link('Profile / conversation ↗',p.profile_url));if(p.source_type==='public_intent'){box.append(el('p','system-reply',p.intent_author+': “'+p.intent_quote+'”'));links.append(link('Original post / comment ↗',p.intent_url));}if(p.qualification){try{const q=JSON.parse(p.qualification),details=el('details','');details.append(el('summary','','Qualification evidence'));for(const [key,label] of [['usa_base','U.S. base'],['usa_operations','U.S. operations'],['trade_fit','Trade'],['advertising_need','Advertising need'],['scale_fit','Commercial fit'],['identity_match','Company identity'],['improvement_fit','How we can help']]){details.append(el('p','',label+': '+q[key]));if(q[key+'_url'])details.append(link('Verify '+label+' ↗',q[key+'_url']));}if(q.usa_base_quote)details.append(el('p','','Location excerpt: '+q.usa_base_quote));if(q.usa_operations_quote)details.append(el('p','','Operations excerpt: '+q.usa_operations_quote));if(q.review_reason)details.append(el('p','','Evidence critique: '+q.review_reason));try{for(const [k,v] of Object.entries(JSON.parse(p.ranking||'{}')))details.append(el('p','system-meta',k.replaceAll('_',' ')+': '+v.points+'/3 — '+v.evidence));}catch(e){}box.append(details);}catch(e){}}box.append(links,el('p','system-meta','Published '+date(p.source_published_at)+' · Source checked '+date(p.checked_at)+(p.sent_at?' · Sent '+date(p.sent_at):'')));if(p.stop_reason)box.append(el('p','',p.stop_reason));if(p.state==='ready'&&c.operator){const skip=el('button','','Skip this company');skip.onclick=async()=>{try{await write({op:'skip',id:p.id});}catch(e){fail(e.message);}};box.append(skip);}root.append(box);}
      if(!rows.length)root.append(el('p','booking-hint',filter==='queue'?'No qualified prospects waiting. The next run checks replies and researches new advertising opportunities.':'No confirmed sends yet.'));
    }
    const history=$('#system-runs');history.replaceChildren();
    for(const r of data.runs){const box=el('details','system-run');box.append(el('summary','',date(r.started_at)+' · '+r.state),el('p','',r.summary||'Checking replies and researching companies…'));history.append(box);}
    if(!data.runs.length)history.append(el('p','booking-hint','The first run will appear here.'));
    restoreDrafts();
  }
  $('#system-toggle').onclick=async()=>{if(!data)return;const b=$('#system-toggle');b.disabled=true;try{await write({op:'settings',enabled:!data.config.enabled});}catch(e){fail(e.message);b.disabled=false;}};
  form.oninput=()=>settingsDirty=true;
  form.onsubmit=async event=>{event.preventDefault();try{await write({op:'settings',daily_cap:Number(form.elements.daily_cap.value),channels:['Facebook','Instagram','Skool'].filter(n=>form.elements.namedItem(n).checked)});settingsDirty=false;$('#system-settings-state').textContent='Settings saved.';}catch(e){$('#system-settings-state').textContent=e.message;}};
  for(const b of $('#system-filters').querySelectorAll('[data-filter]'))b.onclick=()=>{filter=b.dataset.filter;$('#system-filters').querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x===b));if(data)render();};
  $('#system-refresh').onclick=load;document.addEventListener('crm-system-open',load);setInterval(load,30000);load();
})();
