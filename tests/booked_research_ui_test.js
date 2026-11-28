const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{constructor(){this.children=[];this.hidden=false;this.isConnected=true;}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}}
let posts=0;const page=new Element(),context={Intl,Date,Map,setInterval(){},document:{hidden:false,createElement:()=>new Element(),querySelector:()=>page},window:{},api:async(path,opts)=>{if(opts){posts++;return{job:{state:'queued'},worker_online:false,report:null};}return{job:null,report:null};}};
vm.runInNewContext(fs.readFileSync('crm_static/booked_research.js','utf8'),context);
const ui=context.window.BMTBookedResearch;
(async()=>{
 assert.match(ui.photos({status:'unavailable',usable_photos_seen:0}),/Unverified/);
 assert.match(ui.photos({status:'verified',photo_bucket:'10+',photos_reviewed:15}),/10\+/);
 assert.match(ui.ads({status:'none_found'}),/No active ads found in this check/);
 const card=new Element();ui.attach({id:1},card);await new Promise(r=>setImmediate(r));
 const wrap=card.children[0],button=wrap.children[0],state=wrap.children[1];assert.equal(button.textContent,'Gather more information');await button.onclick();assert.equal(posts,1);assert.equal(button.disabled,true);assert.match(state.textContent,/offline/);
 console.log('PASS: evidence labels, unverified photo counts, queued button and explicit offline state');
})().catch(e=>{console.error(e);process.exitCode=1;});
