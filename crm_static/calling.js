/* Calling lists and booking flow. All remote mutations have explicit user actions. */
(() => {
  let listId = localStorage.getItem('bmt-call-list') || '', queue = [], position = 0;
  let callBusy = false, importReady = false, connections = null, jobs = [], currentJob = null, bookingLead = null;
  const current = () => queue[position];
  const error = (id, message) => { $('#'+id).textContent = message || ''; $('#'+id).hidden = !message; };
  const pages = ['calling','booking','leads','calendar'];
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
    data.lists.forEach(l => select.add(new Option(`${l.name} · ${l.completed}/${l.total}`,l.id)));
    if (!data.lists.some(l => l.id===listId)) listId = data.lists[0]?.id || '';
    select.value = listId;
    if (listId) {
      const oldId = current()?.id;
      queue = (await api('/api/calling/lists/'+listId)).leads;
      const found = queue.findIndex(l => l.id===oldId);
      position = found >= 0 ? found : Math.max(0,queue.findIndex(l => !l.outcome && !['Won','Lost','Call booked'].includes(l.status)));
      localStorage.setItem('bmt-call-list',listId);
    } else queue=[];
    renderCard();
  }
  function jobFor(lead) { return jobs.find(j => j.lead_id===lead?.id); }
  function renderCard() {
    const lead = current(); $('#call-card').hidden = !lead; $('#call-empty').hidden = !!lead;
    $('#call-previous').disabled = !lead || position===0; $('#call-next').disabled = !lead || position>=queue.length-1;
    $('#call-progress').textContent = lead ? `${position+1} of ${queue.length} · ${queue.filter(l=>l.outcome).length} completed` : '';
    if (!lead) return;
    $('#call-company').textContent = lead.company;
    $('#call-location').textContent = lead.location || 'Location not recorded';
    $('#call-status').textContent = lead.outcome || lead.status;
    $('#call-phone').textContent = lead.phone || 'No phone number';
    $('#call-phone').href = 'tel:'+lead.phone.replace(/[^+\d]/g,'');
    $('#call-contact').textContent = [lead.contact,lead.email].filter(Boolean).join(' · ');
    $('#call-research').textContent = lead.need || 'No research notes yet.';
    $('#call-note').value = ''; $('#followup-date-label').hidden = true;
    const job = jobFor(lead), locked = !!job || ['Won','Lost','Call booked'].includes(lead.status);
    document.querySelectorAll('[data-outcome],#call-followup-button,#call-book').forEach(b=>b.disabled=locked);
    $('#call-job-state').textContent = job ? job.state==='complete' ? 'Meeting booked · confirmation sent.' : job.error || 'Booking in progress. Open it to review the next step.' : '';
    $('#resume-booking').hidden = !job; $('#resume-booking').textContent = job?.state==='complete' ? 'View booking' : 'Review booking';
    error('call-error','');
  }
  function canLeave() { return !$('#call-note').value.trim() || confirm('Leave these unsaved call notes?'); }
  function next() { if (position<queue.length-1) position++; renderCard(); }
  $('#call-previous').onclick=()=>{if(!callBusy && canLeave()){position--;renderCard();}};
  $('#call-next').onclick=()=>{if(!callBusy && canLeave())next();};
  $('#call-list').onchange=async()=>{
    if(callBusy || !canLeave()) {$('#call-list').value=listId;return;}
    listId=$('#call-list').value;queue=[];position=0;
    try {await refreshLists();} catch(e){error('call-error',e.message);}
  };
  $('#refresh-calls').onclick=async()=>{if(!callBusy && canLeave())try{await refreshLists();}catch(e){error('call-error',e.message);}};
  $('#call-details').onclick=()=>openLead(leads.find(l=>l.id===current().id)||current());
  async function record(outcome) {
    if(callBusy || !current())return;
    callBusy=true;document.querySelectorAll('.call-outcomes button').forEach(b=>b.disabled=true);
    const lead=current();
    try {
      await api(`/api/calling/lists/${listId}/${lead.id}/outcome`,{method:'POST',body:JSON.stringify({revision:lead.revision,outcome,note:$('#call-note').value,follow_up:$('#call-followup').value})});
      $('#call-note').value=''; await load(); await refreshLists(); next();
    } catch(e){error('call-error',e.message);}
    finally{callBusy=false; if(current()?.id===lead.id){const note=$('#call-note').value,msg=$('#call-error').textContent;renderCard();$('#call-note').value=note;error('call-error',msg);}}
  }
  document.querySelectorAll('[data-outcome]').forEach(b=>b.onclick=()=>record(b.dataset.outcome));
  $('#call-followup-button').onclick=()=>{
    if($('#followup-date-label').hidden){$('#followup-date-label').hidden=false;$('#call-followup').focus();return;}
    if(!$('#call-followup').value){error('call-error','Choose a follow-up date.');return;}
    record('Follow up');
  };
  $('#nav-calling').onclick=()=>{location.hash='calling';route();};
  async function route() {
    const target=location.hash.slice(1);
    if(target==='calling') {
      page('calling');try{await refreshLists();}catch(e){error('call-error',e.message);}
    } else if(target==='booking' && bookingLead) page('booking');
    else if(target==='booking'){location.hash='calling';}
    else {$('#calling-page').hidden=true;$('#booking-page').hidden=true;$('#nav-calling').classList.remove('active');showPage(['outreach','customers','calendar'].includes(target)?target:'prospects');}
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
    bookingLead=current();currentJob=null;bookingForm.reset();
    bf('contact').value=bookingLead.contact;bf('email').value=bookingLead.email;bf('note').value=$('#call-note').value;
    bf('zone').value=bookingLead.call_zone||'';
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
  bookingForm.oninput=previewTime;
  function showResult(job){
    currentJob=job;bookingForm.hidden=true;$('#booking-result').hidden=false;
    $('#booking-result-title').textContent=job.state==='complete'?'Meeting booked':'Booking needs attention';
    $('#booking-result-state').textContent=job.state==='complete'?'Zoom created · Google Calendar invitation sent · BMT confirmation sent.':job.error||'Booking in progress. Check the provider before retrying.';
    for(const [id,url]of[['booking-zoom',job.zoom_url],['booking-calendar',job.event_url]]){$('#'+id).hidden=!url;if(url)$('#'+id).href=url;}
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
  window.addEventListener('beforeunload',e=>{if(callBusy||$('#call-note').value.trim()){e.preventDefault();e.returnValue='';}});
  route();
})();
