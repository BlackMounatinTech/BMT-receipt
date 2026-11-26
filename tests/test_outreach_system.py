import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_web
import crm_store as store
import crm_outreach_system as machine
import crm_stats as stats

class OutreachSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
        self.config=patch.dict(crm_web.app.config,{'OUTREACH_WORKER_HASH':hashlib.sha256(b'test-key').hexdigest()});self.config.start()
        self.client=crm_web.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf={'X-CSRF-Token':s['csrf']}
        self.headers={**self.csrf,'X-BMT-Outreach-Key':'test-key'}
    def tearDown(self):self.config.stop();self.env.stop();self.tmp.cleanup()
    def post(self,p,ok=True):
        r=self.client.post('/api/outreach-system',json=p,headers=self.headers)
        if ok:self.assertEqual(r.status_code,200,r.json)
        return r
    def claim(self):
        self.post({'op':'settings','enabled':True})
        return self.post({'op':'claim'}).json['run']
    def candidate(self,run,name='Demo Concrete',site='https://democoncrete.example',phone='5555550100'):
        return {'op':'candidate','run_id':run,'country':'USA','company':name,'location':'Phoenix, AZ','trade':'Concrete','channel':'Facebook','profile_url':'https://www.facebook.com/democoncrete','website':site,'phone':phone,'email':'','ad_url':'https://www.facebook.com/ads/library/?id=123','issue':'Generic ad links to general services.','improvement':'Test a driveway-specific quote path.','scale_evidence':'Installation crew and project portfolio on website.','evidence':'Observed active driveway ad today.','checked_at':store.now(),'source_published_at':store.now(),'message':'Hey, Michael from BMT. Open to a 15-minute Zoom call?'}
    def test_owner_session_secret_survives_server_restart(self):
        with patch.dict(os.environ,{'RENDER':'true'}), patch('os.path.ismount',return_value=True):
            with patch.dict(os.environ,{},clear=False):
                original=os.environ.pop('CRM_SESSION_SECRET',None)
                try:
                    first=crm_web.session_secret();second=crm_web.session_secret()
                    self.assertEqual(first,second);self.assertGreaterEqual(len(first),32)
                finally:
                    if original is not None:os.environ['CRM_SESSION_SECRET']=original

    def test_operator_controls_and_single_use_connection(self):
        self.assertEqual(self.client.post('/api/outreach-system',json={'op':'settings','enabled':True},headers=self.csrf).status_code,403)
        self.assertEqual(self.client.post('/api/outreach-system',json={'op':'claim'},headers={'X-BMT-Outreach-Key':'test-key'}).status_code,403)
        path=self.post({'op':'control-link'}).json['path']
        self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post('/api/outreach-system',json={'op':'settings','enabled':True},headers=self.csrf).status_code,200)
    def test_history_duplicate_gate_and_two_attempts_per_window(self):
        run=self.claim();self.assertIsNone(self.post({'op':'claim'}).json['run'])
        n=store.add_lead('Already called',phone='5555550199',stage='Cold')
        with store.connect() as con:
            machine.schema(con);con.execute("INSERT INTO crm_call_events(event_key,lead_id,outcome,created_at) VALUES('old',?,'No answer',?)",(n,store.now()))
        self.assertEqual(self.post(self.candidate(run,phone='5555550199'),False).status_code,400)
        ident=self.post(self.candidate(run)).json['id']
        self.assertEqual(self.post(self.candidate(run),False).status_code,400)
        self.post({'op':'begin-send','run_id':run,'id':ident})
        other=self.post(self.candidate(run,'Other Fence','https://otherfence.example','5555550101')).json['id']
        self.post({'op':'send-result','id':ident,'state':'sent','proof':'Verified test send'})
        self.post({'op':'begin-send','run_id':run,'id':other})
        third=self.post(self.candidate(run,'Third Fence','https://thirdfence.example','5555550102')).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':third},False).status_code,400)
        self.post({'op':'finish','run_id':run,'summary':'Stopped before confirmation.'})
        data=self.client.get('/api/outreach-system').json
        self.assertFalse(data['config']['enabled'])
        self.assertEqual(next(p for p in data['prospects'] if p['id']==other)['state'],'unconfirmed')
    def test_confirmed_send_reply_promotion_and_stats_are_idempotent(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'begin-send','run_id':run,'id':ident})
        result=self.post({'op':'send-result','id':ident,'state':'sent','proof':'Recipient thread shows the exact sent message.'}).json
        lead=next(x for x in store.list_leads() if x['id']==result['lead_id'])
        self.assertEqual(lead['stage'],'Outreach')
        reply={'op':'reply','id':ident,'text':'Thanks, office hours 8 to 5.','classification':'Auto-reply','source_url':'https://www.facebook.com/messages/t/123','suggested_reply':''}
        self.post(reply);self.assertEqual(store.list_leads()[0]['stage'],'Outreach')
        reply.update(text='Yes, I would like to talk about the ads.',classification='Interested')
        self.post(reply);self.post(reply)
        self.assertEqual(store.list_leads()[0]['stage'],'Prospect')
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['totals']['confirmed_sent'],1);self.assertEqual(data['totals']['replies'],1)
        report=stats.report(machine.day(),machine.day())
        self.assertEqual(report['totals']['calls'],0)
        self.assertEqual(report['automatic_outreach'][0]['sent'],1)
        self.assertEqual(report['automatic_outreach'][0]['replies'],1)
        self.assertEqual(report['outreach'],[])
    def test_public_intent_preserves_comment_and_does_not_require_own_ad(self):
        run=self.claim();p=self.candidate(run)
        p.update(source_type='public_intent',ad_url='https://www.facebook.com/ads/library/?id=agency123',intent_quote='Can you help my fencing company get more jobs?',intent_author='Demo Fence Co',intent_url='https://www.facebook.com/agency/posts/123?comment_id=456',issue='Contractor publicly asked for help finding fence jobs.',website='http://democoncrete.example')
        ident=self.post(p).json['id']
        entry=next(x for x in self.client.get('/api/outreach-system').json['prospects'] if x['id']==ident)
        self.assertEqual(entry['source_type'],'public_intent')
        self.assertEqual(entry['intent_quote'],p['intent_quote'])
        self.assertEqual(entry['intent_url'],p['intent_url'])
        self.assertEqual(entry['ad_url'],p['ad_url'])
        self.assertEqual(entry['website'],'http://democoncrete.example')
        self.post({'op':'begin-send','run_id':run,'id':ident})
        self.post({'op':'send-result','id':ident,'state':'sent','proof':'Isolated test confirmation'})
        self.assertIn(p['intent_quote'],store.notes_for(store.list_leads()[0]['id'])[0]['text'])

    def test_public_intent_rejects_missing_comment_proof(self):
        run=self.claim();p=self.candidate(run);p['source_type']='public_intent'
        self.assertEqual(self.post(p,False).status_code,400)
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'],[])

    def test_pause_and_expired_lease_block_sends(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'settings','enabled':False})
        self.assertEqual(self.post({'op':'begin-send','id':ident,'run_id':run},False).status_code,400)
        with store.connect() as con:con.execute('UPDATE crm_ai_runs SET started_at=? WHERE id=?',((machine.instant()-timedelta(minutes=21)).isoformat(),run))
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['runs'][0]['state'],'interrupted');self.assertFalse(data['config']['enabled'])

    def test_publication_age_required_and_rechecked_before_send(self):
        run=self.claim();p=self.candidate(run)
        p.pop('source_published_at')
        self.assertEqual(self.post(p,False).status_code,400)
        p['source_published_at']=(machine.instant()-timedelta(days=31)).isoformat()
        self.assertEqual(self.post(p,False).status_code,400)
        p['source_published_at']=store.now();ident=self.post(p).json['id']
        with store.connect() as con:con.execute('UPDATE crm_ai_prospects SET source_published_at=? WHERE id=?',((machine.instant()-timedelta(days=31)).isoformat(),ident))
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':ident},False).status_code,400)

    def test_rolling_window_applies_across_runs(self):
        run=self.claim()
        for i in range(2):
            ident=self.post(self.candidate(run,'Company '+str(i),'https://company'+str(i)+'.example','555555011'+str(i))).json['id']
            self.post({'op':'begin-send','run_id':run,'id':ident})
            self.post({'op':'send-result','id':ident,'state':'sent','proof':'Confirmed in test'})
        self.post({'op':'finish','run_id':run,'summary':'Two test sends.'})
        with store.connect() as con:con.execute('UPDATE crm_ai_config SET next_run=NULL')
        second=self.post({'op':'claim'}).json['run']
        ident=self.post(self.candidate(second,'Another','https://another.example','5555550120')).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':second,'id':ident},False).status_code,400)
