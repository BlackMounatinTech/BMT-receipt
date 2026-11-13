import os
import tempfile
import unittest
from unittest.mock import patch
import crm_store as store
import crm_web


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'BMT_DATA_DIR': self.tmp.name})
        self.env.start()
        self.client = crm_web.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as s:
            self.headers = {'X-CSRF-Token': s['csrf']}
        self.record = dict(company='Example Fencing', instagram='https://instagram.com/ExampleFence/',
                           sender='mickeymackrell',confirmed_utc='2026-11-12T07:00:00Z',
                           message='Example outreach message',status='sent',location='Example, WA',focus='Profile cleanup')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def import_records(self, records=None):
        return self.client.post('/api/outreach/import-instagram',json={'records': records or [self.record]},headers=self.headers)

    def test_import_replay_history_and_promote(self):
        response = self.import_records()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['created'],1)
        lead = store.list_leads()[0]
        self.assertEqual(lead['stage'],'Outreach')
        self.assertEqual(lead['status'],'Contacted')
        self.assertEqual(lead['instagram'],'https://www.instagram.com/examplefence/')
        self.assertEqual(lead['contact_account'],'mickeymackrell')
        self.assertEqual(store.counts([lead],'2026-11-12')['new'],0)
        self.assertIn('Example outreach message',store.notes_for(lead['id'])[0]['text'])
        self.assertEqual(self.import_records().json['skipped'],1)
        self.assertEqual(len(store.list_leads()),1)
        self.assertEqual(len(store.notes_for(lead['id'])),1)
        lead.update(stage='Prospect',note='They replied with interest.')
        self.assertEqual(self.client.patch('/api/leads/'+str(lead['id']),json=lead,headers=self.headers).status_code,200)
        current=store.list_leads()[0]
        self.assertEqual(current['stage'],'Prospect')
        self.assertEqual(current['last_contacted_at'],lead['last_contacted_at'])
        self.assertEqual(len(store.notes_for(lead['id'])),2)
        self.assertEqual(self.client.patch('/api/leads/'+str(lead['id']),json=lead,headers=self.headers).status_code,409)

    def test_invalid_batch_is_atomic_and_csrf_required(self):
        invalid={**self.record,'status':'draft'}
        self.assertEqual(self.import_records([self.record,invalid]).status_code,400)
        self.assertEqual(store.list_leads(),[])
        self.assertEqual(self.client.post('/api/outreach/import-instagram',json={'records':[self.record]}).status_code,403)
        invalid={**self.record,'instagram':'javascript:alert(1)'}
        self.assertEqual(self.import_records([invalid]).status_code,400)

    def test_match_preserves_warm_lead(self):
        n=store.add_lead('Existing customer',instagram=self.record['instagram'])
        response=self.import_records()
        self.assertEqual(response.json['created'],0)
        self.assertEqual(response.json['lead_ids'],[n])
        lead=store.list_leads()[0]
        self.assertEqual(lead['stage'],'Prospect')
        self.assertEqual(lead['company'],'Existing customer')


if __name__=='__main__':
    unittest.main()
