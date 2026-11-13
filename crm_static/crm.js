const $ = q => document.querySelector(q);
const form = $('#lead-form'), modal = $('#editor');
let pipeline = ['outreach','customers','calendar'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'prospects';
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
  const pool = leads.filter(l => pipeline === 'outreach' ? l.stage === 'Outreach' && !closed(l) : pipeline === 'customers' ? l.status === 'Won' : l.stage !== 'Outreach' || closed(l));
  const shown = pool.filter(l => (pipeline === 'customers' ? true : view === 'open' ? !closed(l) : view === 'new' ? !closed(l) && !l.seen_at : view === 'due' ? due(l) : closed(l)) && (!query || [l.company,l.contact,l.phone,l.email,l.need,l.location,l.instagram,l.contact_method,l.contact_account].join(' ').toLowerCase().includes(query)));
  const fresh = leads.filter(l => l.stage !== 'Outreach' && !closed(l) && !l.seen_at).length;
  $('#new-count').textContent = fresh || '';
  $('#pipeline-title').textContent = pipeline === 'outreach' ? 'Outreach' : pipeline === 'customers' ? 'Customers' : 'Active prospects';
  $('#lead-filters').hidden = pipeline !== 'prospects';
  $('#summary').textContent = pipeline === 'outreach' ? `${pool.length} contacted · interest not yet confirmed` : pipeline === 'customers' ? `${pool.length} customers` : `${pool.filter(l=>!closed(l)).length} active · ${pool.filter(due).length} to follow up`;
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
    if (lead.contact_method) left.append(el('div','contact-trail',[lead.contact_method,lead.contact_account ? 'from '+(['Instagram DM','Facebook DM'].includes(lead.contact_method)?'@':'')+lead.contact_account.replace(/^@/,'') : '',lead.last_contacted_at ? new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',month:'short',day:'numeric'}).format(new Date(lead.last_contacted_at)) : ''].filter(Boolean).join(' · ')));
    const right = el('div','lead-right');
    if (due(lead)) right.append(el('span','due',lead.follow_up === today() ? 'Follow up today' : 'Follow-up overdue'));
    right.append(el('span','badge' + (lead.status === 'Call booked' ? ' booked' : lead.status === 'Won' ? ' won' : ''),lead.status),el('span','chevron','›'));
    row.append(left,right); row.onclick = () => openLead(lead); root.append(row);
  }
}
async function load() {
  try { leads = (await api('/api/leads')).leads; render(); renderCalendar(); $('#error').hidden = true; $('#sync').textContent = 'Saved on your shared CRM.'; }
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
  editing = lead; form.reset(); $('#form-error').hidden = true; $('#history').replaceChildren();
  $('#editor-title').textContent = lead ? lead.company : 'Add lead';
  $('#status-field').hidden = !lead; $('#update-fields').hidden = !lead;
  for (const name of ['company','contact','phone','email','need','follow_up','status','call_date','call_time','call_zone','zoom_url','instagram','location','stage','contact_method','contact_account']) field(name).value = lead?.[name] || (name === 'stage' ? (pipeline === 'outreach' ? 'Outreach' : 'Prospect') : name === 'status' ? 'New' : name === 'call_zone' ? 'Eastern' : '');
  $('#instagram-link').hidden = !lead?.instagram;
  if (lead?.instagram) $('#instagram-link').href = lead.instagram;
  $('#contact-date').hidden = !lead?.last_contacted_at;
  $('#contact-date').textContent = lead?.last_contacted_at ? 'Last contacted: '+new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',dateStyle:'medium',timeStyle:'short'}).format(new Date(lead.last_contacted_at))+' Vancouver time' : '';
  if (lead?.call_time) { const match = lead.call_time.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)?$/i); if (match) field('call_time').value = String(match[3] ? (+match[1] % 12) + (match[3].toUpperCase() === 'PM' ? 12 : 0) : +match[1]).padStart(2,'0') + ':' + match[2]; }
  $('#seen').hidden = !lead || lead.stage === 'Outreach' || !!lead.seen_at || $('#person').value !== 'Closer';
  $('#seen').disabled = false; $('#seen').textContent = 'Mark as seen by closer';
  callFields(); baseline = snapshot(); modal.showModal(); field('company').focus();
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
$('#refresh').onclick = load;
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
  if (retryKind && !confirm('Check your Sent mail first. Try sending this email again?')) return;
  emailBusy = true; $('#send-email').disabled = true; $('#send-email').textContent = 'Sending…';
  try { await api(`/api/leads/${emailLead.id}/appointment-email`,{method:'POST',body:JSON.stringify({version:emailVersion,kind:retryKind || 'confirmation',retry:!!retryKind})}); await load(); await openEmail(leads.find(l=>l.id===emailLead.id)); }
  catch(e) { $('#email-error').textContent = e.message; $('#email-error').hidden = false; $('#send-email').textContent = 'Send attempted'; retryKind = retryKind || 'confirmation'; $('#send-email').disabled = false; $('#send-email').textContent = 'Retry ' + retryKind; }
  finally { emailBusy = false; }
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
function appointments() { return leads.filter(l=>l.status==='Call booked' && l.call_start_utc).sort((a,b)=>a.call_start_utc.localeCompare(b.call_start_utc)); }
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
  pipeline=page; view='open';
  $('#leads-page').hidden=page==='calendar';$('#calendar-page').hidden=page!=='calendar';
  for (const [id,name] of [['nav-outreach','outreach'],['nav-leads','prospects'],['nav-customers','customers'],['nav-calendar','calendar']]) $('#'+id).classList.toggle('active',page===name);
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view==='open'));
  if(page==='calendar')renderCalendar();else render();
}
for (const [id,page] of [['nav-outreach','outreach'],['nav-leads','prospects'],['nav-customers','customers'],['nav-calendar','calendar']]) $('#'+id).onclick=()=>{location.hash=page;showPage(page)};
window.addEventListener('hashchange',()=>showPage(['outreach','customers','calendar'].includes(location.hash.slice(1))?location.hash.slice(1):'prospects'));
showPage(pipeline);
$('#calendar-today').onclick=()=>{calendarDay=today();calendarMonth=calendarDay.slice(0,7);renderCalendar()};
for(const [id,delta] of [['previous-month',-1],['next-month',1]])$('#'+id).onclick=()=>{const d=dayDate(calendarMonth+'-01');d.setUTCMonth(d.getUTCMonth()+delta);calendarMonth=d.toISOString().slice(0,7);renderCalendar()};
load();
