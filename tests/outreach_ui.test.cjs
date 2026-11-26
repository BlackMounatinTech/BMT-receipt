const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
  let forms=[];
  const document={activeElement:null,querySelectorAll:()=>forms,addEventListener:()=>{}};
  const element={querySelectorAll:()=>[]};
  const context=vm.createContext({document,$:()=>element,api:()=>new Promise(()=>{}),setInterval:()=>{}});
  const source=fs.readFileSync(require('node:path').join(__dirname,'../crm_static/outreach_system.js'),'utf8');
  vm.runInContext(source.replace(/\}\)\(\);\s*$/, 'globalThis.audit={captureDrafts,restoreDrafts,clearedDrafts};})();'),context);
  const field=value=>({value,focus(){document.activeElement=this;},setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}});
  const form=(key,values,open=false)=>{const fields=values.map(field),details={open};return {dataset:{draftKey:key},querySelectorAll:()=>fields,closest:()=>details,fields,details};};
  return {audit:context.audit,document,form,setForms:x=>forms=x};
}
test('automatic refresh preserves separate drafts, expanded form and cursor',()=>{
  const s=setup(),old=s.form('outcome:company-1',['Held','2026-11-25T18:30','Payment evidence being written'],true);
  s.setForms([old]);s.document.activeElement=old.fields[2];old.fields[2].selectionStart=8;old.fields[2].selectionEnd=12;
  s.audit.captureDrafts();
  const replacement=s.form('outcome:company-1',['Held','now','']);const other=s.form('handoff:company-2',['']);
  s.setForms([replacement,other]);s.audit.restoreDrafts();
  assert.equal(replacement.fields[1].value,'2026-11-25T18:30');assert.equal(replacement.fields[2].value,'Payment evidence being written');
  assert.equal(replacement.details.open,true);assert.equal(s.document.activeElement,replacement.fields[2]);assert.equal(replacement.fields[2].selectionStart,8);
  assert.equal(other.fields[0].value,'');
});
test('successful save clears only its own draft on next refresh',()=>{
  const s=setup(),saved=s.form('delivery:a',['sent','Verified message']),other=s.form('outcome:b',['Lost','today','Unfinished evidence']);
  s.setForms([saved,other]);s.audit.captureDrafts();s.audit.clearedDrafts.add('delivery:a');s.audit.captureDrafts();
  const savedNext=s.form('delivery:a',['','']),otherNext=s.form('outcome:b',['Held','now','']);
  s.setForms([savedNext,otherNext]);s.audit.restoreDrafts();
  assert.equal(savedNext.fields[1].value,'');assert.equal(otherNext.fields[2].value,'Unfinished evidence');
});
