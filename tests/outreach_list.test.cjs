const test=require('node:test'), assert=require('node:assert/strict');
const list=require('../crm_static/outreach_list.js');
const rows=[{id:1,company:'Alpha',last_contacted_at:'2026-11-24',contact_method:'Facebook DM',status:'Contacted'}, {id:2,company:'Beta',last_contacted_at:null,contact_method:'Instagram DM',status:'New'}, {id:3,company:'Gamma',last_contacted_at:'2026-11-26T01:00:00Z',contact_method:'Facebook DM',status:'Follow-up',follow_up:'2026-11-28'}];
test('date-only evidence retains its calendar day and invalid dates do not crash',()=>{
 assert.equal(list.day('2026-11-24'),'2026-11-24');assert.equal(list.day(rows[2].last_contacted_at),'2026-11-25');assert.equal(list.label('bad'),'Date not recorded');assert.equal(list.label('2026-11-24'),'Nov 24, 2026');
});
test('sorts contacts newest or oldest with missing dates always last; does not mutate source',()=>{
 assert.deepEqual(list.select(rows).map(l=>l.id),[3,1,2]);assert.deepEqual(list.select(rows,{sort:'oldest'}).map(l=>l.id),[1,3,2]);assert.deepEqual(rows.map(l=>l.id),[1,2,3]);
});
test('combines platform, status and inclusive date range; unknown date is excluded',()=>{
 assert.deepEqual(list.select(rows,{platform:'Facebook DM',status:'Contacted',from:'2026-11-24',to:'2026-11-24'}).map(l=>l.id),[1]);assert.deepEqual(list.select(rows,{to:'2026-11-24'}).map(l=>l.id),[1]);assert.deepEqual(list.select(rows,{sort:'followup'}).map(l=>l.id),[3,1,2]);
});

test('latest conversation activity takes precedence over original contact date',()=>{
 const a={id:1,company:'A',last_contacted_at:'2026-11-20',last_activity_at:'2026-11-26T20:00:00Z'};
 const b={id:2,company:'B',last_contacted_at:'2026-11-25',last_activity_at:'2026-11-26T19:59:59Z'};
 assert.deepEqual(list.select([b,a]).map(l=>l.id),[1,2]);
});
