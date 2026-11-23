import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_web
import crm_store as store
import crm_calling as calling
import crm_booking as booking


class FakeProviders:
    def __init__(self): self.zoom_calls=0;self.calendar_calls=0;self.fail_calendar=False
    def free(self,details): pass
    def zoom(self,details):
        self.zoom_calls+=1
        return '123','https://example.zoom.us/j/123'
    def calendar(self,details,job_id,url):
        self.calendar_calls+=1
        if self.fail_calendar: raise booking.ProviderError('Calendar unavailable')
        return job_id,'https://calendar.google.com/calendar/event?eid=test'


class CallingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name})
        self.env.start()
        self.client=crm_web.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}

    def tearDown(self): self.env.stop();self.tmp.cleanup()

    def upload(self,raw,commit='false'):
        return self.client.post('/api/calling/import',data={'name':'Test list','file':(io.BytesIO(raw.encode()),'leads.csv'),'commit':commit},headers=self.headers)

    def test_preview_import_dedupe_and_call_history(self):
        n=store.add_lead('Existing','Pat','+1 212 555 0100',need='Keep these notes')
        raw='Company,Location,Phone number,Notes\nExisting,NY,(212) 555-0100,Overwrite?\nNew Co,Boston,6175550101,Concrete patios\nNew Co,Boston,+1 617 555 0101,Duplicate\n'
        result=self.upload(raw).json
        self.assertEqual((result['new'],result['existing'],result['duplicates']),(1,1,1))
        self.assertEqual(len(store.list_leads()),1)
        result=self.upload(raw,'true').json
        items=calling.items(result['list_id']);self.assertEqual(len(items),2)
        self.assertEqual(next(l for l in items if l['id']==n)['need'],'Keep these notes')
        new=next(l for l in items if l['id']!=n);self.assertEqual(new['stage'],'Cold')
        path=f"/api/calling/lists/{result['list_id']}/{new['id']}/outcome"
        payload=dict(revision=new['revision'],outcome='Follow up',follow_up='2030-02-01',note='Owner returns Friday')
        self.assertEqual(self.client.post(path,json=payload,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post(path,json=payload,headers=self.headers).status_code,409)
        saved=next(l for l in store.list_leads() if l['id']==new['id'])
        self.assertEqual(saved['status'],'Follow-up');self.assertEqual(saved['follow_up'],'2030-02-01')
        self.assertIn('Owner returns Friday',store.notes_for(new['id'])[0]['text'])

    def test_import_is_atomic_and_accepts_title_rows_in_xlsx(self):
        self.assertEqual(self.upload('Company,Phone\nGood,2125550100\nBad,\n','true').status_code,400)
        self.assertEqual(store.list_leads(),[])
        from openpyxl import Workbook
        book=Workbook();s=book.active;s.append(['BMT calling']);s.append([]);s.append(['Company','Phone number']);s.append(['Sample',2125550100])
        data=io.BytesIO();book.save(data);data.seek(0)
        response=self.client.post('/api/calling/import',data={'file':(data,'leads.xlsx'),'commit':'true'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['new'],1)

    def test_booking_resume_does_not_duplicate_zoom_or_confirmation(self):
        result=self.upload('Company,Phone\nSample,2125550100\n','true').json
        lead=calling.items(result['list_id'])[0]
        host=dict(id='michael',name='Michael',email='michael@example.com',zoom_user='michael@example.com',calendar_id='michael@example.com')
        provider=FakeProviders();provider.fail_calendar=True
        data=dict(revision=lead['revision'],contact='Pat',email='pat@example.com',date='2030-01-02',time='09:00',zone='Eastern',host_id='michael',list_id=result['list_id'],note='Needs consistent project posts')
        with patch.object(booking,'connection_status',return_value={'ready':True}),patch.object(booking,'hosts',return_value=[host]),patch.object(booking,'Providers',return_value=provider):
            job=booking.create(lead['id'],data)
        self.assertEqual(job['state'],'failed');self.assertTrue(job['zoom_url'])
        self.assertNotEqual(store.list_leads()[0]['status'],'Call booked')
        provider.fail_calendar=False
        with patch('tools.email_sender.send_email',return_value={'ok':False}):
            job=booking.resume(job['id'],provider)
        self.assertEqual(job['state'],'confirmation_failed')
        self.assertEqual(store.list_leads()[0]['status'],'Call booked')
        sender=lambda *args: {'ok':True}
        job=booking.resume(job['id'],provider,sender)
        self.assertEqual(job['state'],'complete');self.assertEqual(provider.zoom_calls,1)
        self.assertEqual(provider.calendar_calls,2)
        job=booking.resume(job['id'],provider,lambda *a:self.fail('Duplicate send'))
        self.assertEqual(job['state'],'complete')
        self.assertEqual(calling.items(result['list_id'])[0]['outcome'],'Booked')

    def test_uncertain_zoom_and_concurrent_claim_block_retry(self):
        n=store.add_lead('Test','Pat','2125550100')
        details=dict(host={'id':'michael','name':'Michael'},start='2030-01-02T14:00:00+00:00')
        with store.connect() as con:
            booking.schema(con)
            con.execute("INSERT INTO crm_booking_jobs(id,lead_id,payload,state,updated_at) VALUES('job',?,?, 'pending',?)",(n,json.dumps(details),store.now()))
        provider=FakeProviders()
        provider.zoom=lambda d: (_ for _ in ()).throw(booking.ProviderError('Interrupted',uncertain=True))
        job=booking.resume('job',provider)
        self.assertEqual(job['state'],'review')
        with self.assertRaises(ValueError):booking.resume('job',provider)

    def test_connections_required_and_csrf(self):
        with patch.object(booking,'connection_status',return_value={'ready':False}):
            response=self.client.post('/api/leads/1/book',json={},headers=self.headers)
            self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.post('/api/calling/import').status_code,403)

    def test_failed_draft_can_be_released_but_created_meeting_cannot(self):
        n=store.add_lead('Test','Pat','2125550100')
        with store.connect() as con:
            booking.schema(con)
            con.execute("INSERT INTO crm_booking_jobs(id,lead_id,payload,state,updated_at) VALUES('a',?,'{}','failed',?)",(n,store.now()))
            con.execute("INSERT INTO crm_booking_jobs(id,lead_id,payload,state,zoom_id,updated_at) VALUES('b',?,'{}','failed','123',?)",(n,store.now()))
        booking.abandon('a');self.assertEqual(booking.get_job('a')['state'],'abandoned')
        with self.assertRaises(ValueError):booking.abandon('b')

    def test_calendar_recovers_existing_event_without_sending_another_invitation(self):
        provider=booking.Providers();provider.google_token='test-token'
        response=type('Response',(),{'status_code':200,'json':lambda self:{'htmlLink':'https://calendar.google.com/test'}})()
        with patch('crm_booking.requests.get',return_value=response),patch('crm_booking.request_json') as create:
            event_id,url=provider.calendar({'host':{'calendar_id':'michael@example.com'}},'abc123','https://example.zoom.us/j/123')
            self.assertEqual(event_id,'bmtabc123');self.assertTrue(url);create.assert_not_called()


if __name__=='__main__':unittest.main()
