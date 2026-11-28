import io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from werkzeug.datastructures import FileStorage
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store,crm_sales_close as close,crm_sales_call as sales,crm_sales_questions as questions,crm_customers,crm_onboarding,crm_booking,crm_web

class Provider:
 def __init__(self):self.zooms=0;self.calendars=0;self.fail=False;self.uncertain=False
 def free(self,d):pass
 def zoom(self,d):
  self.zooms+=1
  if self.uncertain:raise crm_booking.ProviderError('Uncertain response',uncertain=True)
  assert d['duration']==20 and d['silent_invite']
  assert (datetime.fromisoformat(d['end'])-datetime.fromisoformat(d['start'])).total_seconds()==1200
  return '123','https://zoom.us/j/123'
 def calendar(self,d,i,z):
  self.calendars+=1
  if self.fail:raise ValueError('Calendar unavailable')
  return 'event','https://calendar.google.com/event'

class CloseTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
  self.id=store.add_lead('Contractor',contact='Pat',email='pat@example.com',location='Phoenix, AZ')
  with store.connect() as con:con.execute("UPDATE crm_leads SET status='Call booked',call_start_utc='2030-01-01T15:00:00+00:00',call_zone='Arizona' WHERE id=?",(self.id,))
  self.client=crm_web.app.test_client();self.client.get('/')
  with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def setup_close(self):
  return close.save(self.id,{'revision':0,'data':{'email':'pat@example.com','payment_plan':'50% deposit','payment_reference':'pi_example','host_id':'michael','date':'2030-01-02','time':'10:00','zone':'Arizona'}})
 def pay(self):
  r=self.setup_close();return close.confirm_payment(self.id,{'revision':r['revision'],'payment_received':True})
 def upload(self,kind):return close.upload(self.id,kind,FileStorage(stream=io.BytesIO(b'%PDF-1.4 '+kind.encode()),filename=kind+'.pdf'))
 def test_full_close_workflow_preserves_sales_booking_and_sends_one_package(self):
  s=sales.read(self.id);sales.save(self.id,{'revision':s['revision'],'data':s['data'],'answers':{'trade':'Concrete','service_area':'Phoenix and Mesa','ideal_jobs':'Stamped patios','lead_quality':'Homeowners ready for an estimate'}})
  self.setup_close();sent=[]
  def sender(to,subject,body,attachments):sent.append((to,subject,body,[p.read_bytes() for p in attachments]));return {'ok':True}
  p=close.preview(self.id,'payment');close.send(self.id,'payment',{'digest':p['digest']},sender=sender)
  self.assertIn('$1,500 USD',sent[0][2]);self.assertIn('buy.stripe.com',sent[0][2]);self.assertEqual(sent[0][3],[])
  with self.assertRaises(ValueError):close.send(self.id,'payment',{'digest':p['digest']},sender=sender)
  self.upload('Contract');r=close.read(self.id)
  close.confirm_payment(self.id,{'revision':r['revision'],'payment_received':True})
  self.assertEqual(store.list_leads()[0]['status'],'Won');self.assertEqual(store.list_leads()[0]['call_start_utc'],'2030-01-01T15:00:00+00:00')
  provider=Provider();booked=close.book(self.id,{'revision':close.read(self.id)['revision']},provider=provider);self.assertEqual(booked['meeting']['state'],'complete')
  close.book(self.id,{'revision':close.read(self.id)['revision']},provider=provider);self.assertEqual(provider.zooms,1);self.assertEqual(provider.calendars,1)
  with self.assertRaises(ValueError):close.preview(self.id,'package')
  self.upload('Receipt');download=self.client.get(f'/api/leads/{self.id}/sales-close/document/Receipt');self.assertEqual(download.status_code,200);self.assertEqual(download.mimetype,'application/pdf');p=close.preview(self.id,'package');self.assertEqual(len(p['attachments']),2);self.assertIn('20 minutes',p['body']);self.assertIn('complete and sign',p['body'])
  close.send(self.id,'package',{'digest':p['digest']},sender=sender);self.assertEqual(len(sent),2);self.assertEqual(len(sent[1][3]),2)
  self.assertEqual(len(crm_customers.read(self.id)['documents']),2)
  self.assertEqual(close.appointments()[0]['duration_minutes'],20)
  self.assertEqual(crm_onboarding.read(self.id)['data']['area'],'Phoenix and Mesa')
  self.assertEqual(crm_onboarding.read(self.id)['data']['project'],'Stamped patios')
 def test_validation_stale_preview_and_unconfirmed_payment(self):
  r=self.setup_close()
  with self.assertRaises(ValueError):close.confirm_payment(self.id,{'revision':r['revision'],'payment_received':False})
  with self.assertRaises(ValueError):close.book(self.id,{'revision':close.read(self.id)['revision']},provider=Provider())
  with self.assertRaises(ValueError):close.preview(self.id,'package')
  p=close.preview(self.id,'payment');close.save(self.id,{'revision':r['revision'],'data':{'email':'corrected@example.com'}})
  with self.assertRaises(store.Conflict):close.send(self.id,'payment',{'digest':p['digest']},sender=lambda *a,**k:self.fail('Must not send stale email'))
  with self.assertRaises(ValueError):close.save(self.id,{'revision':2,'data':{'payment_confirmed':'fake'}})
  with self.assertRaises(ValueError):close.upload(self.id,'Receipt',FileStorage(stream=io.BytesIO(b'not PDF'),filename='receipt.pdf'))
  route=f'/api/leads/{self.id}/sales-close/payment';self.assertEqual(self.client.post(route,json={}).status_code,403)
 def test_failed_email_requires_explicit_review_and_success_is_not_repeated(self):
  self.setup_close();p=close.preview(self.id,'payment');calls=[]
  def sender(*a,**k):calls.append(1);return {'ok':len(calls)>1}
  with self.assertRaises(ValueError):close.send(self.id,'payment',{'digest':p['digest']},sender=sender)
  with self.assertRaises(ValueError):close.send(self.id,'payment',{'digest':p['digest']},sender=sender)
  self.assertEqual(len(calls),1)
  close.send(self.id,'payment',{'digest':p['digest'],'reviewed_sent_mail':True},sender=sender);self.assertEqual(len(calls),2)
 def test_booking_retry_reuses_zoom_and_uncertain_creation_stops(self):
  self.pay();provider=Provider();provider.fail=True;r=close.book(self.id,{'revision':close.read(self.id)['revision']},provider=provider);self.assertEqual(r['meeting']['state'],'failed')
  provider.fail=False;r=close.book(self.id,{'revision':close.read(self.id)['revision']},provider=provider);self.assertEqual(r['meeting']['state'],'complete');self.assertEqual(provider.zooms,1);self.assertEqual(provider.calendars,2)
 def test_default_contract_is_included_and_prospect_timezone_wins(self):
  r=self.setup_close()
  with store.connect() as con:con.execute("UPDATE crm_leads SET lead_timezone='America/Los_Angeles',call_zone='Eastern' WHERE id=?",(self.id,))
  self.assertEqual(close.read(self.id)['data']['zone'],'Pacific (US)')
  r=close.save(self.id,{'revision':r['revision'],'data':{'zone':'Eastern'}})
  self.assertEqual(r['data']['zone'],'Pacific (US)')
  self.assertTrue(next(d for d in r['documents'] if d['kind']=='Contract')['default'])
  self.assertEqual(close.document(self.id,'Contract')['body'],close.DEFAULT_CONTRACT.read_bytes())
  with self.assertRaises(ValueError):self.upload('Receipt')
  close.confirm_payment(self.id,{'revision':r['revision'],'payment_received':True});self.upload('Receipt')
  close.book(self.id,{'revision':close.read(self.id)['revision']},provider=Provider())
  p=close.preview(self.id,'package');self.assertEqual({d['kind'] for d in p['attachments']},{'Contract','Receipt'})
  self.assertEqual(len(crm_customers.read(self.id)['documents']),2)

 def test_uncertain_zoom_is_not_created_twice(self):
  self.pay();p=Provider();p.uncertain=True;r=close.book(self.id,{'revision':close.read(self.id)['revision']},provider=p);self.assertEqual(r['meeting']['state'],'review')
  with self.assertRaises(ValueError):close.book(self.id,{'revision':close.read(self.id)['revision']},provider=p)
  self.assertEqual(p.zooms,1)
 def test_answers_validate_preserve_facts_and_reject_cross_prospect_revision(self):
  r=sales.read(self.id);sales.save(self.id,{'revision':0,'data':r['data'],'answers':{'trade':'Excavation','excavation_work':'Septic work'}})
  r=sales.read(self.id);self.assertEqual(r['answers']['excavation_work'],'Septic work')
  sales.save(self.id,{'revision':1,'data':r['data']});self.assertEqual(sales.read(self.id)['answers']['trade'],'Excavation')
  with self.assertRaises(ValueError):questions.validate({'trade':'Roofing'})
  with self.assertRaises(ValueError):questions.validate({'invented':'bad'})

if __name__=='__main__':unittest.main()
