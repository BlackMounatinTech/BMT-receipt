/* Exercise the actual onboarding controller with an isolated DOM and API. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const nodes=[],ids={},storage=new Map(),server=new Map([[1,{project:'First'}],[2,{project:'Second'}]]);let revision={1:0,2:0},posts=0,accept=true,fail=false,opened=null;
class Element{
 constructor(){this.children=[];this.value='';this.hidden=false;this.disabled=false;nodes.push(this);}
 append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}
 get options(){return this.children.flatMap(c=>c instanceof Option?[c]:c.options||[]);}
 reportValidity(){return true;}
}
class Option{constructor(text,value){this.text=text;this.value=value;}}
const $=q=>ids[q]||(ids[q]=new Element());const form=$('#onboarding-form');form.elements={namedItem:k=>[...nodes].reverse().find(n=>n.name===k)};
const fields=[{key:'project',section:'1. Confirm the plan',label:'Project',prompt:'Which project?',options:[],type:'text'}];
const context={$,el:()=>new Element(),Option,document:{createElement:()=>new Element()},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},location:{hash:''},window:{addEventListener(){},BMTCustomerProfile:{open:id=>opened=id}},confirm:()=>accept,Date,console,
 api:async(path,opts)=>{
  if(path==='/api/onboarding/fields')return{fields};if(path==='/api/customers')return{customers:[1,2].map(id=>({id,status:'Won',company:'Customer '+id}))};
  const id=Number(path.split('/')[3]);if(opts){posts++;if(fail)throw Error('Connection failed');const p=JSON.parse(opts.body);assert.equal(p.revision,revision[id]);server.set(id,p.data);revision[id]++;}
  return{lead_id:id,company:'Customer '+id,customer:true,data:{...server.get(id)},revision:revision[id],updated_at:'2026-11-26T20:00:00Z'};
 }};
vm.runInNewContext(fs.readFileSync('crm_static/onboarding.js','utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r));
const edit=value=>{form.elements.namedItem('project').value=value;form.oninput({target:{name:'project'}});};
(async()=>{
 await context.window.BMTOnboarding.open(1);edit('Unsaved A');await context.window.BMTOnboarding.open(2);assert.equal(form.elements.namedItem('project').value,'Second');await context.window.BMTOnboarding.open(1);assert.equal(form.elements.namedItem('project').value,'Unsaved A');
 fail=true;form.onsubmit({preventDefault(){}});await flush();assert.match($('#onboarding-state').textContent,/Not saved/);assert.equal(form.inert,false);assert.equal($('#onboarding-customer').disabled,false);assert(storage.has('bmt-onboarding-draft:1'));fail=false;
 revision[1]++;server.set(1,{project:'New server answer'});await context.window.BMTOnboarding.open(2);await context.window.BMTOnboarding.open(1);assert.match($('#onboarding-error').textContent,/older/);accept=false;const before=posts;form.onsubmit({preventDefault(){}});await flush();assert.equal(posts,before);
 // Repeated switches must retain the stale revision and keep the overwrite warning.
 await context.window.BMTOnboarding.open(2);await context.window.BMTOnboarding.open(1);form.onsubmit({preventDefault(){}});await flush();assert.equal(posts,before);
 accept=true;await $('#onboarding-reload').onclick();assert.equal(form.elements.namedItem('project').value,'New server answer');assert(!storage.has('bmt-onboarding-draft:1'));
 edit('Final answer');await $('#onboarding-profile').onclick();assert.equal(opened,1);assert.equal(server.get(1).project,'Final answer');assert.equal(server.get(2).project,'Second');assert(!storage.has('bmt-onboarding-draft:1'));
 console.log('PASS: switching, drafts, failed saves, stale-draft protection, reload, profile handoff and customer isolation');
})().catch(e=>{console.error(e);process.exitCode=1;});
