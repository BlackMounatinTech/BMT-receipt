const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),context={Intl,Date};
vm.runInNewContext(fs.readFileSync('crm_static/sales_time.js','utf8'),context);const t=context.BMTSalesTime;
assert.equal(t.instant('2026-12-03','09:00','Pacific (US)').toISOString(),'2026-12-03T17:00:00.000Z');
assert.equal(t.instant('2026-12-03','09:00','Arizona').toISOString(),'2026-12-03T16:00:00.000Z');
assert.equal(t.instant('2026-07-03','09:00','Pacific (US)').toISOString(),'2026-07-03T16:00:00.000Z');
assert.equal(t.instant('2026-07-03','09:00','Arizona').toISOString(),'2026-07-03T16:00:00.000Z');
assert.throws(()=>t.instant('2026-03-08','02:30','Pacific (US)'),/does not exist/);
assert.equal(t.add('2026-12-31',1),'2027-01-01');assert.equal(t.clock(615),'10:15 AM');assert.equal(t.timeValue(615),'10:15');
console.log('PASS: prospect-local times, seasonal US offsets, Arizona, invalid clock-change times and date rollover');
