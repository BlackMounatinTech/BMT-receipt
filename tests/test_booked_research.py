import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store,crm_sales_call as facts,crm_booked_research as research,crm_web

class BookedResearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
  self.id=store.add_lead('Concrete Co',phone='6025550100',location='Phoenix, AZ',need='Keep research notes')
  with store.connect() as con:con.execute("UPDATE crm_leads SET status='Call booked',call_start_utc='2030-01-01T15:00:00+00:00' WHERE id=?",(self.id,))
  self.client=crm_web.app.test_client();self.client.get('/')
  with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def claim(self):
  research.request(self.id);return research.worker({'op':'claim'})['job']
 def report(self,job):
  t=store.now();photo=dict(status='verified',usable_photos_seen=12,photos_reviewed=15,before_after='no',source_url='https://www.facebook.com/concrete/photos',notes='Inspected twelve distinct completed patios and three other images.',checked_at=t)
  return dict(company=dict(location='Phoenix, AZ',identity_notes='Official phone matches 6025550100.',services=['Stamped patios'],service_areas=['Phoenix'],sources=[dict(url='https://example.com',checked_at=t,observation='Phone and service area confirmed.')]),facebook=photo,instagram=dict(status='unavailable',usable_photos_seen=None,photos_reviewed=None,before_after='unverified',source_url='',notes='Login required; no photos inspected.',checked_at=t),ads=dict(status='running',ad_ids=['12345'],source_url='https://www.facebook.com/ads/library/?id=12345',notes='Matching page shows an active patio ad.',checked_at=t),google=dict(status='verified',rating=4.9,reviews=42,profile_quality='Strong',source_url='https://maps.google.com',notes='Reviews, project photos, website and hours are present.',checked_at=t),talking_points=['Your Google profile shows 4.9 stars from 42 reviews.'])
 def test_button_queue_deduplicates_and_worker_finishes_partial_report(self):
  original=store.list_leads();a=research.request(self.id);b=research.request(self.id);self.assertEqual(a['job']['id'],b['job']['id']);self.assertEqual(a['job']['state'],'queued')
  job=research.worker({'op':'claim'})['job'];self.assertEqual(job['company'],'Concrete Co');self.assertIsNone(research.worker({'op':'claim'})['job'])
  research.worker({'op':'finish','job_id':job['id'],'report':self.report(job)})
  s=research.status(self.id);self.assertEqual(s['job']['state'],'partial');self.assertTrue(s['worker_online']);self.assertEqual(s['report']['facebook']['photo_bucket'],'10+');self.assertEqual(s['report']['instagram']['photo_bucket'],'Unknown')
  f=facts.read(self.id);self.assertEqual(f['data']['google_reviews'],'4.9 stars from 42 reviews');self.assertEqual(f['company_research']['ads']['status'],'running')
  self.assertEqual(store.list_leads(),original)
 def test_new_research_preserves_answers_and_manually_updated_facts(self):
  f=facts.read(self.id);facts.save(self.id,{'revision':f['revision'],'data':dict(f['data'],services='Original service'),'answers':{'trade':'Concrete','goals':'More large projects'}})
  job=self.claim();f=facts.read(self.id);facts.save(self.id,{'revision':f['revision'],'data':dict(f['data'],services='Corrected by Michael'),'answers':f['answers']})
  research.worker({'op':'finish','job_id':job['id'],'report':self.report(job)})
  f=facts.read(self.id);self.assertEqual(f['data']['services'],'Corrected by Michael');self.assertEqual(f['answers']['goals'],'More large projects')
 def test_unverified_counts_and_bad_active_ad_proof_are_not_saved(self):
  job=self.claim();r=self.report(job);r['ads']['ad_ids']=[]
  with self.assertRaises(ValueError):research.worker({'op':'finish','job_id':job['id'],'report':r})
  r=self.report(job);r['facebook']['usable_photos_seen']=20;r['facebook']['photos_reviewed']=5
  with self.assertRaises(ValueError):research.worker({'op':'finish','job_id':job['id'],'report':r})
  r=self.report(job);r['facebook']['source_url']='javascript:alert(1)'
  with self.assertRaises(ValueError):research.worker({'op':'finish','job_id':job['id'],'report':r})
  self.assertIsNone(research.status(self.id)['report'])
 def test_worker_requires_auth_and_queue_requires_csrf(self):
  self.assertEqual(self.client.post('/api/booked-research/worker',json={'op':'claim'},headers=self.headers).status_code,403)
  self.assertEqual(self.client.post(f'/api/leads/{self.id}/booked-research',json={}).status_code,403)
  self.assertEqual(self.client.post(f'/api/leads/{self.id}/booked-research',json={},headers=self.headers).status_code,200)
 def test_no_cold_company_or_test_company_can_be_queued(self):
  cold=store.add_lead('Cold',phone='6025550101')
  with self.assertRaises(ValueError):research.request(cold)
  with store.connect() as con:con.execute('UPDATE crm_leads SET is_test=1 WHERE id=?',(self.id,))
  with self.assertRaises(ValueError):research.request(self.id)
 def test_interruption_does_not_fabricate_completed_research(self):
  job=self.claim();research.worker({'op':'fail','job_id':job['id'],'reason':'Instagram and Facebook could not be inspected.'})
  s=research.status(self.id);self.assertEqual(s['job']['state'],'blocked');self.assertIsNone(s['report'])

if __name__=='__main__':unittest.main()
