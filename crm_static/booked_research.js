(() => {
 const cards=new Map(),make=(tag,text,cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
 const date=t=>t?new Intl.DateTimeFormat('en-US',{timeZone:'Etc/GMT+7',dateStyle:'medium',timeStyle:'short'}).format(new Date(t)):'';
 const ads=r=>({running:'Yes — active Meta ads verified',none_found:'No active ads found in this check',unverified:'Unverified'})[r?.status]||'Unverified';
 const photos=p=>p?.status==='verified'?`${p.photo_bucket} usable project photos observed (${p.photos_reviewed} photos reviewed)`:'Unverified'+(p?.status==='not_found'?' — matching profile not found':'');
 function brief(root,r,checked){
  root.replaceChildren();if(!r)return;root.append(make('h3','Company research'),make('p','Checked '+date(checked),'booking-hint'));
  const c=r.company,g=r.google,rows=[['Location',c.location||'Unverified'],['Services',(c.services||[]).join(', ')||'Unverified'],['Service areas',(c.service_areas||[]).join(', ')||'Unverified'],['Facebook photos',photos(r.facebook)],['Instagram photos',photos(r.instagram)],['Meta advertising',ads(r.ads)],['Google profile',g.status==='verified'?`${g.rating===null?'No rating yet':g.rating+' stars'} · ${g.reviews} reviews · ${g.profile_quality}`:'Unverified']];
  const dl=document.createElement('dl');dl.className='research-facts';for(const [label,value] of rows)dl.append(make('dt',label),make('dd',value));root.append(dl);
  if(r.talking_points?.length){const ul=document.createElement('ul');for(const t of r.talking_points)ul.append(make('li',t));root.append(ul);}
  const details=document.createElement('details');details.append(make('summary','Sources, observations & limitations'));
  for(const [name,item] of [['Facebook',r.facebook],['Instagram',r.instagram],['Meta Ads Library',r.ads],['Google Business Profile',r.google]]){
   details.append(make('p',name+': '+item.notes));if(item.source_url){const a=make('a','Open '+name+' source ↗');a.href=item.source_url;a.target='_blank';a.rel='noopener';details.append(a);}
  }
  for(const s of c.sources||[]){const p=make('p',s.observation+' · '+date(s.checked_at));const a=make('a','Company source ↗');a.href=s.url;a.target='_blank';a.rel='noopener';p.append(document.createElement('br'),a);details.append(p);}
  details.append(make('p','Photo buckets are conservative counts from the images actually inspected. They are not a count of the company’s entire photo library. Google profile quality is a research assessment, not a Google score.','booking-hint'));root.append(details);
 }
 function render(entry,data){
  const {button,state,body}=entry,j=data.job,active=j&&['queued','running'].includes(j.state);button.disabled=!!active;
  button.textContent=active?j.state==='queued'?'Research queued…':'Gathering information…':data.report?'Refresh research':'Gather more information';
  state.textContent=active?(j.state==='queued'?'Queued — waiting for the Mac worker.':j.phase||'Researching company.')+(data.worker_online?'':' Mac worker is offline; keep the Mac awake and connected.'):'Checks company details, project photos, Meta ads and Google reviews. No messages are sent.';
  if(!active&&j?.error)state.textContent=j.error;
  else if(!active&&data.report)state.textContent=j?.state==='partial'?'Research saved. Some sources could not be verified.':'Research saved.';
  brief(body,data.report,data.checked_at);entry.active=active;
 }
 async function check(entry){try{render(entry,await api('/api/leads/'+entry.lead.id+'/booked-research'));}catch(e){entry.state.textContent=e.message;entry.button.disabled=false;}}
 function attach(lead,card){
  const wrap=make('section','','booked-research'),button=make('button','Gather more information'),state=make('p','Checking research status…','booking-hint'),body=document.createElement('div');button.type='button';wrap.append(button,state,body);card.append(wrap);
  const entry={lead,wrap,button,state,body,active:false};cards.set(lead.id,entry);
  button.onclick=async()=>{button.disabled=true;state.textContent='Queuing read-only research…';try{render(entry,await api('/api/leads/'+lead.id+'/booked-research',{method:'POST',body:'{}'}));}catch(e){state.textContent=e.message;button.disabled=false;}};
  check(entry);
 }
 setInterval(()=>{if(document.hidden||document.querySelector('#booked-page').hidden)return;for(const [id,e] of cards){if(!e.wrap.isConnected)cards.delete(id);else if(e.active)check(e);}},12000);
 window.BMTBookedResearch={attach,brief,photos,ads};
})();
