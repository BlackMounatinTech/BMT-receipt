const $ = q => document.querySelector(q);
const form = $('#lead-form'), modal = $('#editor');
let pipeline = ['outreach','customers','calendar','followups','stats','system','sales-call','onboarding'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'prospects';
let inboxRows=[], inboxView='all', inboxRefreshBusy=false;
let leads = [], view = 'open', editing = null, baseline = '', busy = false;
const el = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls; if (text != null) n.textContent = text; return n; };
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Etc/GMT+7', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
const closed = lead => ['Won', 'Lost'].includes(lead.status);
const due = lead => !closed(lead) && lead.follow_up && lead.follow_up <= today();
const field = name => form.elements.namedItem(name);
const snapshot = () => JSON.stringify(Object.fromEntries(new FormData(form)));
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type':'application/json', 'X-CSRF-Token':$('meta[name=csrf]').content, ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Could not save. Please try again.');
  return data;
}
function render() {
  const root = $('#lead-list'); root.replaceChildren();
  const query = $('#search').value.trim().toLowerCase();
  const source=pipeline==='outreach'?inboxRows:leads;
  const pool = source.filter(l => pipeline === 'followups' ? (!!l.follow_up || l.status==='Follow-up') && !closed(l) && l.status !== 'Call booked' : pipeline === 'outreach' ? true : pipeline === 'customers' ? l.status === 'Won' : l.stage === 'Prospect' || closed(l));
  if(pipeline==='followups')pool.sort((a,b)=>(a.follow_up||'9999-12-31').localeCompare(b.follow_up||'9999-12-31')||a.company.localeCompare(b.company));
  let shown = pool.filter(l => (['customers','followups','outreach'].includes(pipeline) ? true : view === 'open' ? !closed(l) : view === 'new' ? !closed(l) && !l.seen_at : view === 'due' ? due(l) : closed(l)) && (!query || [l.company,l.contact,l.phone,l.email,l.need,l.location,l.instagram,l.contact_method,l.contact_account].join(' ').toLowerCase().includes(query)));
  $('#outreach-filters').hidden = pipeline !== 'outreach';
  $('#outreach-inbox-tabs').hidden = pipeline !== 'outreach';
  $('#outreach-freshness').hidden = pipeline !== 'outreach';
  $('#outreach-check-now').hidden = pipeline !== 'outreach';
  if(pipeline==='outreach') shown=shown.filter(l=>inboxView==='all'?l.conversation_state!=='Closed':l.conversation_state===inboxView);
  if(pipeline==='outreach') shown=OutreachList.select(shown, {
    platform:$('#outreach-platform').value,status:$('#outreach-status').value,
    from:$('#outreach-from').value,to:$('#outreach-to').value,sort:$('#outreach-sort').value
  });
  const fresh = leads.filter(l => !l.is_test && l.stage !== 'Outreach' && !closed(l) && !l.seen_at).length;
  $('#new-count').textContent = fresh || '';
  $('#pipeline-title').textContent = pipeline === 'followups' ? 'Follow-ups' : pipeline === 'outreach' ? 'Outreach' : pipeline === 'customers' ? 'Customers' : 'Active prospects';
  $('#lead-filters').hidden = pipeline !== 'prospects';
  $('#summary').textContent = pipeline === 'followups' ? `${pool.filter(l=>l.follow_up).length} scheduled · ${pool.filter(l=>!l.follow_up).length} without a date · ${pool.filter(due).length} due or overdue` : pipeline === 'outreach' ? `${shown.length} of ${pool.length} conversations · ${pool.filter(l=>l.new_reply).length} new replies · ${pool.filter(l=>l.conversation_state==='Needs reply').length} need reply` : pipeline === 'customers' ? `${pool.filter(l=>!l.is_test).length} customers${pool.some(l=>l.is_test)?' · '+pool.filter(l=>l.is_test).length+' test record(s)':''}` : `${pool.filter(l=>!l.is_test&&!closed(l)).length} active · ${pool.filter(l=>!l.is_test&&due(l)).length} to follow up`;
  if (!shown.length) {
    const box = el('div', 'empty');
    box.append(el('h2','',!leads.length ? 'Add your first lead.' : 'Nothing here right now.'),el('p','',!leads.length ? 'Put in their details and a few notes. Your closer can take it from there.' : 'Try another filter or search.'));
    root.append(box);
  }
  for (const lead of shown) {
    const row = el('button','lead-row'); row.type = 'button';
    const left = el('div','lead-main'), name = el('div','company');
    if (lead.stage !== 'Outreach' && !lead.seen_at && !closed(lead)) name.append(el('span','new-dot'));
    name.append(document.createTextNode(lead.company));
    const contact = lead.phone || lead.email || (lead.instagram ? '@'+lead.instagram.split('/').filter(Boolean).at(-1) : '');
    left.append(name,el('div','sub',[lead.location,lead.contact,contact].filter(Boolean).join(' · ') || 'Open to view details'));
    if (lead.contact_method) left.append(el('div','contact-trail',[lead.contact_method,lead.contact_account ? 'from '+(['Instagram DM','Facebook DM'].includes(lead.contact_method)?'@':'')+lead.contact_account.replace(/^@/,'') : '',pipeline === 'outreach' ? '' : (lead.last_contacted_at ? OutreachList.label(lead.last_contacted_at) : '')].filter(Boolean).join(' · ')));
    if(pipeline==='outreach') {
      if(lead.new_reply) name.prepend(el('span','reply-dot'));
      if(lead.last_message) left.append(el('div','message-preview',(lead.last_message.direction==='inbound'?'Them: ':'You: ')+lead.last_message.text));
      left.append(el('div','contact-trail','Latest activity: '+activityLabel(lead.last_activity_at)));
      left.append(el('div','contact-date'+(OutreachList.day(lead.last_contacted_at)?'':' unknown'),'Last contacted: '+OutreachList.label(lead.last_contacted_at)));
      left.append(el('div','sub','Added: '+OutreachList.label(lead.created_at)));
      if(lead.follow_up) left.append(el('div','contact-trail','Follow up: '+OutreachList.label(lead.follow_up)));
    }
    const right = el('div','lead-right');
    if(pipeline==='outreach') {
      if(lead.new_reply) right.append(el('span','badge new-reply','New reply'));
      right.append(el('span','badge'+(lead.conversation_state==='Needs reply'?' needs-reply':''),lead.conversation_state));
    }
    if (due(lead)) right.append(el('span','due',lead.follow_up === today() ? 'Follow up today' : 'Follow-up overdue'));
    if (pipeline==='followups')right.append(el('span','followup-date',lead.follow_up?new Date(lead.follow_up+'T12:00:00Z').toLocaleDateString('en-US',{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'}):'No date set'));
    right.append(el('span','badge' + (lead.status === 'Call booked' ? ' booked' : lead.status === 'Won' ? ' won' : ''),lead.is_test?'Test · excluded from totals':pipeline==='outreach'?(lead.contact_method||'Platform not recorded'):lead.status),el('span','chevron','›'));
    row.append(left,right); row.onclick = () => pipeline==='customers' ? window.BMTCustomerProfile.open(lead.id) : openLead(lead); root.append(row);
  }
}
function activityLabel(value) {
  if(!value) return 'Not recorded';
  if(value.length===10) return OutreachList.label(value);
  const date=new Date(value);return Number.isNaN(date.getTime())?'Not recorded':new Intl.DateTimeFormat('en-US',{timeZone:'America/Vancouver',dateStyle:'medium',timeStyle:'short'}).format(date)+' Vancouver';
}
async function refreshInbox() {
  if(inboxRefreshBusy)return;
  inboxRefreshBusy=true;
  try {
    const data=await api('/api/outreach-inbox');inboxRows=data.conversations;
    $('#outreach-check-now').disabled=!data.operator||data.check_queued||data.check_running;
    $('#outreach-check-now').textContent=data.check_running?'Checking DMs…':data.check_queued?'DM check queued':'Check DMs';
    $('#outreach-check-now').title=data.operator?'Read-only check through your connected Mac. Does not enable scheduled outreach.':'Connect the owner session under Outreach System to request a DM check.';
    const checks=inboxRows.filter(l=>l.last_checked_at).map(l=>l.last_checked_at).sort();
    $('#outreach-freshness').textContent='CRM refreshed '+activityLabel(data.checked_at)+'. '+(checks.length?'Most recent DM check: '+activityLabel(checks.at(-1))+'. ':'No DM checks recorded yet. ')+'Refreshing this page does not check the social inboxes.'+(data.check_queued?' DM check queued; waiting for the Mac worker.':'')+(data.check_running?' A read-only DM check is running.':'');
    if(pipeline==='outreach')render();
  } catch(e){$('#outreach-freshness').textContent='Could not refresh conversations: '+e.message;}
  finally{inboxRefreshBusy=false;}
}
async function load() {
  try { leads = (await api('/api/leads')).leads; render(); renderCalendar(); await refreshInbox(); document.dispatchEvent(new Event('crm-leads-updated')); $('#error').hidden = true; $('#sync').textContent = 'Saved on your shared CRM.'; }
  catch(e) { $('#error').textContent = e.message; $('#error').hidden = false; }
}
function callFields() {
  const booked = !!editing && field('status').value === 'Call booked';
  $('#call-fields').hidden = !booked;
  field('call_date').required = booked; field('call_time').required = booked;
  $('#save').textContent = booked ? 'Save appointment' : 'Save lead';
  $('#book-appointment').hidden = !editing || booked;
  $('#show-email').hidden = !editing?.call_start_utc;
}
async function openLead(lead = null) {
  editing = lead; form.reset();
  $('#outreach-conversation').hidden=true; $('#conversation-messages').replaceChildren();
  if(lead?.conversation) {
    $('#outreach-conversation').hidden=false;
    $('#conversation-check').textContent='Last DM check: '+activityLabel(lead.last_checked_at);
    for(const message of lead.conversation) {
      const item=el('div','conversation-message '+message.direction);
      item.append(el('small','',(message.direction==='inbound'?'Them':'You')+' · '+activityLabel(message.at)+' · '+message.state),el('p','',message.text));
      $('#conversation-messages').append(item);
    }
    if(!lead.conversation.length) $('#conversation-messages').append(el('p','booking-hint','No captured messages yet. Earlier outreach details may be in the notes below.'));
    if(lead.new_reply) {
      try {await api('/api/outreach-inbox/'+lead.id+'/read',{method:'POST',body:JSON.stringify({sequence:lead.inbound_sequence})});lead.new_reply=false;render();}
      catch(e){$('#conversation-check').textContent+=' · Could not mark read: '+e.message;}
    }
  } $('#form-error').hidden = true; $('#history').replaceChildren();
  $('#editor-title').textContent = lead ? lead.company : 'Add lead';
  $('#status-field').hidden = !lead; $('#update-fields').hidden = !lead;
  for (const name of ['company','contact','phone','email','need','follow_up','status','call_date','call_time','call_zone','zoom_url','instagram','location','stage','contact_method','contact_account']) field(name).value = lead?.[name] || (name === 'stage' ? (pipeline === 'outreach' ? 'Outreach' : 'Prospect') : name === 'status' ? 'New' : name === 'call_zone' ? 'Eastern' : '');
  $('#instagram-link').hidden = !lead?.instagram;
  if (lead?.instagram) $('#instagram-link').href = lead.instagram;
  field('last_contacted_date').value = OutreachList.day(lead?.last_contacted_at);
  $('#contact-date').hidden = !lead;
  $('#contact-date').textContent = lead ? 'Last contacted: '+OutreachList.label(lead.last_contacted_at) : '';
  if (lead?.call_time) { const match = lead.call_time.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)?$/i); if (match) field('call_time').value = String(match[3] ? (+match[1] % 12) + (match[3].toUpperCase() === 'PM' ? 12 : 0) : +match[1]).padStart(2,'0') + ':' + match[2]; }
  $('#seen').hidden = !lead || lead.stage === 'Outreach' || !!lead.seen_at || $('#person').value !== 'Closer';
  $('#seen').disabled = false; $('#seen').textContent = 'Mark as seen by closer';
  callFields(); baseline = snapshot(); modal.showModal(); (lead?.conversation?$('#outreach-conversation'):field('company')).focus();
  if (lead) {
    try {
      const data = await api(`/api/leads/${lead.id}/notes`);
      if (editing?.id !== lead.id) return;
      for (const note of data.notes) {
        const p = el('p',''); p.append(el('small','',`${note.author} · ${new Date(note.created_at).toLocaleDateString('en-US',{timeZone:'Etc/GMT+7'})}`),document.createTextNode(note.text)); $('#history').append(p);
      }
    } catch(e) { $('#form-error').textContent = 'Could not load earlier updates. ' + e.message; $('#form-error').hidden = false; }
  }
}
function closeEditor() { if (busy) return; if (snapshot() !== baseline && !confirm('Discard these unsaved changes?')) return; modal.close(); editing = null; }
$('#close').onclick = $('#cancel').onclick = closeEditor;
modal.oncancel = e => { e.preventDefault(); closeEditor(); };
field('status').onchange = callFields;
$('#add').onclick = () => openLead();
$('#search').oninput = render;
for(const id of ['outreach-platform','outreach-status','outreach-from','outreach-to','outreach-sort']) $('#'+id).onchange=render;
$('#outreach-clear').onclick=()=>{
  for(const id of ['outreach-platform','outreach-status','outreach-from','outreach-to']) $('#'+id).value='';
  $('#outreach-sort').value='activity'; inboxView='all'; document.querySelectorAll('[data-inbox]').forEach(b=>b.classList.toggle('selected',b.dataset.inbox==='all')); $('#search').value=''; render();
};
$('#refresh').onclick = load;
$('#outreach-check-now').onclick=async()=>{
  $('#outreach-check-now').disabled=true;
  try{await api('/api/outreach-system',{method:'POST',body:JSON.stringify({op:'request-inbox-check'})});await refreshInbox();}
  catch(e){$('#outreach-freshness').textContent='Could not request DM check: '+e.message;$('#outreach-check-now').disabled=false;}
};
document.querySelectorAll('[data-inbox]').forEach(button=>button.onclick=()=>{inboxView=button.dataset.inbox;document.querySelectorAll('[data-inbox]').forEach(b=>b.classList.toggle('selected',b===button));render();});
setInterval(()=>{if(pipeline==='outreach'&&!document.hidden)refreshInbox();},15000);
$('#person').value = localStorage.getItem('bmt-person') === 'Closer' ? 'Closer' : 'Michael';
$('#person').onchange = () => localStorage.setItem('bmt-person',$('#person').value);
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => {
  view = button.dataset.view; document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('selected',b === button)); render();
});
$('#seen').onclick = async () => {
  if (!editing) return;
  $('#seen').disabled = true; busy = true; $('#save').disabled = true;
  try {
    await api(`/api/leads/${editing.id}/seen`,{method:'POST'}); await load();
    editing = {...editing, revision: editing.revision + 1}; $('#seen').hidden = true;
  } catch(e) { $('#seen').disabled = false; $('#form-error').textContent = e.message; $('#form-error').hidden = false; }
  finally { busy = false; $('#save').disabled = false; }
};
form.onsubmit = async event => {
  event.preventDefault(); if (busy) return;
  const data = Object.fromEntries(new FormData(form));
  if(data.status==='Won' && editing?.status!=='Won' && !confirm('Only mark this company as a customer after receiving their signed contract and payment. Have both been received?')) return;
  if(data.last_contacted_date !== OutreachList.day(editing?.last_contacted_at)) data.last_contacted_at=data.last_contacted_date;
  delete data.last_contacted_date;
  if (!data.phone.trim() && !data.email.trim() && !data.instagram.trim()) { $('#form-error').textContent = 'Add a phone number, email or Instagram profile.'; $('#form-error').hidden = false; return; }
  busy = true; $('#save').disabled = true; $('#save').textContent = 'Saving…';
  try {
    if (editing) { data.revision = editing.revision; data.author = $('#person').value; }
    const savedId = editing?.id;
    await api(editing ? `/api/leads/${editing.id}` : '/api/leads', {method:editing ? 'PATCH' : 'POST',body:JSON.stringify(data)});
    modal.close(); editing = null; await load();
    if (savedId && data.status === 'Call booked' && data.zoom_url && data.email) await openEmail(leads.find(l => l.id === savedId));
  } catch(e) { $('#form-error').textContent = e.message; $('#form-error').hidden = false; }
  finally { busy = false; $('#save').disabled = false; $('#save').textContent = 'Save lead'; }
};
document.addEventListener('visibilitychange',() => { if (!document.hidden && !modal.open) load(); });
window.addEventListener('beforeunload',event => { if (modal.open && snapshot() !== baseline) { event.preventDefault(); event.returnValue=''; } });

$('#book-appointment').onclick = () => {
  field('status').value = 'Call booked'; field('call_date').value ||= today(); callFields(); field('call_time').focus();
};
$('#show-email').onclick = () => {
  if (snapshot() !== baseline) { $('#form-error').textContent = 'Save the appointment changes first.'; $('#form-error').hidden = false; return; }
  const lead = editing; modal.close(); editing = null; openEmail(lead);
};
const emailDialog = $('#email-dialog');
let emailLead = null, emailVersion = null, retryKind = null;
async function openEmail(lead) {
  try {
    const data = await api(`/api/leads/${lead.id}/appointment-email`);
    emailLead = lead; emailVersion = data.version;
    $('#email-to').textContent = 'To: ' + data.to;
    $('#booking-correct-email').value=data.to;
    $('#email-subject').textContent = data.subject; $('#email-body').textContent = data.body;
    $('#send-email').disabled = !!data.sent_at; $('#send-email').textContent = data.sent_at ? 'Confirmation sent' : 'Send confirmation';
    $('#confirm-reply').disabled = !data.sent_at || !!data.confirmed_at;
    $('#confirm-reply').textContent = data.confirmed_at ? 'Confirmed ✓' : 'Mark confirmed after reply';
    $('#email-state').textContent = data.confirmed_at ? 'Confirmed by reply (marked manually).' : data.sent_at ? 'Email sent · awaiting their reply.' : 'Review the details, then send.';
    if (data.reminder_sent_at) $('#email-state').textContent += ' Reminder sent.';
    retryKind = data.send_states?.reminder === 'failed' ? 'reminder' : data.send_states?.confirmation === 'failed' ? 'confirmation' : null;
    if (retryKind) { $('#send-email').disabled = false; $('#send-email').textContent = 'Retry ' + retryKind; $('#email-state').textContent += ' Last ' + retryKind + ' send failed.'; }
    if (data.send_states?.confirmation === 'sending') { $('#send-email').disabled = true; $('#send-email').textContent = 'Sending / check Sent mail'; }
    $('#email-error').hidden = true; if (!emailDialog.open) emailDialog.showModal();
  } catch(e) { $('#error').textContent = e.message; $('#error').hidden = false; }
}
let emailBusy = false;
$('#close-email').onclick = () => { if (!emailBusy) emailDialog.close(); };
emailDialog.oncancel = event => { if (emailBusy) event.preventDefault(); };
$('#send-email').onclick = async () => {
  if (emailBusy) return;
  if($('#booking-correct-email').value.trim()!==emailLead.email){$('#email-error').textContent='Use Save email & resend booking to apply the corrected address.';$('#email-error').hidden=false;return;}
  if (retryKind && !confirm('Check your Sent mail first. Try sending this email again?')) return;
  emailBusy = true; $('#send-email').disabled = true; $('#send-email').textContent = 'Sending…';
  try { await api(`/api/leads/${emailLead.id}/appointment-email`,{method:'POST',body:JSON.stringify({version:emailVersion,kind:retryKind || 'confirmation',retry:!!retryKind})}); await load(); await openEmail(leads.find(l=>l.id===emailLead.id)); }
  catch(e) { $('#email-error').textContent = e.message; $('#email-error').hidden = false; $('#send-email').textContent = 'Send attempted'; retryKind = retryKind || 'confirmation'; $('#send-email').disabled = false; $('#send-email').textContent = 'Retry ' + retryKind; }
  finally { emailBusy = false; }
};
$('#correct-booking-email').onclick = async () => {
  if(emailBusy)return;
  const email=$('#booking-correct-email').value.trim();
  if(!$('#booking-correct-email').reportValidity() || !email)return;
  emailBusy=true; $('#correct-booking-email').disabled=true; $('#send-email').disabled=true; $('#confirm-reply').disabled=true;
  $('#correct-booking-email').textContent='Updating & sending…'; $('#email-error').hidden=true;
  try {
    await api(`/api/leads/${emailLead.id}/booking-email`,{method:'POST',body:JSON.stringify({version:emailVersion,email})});
    await load(); await openEmail(leads.find(l=>l.id===emailLead.id));
    $('#email-state').textContent='Booking sent to '+email+'. The time and Zoom link are unchanged.';
  } catch(e) {
    await load(); await openEmail(leads.find(l=>l.id===emailLead.id));
    $('#email-error').textContent=e.message+' Your correction is saved if the address above changed. Retry this button to finish.'; $('#email-error').hidden=false;
  } finally {emailBusy=false;$('#correct-booking-email').disabled=false;$('#correct-booking-email').textContent='Save email & resend booking';}
};
$('#confirm-reply').onclick = async () => {
  $('#confirm-reply').disabled = true;
  try { await api(`/api/leads/${emailLead.id}/confirm-appointment`,{method:'POST',body:JSON.stringify({version:emailVersion})}); await load(); await openEmail(leads.find(l=>l.id===emailLead.id)); }
  catch(e) { $('#email-error').textContent = e.message; $('#email-error').hidden = false; $('#confirm-reply').disabled = false; }
};

let calendarDay = today(), calendarMonth = calendarDay.slice(0,7);
const dayDate = day => new Date(day + 'T12:00:00Z');
const vanDate = iso => new Intl.DateTimeFormat('en-CA',{timeZone:'Etc/GMT+7',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(iso));
const vanTime = iso => new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',hour:'numeric',minute:'2-digit'}).format(new Date(iso));
function appointments() { return leads.filter(l=>!l.is_test && l.status==='Call booked' && l.call_start_utc).sort((a,b)=>a.call_start_utc.localeCompare(b.call_start_utc)); }
function renderCalendar() {
  const first = dayDate(calendarMonth+'-01'), year=first.getUTCFullYear(), month=first.getUTCMonth();
  $('#calendar-month').textContent = first.toLocaleDateString('en-US',{timeZone:'UTC',month:'long',year:'numeric'});
  const offset=(first.getUTCDay()+6)%7, count=new Date(Date.UTC(year,month+1,0)).getUTCDate();
  const grid=$('#calendar-grid');grid.replaceChildren(); const calls=appointments();
  for(let i=0;i<Math.ceil((offset+count)/7)*7;i++) {
    const date=new Date(Date.UTC(year,month,i-offset+1,12)),key=date.toISOString().slice(0,10);
    const dayCalls=calls.filter(l=>vanDate(l.call_start_utc)===key);
    const button=el('button','calendar-day'+(date.getUTCMonth()!==month?' outside':'')+(key===calendarDay?' selected':'')+(key===today()?' today':''));
    button.type='button';button.setAttribute('aria-label',date.toLocaleDateString('en-US',{timeZone:'UTC',weekday:'long',month:'long',day:'numeric'})+`, ${dayCalls.length} appointments`);
    button.append(el('span','day-number',date.getUTCDate()));
    if(dayCalls.length)button.append(el('span','calendar-call',dayCalls.length===1 ? vanTime(dayCalls[0].call_start_utc) : dayCalls.length+' calls'));
    button.onclick=()=>{calendarDay=key;calendarMonth=key.slice(0,7);renderCalendar()};grid.append(button);
  }
  $('#agenda-title').textContent=dayDate(calendarDay).toLocaleDateString('en-US',{timeZone:'UTC',weekday:'long',month:'long',day:'numeric'});
  const agenda=$('#agenda');agenda.replaceChildren();
  const dayCalls=calls.filter(l=>vanDate(l.call_start_utc)===calendarDay);
  if(!dayCalls.length)agenda.append(el('p','booking-hint','No appointments on this day. Open a lead to book one.'));
  for(const lead of dayCalls) {
    const row=el('button','lead-row');row.type='button';
    const info=el('div','lead-main');info.append(el('div','company',lead.company),el('div','sub',`${vanTime(lead.call_start_utc)} Vancouver · ${lead.call_time} ${lead.call_zone} · 30 min`));
    row.append(info,el('span','badge',lead.confirmed_at?'Confirmed':lead.confirmation_sent_at?'Awaiting reply':'Email not sent'));row.onclick=()=>openLead(lead);agenda.append(row);
  }
}
function showPage(page) {
  if (['calling','called','booked','booking'].includes(location.hash.slice(1))) return;
  $('#called-page').hidden=true;
  $('#booked-page').hidden=true;
  pipeline=page; view='open';
  $('#leads-page').hidden=['calendar','stats','system','sales-call','onboarding'].includes(page);$('#calendar-page').hidden=page!=='calendar';$('#stats-page').hidden=page!=='stats';$('#system-page').hidden=page!=='system';$('#sales-call-page').hidden=page!=='sales-call';$('#onboarding-page').hidden=page!=='onboarding';
  for (const [id,name] of [['nav-outreach','outreach'],['nav-leads','prospects'],['nav-customers','customers'],['nav-calendar','calendar'],['nav-followups','followups'],['nav-stats','stats'],['nav-system','system'],['nav-sales-call','sales-call'],['nav-onboarding','onboarding']]) $('#'+id).classList.toggle('active',page===name);
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view==='open'));
  if(page==='outreach')refreshInbox();
  if(page==='calendar')renderCalendar();else if(page==='stats')document.dispatchEvent(new Event('crm-stats-open'));else if(page==='system')document.dispatchEvent(new Event('crm-system-open'));else if(!['sales-call','onboarding'].includes(page)) render();
}
for (const [id,page] of [['nav-outreach','outreach'],['nav-leads','prospects'],['nav-customers','customers'],['nav-calendar','calendar'],['nav-followups','followups'],['nav-stats','stats'],['nav-system','system'],['nav-sales-call','sales-call'],['nav-onboarding','onboarding']]) $('#'+id).onclick=()=>{location.hash=page;showPage(page)};
window.addEventListener('hashchange',()=>showPage(['outreach','customers','calendar','followups','stats','system','sales-call','onboarding'].includes(location.hash.slice(1))?location.hash.slice(1):'prospects'));
showPage(pipeline);
$('#calendar-today').onclick=()=>{calendarDay=today();calendarMonth=calendarDay.slice(0,7);renderCalendar()};
for(const [id,delta] of [['previous-month',-1],['next-month',1]])$('#'+id).onclick=()=>{const d=dayDate(calendarMonth+'-01');d.setUTCMonth(d.getUTCMonth()+delta);calendarMonth=d.toISOString().slice(0,7);renderCalendar()};
load();
