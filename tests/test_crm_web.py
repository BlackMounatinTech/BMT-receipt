import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crm_web
import crm_store


class SimpleCRMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('BMT_DATA_DIR')
        os.environ['BMT_DATA_DIR'] = self.tmp.name
        self.client = crm_web.app.test_client()
        self.assertEqual(self.client.get('/').status_code, 200)
        with self.client.session_transaction() as sess:
            self.headers = {'X-CSRF-Token': sess['csrf']}

    def tearDown(self):
        if self.old is None:
            os.environ.pop('BMT_DATA_DIR', None)
        else:
            os.environ['BMT_DATA_DIR'] = self.old
        self.tmp.cleanup()

    def test_shared_lead_workflow_and_conflicts(self):
        data = dict(company='Example contractor',contact='Alex',phone='2505550100',email='',need='Website',follow_up='2026-11-07')
        response = self.client.post('/api/leads',json=data,headers=self.headers)
        self.assertEqual(response.status_code, 201)
        n = response.json['id']
        # Existing store sees the same data; no import or migration is needed.
        lead = crm_store.list_leads()[0]
        self.assertEqual(lead['company'], data['company'])
        self.assertEqual(self.client.post(f'/api/leads/{n}/seen',headers=self.headers).status_code,200)
        current = self.client.get('/api/leads').json['leads'][0]
        self.assertEqual(current['seen_by'],'Closer')
        current.update(status='Follow-up',note='Call Monday',author='Closer')
        self.assertEqual(self.client.patch(f'/api/leads/{n}',json=current,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get(f'/api/leads/{n}/notes').json['notes'][0]['text'],'Call Monday')
        current['note'] = 'Stale change'
        self.assertEqual(self.client.patch(f'/api/leads/{n}',json=current,headers=self.headers).status_code,409)
        self.assertEqual(len(crm_store.notes_for(n)),1)

    def test_validation_and_csrf(self):
        self.assertEqual(self.client.post('/api/leads',json={'company':'No contact'},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/leads',json={'company':'External','phone':'123'}).status_code,403)
        self.assertEqual(self.client.get('/healthz').status_code,200)
        with self.client.get('/crm-assets/crm.js') as response:
            self.assertEqual(response.status_code,200)

    def test_booking_email_and_manual_reply_confirmation(self):
        n=self.client.post('/api/leads',json={'company':'Appointment test','email':'alex@example.com'},headers=self.headers).json['id']
        lead=self.client.get('/api/leads').json['leads'][0]
        lead.update(status='Call booked',call_date='2030-01-02',call_time='09:30',call_zone='Eastern',zoom_url='https://example.zoom.us/j/123')
        self.assertEqual(self.client.patch(f'/api/leads/{n}',json=lead,headers=self.headers).status_code,200)
        preview=self.client.get(f'/api/leads/{n}/appointment-email').json
        self.assertIn('9:30 AM',preview['body'])
        payload={'version':preview['version']}
        self.assertEqual(self.client.post(f'/api/leads/{n}/confirm-appointment',json=payload,headers=self.headers).status_code,409)
        with patch('tools.email_sender.send_email',return_value={'ok':True}) as sender:
            self.assertEqual(self.client.post(f'/api/leads/{n}/appointment-email',json=payload,headers=self.headers).status_code,200)
            sender.assert_called_once()
        self.assertEqual(self.client.post(f'/api/leads/{n}/confirm-appointment',json=payload,headers=self.headers).status_code,200)
        result=self.client.get('/api/leads').json['leads'][0]
        self.assertTrue(result['confirmed_at']);self.assertTrue(result['confirmation_sent_at']);self.assertEqual(result['call_start_utc'],'2030-01-02T14:30:00+00:00')


if __name__ == '__main__':
    unittest.main()
