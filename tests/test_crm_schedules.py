import json,os,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_schedules as schedule
import crm_calling as calling
import crm_store as store
import crm_booking as booking
import crm_web

NOW=datetime(2026,11,25,18,tzinfo=timezone.utc)
def lead(n,zone,weekly):
    return dict(id=n,company=str(n),call_zone=zone,lead_timezone='',business_hours=json.dumps({'weekly':weekly}))

class ScheduleTests(unittest.TestCase):
    def test_morning_needs_open_at_six_and_order_is_our_opening_time(self):
        rows=[lead(1,'Eastern',{'2':[[480,1020]]}),lead(2,'Central',{'2':[[360,1020]]}),
              lead(3,'Eastern',{'2':[[540,1020]]}),lead(4,'Pacific (US)',{'2':[[360,1020]]})]
        result=schedule.select('morning',rows,NOW)
        self.assertEqual([r['id'] for r in result],[2,1])
        self.assertEqual([r['opening_minute'] for r in result],[300,360])

    def test_daytime_evening_and_unknown_hours(self):
        rows=[lead(1,'Pacific (US)',{'2':[[420,1020]]}),lead(2,'Mountain',{'2':[[480,1140]]}),
              lead(3,'Eastern',{'2':[[480,1020]]}),lead(4,'Pacific (US)',{}),
              lead(5,'Pacific (US)',{'2':[]})]
        self.assertEqual([r['id'] for r in schedule.select('daytime',rows,NOW)],[1,2])
        self.assertEqual({r['id'] for r in schedule.select('evening',rows,NOW)},{1,2})
        self.assertEqual(schedule.select('daytime',rows,NOW)[0]['opening_minute'],480)

    def test_weekends_and_overnight_periods(self):
        rows=[lead(1,'Pacific (US)',{'5':[[360,720]],'6':[]}),
              lead(2,'Eastern',{'5':[[480,720]],'6':[[600,840]]}),
              lead(3,'Arizona',{'4':[[1320,120]]})]
        sat=schedule.select('saturday',rows,NOW)
        self.assertEqual([r['id'] for r in sat],[3,2,1])
        self.assertEqual([r['opening_minute'] for r in sat],[0,360,420])
        self.assertEqual([r['id'] for r in schedule.select('sunday',rows,NOW)],[2])

    def test_24_hour_periods_merge_across_company_local_midnight(self):
        row=lead(1,'Pacific (US)',{str(i):[[0,1440]] for i in range(7)})
        result=schedule.select('daytime',[row],NOW)[0]
        self.assertEqual((result['opening_minute'],result['closing_minute']),(0,1440))

    def test_us_daylight_saving_conversion(self):
        row=lead(1,'Eastern',{'2':[[480,1020]]})
        summer=datetime(2026,7,1,18,tzinfo=timezone.utc)
        self.assertEqual(schedule.select('morning',[row],summer),[]) # Now +3, outside +1/+2.
        self.assertEqual(schedule.select('morning',[row],NOW)[0]['opening_minute'],360)

    def test_shared_history_across_lists_and_no_duplicate_call_events(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BMT_DATA_DIR':tmp}):
            result=calling.import_list('Original',[dict(company='Builder',phone='2065550100',location='Seattle, WA',email='',contact='',need='',website='',call_zone='Pacific (US)')],True)
            row=calling.items(result['list_id'])[0]
            weekly={str(i):[[360,1200]] for i in range(7)}
            with store.connect() as con:con.execute('UPDATE crm_leads SET business_hours=? WHERE id=?',(json.dumps({'weekly':weekly}),row['id']))
            calling.save_notes(row['id'],'Try owner tomorrow',0)
            calling.outcome('schedule:daytime',row['id'],row['revision'],'Follow up','Try owner tomorrow')
            for name in ('daytime','evening','saturday','sunday'):
                self.assertEqual(calling.items('schedule:'+name),[])
            item=calling.called()[0]
            self.assertEqual(item['last_call_outcome'],'Follow up')
            self.assertTrue(item['last_called_at'])
            self.assertEqual(item['call_notes'],'Try owner tomorrow')
            self.assertEqual(calling.call_counts()['total'],1)
            with self.assertRaises(store.Conflict):calling.outcome('schedule:evening',row['id'],row['revision'],'No answer')
            self.assertEqual(calling.call_counts()['total'],1)
            self.assertEqual(len(store.list_leads()),1)
            lists=calling.lists()
            self.assertEqual([l['kind'] for l in lists[:5]],list(schedule.NAMES))
            self.assertEqual(len(lists),6)
            self.assertEqual(calling.items(result['list_id'])[0]['last_call_outcome'],'Follow up')

    def test_booking_from_a_schedule_uses_imported_list(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BMT_DATA_DIR':tmp}):
            result=calling.import_list('Original',[dict(company='Builder',phone='2065550100',location='Seattle, WA',email='',contact='',need='',website='',call_zone='Pacific (US)')],True)
            row=calling.items(result['list_id'])[0]
            host={'id':'michael','name':'Michael','email':'host@example.com','calendar_id':'host@example.com','zoom_user':'host@example.com'}
            data=dict(host_id='michael',contact='Pat',email='pat@example.com',date='2030-01-02',time='10:00',zone='Pacific (US)',revision=row['revision'],list_id='schedule:daytime')
            with patch.object(booking,'connection_status',return_value={'ready':True}),patch.object(booking,'hosts',return_value=[host]),patch.object(booking,'resume',side_effect=lambda n:n):
                job=booking.create(row['id'],data)
            with store.connect() as con:
                payload=json.loads(con.execute('SELECT payload FROM crm_booking_jobs WHERE id=?',(job,)).fetchone()[0])
            self.assertEqual(payload['list_id'],result['list_id'])
            self.assertEqual(calling.items(result['list_id'])[0]['last_call_outcome'],'Book meeting')

    def test_called_tab_deduplicates_company_and_keeps_source_sheets_and_notes(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BMT_DATA_DIR':tmp}):
            seed=dict(company='Builder',phone='2065550100',location='Seattle, WA',email='',contact='',need='',website='',call_zone='Pacific (US)')
            first=calling.import_list('Original',[seed],True)
            second=calling.import_list('Another sheet',[seed],True)
            row=calling.items(first['list_id'])[0]
            with store.connect() as con:
                con.execute('UPDATE crm_leads SET business_hours=? WHERE id=?',(json.dumps({'weekly':{str(i):[[0,1440]] for i in range(7)}}),row['id']))
            calling.save_notes(row['id'],'Owner asked for an email',0)
            calling.outcome('schedule:daytime',row['id'],row['revision'],'No answer','Owner asked for an email')
            for name in schedule.NAMES:
                self.assertFalse(any(r['id']==row['id'] for r in calling.items('schedule:'+name)))
            response=crm_web.app.test_client().get('/api/calling/called')
            self.assertEqual(response.status_code,200)
            called=response.json['leads']
            self.assertEqual(len(called),1)
            self.assertEqual(called[0]['call_notes'],'Owner asked for an email')
            self.assertEqual(called[0]['last_call_outcome'],'No answer')
            for source in (first,second):
                self.assertEqual(len(calling.items(source['list_id'])),1)
            self.assertEqual(calling.call_counts()['total'],1)

    def test_called_tab_recovers_legacy_items_without_a_call_event(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BMT_DATA_DIR':tmp}):
            result=calling.import_list('Legacy',[dict(company='Legacy builder',phone='2065550100',location='',email='',contact='',need='',website='',call_zone='Pacific (US)')],True)
            with store.connect() as con:
                con.execute("UPDATE crm_call_items SET outcome='Not interested',called_at='2026-11-27T20:00:00+00:00' WHERE list_id=?",(result['list_id'],))
            row=calling.called()[0]
            self.assertEqual(row['last_call_outcome'],'Not interested')
            self.assertEqual(row['last_called_at'],'2026-11-27T20:00:00+00:00')

if __name__=='__main__':unittest.main()
