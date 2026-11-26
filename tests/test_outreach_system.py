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
        return {'op':'candidate','run_id':run,'country':'USA','company':name,'location':'Phoenix, AZ','trade':'Concrete','channel':'Facebook','profile_url':'https://www.facebook.com/democoncrete','website':site,'phone':phone,'email':'','ad_url':'https://www.facebook.com/ads/library/?id=123','issue':'Generic ad links to general services.','improvement':'Test a driveway-specific quote path.','scale_evidence':'Installation crew and project portfolio on website.','evidence':'Observed active driveway ad today.','checked_at':store.now(),'message':'Hey, Michael from BMT. Open to a 15-minute Zoom call?'}
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
    def test_history_duplicate_gate_and_one_attempt_per_run(self):
        run=self.claim();self.assertIsNone(self.post({'op':'claim'}).json['run'])
        n=store.add_lead('Already called',phone='5555550199',stage='Cold')
        with store.connect() as con:
            machine.schema(con);con.execute("INSERT INTO crm_call_events(event_key,lead_id,outcome,created_at) VALUES('old',?,'No answer',?)",(n,store.now()))
        self.assertEqual(self.post(self.candidate(run,phone='5555550199'),False).status_code,400)
        ident=self.post(self.candidate(run)).json['id']
        self.assertEqual(self.post(self.candidate(run),False).status_code,400)
        self.post({'op':'begin-send','run_id':run,'id':ident})
        other=self.post(self.candidate(run,'Other Fence','https://otherfence.example','5555550101')).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':other},False).status_code,400)
        self.post({'op':'finish','run_id':run,'summary':'Stopped before confirmation.'})
        data=self.client.get('/api/outreach-system').json
        self.assertFalse(data['config']['enabled'])
        self.assertEqual(next(p for p in data['prospects'] if p['id']==ident)['state'],'unconfirmed')
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
    def test_pause_and_expired_lease_block_sends(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'settings','enabled':False})
        self.assertEqual(self.post({'op':'begin-send','id':ident,'run_id':run},False).status_code,400)
        with store.connect() as con:con.execute('UPDATE crm_ai_runs SET started_at=? WHERE id=?',((machine.instant()-timedelta(minutes=21)).isoformat(),run))
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['runs'][0]['state'],'interrupted');self.assertFalse(data['config']['enabled'])
