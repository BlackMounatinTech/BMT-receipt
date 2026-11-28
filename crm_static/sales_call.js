(() => {
  const $=s=>document.querySelector(s),picker=$('#sales-prospect'),form=$('#sales-facts-form'),opening=$('#sales-opening');
  const keys=['services','service_areas','google_reviews','project_photos','sources'];
  let record=null,rows=[],ticket=0,saving=false,refreshTicket=0;
  const storageKey=id=>'bmt-sales-facts:'+id;
  const error=message=>{const e=$('#sales-prospect-error');e.textContent=message||'';e.hidden=!message;};
  const values=()=>Object.fromEntries(keys.map(k=>[k,form.elements.namedItem(k).value.trim()]));
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
  function draft(){if(record){try{localStorage.setItem(storageKey(record.lead_id),JSON.stringify({data:values(),revision:record.revision}));}catch(_){}}}
  async function choose(id){
    draft();const current=++ticket;record=null;form.reset();$('#sales-prospect-context').hidden=true;$('#sales-prospect-summary').textContent='';error('');draw();
    if(!id){localStorage.removeItem('bmt-sales-prospect');return;}
    try{
      const data=await api('/api/leads/'+id+'/sales-call');if(current!==ticket)return;
      record=data;let d=data.data,restored=false;
      try{const saved=JSON.parse(localStorage.getItem(storageKey(id))||'null');if(saved&&saved.revision===data.revision){d=saved.data;restored=true;}}catch(_){}
      for(const k of keys)form.elements.namedItem(k).value=d[k]||'';
      $('#sales-prospect-context').hidden=false;$('#sales-prospect-summary').textContent=[data.company,data.contact,data.location].filter(Boolean).join(' · ');
      $('#sales-saved-research').textContent=data.research||'No saved research notes.';
      $('#sales-facts-state').textContent=restored?'Local draft loaded. Save to sync to the CRM.':data.updated_at?'Saved company facts loaded.':'Add checked company facts to personalize the opening.';
      localStorage.setItem('bmt-sales-prospect',id);document.dispatchEvent(new Event('crm-sales-prospect-selected'));draw();
    }catch(e){if(current===ticket)error(e.message);}
  }
  async function refresh(){
    const current=++refreshTicket;$('#sales-prospects-refresh').disabled=true;error('');
    try{
      const data=await api('/api/leads');if(current!==refreshTicket)return;
      rows=data.leads.filter(l=>!l.is_test&&l.status==='Call booked'&&l.call_start_utc).sort((a,b)=>a.call_start_utc.localeCompare(b.call_start_utc));
      const selected=picker.value||localStorage.getItem('bmt-sales-prospect')||'';
      picker.replaceChildren(new Option(rows.length?'Choose a prospect from Booked':'No booked prospects yet',''));
      for(const r of rows)picker.add(new Option(r.company+(r.contact?' · '+r.contact:''),r.id));
      const id=rows.some(r=>String(r.id)===selected)?selected:'';picker.value=id;
      if(!record||String(record.lead_id)!==id)await choose(id);
    }catch(e){error(e.message);}finally{if(current===refreshTicket)$('#sales-prospects-refresh').disabled=false;}
  }
  picker.onchange=()=>choose(picker.value);
  form.oninput=()=>{draw();draft();$('#sales-facts-state').textContent='Draft kept on this device. Save company facts to sync.';};
  form.onsubmit=async e=>{
    e.preventDefault();if(!record||saving)return;const active=record,current=ticket;saving=true;form.inert=true;picker.disabled=true;error('');
    try{
      const data=await api('/api/leads/'+active.lead_id+'/sales-call',{method:'POST',body:JSON.stringify({revision:active.revision,data:values()})});
      if(current===ticket){record=data;localStorage.removeItem(storageKey(active.lead_id));$('#sales-facts-state').textContent='Saved to '+data.company+'.';}
    }catch(e){error(e.message);draft();}finally{saving=false;form.inert=false;picker.disabled=false;}
  };
  $('#sales-prospects-refresh').onclick=refresh;
  window.addEventListener('hashchange',()=>{if(location.hash==='#sales-call')refresh();else draft();});
  window.addEventListener('beforeunload',draft);
  if(location.hash==='#sales-call')refresh();
})();
