"""Test fixtures must remain usable without inflating real sales reporting."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store
import crm_calling as calling
import crm_stats as stats
import crm_web

class TestRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()
    def test_reporting_excludes_test_bookings_wins_and_call_events(self):
        real=store.add_lead('Real contractor',phone='2125550100')
        test=store.add_lead('TEST — Booking sample',email='owner@example.com')
        demo=store.add_lead('Onboarding sample',email='demo@example.com',is_test=True)
        stamp='2026-11-27T16:00:00+00:00'
        with store.connect() as con:
            calling.schema(con)
            for lead in (real,test):
                con.execute("UPDATE crm_leads SET status='Call booked',booked_at=? WHERE id=?",(stamp,lead))
                stats.record_booking(con,lead,stamp)
                calling.record_event(con,str(lead),lead,'Book meeting',stamp)
            con.execute("UPDATE crm_leads SET status='Won' WHERE id=?",(demo,))
        self.assertEqual(calling.pipeline_counts(),{'booked':1,'closes':0})
        self.assertEqual(calling.call_counts()['total'],1)
        report=stats.report('2026-11-27','2026-11-27')['totals']
        self.assertEqual(report['meetings_booked'],1);self.assertEqual(report['calls'],1)
        # The onboarding demo and its Won state are preserved.
        self.assertEqual(next(l for l in store.list_leads() if l['id']==demo)['status'],'Won')
        with store.connect() as con:con.execute("UPDATE crm_leads SET status='Won' WHERE id=?",(real,))
        self.assertEqual(calling.pipeline_counts(),{'booked':1,'closes':1})
    def test_existing_fixture_migration_does_not_hide_similarly_named_real_company(self):
        test=store.add_lead('TEST — CRM Booking Email — Michael',email='michael@blackmountaintechnologies.ca')
        demo=store.add_lead('TEST — Demo Concrete Contractor',email='demo@example.com')
        real=store.add_lead('Test Concrete LLC',phone='2125550101')
        with store.connect() as con:con.execute('ALTER TABLE crm_leads DROP COLUMN is_test')
        rows={l['id']:l for l in store.list_leads()}
        self.assertEqual(rows[test]['is_test'],1);self.assertEqual(rows[demo]['is_test'],1)
        self.assertEqual(rows[real]['is_test'],0)
        self.assertEqual(len(rows),3)
    def test_api_accepts_explicit_boolean_test_flag(self):
        client=crm_web.app.test_client();client.get('/')
        with client.session_transaction() as session:headers={'X-CSRF-Token':session['csrf']}
        r=client.post('/api/leads',json={'company':'QA sample','email':'qa@example.com','is_test':True},headers=headers)
        self.assertEqual(r.status_code,201)
        self.assertEqual(store.list_leads()[0]['is_test'],1)
        self.assertEqual(client.post('/api/leads',json={'company':'QA sample','email':'qa@example.com','is_test':'true'},headers=headers).status_code,400)
