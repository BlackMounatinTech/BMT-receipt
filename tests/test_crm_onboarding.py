import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store
import crm_onboarding as onboarding
import crm_web


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name})
        self.env.start()
        self.a=store.add_lead('A Concrete',contact='Alex',phone='5551234567',email='alex@example.com',location='Dallas, TX')
        self.b=store.add_lead('B Excavation',phone='5557654321')
        self.client=crm_web.app.test_client(); self.client.get('/')
        with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def post(self,n,p):
        return self.client.post(f'/api/leads/{n}/onboarding',json=p,headers=self.headers)

    def test_prefill_and_durable_per_customer_roundtrip(self):
        initial=self.client.get(f'/api/leads/{self.a}/onboarding').json
        self.assertEqual(initial['data']['email'],'alex@example.com')
        self.assertEqual(initial['data']['area'],'Dallas, TX')
        data={**initial['data'],'project':'Driveway replacements','service':'Concrete','minimum':'5000'}
        saved=self.post(self.a,dict(revision=0,data=data))
        self.assertEqual(saved.status_code,200)
        self.assertEqual(saved.json['revision'],1)
        self.assertEqual(onboarding.read(self.a)['data']['project'],'Driveway replacements')
        self.assertNotIn('project',onboarding.read(self.b)['data'])
        self.assertEqual(self.post(self.a,dict(revision=0,data=data)).status_code,409)
        self.assertEqual(onboarding.read(self.a)['data']['project'],'Driveway replacements')

    def test_promotion_requires_confirmed_close_and_preserves_booking(self):
        with store.connect() as con:
            con.execute("UPDATE crm_leads SET call_date='2026-12-01',zoom_url='https://zoom.us/j/example' WHERE id=?",(self.a,))
        p=dict(revision=0,lead_revision=0,mark_customer=True,data={'contract':'Yes','payment':'Not received'})
        self.assertEqual(self.post(self.a,p).status_code,400)
        self.assertEqual(onboarding.read(self.a)['revision'],0)
        p['data'].update(payment='$1,500 USD deposit received',onboarding_date='2026-12-01',onboarding_time='10:00',onboarding_zone='Central')
        p['lead_revision']=99
        self.assertEqual(self.post(self.a,p).status_code,409)
        p['lead_revision']=0
        self.assertEqual(self.post(self.a,p).status_code,200)
        lead=next(l for l in store.list_leads() if l['id']==self.a)
        self.assertEqual(lead['status'],'Won')
        self.assertEqual(lead['call_date'],'2026-12-01')
        self.assertEqual(lead['zoom_url'],'https://zoom.us/j/example')
        self.assertEqual(onboarding.read(self.a)['data']['onboarding_time'],'10:00')

    def test_validation_missing_customer_and_csrf(self):
        for data in [{'service':'Invalid'},{'minimum':'NaN'},{'launch_date':'bad'},{'onboarding_time':'25:70'},{'email':'wrong'},{'folder':'javascript:alert(1)'},{'password':'do not store'}]:
            self.assertEqual(self.post(self.a,dict(revision=0,data=data)).status_code,400)
        self.assertEqual(self.client.get('/api/leads/999/onboarding').status_code,404)
        self.assertEqual(self.client.post(f'/api/leads/{self.a}/onboarding',json=dict(revision=0,data={})).status_code,403)
        self.assertEqual(onboarding.read(self.a)['revision'],0)
        fields=self.client.get('/api/onboarding/fields').json['fields']
        self.assertEqual(len({f['key'] for f in fields}),len(fields))


if __name__=='__main__':unittest.main()
