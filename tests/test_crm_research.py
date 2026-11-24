import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_store,crm_web,crm_calling

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=os.environ.get('BMT_DATA_DIR');os.environ['BMT_DATA_DIR']=self.tmp.name
        self.client=crm_web.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.headers={'X-CSRF-Token':s['csrf']}
        self.id=crm_store.add_lead('Contractor',phone='5551234567',need='Original research')
        crm_calling.save_notes(self.id,'Owner asked for a callback',0)
        self.payload={'revision':0,'need':'Paver patios\nAngle: project ads + quote form','website':'https://example.com',
                      'business_hours':{'weekly':{'0':[[480,1020]],'6':[]},'source_url':'https://example.com/contact','source':'Company website','checked_at':'2026-11-23'}}
    def tearDown(self):
        if self.old is None:os.environ.pop('BMT_DATA_DIR',None)
        else:os.environ['BMT_DATA_DIR']=self.old
        self.tmp.cleanup()
    def test_enrichment_preserves_sales_state_and_call_notes(self):
        route=f'/api/calling/leads/{self.id}/research'
        self.assertEqual(self.client.post(route,json=self.payload,headers=self.headers).status_code,200)
        lead=crm_store.list_leads()[0]
        self.assertEqual(lead['need'],self.payload['need']);self.assertEqual(lead['status'],'New')
        self.assertEqual(json.loads(lead['business_hours'])['weekly']['6'],[])
        with crm_store.connect() as c:self.assertEqual(c.execute('SELECT text FROM crm_call_notes WHERE lead_id=?',(self.id,)).fetchone()[0],'Owner asked for a callback')
        self.assertEqual(self.client.post(route,json=self.payload,headers=self.headers).status_code,409)
    def test_invalid_hours_and_csrf_do_not_change_research(self):
        route=f'/api/calling/leads/{self.id}/research'
        self.assertEqual(self.client.post(route,json=self.payload).status_code,403)
        for periods in [[[480,480]],[[1500,1600]],[[True,600]],'8-5']:
            self.payload['business_hours']['weekly']['0']=periods
            self.assertEqual(self.client.post(route,json=self.payload,headers=self.headers).status_code,400)
        self.assertEqual(crm_store.list_leads()[0]['need'],'Original research')

if __name__=='__main__':unittest.main()
