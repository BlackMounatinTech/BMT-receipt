const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes={},storage=new Map(),handlers={};
class Element{constructor(){this.value='';this.children=[];this.hidden=false;this.checked=false;}replaceChildren(...x){this.children=x;}append(...x){this.children.push(...x);}add(x){this.children.push(x);}reportValidity(){return true;}}
class Option{constructor(text,value){this.text=text;this.value=String(value);}}
const $=q=>nodes[q]||(nodes[q]=new Element()),inputs={};for(const k of ['email','payment_plan','payment_reference','date','time','zone','host_id'])inputs[k]=new Element();
$('#sales-close-details').elements={namedItem:k=>['email','payment_plan','payment_reference'].includes(k)?inputs[k]:null};$('#sales-onboarding-details').elements={namedItem:k=>['date','time','zone','host_id'].includes(k)?inputs[k]:null};
$('#sales-prospect').value='';
const server={lead_id:1,company:'One',contact:'Pat',data:{email:'pat@example.com',payment_plan:'50% deposit',payment_reference:'',zone:'Arizona',host_id:'michael'},revision:0,hosts:[{id:'michael',name:'Michael'}],messages:[],documents:[],meeting:null};let sent=0,paid=0,booked=0;
const context={Option,Intl,Date,FormData:class{},document:{querySelector:$,createElement:()=>new Element(),addEventListener:(name,f)=>handlers[name]=f},window:{addEventListener(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},load:async()=>{},api:async(path,opts)=>{
 const p=opts?JSON.parse(opts.body):null;
 if(path.endsWith('/sales-close')&&p){assert.equal(p.revision,server.revision);server.data={...server.data,...p.data};server.revision++;}
 if(path.endsWith('/email/payment')){
  if(!p)return{to:server.data.email,sender:'michael@blackmountaintechnologies.ca',subject:'Payment link',body:'Pay $1,500 USD',digest:'preview-hash',attachments:[]};
  assert.equal(p.digest,'preview-hash');sent++;server.messages=[{kind:'payment',state:'sent'}];
 }
 if(path.endsWith('/payment')&&!path.includes('/email/')){paid++;assert(p.payment_received);server.customer=true;server.data.payment_confirmed='now';server.revision++;}
 if(path.endsWith('/book')){booked++;server.meeting={state:'complete',start:'2030-01-02T17:00:00+00:00',timezone:'America/Phoenix',zone:'Arizona'};}
 return structuredClone(server);
 }};
vm.runInNewContext(fs.readFileSync('crm_static/sales_close.js','utf8'),context);
(async()=>{
 await handlers['crm-sales-prospect-selected']({detail:{id:1}});assert.equal(inputs.email.value,'pat@example.com');assert.equal($('#sales-close-workspace').hidden,false);
 await $('#sales-preview-payment').onclick();assert.equal(sent,0);assert.equal($('#sales-close-preview').hidden,false);assert.match($('#sales-close-recipient').textContent,/pat@example.com/);
 await $('#sales-close-send').onclick();assert.equal(sent,1);
 await $('#sales-confirm-payment').onclick();assert.equal(paid,0);assert.match($('#sales-close-error').textContent,/Check Stripe/);
 inputs.payment_reference.value='pi_test';$('#sales-payment-checked').checked=true;await $('#sales-confirm-payment').onclick();assert.equal(paid,1);assert.equal($('#sales-confirm-payment').disabled,true);
 inputs.date.value='2030-01-02';inputs.time.value='10:00';await $('#sales-book-onboarding').onclick();assert.equal(booked,1);assert.match($('#sales-onboarding-status').textContent,/20 minutes/);
 console.log('PASS: selected customer, preview-before-send, explicit Stripe check, payment confirmation and onboarding handoff');
})().catch(e=>{console.error(e);process.exitCode=1;});
