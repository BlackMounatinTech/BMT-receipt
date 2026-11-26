import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_web
import crm_store as store
import crm_calling as calling
import crm_stats as stats

class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
        self.client=crm_web.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}
        self.lead=store.add_lead('Test concrete',phone='5555550100')
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()
    def test_calendar_days_outcomes_unknown_and_reset_do_not_change_history(self):
        with store.connect() as con:
            calling.schema(con)
            for index,(outcome,stamp) in enumerate([
                ('No answer','2026-11-25T06:59:59+00:00'), # Nov24 at11:59PM
                ('Not interested','2026-11-25T07:00:00+00:00'),
                ('Follow up','2026-11-25T15:00:00+00:00'),
                ('Book meeting','2026-11-25T16:00:00+00:00'),
                ('Called','2026-11-25T17:00:00+00:00')]):
                calling.record_event(con,str(index),self.lead,outcome,stamp)
            stats.record_booking(con,self.lead,'2026-11-25T16:30:00+00:00')
            stats.record_booking(con,self.lead,'2026-11-26T16:30:00+00:00')
        calling.call_counts(reset=True,instant=datetime(2026,11,25,20,tzinfo=timezone.utc))
        r=stats.report('2026-11-24','2026-11-25')
        self.assertEqual(r['totals']['calls'],5)
        self.assertEqual(r['days'][0]['answered'],3)
        self.assertEqual(r['days'][0]['unknown'],1)
        self.assertEqual(r['days'][1]['no_answer'],1)
        self.assertEqual(r['totals']['meetings_booked'],1)
        self.assertEqual(stats.report('2026-11-24','2026-11-25')['totals'],r['totals'])
    def test_outreach_replace_revision_and_separate_channels(self):
        p=dict(day='2026-11-25',channel='Facebook',sent=20,replies=5,booked=1,notes='Objection',revision=0)
        self.assertEqual(self.client.post('/api/stats/outreach',json=p).status_code,403)
        self.assertEqual(self.client.post('/api/stats/outreach',json=p,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/stats/outreach',json=p,headers=self.headers).status_code,409)
        p.update(revision=1,sent=25)
        self.client.post('/api/stats/outreach',json=p,headers=self.headers)
        self.assertEqual(stats.outreach_row(p['day'],'Facebook')['sent'],25)
        self.assertEqual(stats.outreach_row(p['day'],'Instagram')['sent'],0)
        self.assertEqual(stats.report(p['day'],p['day'])['totals']['calls'],0)
    def test_discovery_edit_no_show_and_collected(self):
        p=dict(id='one',revision=0,day='2026-11-25',company='Fence Co',minutes=30,outcome='Closed',rating=4,offer_presented=True,collected_usd=1500,notes='Trust objection')
        self.assertEqual(self.client.post('/api/stats/discovery',json=p,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/stats/discovery',json=p,headers=self.headers).status_code,409)
        p.update(revision=1,minutes=40)
        self.client.post('/api/stats/discovery',json=p,headers=self.headers)
        p.update(id='two',revision=0,outcome='No-show',collected_usd=0,offer_presented=False,rating=None)
        self.client.post('/api/stats/discovery',json=p,headers=self.headers)
        r=stats.report('2026-11-25','2026-11-25')
        self.assertEqual(r['totals']['discoveries'],1);self.assertEqual(r['totals']['no_shows'],1)
        self.assertEqual(r['totals']['closes'],1);self.assertEqual(r['totals']['minutes'],40)
        self.assertEqual(r['totals']['collected_usd'],1500)
        self.assertEqual(store.list_leads()[0]['status'],'New')
    def test_booking_attempt_does_not_claim_a_successful_meeting(self):
        with store.connect() as con:
            calling.schema(con)
            calling.record_event(con,'attempt',self.lead,'Book meeting','2026-11-25T18:00:00+00:00')
        r=stats.report('2026-11-25','2026-11-25')['totals']
        self.assertEqual(r['answered'],1)
        self.assertEqual(r['booking_outcomes'],1)
        self.assertEqual(r['meetings_booked'],0)

    def test_validation_and_page(self):
        self.assertEqual(self.client.get('/api/stats?start=bad&end=bad').status_code,400)
        self.assertEqual(self.client.get('/api/stats?start=2026-11-26&end=2026-11-25').status_code,400)
        self.assertIn('id="stats-page"',self.client.get('/').get_data(as_text=True))
        p=dict(day='2026-11-25',channel='Facebook',sent=-1,replies=0,booked=0,revision=0)
        self.assertEqual(self.client.post('/api/stats/outreach',json=p,headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/stats/discovery',json={'day':'2026-11-25','company':'X','minutes':0,'outcome':'Closed'},headers=self.headers).status_code,400)
