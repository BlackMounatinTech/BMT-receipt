import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store,crm_web,crm_calling

class SalesCallTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
  self.client=crm_web.app.test_client();self.client.get('/')
  with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}
  self.id=store.add_lead('Booked Contractor',contact='Pat',phone='6025550100',need='Original research',location='Phoenix, AZ')
  with store.connect() as con:con.execute("UPDATE crm_leads SET status='Call booked',call_start_utc='2030-01-01T15:00:00+00:00' WHERE id=?",(self.id,))
  crm_calling.save_notes(self.id,'Private call notes',0)
  self.route=f'/api/leads/{self.id}/sales-call'
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def test_facts_persist_separately_and_do_not_change_lead_or_counts(self):
  before=store.list_leads();counts=crm_calling.call_counts()
  initial=self.client.get(self.route).json
  self.assertEqual(initial['location'],'Phoenix, AZ');self.assertTrue(all(not v for v in initial['data'].values()))
  body={'revision':0,'data':{'services':'Pavers','service_areas':'Phoenix','google_reviews':'4.8 stars from 25 reviews','project_photos':'Completed-project photos verified'}}
  saved=self.client.post(self.route,json=body,headers=self.headers)
  self.assertEqual(saved.status_code,200);self.assertEqual(saved.json['revision'],1)
  self.assertEqual(self.client.get(self.route).json['data']['services'],'Pavers')
  self.assertEqual(self.client.post(self.route,json=body,headers=self.headers).status_code,409)
  self.assertEqual(store.list_leads(),before);self.assertEqual(crm_calling.call_counts(),counts)
  with store.connect() as con:self.assertEqual(con.execute('SELECT text FROM crm_call_notes WHERE lead_id=?',(self.id,)).fetchone()[0],'Private call notes')
 def test_rejects_unbooked_tests_invalid_facts_and_missing_csrf(self):
  body={'revision':0,'data':{}}
  self.assertEqual(self.client.post(self.route,json=body).status_code,403)
  for data in ({'made_up':1},{'services':False},{'services':'x'*2001},{'project_photos':'Yes'}):
   self.assertEqual(self.client.post(self.route,json={'revision':0,'data':data},headers=self.headers).status_code,400)
  with store.connect() as con:con.execute("UPDATE crm_leads SET status='New' WHERE id=?",(self.id,))
  self.assertEqual(self.client.post(self.route,json=body,headers=self.headers).status_code,400)
  with store.connect() as con:con.execute("UPDATE crm_leads SET status='Call booked',is_test=1 WHERE id=?",(self.id,))
  self.assertEqual(self.client.post(self.route,json=body,headers=self.headers).status_code,400)
  self.assertEqual(self.client.get('/api/leads/9999/sales-call').status_code,404)
 def test_page_has_ordered_navigation_selector_and_new_opening_script(self):
  html=self.client.get('/').text
  self.assertLess(html.index('id="nav-calling"'),html.index('id="nav-called"'))
  self.assertLess(html.index('id="nav-called"'),html.index('id="nav-booked"'))
  self.assertIn('id="sales-prospect"',html);self.assertIn('/crm-assets/sales_call.js?v=1',html)

if __name__=='__main__':unittest.main()
