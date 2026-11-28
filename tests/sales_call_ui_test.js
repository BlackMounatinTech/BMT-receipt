const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ids={},storage=new Map(),handlers={};
class Element{constructor(){this.value='';this.children=[];this.hidden=false;}replaceChildren(...x){this.children=x;}append(x){this.children.push(x);}add(x){this.children.push(x);}}
class Option{constructor(text,value){this.text=text;this.value=String(value);}}
const $=q=>ids[q]||(ids[q]=new Element());
const fields=Object.fromEntries(['services','service_areas','google_reviews','project_photos','sources'].map(k=>[k,new Element()]));
const form=$('#sales-facts-form');form.elements={namedItem:k=>fields[k]};form.reset=()=>Object.values(fields).forEach(x=>x.value='');
const server={1:{services:'Excavation',service_areas:'Phoenix',google_reviews:'',project_photos:'',sources:''},2:{services:'Pavers',service_areas:'Mesa',google_reviews:'4.8 stars from 20 reviews',project_photos:'Before-and-after photos verified',sources:''}};
const rev={1:0,2:0};let fail=false;
const context={Option,Event:class{constructor(type){this.type=type;}},document:{querySelector:$,createElement:()=>new Element(),dispatchEvent(){},addEventListener(){}},window:{addEventListener:(k,v)=>handlers[k]=v},location:{hash:'#sales-call'},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},api:async(path,opts)=>{
 if(path==='/api/leads')return{leads:[{id:1,company:'One',status:'Call booked',call_start_utc:'2030-01-01'},{id:2,company:'Two',status:'Call booked',call_start_utc:'2030-01-02'},{id:3,company:'Cold',status:'New',call_start_utc:null},{id:4,company:'Test',status:'Call booked',call_start_utc:'2030-01-01',is_test:1},{id:5,company:'Customer',status:'Won',call_start_utc:'2030-01-01'}]};
 const id=Number(path.split('/')[3]);if(opts){if(fail)throw Error('Save failed');const p=JSON.parse(opts.body);assert.equal(p.revision,rev[id]);server[id]=p.data;rev[id]++;}
 return{lead_id:id,company:id===1?'One':'Two',location:'Arizona',data:{...server[id]},revision:rev[id]};
 }};
vm.runInNewContext(fs.readFileSync('crm_static/sales_call.js','utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r)),picker=$('#sales-prospect'),text=()=>$('#sales-opening').children.map(p=>p.textContent).join('\n');
(async()=>{
 await flush();assert.deepEqual(picker.children.map(x=>x.value),['','1','2']);
 picker.value='1';await picker.onchange();assert.match(text(),/Excavation/);assert.match(text(),/not checked/);assert.doesNotMatch(text(),/definitely have/);
 fields.services.value='Foundation excavation';form.oninput();
 picker.value='2';await picker.onchange();assert.match(text(),/Pavers/);assert.match(text(),/definitely have some before-and-after photos/);assert.doesNotMatch(text(),/Foundation excavation/);
 picker.value='1';await picker.onchange();assert.equal(fields.services.value,'Foundation excavation');
 fail=true;await form.onsubmit({preventDefault(){}});assert.match($('#sales-prospect-error').textContent,/Save failed/);assert(storage.has('bmt-sales-facts:1'));assert.equal(picker.disabled,false);
 fail=false;await form.onsubmit({preventDefault(){}});assert.equal(server[1].services,'Foundation excavation');assert.equal(server[2].services,'Pavers');assert(!storage.has('bmt-sales-facts:1'));
 console.log('PASS: booked-only options, personalized opening, unknown facts, prospect isolation, draft restoration, failed save recovery and persistence');
})().catch(e=>{console.error(e);process.exitCode=1;});
