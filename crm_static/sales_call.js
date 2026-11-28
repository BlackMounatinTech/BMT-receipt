(() => {
 const $=s=>document.querySelector(s),picker=$('#sales-prospect'),form=$('#sales-facts-form'),opening=$('#sales-opening'),questions=$('#sales-questions-form');
 const keys=['services','service_areas','google_reviews','project_photos','sources'];
 let record=null,ticket=0,saving=null,refreshTicket=0,definition=null,answerData={},dirty=false,stale=false,timer=null;
 const storageKey=id=>'bmt-sales-facts:'+id;
 const error=message=>{const e=$('#sales-prospect-error');e.textContent=message||'';e.hidden=!message;};
 const state=t=>{$('#sales-facts-state').textContent=t;$('#sales-answer-state').textContent=t;};
 const values=()=>Object.fromEntries(keys.map(k=>[k,form.elements.namedItem(k).value.trim()]));
 function collect(){for(const input of document.querySelectorAll('[data-sales-answer]'))answerData[input.dataset.salesAnswer]=input.value;answerData.trade=$('#sales-trade').value;return {...answerData};}
 function paragraph(text){const p=document.createElement('p');p.textContent=text;opening.append(p);}
 function draw(){
  opening.replaceChildren();if(!record){paragraph('Choose a booked prospect above to load their opening.');return;}
  const d=values();
  paragraph('“Hey, how’s it going? Good. Let’s just jump right into this.');
  paragraph(`I’ve already done some research on your company, ${record.company}. I know that you’re located in ${record.location||'[location — confirm]'}. Your services include ${d.services||'[services — confirm]'}. Here are probably a few of your service areas: ${d.service_areas||'[service areas — confirm]'}.`);
  paragraph(d.google_reviews?`I see that you have ${d.google_reviews} on Google.`:'[Google rating and review count — confirm before mentioning.]');
  if(d.project_photos==='Before-and-after photos verified')paragraph('I see that you definitely have some before-and-after photos.');
  else if(d.project_photos==='Completed-project photos verified')paragraph('I see that you have photos of your completed projects.');
  else if(!d.project_photos)paragraph('[Project photos — not checked yet. Confirm before mentioning.]');
  paragraph('Correct me if I got any of that wrong.');
  paragraph('But I do need to ask you more questions about your company, your goals, where you’re headed, and the types of jobs you actually want more of. That’ll give me a better understanding of your business so I can see what actually helps.');
  paragraph('Because when I give you our guarantee, I don’t want to be blowing smoke up your ass. I want you to understand your situation and be confident that we can deliver. Does that sound fair?”');
 }
 function draft(){if(record&&dirty){try{localStorage.setItem(storageKey(record.lead_id),JSON.stringify({data:values(),answers:collect(),revision:record.revision}));}catch(_){}}}
 function changed(){dirty=true;draw();draft();state(stale?'Older local draft. Load saved answers before saving.':'Saving answers…');clearTimeout(timer);if(!stale)timer=setTimeout(save,900);}
 function renderRows(root,items){
  root.replaceChildren();for(const [key,prompt] of items){
   const row=document.createElement('div');row.className='onboarding-row';const label=document.createElement('label');label.textContent=prompt;label.htmlFor='sales-answer-'+key;
   const input=document.createElement('textarea');input.id=label.htmlFor;input.rows=2;input.maxLength=5000;input.dataset.salesAnswer=key;input.value=answerData[key]||'';input.oninput=changed;row.append(label,input);root.append(row);
  }
 }
 function buildQuestions(){
  const trade=$('#sales-trade');trade.replaceChildren(new Option('Choose contractor type',''));
  for(const t of definition.trades)trade.add(new Option(t,t));trade.value=answerData.trade||'';
  renderRows($('#sales-common-questions'),definition.common);renderRows($('#sales-trade-questions'),definition.specific[trade.value]||[]);renderRows($('#sales-followup-questions'),definition.follow_up);
 }
 function bookedDetails(data){
  const l=data.lead||{},root=$('#sales-booked-details');root.replaceChildren();
  const p=document.createElement('p');p.textContent=[data.contact,data.phone,data.email,data.location].filter(Boolean).join(' · ');root.append(p);
  if(data.call_start_utc){const p=document.createElement('p');p.textContent='Sales call: '+new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',dateStyle:'full',timeStyle:'short'}).format(new Date(data.call_start_utc))+' · your time';root.append(p);}
  if(data.website){const a=document.createElement('a');a.href=data.website;a.textContent='Company website ↗';a.target='_blank';a.rel='noopener';root.append(a);}
  const history=(data.history||[]).map(n=>n.text).join('\n\n');$('#sales-saved-research').textContent=[data.research,data.call_notes,history].filter(Boolean).join('\n\n');
 }
 async function save(){
  clearTimeout(timer);if(saving){await saving;if(dirty&&!stale)return save();return true;}
  if(!record||!dirty)return true;if(stale){error('Your local draft is older than the saved worksheet. Load saved answers to review the current record.');return false;}
  const active=record,payload={revision:active.revision,data:values(),answers:collect()},snapshot=JSON.stringify([payload.data,payload.answers]);
  saving=(async()=>{try{
   const result=await api('/api/leads/'+active.lead_id+'/sales-call',{method:'POST',body:JSON.stringify(payload)});
   if(record?.lead_id===active.lead_id){record=result;dirty=JSON.stringify([values(),collect()])!==snapshot;
    if(dirty){draft();timer=setTimeout(save,900);}else{localStorage.removeItem(storageKey(active.lead_id));state('Saved to '+result.company+'.');}}
   return true;
  }catch(e){error(e.message);draft();state('Not saved to the CRM. Draft kept on this device.');return false;}finally{saving=null;}})();
  return saving;
 }
 async function choose(id,{reload=false}={}){
  clearTimeout(timer);
  if(!reload&&record&&dirty&&!(await save())){picker.value=String(record.lead_id);return;}
  const current=++ticket;record=null;dirty=false;stale=false;answerData={};form.reset();$('#sales-prospect-context').hidden=true;questions.hidden=true;$('#sales-questions-empty').hidden=false;$('#sales-followup-questions').replaceChildren();$('#sales-booked-details').replaceChildren();$('#sales-prospect-summary').textContent='';error('');draw();
  if(!id){localStorage.removeItem('bmt-sales-prospect');document.dispatchEvent(new CustomEvent('crm-sales-prospect-selected',{detail:{id:''}}));return;}
  try{
   const [data,defs]=await Promise.all([api('/api/leads/'+id+'/sales-call'),definition||api('/api/sales-call/questions')]);if(current!==ticket)return;
   definition=defs;record=data;let d=data.data;answerData={...(data.answers||{})};
   try{const saved=JSON.parse(localStorage.getItem(storageKey(id))||'null');if(saved&&!reload){d=saved.data;answerData=saved.answers||answerData;dirty=true;stale=saved.revision!==data.revision;}}catch(_){}
   for(const k of keys)form.elements.namedItem(k).value=d[k]||'';
   if(!answerData.trade){const text=[data.company,d.services,data.research].join(' ');answerData.trade=/excavat|grading/i.test(text)?'Excavation':/concrete/i.test(text)?'Concrete':/deck|fenc|gazebo|pergola|carpentry/i.test(text)?'Carpentry':/landscap|hardscap|paver/i.test(text)?'Landscaping':'';}
   $('#sales-prospect-context').hidden=false;questions.hidden=false;$('#sales-questions-empty').hidden=true;$('#sales-prospect-summary').textContent=[data.company,data.contact,data.location].filter(Boolean).join(' · ');
   bookedDetails(data);buildQuestions();state(stale?'Older local draft loaded. Load saved answers to review the latest CRM record.':dirty?'Local draft recovered. Save answers to sync.':'Saved company details and answers loaded.');
   localStorage.setItem('bmt-sales-prospect',id);document.dispatchEvent(new CustomEvent('crm-sales-prospect-selected',{detail:{id}}));draw();
  }catch(e){if(current===ticket)error(e.message);}
 }
 async function refresh(){
  const current=++refreshTicket;$('#sales-prospects-refresh').disabled=true;error('');
  try{
   const data=await api('/api/leads');if(current!==refreshTicket)return;
   const selected=picker.value||localStorage.getItem('bmt-sales-prospect')||'';
   const rows=data.leads.filter(l=>!l.is_test&&l.call_start_utc&&(l.status==='Call booked'||(l.status==='Won'&&String(l.id)===selected))).sort((a,b)=>a.call_start_utc.localeCompare(b.call_start_utc));
   picker.replaceChildren(new Option(rows.length?'Choose a prospect from Booked':'No booked prospects yet',''));
   for(const r of rows)picker.add(new Option(r.company+(r.contact?' · '+r.contact:''),r.id));
   const id=rows.some(r=>String(r.id)===selected)?selected:'';picker.value=id;if(!record||String(record.lead_id)!==id)await choose(id);
  }catch(e){error(e.message);}finally{if(current===refreshTicket)$('#sales-prospects-refresh').disabled=false;}
 }
 picker.onchange=()=>choose(picker.value);form.oninput=changed;form.onsubmit=questions.onsubmit=e=>{e.preventDefault();save();};
 $('#sales-trade').onchange=()=>{collect();renderRows($('#sales-trade-questions'),definition.specific[$('#sales-trade').value]||[]);changed();};
 $('#sales-answers-reload').onclick=()=>{if(record&&(!dirty||confirm('Discard the local draft and load the saved answers?'))){localStorage.removeItem(storageKey(record.lead_id));choose(String(record.lead_id),{reload:true});}};
 $('#sales-prospects-refresh').onclick=refresh;
 window.addEventListener('hashchange',()=>{if(location.hash==='#sales-call')refresh();else{draft();if(dirty&&!stale)save();}});
 window.addEventListener('beforeunload',draft);if(location.hash==='#sales-call')refresh();
})();
