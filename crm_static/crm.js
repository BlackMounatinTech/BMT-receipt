const $ = q => document.querySelector(q);
const form = $('#lead-form'), modal = $('#editor');
let leads = [], view = 'open', editing = null, baseline = '', busy = false;
const el = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls; if (text != null) n.textContent = text; return n; };
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone:'America/Vancouver', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
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
  const shown = leads.filter(l => (view === 'open' ? !closed(l) : view === 'new' ? !closed(l) && !l.seen_at : view === 'due' ? due(l) : closed(l)) && (!query || [l.company,l.contact,l.phone,l.email,l.need].join(' ').toLowerCase().includes(query)));
  const fresh = leads.filter(l => !closed(l) && !l.seen_at).length;
  $('#new-count').textContent = fresh || '';
  $('#summary').textContent = `${leads.filter(l => !closed(l)).length} open · ${leads.filter(due).length} to follow up`;
  if (!shown.length) {
    const box = el('div', 'empty');
    box.append(el('h2','',!leads.length ? 'Add your first lead.' : 'Nothing here right now.'),el('p','',!leads.length ? 'Put in their details and a few notes. Your closer can take it from there.' : 'Try another filter or search.'));
    root.append(box);
  }
  for (const lead of shown) {
    const row = el('button','lead-row'); row.type = 'button';
    const left = el('div','lead-main'), name = el('div','company');
    if (!lead.seen_at && !closed(lead)) name.append(el('span','new-dot'));
    name.append(document.createTextNode(lead.company));
    left.append(name,el('div','sub',[lead.contact,lead.phone || lead.email].filter(Boolean).join(' · ') || 'Open to view details'));
    const right = el('div','lead-right');
    if (due(lead)) right.append(el('span','due',lead.follow_up === today() ? 'Follow up today' : 'Follow-up overdue'));
    right.append(el('span','badge' + (lead.status === 'Call booked' ? ' booked' : lead.status === 'Won' ? ' won' : ''),lead.status),el('span','chevron','›'));
    row.append(left,right); row.onclick = () => openLead(lead); root.append(row);
  }
}
async function load() {
  try { leads = (await api('/api/leads')).leads; render(); $('#error').hidden = true; $('#sync').textContent = 'Shared with your closer.'; }
  catch(e) { $('#error').textContent = e.message; $('#error').hidden = false; }
}
function callFields() { const booked = !!editing && field('status').value === 'Call booked'; $('#call-fields').hidden = !booked; field('call_date').required = booked; }
async function openLead(lead = null) {
  editing = lead; form.reset(); $('#form-error').hidden = true; $('#history').replaceChildren();
  $('#editor-title').textContent = lead ? lead.company : 'Add lead';
  $('#status-field').hidden = !lead; $('#update-fields').hidden = !lead;
  for (const name of ['company','contact','phone','email','need','follow_up','status','call_date','call_time','call_zone']) field(name).value = lead?.[name] || (name === 'status' ? 'New' : name === 'call_zone' ? 'Eastern' : '');
  $('#seen').hidden = !lead || !!lead.seen_at || $('#person').value !== 'Closer';
  $('#seen').disabled = false; $('#seen').textContent = 'Mark as seen by closer';
  callFields(); baseline = snapshot(); modal.showModal(); field('company').focus();
  if (lead) {
    try {
      const data = await api(`/api/leads/${lead.id}/notes`);
      if (editing?.id !== lead.id) return;
      for (const note of data.notes) {
        const p = el('p',''); p.append(el('small','',`${note.author} · ${new Date(note.created_at).toLocaleDateString()}`),document.createTextNode(note.text)); $('#history').append(p);
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
  if (!data.phone.trim() && !data.email.trim()) { $('#form-error').textContent = 'Add a phone number or email.'; $('#form-error').hidden = false; return; }
  busy = true; $('#save').disabled = true; $('#save').textContent = 'Saving…';
  try {
    if (editing) { data.revision = editing.revision; data.author = $('#person').value; }
    await api(editing ? `/api/leads/${editing.id}` : '/api/leads', {method:editing ? 'PATCH' : 'POST',body:JSON.stringify(data)});
    modal.close(); editing = null; await load();
  } catch(e) { $('#form-error').textContent = e.message; $('#form-error').hidden = false; }
  finally { busy = false; $('#save').disabled = false; $('#save').textContent = 'Save lead'; }
};
document.addEventListener('visibilitychange',() => { if (!document.hidden && !modal.open) load(); });
window.addEventListener('beforeunload',event => { if (modal.open && snapshot() !== baseline) { event.preventDefault(); event.returnValue=''; } });
load();
