(() => {
 const $=s=>document.querySelector(s),details=$('#sales-close-details'),schedule=$('#sales-onboarding-details'),workspace=$('#sales-close-workspace');
 const fields=['email','payment_plan','payment_reference','date','time','zone','host_id'];
 const input=k=>details.elements.namedItem(k)||schedule.elements.namedItem(k);
 let record=null,selected='',busy=false,ticket=0,preview=null,previewKind='',baseDate='';
 const daySlider=$('#sales-onboarding-day'),timeSlider=$('#sales-onboarding-time');
 const error=m=>{$('#sales-close-error').textContent=m||'';$('#sales-close-error').hidden=!m;};
 const state=m=>$('#sales-close-state').textContent=m;
 const key=id=>'bmt-close-draft:'+id;
 function values(){return Object.fromEntries(fields.map(k=>[k,input(k).value]));}
 function draft(){if(record)try{localStorage.setItem(key(record.lead_id),JSON.stringify({data:values(),revision:record.revision}));}catch(_){}}
 function invalidate(){preview=null;$('#sales-close-preview').hidden=true;draft();}
 function renderTime(){
  const z=input('zone').value;if(!BMTSalesTime.zones[z])return;
  input('date').value=BMTSalesTime.add(baseDate,Number(daySlider.value));input('time').value=BMTSalesTime.timeValue(Number(timeSlider.value));
  const days=Number(daySlider.value),label=(days===0?'Today · ':days===1?'Tomorrow · ':'')+new Intl.DateTimeFormat('en-US',{timeZone:'UTC',weekday:'short',month:'short',day:'numeric'}).format(new Date(input('date').value+'T12:00:00Z'));
  $('#sales-onboarding-date-label').textContent=label;$('#sales-onboarding-time-label').textContent=BMTSalesTime.clock(Number(timeSlider.value));
  daySlider.setAttribute('aria-valuetext',label);timeSlider.setAttribute('aria-valuetext',$('#sales-onboarding-time-label').textContent);$('#sales-onboarding-exact-date').value=input('date').value;
  try{const utc=BMTSalesTime.instant(input('date').value,input('time').value,z);$('#sales-onboarding-time-preview').textContent='Their time: '+BMTSalesTime.clock(Number(timeSlider.value))+' '+z+' · Your time: '+new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',dateStyle:'medium',timeStyle:'short'}).format(utc);}
  catch(e){$('#sales-onboarding-time-preview').textContent=e.message;}
 }
 function initializeTime(){
  const z=input('zone').value;$('#sales-company-zone').textContent=z?z+' · carried over from this prospect':'Not saved — set the company time zone on its lead record.';
  if(!BMTSalesTime.zones[z]){daySlider.disabled=timeSlider.disabled=$('#sales-time-earlier').disabled=$('#sales-time-later').disabled=true;return;}
  baseDate=BMTSalesTime.today(z);const saved=input('date').value||BMTSalesTime.add(baseDate,1);
  const days=Math.round((new Date(saved+'T12:00:00Z')-new Date(baseDate+'T12:00:00Z'))/86400000);daySlider.min=String(Math.min(0,days));daySlider.max=String(Math.max(14,days));daySlider.value=String(days);
  const t=(input('time').value||'09:00').split(':').map(Number);const minutes=t[0]*60+t[1];timeSlider.step=String(minutes%15===0?15:minutes%5===0?5:1);timeSlider.min=String(Math.min(360,minutes));timeSlider.max=String(Math.max(1200,minutes));timeSlider.value=String(minutes);$('#sales-onboarding-exact-date').min=baseDate;
  const locked=record.meeting?.state==='complete';daySlider.disabled=timeSlider.disabled=$('#sales-onboarding-exact-date').disabled=locked;$('#sales-time-earlier').disabled=$('#sales-time-later').disabled=locked;renderTime();
 }
 daySlider.oninput=timeSlider.oninput=()=>{renderTime();invalidate();};
 $('#sales-time-earlier').onclick=()=>{timeSlider.value=String(Math.max(Number(timeSlider.min),Number(timeSlider.value)-15));renderTime();invalidate();};
 $('#sales-time-later').onclick=()=>{timeSlider.value=String(Math.min(Number(timeSlider.max),Number(timeSlider.value)+15));renderTime();invalidate();};
 $('#sales-onboarding-exact-date').onchange=()=>{const date=$('#sales-onboarding-exact-date').value;if(!date||date<baseDate)return;const days=Math.round((new Date(date+'T12:00:00Z')-new Date(baseDate+'T12:00:00Z'))/86400000);daySlider.max=String(Math.max(14,days));daySlider.value=String(days);renderTime();invalidate();};
 function apply(data){
  record=data;selected=String(data.lead_id);const host=input('host_id');host.replaceChildren();for(const h of data.hosts)host.add(new Option(h.name,h.id));
  for(const k of fields)input(k).value=data.data[k]||'';
  const paid=!!data.data.payment_confirmed;$('#sales-payment-status').textContent=paid?'Payment confirmed. Customer profile created; contract awaiting signature.':'Not confirmed yet.';
  $('#sales-confirm-payment').disabled=paid;input('payment_plan').disabled=paid;$('#sales-book-onboarding').disabled=!paid||data.meeting?.state==='complete';
  const meeting=data.meeting;$('#sales-onboarding-status').textContent=meeting?meeting.state==='complete'?'Onboarding booked: '+new Intl.DateTimeFormat('en-US',{timeZone:meeting.timezone,dateStyle:'full',timeStyle:'short'}).format(new Date(meeting.start))+' · '+meeting.zone+' · 20 minutes':meeting.error||'Booking in progress. Check Zoom and Calendar.':'Not booked yet.';
  for(const k of ['date','time','zone','host_id'])input(k).disabled=meeting?.state==='complete';
  initializeTime();
  for(const e of $('#sales-receipt-upload').elements)e.disabled=!paid;
  const docs=$('#sales-close-documents');docs.replaceChildren();for(const d of data.documents){const a=document.createElement('a');a.textContent=d.kind==='Contract'?'Contract: BMT Marketing Services Agreement'+(d.default?' · included':''):d.kind+': '+d.filename;a.href='/api/leads/'+data.lead_id+'/sales-close/document/'+d.kind;a.target='_blank';a.rel='noopener';const p=document.createElement('p');p.append(a);docs.append(p);}
  const sent=data.messages.filter(m=>m.state==='sent');state(sent.length?sent.map(m=>(m.kind==='payment'?'Payment email':'Package email')+' sent.').join(' '):'Send each email when you are ready.');
 }
 async function choose(id){
  draft();const current=++ticket;record=null;selected=String(id||'');workspace.hidden=true;$('#sales-close-empty').hidden=!!id;preview=null;$('#sales-close-preview').hidden=true;error('');
  $('#sales-payment-checked').checked=false;$('#sales-receipt-upload').reset();
  if(!id)return;
  try{const data=await api('/api/leads/'+id+'/sales-close');if(current!==ticket)return;apply(data);workspace.hidden=false;
   try{const saved=JSON.parse(localStorage.getItem(key(id))||'null');if(saved&&saved.revision===data.revision){for(const k of fields)if(k!=='zone')input(k).value=saved.data[k]||'';initializeTime();}}catch(_){}
  }catch(e){if(current===ticket){workspace.hidden=false;error(e.message);}}
 }
 async function saveDetails(){
  if(!record)throw Error('Choose a booked prospect first.');if(!input('email').reportValidity()||!input('payment_plan').reportValidity())throw Error('Choose the payment option and check the email.');
  const data=await api('/api/leads/'+record.lead_id+'/sales-close',{method:'POST',body:JSON.stringify({revision:record.revision,data:values()})});apply(data);localStorage.removeItem(key(data.lead_id));return data;
 }
 async function action(fn){
  if(busy||!record)return;busy=true;workspace.inert=true;$('#sales-prospect').disabled=true;error('');state('Working…');
  try{await fn();}catch(e){error(e.message);draft();state('Not completed. Your saved details are kept.');}finally{busy=false;workspace.inert=false;$('#sales-prospect').disabled=false;}
 }
 details.oninput=schedule.oninput=invalidate;
 details.onsubmit=schedule.onsubmit=e=>{e.preventDefault();action(async()=>{await saveDetails();state('Close details saved.');});};
 async function showPreview(kind){await saveDetails();const p=await api('/api/leads/'+record.lead_id+'/sales-close/email/'+kind);preview=p;previewKind=kind;
  $('#sales-close-recipient').textContent='From: '+p.sender+' · To: '+p.to;$('#sales-close-subject').textContent=p.subject;$('#sales-close-body').textContent=p.body;$('#sales-close-attachments').textContent=p.attachments.map(d=>d.kind+': '+d.filename).join(' · ')||'No attachments';$('#sales-email-retry').checked=false;$('#sales-close-preview').hidden=false;state('Review the email, then click Send.');}
 $('#sales-preview-payment').onclick=()=>action(()=>showPreview('payment'));
 $('#sales-preview-package').onclick=()=>action(()=>showPreview('package'));
 $('#sales-close-send').onclick=()=>action(async()=>{if(!preview)throw Error('Preview the email first.');const p=preview;const data=await api('/api/leads/'+record.lead_id+'/sales-close/email/'+previewKind,{method:'POST',body:JSON.stringify({digest:p.digest,reviewed_sent_mail:$('#sales-email-retry').checked})});apply(data);preview=null;$('#sales-close-preview').hidden=true;state('Email sent to '+p.to+'.');});
 $('#sales-confirm-payment').onclick=()=>action(async()=>{
  if(!$('#sales-payment-checked').checked)throw Error('Check Stripe and tick the payment confirmation first.');
  await saveDetails();apply(await api('/api/leads/'+record.lead_id+'/sales-close/payment',{method:'POST',body:JSON.stringify({revision:record.revision,payment_received:true})}));
  await load();state('Payment confirmed. This company is now in Customers; contract awaiting signature.');
 });
 $('#sales-book-onboarding').onclick=()=>action(async()=>{await saveDetails();const data=await api('/api/leads/'+record.lead_id+'/sales-close/book',{method:'POST',body:JSON.stringify({revision:record.revision})});apply(data);if(data.meeting?.state!=='complete')throw Error(data.meeting?.error||'Booking is incomplete. Check the meeting status.');await load();state('20-minute onboarding meeting created. Add the Stripe receipt, then preview the package email. The contract is already included.');});
 for(const [id,kind] of [['sales-receipt-upload','Receipt']]){
  const form=$('#'+id);form.onsubmit=e=>{e.preventDefault();if(!form.reportValidity())return;action(async()=>{const response=await fetch('/api/leads/'+record.lead_id+'/sales-close/document/'+kind,{method:'POST',headers:{'X-CSRF-Token':$('meta[name="csrf"]').content},body:new FormData(form)});const data=await response.json();if(!response.ok)throw Error(data.error||'Upload failed.');apply(data);invalidate();form.reset();state(kind+' attached.');});};
 }
 document.addEventListener('crm-sales-prospect-selected',e=>choose(e.detail?.id||$('#sales-prospect').value));
 window.addEventListener('beforeunload',draft);
 if($('#sales-prospect').value)choose($('#sales-prospect').value);
})();
