import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store
import crm_appointments as appointments


class AppointmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=os.environ.get('BMT_DATA_DIR')
        os.environ['BMT_DATA_DIR']=self.tmp.name
        self.n=store.add_lead('Example contractor','Alex','2505550100','alex@example.com','Website and social media')
        self.update()
        self.sent=[]

    def tearDown(self):
        if self.old is None:os.environ.pop('BMT_DATA_DIR',None)
        else:os.environ['BMT_DATA_DIR']=self.old
        self.tmp.cleanup()

    def row(self):return store.list_leads()[0]

    def update(self,clock='09:30'):
        r=self.row()
        store.update_lead(self.n,r['revision'],company=r['company'],contact=r['contact'],phone=r['phone'],email=r['email'],need=r['need'],
            status='Call booked',call_date='2030-01-02',call_time=clock,call_zone='Eastern',zoom_url='https://example.zoom.us/j/123')

    def sender(self,*args):self.sent.append(args);return {'ok':True}

    def test_time_zones_and_clock_gap(self):
        self.assertEqual(appointments.start_time('2026-11-07','09:00','Eastern'),'2026-11-07T14:00:00+00:00')
        self.assertEqual(appointments.start_time('2026-11-07','06:00','Vancouver'),'2026-11-07T13:00:00+00:00')
        with self.assertRaises(ValueError):appointments.start_time('2027-03-14','02:30','Eastern')

    def test_confirmation_reminder_and_reschedule(self):
        r=self.row();version=r['booking_version']
        message=appointments.preview(r)
        self.assertIn('9:30 AM',message['body']);self.assertIn('30 minutes',message['body']);self.assertIn('https://example.zoom.us/j/123',message['body'])
        appointments.send(self.n,version,sender=self.sender)
        with self.assertRaises(ValueError):appointments.send(self.n,version,sender=self.sender)
        appointments.run_reminders(sender=self.sender,now=datetime(2030,1,1,14,30,tzinfo=timezone.utc))
        appointments.run_reminders(sender=self.sender,now=datetime(2030,1,1,15,30,tzinfo=timezone.utc))
        self.assertEqual(len(self.sent),2);self.assertTrue(self.row()['reminder_sent_at'])
        self.update('10:00');new=self.row()
        self.assertGreater(new['booking_version'],version);self.assertIsNone(new['confirmation_sent_at']);self.assertIsNone(new['reminder_sent_at'])
        with self.assertRaises(store.Conflict):appointments.send(self.n,version,sender=self.sender)

    def test_failure_never_claims_success_or_retries_automatically(self):
        version=self.row()['booking_version']
        with self.assertRaises(ValueError):appointments.send(self.n,version,sender=lambda *args:{'ok':False})
        self.assertIsNone(self.row()['confirmation_sent_at'])
        with self.assertRaises(ValueError):appointments.send(self.n,version,sender=self.sender)
        self.assertEqual(self.sent,[])
        appointments.send(self.n,version,sender=self.sender,retry=True)
        self.assertTrue(self.row()['confirmation_sent_at'])

    def test_overlap_rejected_and_adjacent_calls_allowed(self):
        n=store.add_lead('Second lead',phone='2505550101')
        def book(clock):
            store.update_lead(n,0,company='Second lead',contact='',phone='2505550101',email='',need='',status='Call booked',call_date='2030-01-02',call_time=clock,call_zone='Eastern')
        with self.assertRaises(ValueError):book('09:45')
        book('10:00')

    def test_no_reminder_for_closed_or_short_notice_calls(self):
        r=self.row()
        with store.connect() as con:
            con.execute('UPDATE crm_leads SET confirmation_sent_at=? WHERE id=?',('2030-01-02T13:00:00+00:00',self.n))
        appointments.run_reminders(sender=self.sender,now=datetime(2030,1,2,13,30,tzinfo=timezone.utc))
        self.assertEqual(self.sent,[])
        with store.connect() as con:con.execute("UPDATE crm_leads SET status='Lost' WHERE id=?",(self.n,))
        appointments.run_reminders(sender=self.sender,now=datetime(2030,1,2,13,30,tzinfo=timezone.utc))
        self.assertEqual(self.sent,[])

if __name__=='__main__':unittest.main()
