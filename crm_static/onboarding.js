/* One durable worksheet per CRM company; local drafts never switch company IDs. */
(() => {
  const form=$('#onboarding-form'), top=$('#onboarding-customer'), bottom=$('#onboarding-customer-bottom');
  let fields=[], companies=[], record=null, loading=0, saving=false, dirty=false, draftRevision=0;
  const draftKey=id=>'bmt-onboarding-draft:'+id;
  const state=text=>{$('#onboarding-state').textContent=text;$('#onboarding-bottom-state').textContent=text;};
  const error=text=>{$('#onboarding-error').textContent=text;$('#onboarding-error').hidden=!text;};
  function answers(){return Object.fromEntries(fields.map(f=>[f.key,form.elements.namedItem(f.key)?.value||'']));}
  function keepDraft(){
    if(!record||!dirty)return;
    try{localStorage.setItem(draftKey(record.lead_id),JSON.stringify({data:answers(),revision:draftRevision}));}catch(_){state('Unsaved changes. Save the worksheet before leaving.');}
  }
  function syncPickers(id){top.value=String(id||'');bottom.value=String(id||'');}
  function pickers(){
    for(const select of [top,bottom]){
      select.replaceChildren(new Option('Choose a customer',''));
      for(const [label,items] of [['Customers',companies.filter(l=>l.status==='Won')]]){
        if(!items.length)continue;
        const group=document.createElement('optgroup');group.label=label;
        for(const l of items.sort((a,b)=>a.company.localeCompare(b.company)))group.append(new Option(l.company,String(l.id)));
        select.append(group);
      }
    }
    syncPickers(record?.lead_id);
  }
  const accessHelp='Have the client share their screen and sign in themselves. In their Meta business settings, add BMT as a partner using BMT’s business portfolio ID, then share the Page, Instagram, ad account, lead access, and tracking assets needed. Give campaign-management permissions; only request admin control if a specific setup task requires it. Keep ownership and billing with the client. Verify access from BMT before marking it verified. Never enter passwords, payment-card details, or verification codes in this worksheet.';
  function build(){
    const root=$('#onboarding-questions');root.replaceChildren();let section=null;
    for(const f of fields){
      if(f.section!==section){section=f.section;const h=el('h2','onboarding-section-title',section);root.append(h);
        if(section.startsWith('2.'))root.append(el('p','onboarding-access-help',accessHelp));
        if(section==='Customer & call record')root.append(el('p','booking-hint','These fields record the existing agreement, payment, and meeting. Saving does not charge Stripe, create a Zoom meeting, or send an email.'));
      }
      const row=el('div','onboarding-row'), prompt=el('div','onboarding-prompt');
      const id='onboarding-'+f.key;const label=el('label','',f.label);label.htmlFor=id;
      prompt.append(label,el('p','',f.prompt));
      let input;
      if(f.options.length){input=document.createElement('select');input.append(new Option('Choose an answer',''));for(const option of f.options)input.append(new Option(option,option));}
      else{input=document.createElement(f.type==='textarea'?'textarea':'input');if(f.type!=='textarea')input.type=f.type;else input.rows=3;input.maxLength=5000;if(f.type==='number'){input.min='0';input.step='0.01';}}
      input.name=f.key;input.id=id;input.value=record.data[f.key]||'';
      row.append(prompt,input);root.append(row);
    }
  }
  async function refresh(){
    try{const [a,b]=await Promise.all([api('/api/onboarding/fields'),api('/api/customers')]);fields=a.fields;companies=b.customers;
      if(record&&!companies.some(l=>l.id===record.lead_id)){keepDraft();record=null;dirty=false;form.hidden=true;$('#onboarding-empty').hidden=false;$('#onboarding-customer-summary').textContent='';state('This company is no longer in Customers.');}
      pickers();error('');
      $('#onboarding-empty').textContent=companies.length?'Choose a customer to load their saved onboarding details.':'No customers yet. After a prospect signs and pays, confirm their purchase in Sales Call. They will then appear here.';
      if(!record){let last='';try{last=localStorage.getItem('bmt-onboarding-customer')||'';}catch(_){}if([...top.options].some(o=>o.value===last)&&last)await choose(last);}
    }
    catch(e){error(e.message);}
  }
  async function choose(id){
    if(saving){syncPickers(record?.lead_id);return;}
    keepDraft();const ticket=++loading;dirty=false;record=null;form.hidden=true;$('#onboarding-empty').hidden=!!id;syncPickers(id);error('');
    try{if(id)localStorage.setItem('bmt-onboarding-customer',id);else localStorage.removeItem('bmt-onboarding-customer');}catch(_){}
    $('#onboarding-customer-summary').textContent='';
    if(!id){state('Choose a company to begin.');return;}
    state('Loading worksheet…');
    try{
      const data=await api('/api/leads/'+id+'/onboarding');if(ticket!==loading)return;
      record=data;draftRevision=data.revision;let restored=false,stale=false;
      try{const draft=JSON.parse(localStorage.getItem(draftKey(id))||'null');if(draft){restored=true;draftRevision=draft.revision;stale=draftRevision!==data.revision;record.data={...record.data,...draft.data};dirty=true;}}catch(_){}
      build();form.hidden=false;syncPickers(id);
      $('#onboarding-customer-summary').textContent=record.company+(record.customer?' · Customer':' · Prospect');
      state(stale?'Recovered a local draft, but a newer worksheet exists on the server. Review before saving.':restored?'Recovered unsaved answers from this device. Save to sync to the CRM.':record.updated_at?'Saved worksheet loaded.':'Prefilled from the company record. Save to store this worksheet.');
      if(stale)error('Your local draft is older than the saved worksheet. Compare your answers before saving; saving will replace the saved answers.');
    }catch(e){if(ticket===loading){error(e.message);state('Could not load worksheet. Choose the company again to retry.');}}
  }
  async function save(){
    if(!record||saving||!form.reportValidity())return false;
    if(draftRevision!==record.revision&&!confirm('A newer worksheet was saved elsewhere. Replace its answers with this local draft? Cancel to keep both, or use Load saved answers to discard this draft.'))return;
    saving=true;form.inert=true;$('#onboarding-refresh').disabled=true;top.disabled=true;bottom.disabled=true;error('');state('Saving to CRM…');keepDraft();
    const id=record.lead_id;
    try{
      const result=await api('/api/leads/'+id+'/onboarding',{method:'POST',body:JSON.stringify({data:answers(),revision:record.revision,lead_revision:record.lead_revision})});
      record=result;draftRevision=result.revision;dirty=false;try{localStorage.removeItem(draftKey(id));}catch(_){}
      $('#onboarding-customer-summary').textContent=result.company+(result.customer?' · Customer':' · Prospect');
      state('Saved to '+result.company+' · '+new Date(result.updated_at).toLocaleString());return true;
    }catch(e){error(e.message);state('Not saved to CRM. Your answers remain in this worksheet and its local draft.');}
    finally{saving=false;form.inert=false;$('#onboarding-refresh').disabled=false;top.disabled=false;bottom.disabled=false;}
  }
  $('#onboarding-reload').onclick=async()=>{if(!record||saving)return;if(dirty&&!confirm('Discard this customer’s unsaved answers and load the saved worksheet?'))return;const id=record.lead_id;try{localStorage.removeItem(draftKey(id));}catch(_){error('Could not clear the local draft. Your answers have been kept.');return;}dirty=false;await choose(String(id));};
  $('#onboarding-profile').onclick=async()=>{if(!record||saving)return;const saved=await save();if(saved&&record)window.BMTCustomerProfile.open(record.lead_id);};
  top.onchange=()=>choose(top.value);bottom.onchange=()=>choose(bottom.value);
  form.oninput=e=>{if(!fields.some(f=>f.key===e.target.name))return;dirty=true;keepDraft();state('Unsaved changes · draft kept on this device. Click Save worksheet to sync.');};
  form.onsubmit=e=>{e.preventDefault();save();};
  $('#onboarding-refresh').onclick=async()=>{keepDraft();await refresh();};
  window.addEventListener('beforeunload',e=>{keepDraft();if(dirty){e.preventDefault();e.returnValue='';}});
  window.addEventListener('hashchange',()=>{if(location.hash==='#onboarding')refresh();else keepDraft();});
  window.BMTOnboarding={open:async id=>{keepDraft();await refresh();await choose(String(id));location.hash='onboarding';}};
  if(location.hash==='#onboarding')refresh();
})();
