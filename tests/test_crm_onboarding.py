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
        with store.connect() as con:con.execute("UPDATE crm_leads SET status='Won'")
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

    def test_purchase_required_and_preserves_booking(self):
        import crm_customers as customers
        with store.connect() as con:
            con.execute("UPDATE crm_leads SET status='Call booked',call_date='2026-12-01',zoom_url='https://zoom.us/j/example' WHERE id=?",(self.a,))
        self.assertEqual(self.client.get(f'/api/leads/{self.a}/onboarding').status_code,400)
        self.assertEqual(self.post(self.a,dict(revision=0,data={})).status_code,400)
        p=dict(revision=0,payment_plan='50% deposit',contract_signed=True,payment_received=False)
        url=f'/api/leads/{self.a}/confirm-sale'
        self.assertEqual(self.client.post(url,json=p,headers=self.headers).status_code,400)
        p['payment_received']=True
        r=self.client.post(url,json=p,headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['lead']['status'],'Won')
        self.assertEqual(r.json['lead']['call_date'],'2026-12-01')
        self.assertEqual(r.json['lead']['zoom_url'],'https://zoom.us/j/example')
        self.assertEqual(self.client.get(f'/api/leads/{self.a}/onboarding').status_code,200)
        self.assertEqual(self.post(self.a,dict(revision=0,data={},mark_customer=True)).status_code,400)
        self.assertEqual(self.client.post(url,json=p,headers=self.headers).status_code,409)

    def test_profiles_documents_and_isolation(self):
        import io
        url=f'/api/customers/{self.a}'
        payload=dict(revision=0,data={'qualified_leads':'6','payment_url':'https://example.com/pay'})
        r=self.client.post(url,json=payload,headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get(f'/api/customers/{self.b}').json['data'],{})
        self.assertEqual(self.client.post(url,json=payload,headers=self.headers).status_code,409)
        payload.update(revision=1,data={'qualified_leads':'NaN'})
        self.assertEqual(self.client.post(url,json=payload,headers=self.headers).status_code,400)
        r=self.client.post(url+'/documents',data={'kind':'Contract','file':(io.BytesIO(b'%PDF-1.4 test'),'signed.pdf')},headers=self.headers)
        self.assertEqual(r.status_code,200)
        doc=r.json['documents'][0]['id']
        self.assertEqual(self.client.get(url+f'/documents/{doc}').data,b'%PDF-1.4 test')
        self.assertEqual(self.client.get(f'/api/customers/{self.b}/documents/{doc}').status_code,404)
        with store.connect() as con:con.execute("UPDATE crm_leads SET status='New' WHERE id=?",(self.b,))
        self.assertEqual(len(self.client.get('/api/customers').json['customers']),1)
        self.assertEqual(self.client.get(f'/api/customers/{self.b}').status_code,400)

    def test_validation_missing_customer_and_csrf(self):
        for data in [{'service':'Invalid'},{'minimum':'NaN'},{'launch_date':'bad'},{'onboarding_time':'25:70'},{'email':'wrong'},{'folder':'javascript:alert(1)'},{'password':'do not store'}]:
            self.assertEqual(self.post(self.a,dict(revision=0,data=data)).status_code,400)
        self.assertEqual(self.client.get('/api/leads/999/onboarding').status_code,404)
        self.assertEqual(self.client.post(f'/api/leads/{self.a}/onboarding',json=dict(revision=0,data={})).status_code,403)
        self.assertEqual(onboarding.read(self.a)['revision'],0)
        fields=self.client.get('/api/onboarding/fields').json['fields']
        self.assertEqual(len({f['key'] for f in fields}),len(fields))


if __name__=='__main__':unittest.main()
