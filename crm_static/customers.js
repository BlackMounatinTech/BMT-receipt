(()=>{
const dialog=$('#customer-profile');let record=null,dirty=false,ticket=0;
let salesLabels={};api('/api/sales-call/questions').then(r=>{salesLabels=Object.fromEntries([...r.common,...Object.values(r.specific).flat(),...r.follow_up]);salesLabels.trade='Contractor type';}).catch(()=>{});
let onboardingLabels={};api('/api/onboarding/fields').then(r=>{onboardingLabels=Object.fromEntries(r.fields.map(f=>[f.key,f.label]));}).catch(()=>{});
const fields=['contract_url','invoice_url','payment_url','payment_reference','payment_plan','paid_at','notes','results_from','results_to','ad_spend','qualified_leads','quotes_sent','jobs_won','job_revenue'];
const form=$('#customer-profile-form'),state=t=>$('#customer-profile-state').textContent=t;
function documents(){const root=$('#customer-documents');root.replaceChildren();for(const d of record.documents){const a=el('a','',d.kind+': '+d.filename);a.href='/api/customers/'+record.lead.id+'/documents/'+d.id;root.append(a,document.createElement('br'));}if(!record.documents.length)root.textContent='No documents attached yet.';}
function render(){
 $('#customer-profile-title').textContent=record.lead.company;$('#customer-profile-contact').textContent=[record.lead.contact,record.lead.email,record.lead.phone].filter(Boolean).join(' · ');
 for(const k of fields)form.elements[k].value=record.data[k]||'';
 const metrics=$('#customer-profile-metrics');metrics.replaceChildren();for(const [label,value]of [['Logged calls',record.calls],['Qualified leads',record.data.qualified_leads||'—'],['Jobs won',record.data.jobs_won||'—']])metrics.append(el('div','stat-card',label+': '+value));
 const prefs=$('#customer-ad-preferences');prefs.replaceChildren();if(record.onboarding){for(const[k,v]of Object.entries(record.onboarding.data)){if(v)prefs.append(el('p','',(onboardingLabels[k]||k.replaceAll('_',' '))+': '+v));}}else prefs.textContent='Complete their onboarding worksheet to save advertising preferences here.';
 if(record.discovery&&Object.values(record.discovery).some(Boolean)){prefs.append(el('h3','','Sales call answers'));for(const[k,v]of Object.entries(record.discovery)){if(v)prefs.append(el('p','',(salesLabels[k]||k.replaceAll('_',' '))+': '+v));}}
 documents();dirty=false;state('');
}
async function open(id){if(dirty&&!confirm('Discard unsaved profile changes?'))return;const n=++ticket;record=null;dirty=false;dialog.showModal();form.inert=true;$('#customer-profile-title').textContent='Loading customer…';$('#customer-profile-contact').textContent='';$('#customer-profile-metrics').replaceChildren();$('#customer-ad-preferences').replaceChildren();$('#customer-documents').replaceChildren();form.reset();state('Loading customer…');try{const r=await api('/api/customers/'+id);if(n!==ticket)return;record=r;render();}catch(e){state(e.message);}finally{form.inert=false;}}
function close(){if(dirty&&!confirm('Discard unsaved profile changes?'))return;dirty=false;++ticket;dialog.close();}
$('#customer-profile-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});form.oninput=()=>{dirty=true;};
form.onsubmit=async e=>{e.preventDefault();if(!record)return;form.inert=true;try{const data={};for(const k of fields)data[k]=form.elements[k].value;record=await api('/api/customers/'+record.lead.id,{method:'POST',body:JSON.stringify({data,revision:record.revision})});render();state('Customer profile saved.');}catch(e){state(e.message);}finally{form.inert=false;}};
$('#customer-edit-contact').onclick=()=>{if(!record)return;if(dirty&&!confirm('Discard unsaved changes?'))return;dirty=false;dialog.close();openLead(record.lead);};
$('#customer-open-onboarding').onclick=async()=>{if(!record)return;if(dirty&&!confirm('Discard unsaved changes?'))return;dirty=false;dialog.close();await window.BMTOnboarding.open(record.lead.id);};
$('#customer-document-form').onsubmit=async e=>{e.preventDefault();if(!record)return;const f=e.currentTarget;f.inert=true;try{const response=await fetch('/api/customers/'+record.lead.id+'/documents',{method:'POST',headers:{'X-CSRF-Token':$('meta[name="csrf"]').content},body:new FormData(f)});const r=await response.json();if(!response.ok)throw Error(r.error||'Upload failed');record.documents=r.documents;documents();f.reset();state('Document attached.');}catch(e){state(e.message);}finally{f.inert=false;}};
window.BMTCustomerProfile={open};
})();
