/* Calling lists and booking flow. All remote mutations have explicit user actions. */
(() => {
  let listId = localStorage.getItem('bmt-call-list') || '', queue = [], position = 0;
  let callBusy = false, importReady = false, connections = null, jobs = [], currentJob = null, bookingLead = null;
  const current = () => queue[position];
  const error = (id, message) => { $('#'+id).textContent = message || ''; $('#'+id).hidden = !message; };
  const pages = ['calling','booking','leads','calendar'];
  let noteTimer=null, noteWrites=Promise.resolve(), displayedLeadId=null;
  const noteKey=id=>'bmt-call-notes:'+id;
  function localDraft(id){try{return JSON.parse(localStorage.getItem(noteKey(id))||'null');}catch{return null;}}
  function noteState(message){$('#call-note-state').textContent=message;}
  function rememberDraft(lead,text){
    localStorage.setItem(noteKey(lead.id),JSON.stringify({text,version:lead.note_version||0}));
    noteState('Saving…');clearTimeout(noteTimer);
    noteTimer=setTimeout(()=>flushNotes().catch(e=>error('call-error',e.message)),500);
  }
  async function flushNotes(){
    clearTimeout(noteTimer);
    const lead=queue.find(l=>l.id===displayedLeadId);
    if(!lead)return noteWrites;
    const draft=localDraft(lead.id);
    if(!draft)return noteWrites;
    const text=draft.text;
    const operation=noteWrites.catch(()=>{}).then(async()=>{
      const pending=localDraft(lead.id);
      if(!pending)return;
      if(text===lead.call_notes){if(pending.text===text){localStorage.removeItem(noteKey(lead.id));if(displayedLeadId===lead.id)noteState('Saved');}return;}
      try{
        const saved=await api(`/api/calling/leads/${lead.id}/notes`,{method:'POST',body:JSON.stringify({text,version:pending.version})});
        for(const item of queue.filter(l=>l.id===lead.id)){item.call_notes=text;item.note_version=saved.version;}
        lead.call_notes=text;lead.note_version=saved.version;
        const latest=localDraft(lead.id);
        if(latest?.text===text)localStorage.removeItem(noteKey(lead.id));
        else if(latest)localStorage.setItem(noteKey(lead.id),JSON.stringify({...latest,version:saved.version}));
        if(displayedLeadId===lead.id){noteState(localDraft(lead.id)?'Saving…':'Saved');$('#restore-call-notes').hidden=true;}
      }catch(e){
        if(displayedLeadId===lead.id){noteState('Not saved to server · draft kept in this browser');$('#restore-call-notes').hidden=false;}
        throw e;
      }
    });
    noteWrites=operation;return operation;
  }
  $('#call-note').oninput=()=>{if(current())rememberDraft(current(),$('#call-note').value);};
  $('#restore-call-notes').onclick=async()=>{
    if(!current()||!confirm('Replace the draft in this box with the notes last saved on the server? Copy your draft first if you want to keep it.'))return;
    localStorage.removeItem(noteKey(current().id));noteWrites=Promise.resolve();await refreshLists();
  };
  function showCounts(counts) {
    $('#calls-today').textContent=counts.today.toLocaleString();
    $('#calls-total').textContent=counts.total.toLocaleString();
    $('#meetings-booked').textContent=counts.booked.toLocaleString();
    $('#deals-closed').textContent=counts.closes.toLocaleString();
    $('#counter-error').hidden=true;
  }
  async function refreshCounts() {
    try{showCounts(await api('/api/calling/counts'));}
    catch(e){$('#counter-error').textContent='Counter unavailable — refresh to retry.';$('#counter-error').hidden=false;}
  }
  $('#new-call-day').onclick=async()=>{
    if(callBusy || !confirm('Reset today’s cold call count to zero? Your overall total and call history will stay.'))return;
    $('#new-call-day').disabled=true;
    try{showCounts(await api('/api/calling/new-day',{method:'POST',body:'{}'}));}
    catch(e){$('#counter-error').textContent=e.message;$('#counter-error').hidden=false;}
    finally{$('#new-call-day').disabled=false;}
  };
  function page(name) {
    pages.forEach(p => $('#'+p+'-page').hidden = p !== name);
    if (['calling','booking'].includes(name)) {
      document.querySelectorAll('.main-nav button').forEach(b => b.classList.toggle('active',b.id==='nav-calling'));
    }
  }
  async function refreshLists() {
    const [data, pending] = await Promise.all([api('/api/calling/lists'),api('/api/booking/jobs')]);
    jobs = pending.jobs;
    const select = $('#call-list'); select.replaceChildren(new Option('Choose a list',''));
    for(const [label,scheduled] of [['Calling times',true],['Original imported sheets',false]]){
      const group=document.createElement('optgroup');group.label=label;
      data.lists.filter(l=>!!l.scheduled===scheduled).forEach(l=>group.append(new Option(`${scheduled?'':'Original sheet: '}${l.name} · ${l.completed}/${l.total}`,l.id)));
      select.append(group);
    }
    if (!data.lists.some(l => l.id===listId)) listId = data.lists[0]?.id || '';
    select.value = listId;
    $('#call-list-description').textContent=data.lists.find(l=>l.id===listId)?.description||'Original imported sheet. Use a calling-time list above to filter by verified opening hours.';
    if (listId) {
      const oldId = current()?.id || Number(localStorage.getItem('bmt-call-position:'+listId));
      queue = (await api('/api/calling/lists/'+listId)).leads;
      const found = queue.findIndex(l => l.id===oldId);
      position = found >= 0 ? found : Math.max(0,queue.findIndex(l => !l.outcome && !['Won','Lost','Call booked'].includes(l.status)));
      localStorage.setItem('bmt-call-list',listId);
    } else queue=[];
    renderCard();
    await refreshCounts();
  }
  function jobFor(lead) { return jobs.find(j => j.lead_id===lead?.id); }
  function updateCompanyClock(){
    const zone=current()&&BMTLeadTime.zoneFor(current());
    const clock=zone&&BMTLeadTime.clock(zone);
    $('#company-clock').textContent=clock?`Their time: ${clock.time} · ${clock.label} vs Vancouver`:'Choose the company’s time zone to show its local time.';
    const hours=BMTBusinessHours.describe(current()?.business_hours,zone);
    const status=$('#business-hours-status');status.textContent=hours.text;status.dataset.state=hours.state;
    $('#business-hours-today').textContent=hours.today||'';
    $('#business-hours-details').hidden=!hours.week.length;
    $('#business-hours-week').textContent=hours.week.join('\n');
    const source=$('#business-hours-source');
    source.textContent=hours.source?`${hours.source}${hours.checkedAt?' · '+hours.checkedAt.slice(0,10):''}`:'';
    if(/^https?:\/\//.test(hours.sourceUrl))source.href=hours.sourceUrl;else source.removeAttribute('href');
  }
  $('#company-zone').onchange=async()=>{
    const lead=current(),zone=$('#company-zone').value;
    if(!lead)return;
    if(!zone||callBusy){$('#company-zone').value=BMTLeadTime.zoneFor(lead);return;}
    $('#company-zone').disabled=true;
    try{await api(`/api/calling/leads/${lead.id}/timezone`,{method:'POST',body:JSON.stringify({zone})});lead.lead_timezone=zone;updateCompanyClock();}
    catch(e){$('#company-zone').value=BMTLeadTime.zoneFor(lead);error('call-error',e.message);}
    finally{$('#company-zone').disabled=false;}
  };
  setInterval(()=>{if(!document.hidden&&current())updateCompanyClock();},15000);
  function renderCard() {
    const lead = current(); $('#call-card').hidden = !lead; $('#call-empty').hidden = !!lead;
    $('#call-previous').disabled = !lead || position===0; $('#call-next').disabled = !lead || position>=queue.length-1;
    $('#call-progress').textContent = lead ? `${position+1} of ${queue.length} · ${queue.filter(l=>l.outcome).length} completed` : '';
    if (!lead) return;
    localStorage.setItem('bmt-call-position:'+listId,String(lead.id));
    $('#call-company').textContent = lead.company;
    $('#call-location').textContent = lead.location || 'Location not recorded';
    $('#company-zone').value=BMTLeadTime.zoneFor(lead);updateCompanyClock();
    $('#call-status').textContent = lead.outcome || lead.status;
    const last=lead.last_called_at||lead.called_at;
    $('#previous-call-banner').hidden=!last;
    $('#previous-call-details').textContent=last?`${new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',dateStyle:'full',timeStyle:'short'}).format(new Date(last))} · ${lead.last_call_outcome||lead.outcome||'Call logged'} · your time`:'';
    const homeTime=n=>{const h=Math.floor(n/60)%24,m=n%60;return `${h%12||12}${m?':'+String(m).padStart(2,'0'):''} ${h>=12?'PM':'AM'}`;};
    $('#call-opening-home').textContent=lead.opening_minute===0&&lead.closing_minute===1440?`Open 24 hours in your time · ${lead.schedule_date}`:Number.isFinite(lead.opening_minute)?`Hours in your time: ${homeTime(lead.opening_minute)}–${homeTime(lead.closing_minute)} · ${lead.schedule_date}`:'';
    $('#call-phone').textContent = lead.phone || 'No phone number';
    $('#call-phone').href = 'tel:'+lead.phone.replace(/[^+\d]/g,'');
    $('#call-contact').textContent = [lead.contact,lead.email].filter(Boolean).join(' · ');
    $('#call-research').textContent = lead.need || 'No research notes yet.';
    const site=$('#call-website');site.hidden=!/^https?:\/\//.test(lead.website||'');
    if(!site.hidden)site.href=lead.website;else site.removeAttribute('href');
    displayedLeadId=lead.id;
    const draft=localDraft(lead.id);
    $('#call-note').value=draft?.text ?? lead.call_notes ?? '';
    noteState(draft?'Draft kept in this browser · saving…':'Saved');
    $('#restore-call-notes').hidden=!draft;
    if(draft){clearTimeout(noteTimer);noteTimer=setTimeout(()=>flushNotes().catch(e=>error('call-error',e.message)),500);}
    $('#followup-date-label').hidden = true;
    $('#call-followup').value=lead.follow_up||'';
    $('#call-followup-date').textContent=lead.follow_up?'Follow up on '+lead.follow_up:lead.status==='Follow-up'?'Follow-up · No date set':'';
    const job = jobFor(lead), locked = !!job || ['Won','Lost','Call booked'].includes(lead.status);
    document.querySelectorAll('[data-outcome],#call-followup-button,#call-book,#clear-call-followup,#save-call-followup,#call-followup').forEach(b=>b.disabled=locked);
    $('#call-job-state').textContent = job ? job.state==='complete' ? 'Meeting booked · confirmation sent.' : job.error || 'Booking in progress. Open it to review the next step.' : '';
    $('#resume-booking').hidden = !job; $('#resume-booking').textContent = job?.state==='complete' ? 'View booking' : 'Review booking';
    error('call-error','');
  }
  async function canLeave() {$('#call-note').disabled=true;try{await flushNotes();return true;}catch(e){error('call-error',e.message);return false;}finally{$('#call-note').disabled=false;}}
  function next() { if (position<queue.length-1) position++; renderCard(); }
  let navigating=false;
  async function move(delta){if(callBusy||navigating)return;navigating=true;try{if(await canLeave()){position=Math.max(0,Math.min(queue.length-1,position+delta));renderCard();}}finally{navigating=false;}}
  $('#call-previous').onclick=()=>move(-1);
  $('#call-next').onclick=()=>move(1);
  $('#call-list').onchange=async()=>{
    if(callBusy || !await canLeave()) {$('#call-list').value=listId;return;}
    listId=$('#call-list').value;queue=[];position=0;
    try {await refreshLists();} catch(e){error('call-error',e.message);}
  };
  $('#refresh-calls').onclick=async()=>{if(!callBusy && await canLeave())try{await refreshLists();}catch(e){error('call-error',e.message);}};
  $('#call-details').onclick=()=>openLead(leads.find(l=>l.id===current().id)||current());
  async function record(outcome) {
    if(callBusy || !current())return;
    callBusy=true;document.querySelectorAll('.call-outcomes button,#clear-call-followup,#save-call-followup,#call-followup').forEach(b=>b.disabled=true);$('#call-note').disabled=true;
    const lead=current();
    try {
      await flushNotes();
      await api(`/api/calling/lists/${listId}/${lead.id}/outcome`,{method:'POST',body:JSON.stringify({revision:lead.revision,outcome,note:$('#call-note').value,follow_up:$('#call-followup').value})});
      $('#call-note').value=''; await load(); await refreshLists(); next();
    } catch(e){error('call-error',e.message);}
    finally{callBusy=false;$('#call-note').disabled=false; if(current()?.id===lead.id){const note=$('#call-note').value,msg=$('#call-error').textContent;renderCard();$('#call-note').value=note;error('call-error',msg);}}
  }
  document.querySelectorAll('[data-outcome]').forEach(b=>b.onclick=()=>record(b.dataset.outcome));
  $('#call-followup-button').onclick=()=>{
    $('#followup-date-label').hidden=false;$('#call-followup').focus();
  };
  $('#clear-call-followup').onclick=()=>{
    if(callBusy)return;
    $('#call-followup').value='';
    record('Follow up');
  };
  $('#save-call-followup').onclick=()=>record('Follow up');
  $('#nav-calling').onclick=()=>{if(location.hash==='#calling')route();else location.hash='calling';};
  async function route() {
    const target=location.hash.slice(1);
    if(!await canLeave()){page('calling');return;}
    if(target==='calling') {
      page('calling');try{await refreshLists();}catch(e){error('call-error',e.message);}
    } else if(target==='booking' && bookingLead) page('booking');
    else if(target==='booking'){location.hash='calling';}
    else {$('#calling-page').hidden=true;$('#booking-page').hidden=true;$('#nav-calling').classList.remove('active');showPage(['outreach','customers','calendar','followups'].includes(target)?target:'prospects');}
  }
  window.addEventListener('hashchange',route);

  const importDialog=$('#import-dialog'), importForm=$('#import-form');
  $('#upload-sheet').onclick=()=>{importForm.reset();importReady=false;$('#import-submit').textContent='Preview import';$('#import-preview').textContent='';error('import-error','');importDialog.showModal();};
  $('#close-import').onclick=()=>{if(!callBusy)importDialog.close();};
  importDialog.oncancel=e=>{if(callBusy)e.preventDefault();};
  importForm.oninput=()=>{importReady=false;$('#import-submit').textContent='Preview import';$('#import-preview').textContent='';};
  importForm.onsubmit=async e=>{
    e.preventDefault();if(callBusy)return;callBusy=true;$('#import-submit').disabled=true;error('import-error','');
    try {
      const data=new FormData(importForm);data.set('commit',String(importReady));
      const response=await fetch('/api/calling/import',{method:'POST',headers:{'X-CSRF-Token':$('meta[name=csrf]').content},body:data});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Could not import.');
      if(importReady){listId=result.list_id;queue=[];await load();await refreshLists();importDialog.close();}
      else {$('#import-preview').textContent=`${result.total} callable leads: ${result.new} new, ${result.existing} existing contacts reused. ${result.duplicates} duplicate rows and ${result.excluded} closed/booked contacts skipped.`;importReady=true;$('#import-submit').textContent='Import & start calling';}
    } catch(e){error('import-error',e.message);}
    finally{callBusy=false;$('#import-submit').disabled=false;}
  };
  async function connectionInfo() {connections=await api('/api/booking/connections');return connections;}
  $('#connection-button').onclick=async()=>{
    try {
      const c=await connectionInfo(),root=$('#connections-status');root.replaceChildren();
      for(const [label,ready] of [['Zoom',c.zoom],['Google Calendar',c.google],['Email sender: '+c.sender,c.email],['Meeting hosts',c.hosts.length]])root.append(el('p','',label+' — '+(ready?'Configured':'Needs setup')));
      root.append(el('p','booking-hint','Configured means credentials are present. A successful booking verifies the live connections.'));
      $('#connections-dialog').showModal();
    }catch(e){error('call-error',e.message);}
  };
  $('#close-connections').onclick=()=>$('#connections-dialog').close();

  const bookingForm=$('#booking-form'),bf=n=>bookingForm.elements.namedItem(n);
  $('#call-book').onclick=async()=>{
    if(callBusy)return;
    if(!await canLeave())return;
    bookingLead=current();currentJob=null;bookingForm.reset();
    bf('contact').value=bookingLead.contact;bf('email').value=bookingLead.email;bf('note').value=$('#call-note').value;
    bf('zone').value=bookingLead.call_zone||Object.keys(BMTLeadTime.labels).find(k=>BMTLeadTime.labels[k]===BMTLeadTime.zoneFor(bookingLead))||'';
    $('#booking-company').textContent=bookingLead.company;$('#booking-result').hidden=true;bookingForm.hidden=false;error('booking-error','');
    try {
      const c=await connectionInfo();bf('host_id').replaceChildren(new Option('Choose the meeting host',''));
      c.hosts.forEach(h=>bf('host_id').add(new Option(h.name+' · '+h.email,h.id)));
      if(c.hosts.length===1)bf('host_id').value=c.hosts[0].id;
      $('#booking-connections').textContent=c.ready?'Confirmation from '+c.sender:'Booking needs Zoom, Google Calendar, email and a meeting host connected. You can keep calling while these are set up.';
      $('#create-booking').disabled=!c.ready;location.hash='booking';page('booking');previewTime();
    }catch(e){error('call-error',e.message);}
  };
  function previewTime(){
    const d=bf('date').value,t=bf('time').value,z=bf('zone').value;
    if(!d||!t||!z){$('#booking-time-preview').textContent='';return;}
    const zones={'Eastern':'America/New_York','Central':'America/Chicago','Mountain':'America/Denver','Pacific (US)':'America/Los_Angeles','Arizona':'America/Phoenix','Vancouver':'Etc/GMT+7'};
    const nominal=new Date(d+'T'+t+':00Z');let utc=nominal;
    for(let i=0;i<3;i++){
      const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zones[z],year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(utc).map(p=>[p.type,p.value]));
      const shown=Date.UTC(+parts.year,+parts.month-1,+parts.day,+parts.hour,+parts.minute);
      utc=new Date(utc.getTime()+nominal.getTime()-shown);
    }
    $('#booking-time-preview').textContent=`Their time: ${d} ${t} ${z} · Your time: `+new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',dateStyle:'medium',timeStyle:'short'}).format(utc)+' Vancouver';
  }
  bookingForm.oninput=e=>{previewTime();if(e.target.name==='note'&&bookingLead){$('#call-note').value=bf('note').value;rememberDraft(bookingLead,bf('note').value);}};
  $('#booking-edit-email').onclick=async()=>{
    try{const data=await api('/api/leads');await openEmail(data.leads.find(l=>l.id===currentJob.lead_id));}
    catch(e){$('#booking-result-state').textContent=e.message;}
  };
  function showResult(job){
    currentJob=job;bookingForm.hidden=true;$('#booking-result').hidden=false;
    $('#booking-result-title').textContent=job.state==='complete'?'Meeting booked':'Booking needs attention';
    $('#booking-result-state').textContent=job.state==='complete'?'Zoom created · Google Calendar invitation sent · BMT confirmation sent.':job.error||'Booking in progress. Check the provider before retrying.';
    for(const [id,url]of[['booking-zoom',job.zoom_url],['booking-calendar',job.event_url]]){$('#'+id).hidden=!url;if(url)$('#'+id).href=url;}
    $('#booking-edit-email').hidden=job.state!=='complete';
    $('#booking-retry').hidden=job.state==='complete'||job.state==='review'||!!job.busy;
    $('#booking-abandon').hidden=job.state!=='failed'||!!job.zoom_url||!!job.busy;
    $('#booking-next').textContent=job.state==='complete'?'Next lead →':'Back to calling';
  }
  bookingForm.onsubmit=async e=>{
    e.preventDefault();if(callBusy)return;callBusy=true;$('#create-booking').disabled=true;$('#create-booking').textContent='Booking…';
    try{
      const data=Object.fromEntries(new FormData(bookingForm));Object.assign(data,{revision:bookingLead.revision,list_id:listId});
      const job=await api(`/api/leads/${bookingLead.id}/book`,{method:'POST',body:JSON.stringify(data)});
      $('#call-note').value='';showResult(job);await load();await refreshLists();
    }catch(e){error('booking-error',e.message+' If the connection was interrupted, return to Calling and review the booking before trying again.');}
    finally{callBusy=false;$('#create-booking').disabled=!connections?.ready;$('#create-booking').textContent='Book & send confirmation';}
  };
  $('#resume-booking').onclick=()=>{bookingLead=current();$('#booking-company').textContent=bookingLead.company;showResult(jobFor(bookingLead));location.hash='booking';page('booking');};
  $('#booking-retry').onclick=async()=>{
    if(callBusy)return;callBusy=true;$('#booking-retry').disabled=true;
    try{showResult(await api(`/api/booking/jobs/${currentJob.id}/resume`,{method:'POST',body:'{}'}));await load();await refreshLists();}
    catch(e){$('#booking-result-state').textContent=e.message;}
    finally{callBusy=false;$('#booking-retry').disabled=false;}
  };
  $('#booking-back').onclick=()=>{if(callBusy)return;if(!bookingForm.hidden && !confirm('Leave this booking without sending?'))return;location.hash='calling';};
  $('#booking-next').onclick=()=>{if(callBusy)return;if(currentJob?.state==='complete')next();location.hash='calling';};
  $('#booking-abandon').onclick=async()=>{
    if(callBusy)return;callBusy=true;
    try{await api(`/api/booking/jobs/${currentJob.id}/abandon`,{method:'POST',body:'{}'});await refreshLists();location.hash='calling';}
    catch(e){$('#booking-result-state').textContent=e.message;}
    finally{callBusy=false;}
  };
  window.addEventListener('beforeunload',e=>{
    const lead=queue.find(l=>l.id===displayedLeadId),draft=lead&&localDraft(lead.id);
    if(draft)fetch(`/api/calling/leads/${lead.id}/notes`,{method:'POST',keepalive:true,headers:{'Content-Type':'application/json','X-CSRF-Token':$('meta[name=csrf]').content},body:JSON.stringify({text:draft.text,version:draft.version})}).catch(()=>{});
    if(callBusy||draft){e.preventDefault();e.returnValue='';}
  });
  document.addEventListener('crm-leads-updated',refreshCounts);
  refreshCounts();
  setInterval(()=>{if(!document.hidden)refreshCounts();},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshCounts();});
  route();
})();
