const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ids={},storage=new Map(),handlers={};
class Element{constructor(){this.value='';this.children=[];this.hidden=false;this.dataset={};}replaceChildren(...x){this.children=x;}append(...x){this.children.push(...x);}add(x){this.children.push(x);}}
class Option{constructor(text,value){this.text=text;this.value=String(value);}}
const $=q=>ids[q]||(ids[q]=new Element());
function answerNodes(){const all=new Set();function visit(n){if(!n||all.has(n))return;all.add(n);for(const c of n.children||[])visit(c);}Object.values(ids).forEach(visit);return [...all].filter(n=>n.dataset?.salesAnswer);}
const fields=Object.fromEntries(['services','service_areas','google_reviews','project_photos','sources'].map(k=>[k,new Element()]));
const form=$('#sales-facts-form');form.elements={namedItem:k=>fields[k]};form.reset=()=>Object.values(fields).forEach(x=>x.value='');
const server={1:{services:'Excavation',service_areas:'Phoenix',google_reviews:'',project_photos:'',sources:''},2:{services:'Pavers',service_areas:'Mesa',google_reviews:'4.8 stars from 20 reviews',project_photos:'Before-and-after photos verified',sources:''}},answers={1:{},2:{}};
const rev={1:0,2:0};let fail=false;
const defs={trades:['Excavation','Concrete','Landscaping','Carpentry'],common:[['goals','Goals?']],specific:{Excavation:[['excavation_work','Excavation work?']],Landscaping:[['landscape_work','Landscape work?']]},follow_up:[['concerns','Concerns?']]};
const context={Option,CustomEvent:class{constructor(type,opts){this.type=type;this.detail=opts.detail;}},setTimeout:()=>1,clearTimeout(){},confirm:()=>true,document:{querySelector:$,querySelectorAll:answerNodes,createElement:()=>new Element(),dispatchEvent(){},addEventListener(){}},window:{addEventListener:(k,v)=>handlers[k]=v},location:{hash:'#sales-call'},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},api:async(path,opts)=>{
 if(path==='/api/sales-call/questions')return defs;
 if(path==='/api/leads')return{leads:[{id:1,company:'One',status:'Call booked',call_start_utc:'2030-01-01'},{id:2,company:'Two',status:'Call booked',call_start_utc:'2030-01-02'},{id:3,company:'Cold',status:'New',call_start_utc:null},{id:4,company:'Test',status:'Call booked',call_start_utc:'2030-01-01',is_test:1},{id:5,company:'Customer',status:'Won',call_start_utc:'2030-01-01'}]};
 const id=Number(path.split('/')[3]);if(opts){if(fail)throw Error('Save failed');const p=JSON.parse(opts.body);assert.equal(p.revision,rev[id]);server[id]=p.data;answers[id]=p.answers;rev[id]++;}
 return{lead_id:id,company:id===1?'One':'Two',location:'Arizona',data:{...server[id]},answers:{...answers[id]},revision:rev[id]};
 }};
vm.runInNewContext(fs.readFileSync('crm_static/sales_call.js','utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r)),picker=$('#sales-prospect'),text=()=>$('#sales-opening').children.map(p=>p.textContent).join('\n');
(async()=>{
 await flush();assert.deepEqual(picker.children.map(x=>x.value),['','1','2']);
 picker.value='1';await picker.onchange();assert.match(text(),/Excavation/);assert.match(text(),/not checked/);assert.doesNotMatch(text(),/definitely have/);
 const goal=answerNodes().find(n=>n.dataset.salesAnswer==='goals');goal.value='More septic jobs';goal.oninput();
 fields.services.value='Foundation excavation';form.oninput();
 picker.value='2';await picker.onchange();assert.match(text(),/Pavers/);assert.equal(answers[1].goals,'More septic jobs');assert.match(text(),/definitely have some before-and-after photos/);assert.doesNotMatch(text(),/Foundation excavation/);
 assert.equal($('#sales-trade').value,'Landscaping');assert(answerNodes().some(n=>n.dataset.salesAnswer==='landscape_work'));
 picker.value='1';await picker.onchange();assert.equal(fields.services.value,'Foundation excavation');assert.equal(answerNodes().find(n=>n.dataset.salesAnswer==='goals').value,'More septic jobs');
 fields.services.value='Septic excavation';form.oninput();fail=true;form.onsubmit({preventDefault(){}});await flush();assert.match($('#sales-prospect-error').textContent,/Save failed/);assert(storage.has('bmt-sales-facts:1'));
 picker.value='2';await picker.onchange();assert.equal(picker.value,'1');
 fail=false;form.onsubmit({preventDefault(){}});await flush();assert.equal(server[1].services,'Septic excavation');assert.equal(server[2].services,'Pavers');assert(!storage.has('bmt-sales-facts:1'));
 console.log('PASS: booked-only selection, trade questions, saved answers, prospect isolation, save-before-switch and failed-save recovery');
})().catch(e=>{console.error(e);process.exitCode=1;});
