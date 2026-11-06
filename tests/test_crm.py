import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store as store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('BMT_DATA_DIR')
        os.environ['BMT_DATA_DIR'] = self.tmp.name

    def tearDown(self):
        if self.old is None: os.environ.pop('BMT_DATA_DIR',None)
        else: os.environ['BMT_DATA_DIR'] = self.old
        self.tmp.cleanup()

    def test_new_seen_follow_up_notes_and_restart(self):
        n = store.add_lead('Warm contractor','Pat','555-0100','','Website needs work','2026-11-06')
        row = store.list_leads()[0]
        self.assertEqual(store.counts([row],'2026-11-06'),{'new':1,'due':1,'booked':0})
        store.mark_seen(n,'Closer')
        row = store.list_leads()[0]
        self.assertEqual(row['seen_by'],'Closer')
        store.update_lead(n,row['revision'],company=row['company'],contact=row['contact'],phone=row['phone'],
            email=row['email'],need=row['need'],status='Call booked',call_date='2026-11-09',call_time='10:00 AM',
            call_zone='Eastern',follow_up='2026-11-07',note='Confirmed decision maker and budget.',author='Closer')
        import importlib
        importlib.reload(store)
        row = store.list_leads()[0]
        self.assertEqual(row['status'],'Call booked')
        self.assertEqual(store.counts([row],'2026-11-06'),{'new':0,'due':0,'booked':1})
        self.assertEqual(store.notes_for(n)[0]['text'],'Confirmed decision maker and budget.')
        self.assertFalse(Path(self.tmp.name,'leads_log.csv').exists())

    def test_stale_save_cannot_overwrite_or_append_note(self):
        n = store.add_lead('Contractor',phone='555-0100')
        store.mark_seen(n,'Closer')
        with self.assertRaises(store.Conflict):
            store.update_lead(n,0,company='Old form',contact='',phone='555-0100',email='',need='',
                              status='Lost',note='Stale note')
        self.assertEqual(store.list_leads()[0]['company'],'Contractor')
        self.assertEqual(store.notes_for(n),[])

    def test_validation(self):
        with self.assertRaises(ValueError):store.add_lead('No contact')
        with self.assertRaises(ValueError):store.add_lead('',phone='555-0100')


class UIFlowTests(unittest.TestCase):
    setUp = StoreTests.setUp
    tearDown = StoreTests.tearDown
    def test_owner_and_closer_workflow(self):
        from streamlit.testing.v1 import AppTest
        old_password = os.environ.get('BMT_CRM_PASSWORD')
        os.environ['BMT_CRM_PASSWORD'] = 'isolated-test-password'
        try:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'receipt_app.py')).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertFalse(app.metric)
            app.text_input[0].input('isolated-test-password')
            app.button[0].click().run(timeout=20)
            def field(label):return next(x for x in app.text_input if x.label==label)
            def button(label):return next(x for x in app.button if x.label==label)
            field('Company name *').input('Test Warm Lead')
            field('Contact name').input('Alex')
            field('Phone').input('555-0100')
            app.text_area[0].input('Needs an updated website')
            button('Add lead').click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value,'1')
            app.selectbox[0].select('Closer').run(timeout=20)
            button('Mark as seen').click().run(timeout=20)
            self.assertEqual(app.metric[0].value,'0')
            next(x for x in app.selectbox if x.label=='Status').select('Follow-up')
            next(x for x in app.text_area if x.label=='Add closer note / next step').input('Call back Monday.')
            button('Save update').click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(store.list_leads()[0]['status'],'Follow-up')
            self.assertEqual(store.notes_for(store.list_leads()[0]['id'])[0]['text'],'Call back Monday.')
            # A second session changes the lead after the first session rendered its form.
            row=store.list_leads()[0]
            store.update_lead(row['id'],row['revision'],company=row['company'],contact=row['contact'],phone=row['phone'],
                              email=row['email'],need=row['need'],status='Contacted',author='Michael')
            button('Save update').click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(store.list_leads()[0]['status'],'Contacted')
            self.assertTrue(any('changed in another session' in x.value for x in app.error))
        finally:
            if old_password is None:os.environ.pop('BMT_CRM_PASSWORD',None)
            else:os.environ['BMT_CRM_PASSWORD']=old_password


if __name__=='__main__':unittest.main()
