import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import crm_web
import crm_store as store
import crm_outreach_system as machine
import crm_stats as stats

class OutreachSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BMT_DATA_DIR':self.tmp.name});self.env.start()
        self.config=patch.dict(crm_web.app.config,{'OUTREACH_WORKER_HASH':hashlib.sha256(b'test-key').hexdigest()});self.config.start()
        self.client=crm_web.app.test_client();self.client.get('/')
        with self.client.session_transaction() as s:self.csrf={'X-CSRF-Token':s['csrf']}
        self.headers={**self.csrf,'X-BMT-Outreach-Key':'test-key'}
    def tearDown(self):self.config.stop();self.env.stop();self.tmp.cleanup()
    def post(self,p,ok=True):
        r=self.client.post('/api/outreach-system',json=p,headers=self.headers)
        if ok:self.assertEqual(r.status_code,200,r.json)
        return r
    def claim(self):
        self.post({'op':'settings','enabled':True})
        run=self.post({'op':'claim'}).json['run']
        for channel in machine.CHANNELS:self.post({'op':'channel-ready','channel':channel,'run_id':run,'proof':'Isolated test: verified correct signed-in account and complete readable thread history.'})
        return run
    def candidate(self,run,name='Demo Concrete',site='https://democoncrete.example',phone='5555550100'):
        observation='I saw your driveway advertisement.';approach='I would test a driveway-specific quote campaign.';cta='Open to a 15-minute Zoom call?'
        return {'op':'candidate','run_id':run,'country':'USA','qualification':{
            **{k:'Verified public business evidence for '+k for k in machine.QUALIFICATION},
            'checks':{k:'pass' for k in machine.QUALIFICATION},'country':'USA','us_city':'Phoenix','us_state':'AZ',
            'usa_base_url':site+'/contact','usa_operations_url':site+'/projects',
            'usa_base_quote':'Our concrete business is based in Phoenix, AZ.',
            'usa_operations_quote':'We install concrete driveways throughout Phoenix and nearby Arizona cities.',
            'usa_base_source_kind':'official_website','usa_operations_source_kind':'official_website',
            'review_result':'pass','review_reason':'The exact official website identifies the company location and current services.'},
            'ranking':{k:{'points':2,'evidence':'Observed public company project and advertising evidence.'} for k in ('intent','commercial_fit','specific_gap','readiness')},
            'message_review':{'observation':observation,'approach':approach,'cta':cta,'grounded':True,'reason':'The message refers to the observed driveway ad and a testable advertising improvement.'},'variant':'specific-ad-test',
            'company':name,'location':'Phoenix, AZ','trade':'Concrete','channel':'Facebook','profile_url':'https://www.facebook.com/'+name.lower().replace(' ',''),'website':site,'phone':phone,'email':'','ad_url':'https://www.facebook.com/ads/library/?id=123','issue':'Generic ad links to general services.','improvement':'Test a driveway-specific quote path.','scale_evidence':'Installation crew and project portfolio on website.','evidence':'Observed active driveway ad today.','checked_at':store.now(),'source_published_at':store.now(),'message':'Hey, Michael from BMT. '+observation+' '+approach+' '+cta}

    def test_owner_session_secret_survives_server_restart(self):
        with patch.dict(os.environ,{'RENDER':'true'}), patch('os.path.ismount',return_value=True):
            with patch.dict(os.environ,{},clear=False):
                original=os.environ.pop('CRM_SESSION_SECRET',None)
                try:
                    first=crm_web.session_secret();second=crm_web.session_secret()
                    self.assertEqual(first,second);self.assertGreaterEqual(len(first),32)
                finally:
                    if original is not None:os.environ['CRM_SESSION_SECRET']=original

    def test_operator_controls_and_single_use_connection(self):
        self.assertEqual(self.client.post('/api/outreach-system',json={'op':'settings','enabled':True},headers=self.csrf).status_code,403)
        self.assertEqual(self.client.post('/api/outreach-system',json={'op':'claim'},headers={'X-BMT-Outreach-Key':'test-key'}).status_code,403)
        path=self.post({'op':'control-link'}).json['path']
        self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post('/api/outreach-system',json={'op':'settings','enabled':True},headers=self.csrf).status_code,200)
    def test_history_duplicate_gate_and_two_attempts_per_window(self):
        run=self.claim();self.assertIsNone(self.post({'op':'claim'}).json['run'])
        n=store.add_lead('Already called',phone='5555550199',stage='Cold')
        with store.connect() as con:
            machine.schema(con);con.execute("INSERT INTO crm_call_events(event_key,lead_id,outcome,created_at) VALUES('old',?,'No answer',?)",(n,store.now()))
        self.assertEqual(self.post(self.candidate(run,phone='5555550199'),False).status_code,400)
        ident=self.post(self.candidate(run)).json['id']
        self.assertEqual(self.post(self.candidate(run),False).status_code,400)
        self.post({'op':'begin-send','run_id':run,'id':ident})
        other=self.post(self.candidate(run,'Other Fence','https://otherfence.example','5555550101')).json['id']
        self.post({'op':'send-result','id':ident,'state':'sent','proof':'Verified test send'})
        self.post({'op':'begin-send','run_id':run,'id':other})
        third=self.post(self.candidate(run,'Third Fence','https://thirdfence.example','5555550102')).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':third},False).status_code,400)
        self.post({'op':'finish','run_id':run,'summary':'Stopped before confirmation.'})
        data=self.client.get('/api/outreach-system').json
        self.assertFalse(data['config']['enabled'])
        self.assertEqual(next(p for p in data['prospects'] if p['id']==other)['state'],'unconfirmed')
    def test_confirmed_send_reply_promotion_and_stats_are_idempotent(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'begin-send','run_id':run,'id':ident})
        result=self.post({'op':'send-result','id':ident,'state':'sent','proof':'Recipient thread shows the exact sent message.'}).json
        lead=next(x for x in store.list_leads() if x['id']==result['lead_id'])
        self.assertEqual(lead['stage'],'Outreach')
        reply={'op':'reply','id':ident,'text':'Thanks, office hours 8 to 5.','classification':'Auto-reply','source_url':'https://www.facebook.com/messages/t/123','suggested_reply':''}
        self.post(reply);self.assertEqual(store.list_leads()[0]['stage'],'Outreach')
        reply.update(text='Yes, I would like to talk about the ads.',classification='Interested')
        self.post(reply);self.post(reply)
        self.assertEqual(store.list_leads()[0]['stage'],'Prospect')
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['totals']['confirmed_sent'],1);self.assertEqual(data['totals']['replies'],1)
        report=stats.report(machine.day(),machine.day())
        self.assertEqual(report['totals']['calls'],0)
        self.assertEqual(report['automatic_outreach'][0]['sent'],1)
        self.assertEqual(report['automatic_outreach'][0]['replies'],1)
        self.assertEqual(report['outreach'],[])
    def test_public_intent_preserves_comment_and_does_not_require_own_ad(self):
        run=self.claim();p=self.candidate(run)
        p.update(source_type='public_intent',ad_url='https://www.facebook.com/ads/library/?id=agency123',intent_quote='Can you help my fencing company get more jobs?',intent_author='Demo Fence Co',intent_url='https://www.facebook.com/agency/posts/123?comment_id=456',issue='Contractor publicly asked for help finding fence jobs.',website='http://democoncrete.example')
        ident=self.post(p).json['id']
        entry=next(x for x in self.client.get('/api/outreach-system').json['prospects'] if x['id']==ident)
        self.assertEqual(entry['source_type'],'public_intent')
        self.assertEqual(entry['intent_quote'],p['intent_quote'])
        self.assertEqual(entry['intent_url'],p['intent_url'])
        self.assertEqual(entry['ad_url'],p['ad_url'])
        self.assertEqual(entry['website'],'http://democoncrete.example')
        self.post({'op':'begin-send','run_id':run,'id':ident})
        self.post({'op':'send-result','id':ident,'state':'sent','proof':'Isolated test confirmation'})
        self.assertIn(p['intent_quote'],store.notes_for(store.list_leads()[0]['id'])[0]['text'])

    def test_public_intent_rejects_missing_comment_proof(self):
        run=self.claim();p=self.candidate(run);p['source_type']='public_intent'
        self.assertEqual(self.post(p,False).status_code,400)
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'],[])

    def test_pause_and_expired_lease_block_sends(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'settings','enabled':False})
        self.assertEqual(self.post({'op':'begin-send','id':ident,'run_id':run},False).status_code,400)
        with store.connect() as con:con.execute('UPDATE crm_ai_runs SET started_at=? WHERE id=?',((machine.instant()-timedelta(minutes=21)).isoformat(),run))
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['runs'][0]['state'],'interrupted');self.assertFalse(data['config']['enabled'])

    def test_publication_age_required_and_rechecked_before_send(self):
        run=self.claim();p=self.candidate(run)
        p.pop('source_published_at')
        self.assertEqual(self.post(p,False).status_code,400)
        p['source_published_at']=(machine.instant()-timedelta(days=31)).isoformat()
        self.assertEqual(self.post(p,False).status_code,400)
        p['source_published_at']=store.now();ident=self.post(p).json['id']
        with store.connect() as con:con.execute('UPDATE crm_ai_prospects SET source_published_at=? WHERE id=?',((machine.instant()-timedelta(days=31)).isoformat(),ident))
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':ident},False).status_code,400)

    def test_rolling_window_applies_across_runs(self):
        run=self.claim()
        for i in range(2):
            ident=self.post(self.candidate(run,'Company '+str(i),'https://company'+str(i)+'.example','555555011'+str(i))).json['id']
            self.post({'op':'begin-send','run_id':run,'id':ident})
            self.post({'op':'send-result','id':ident,'state':'sent','proof':'Confirmed in test'})
        self.post({'op':'finish','run_id':run,'summary':'Two test sends.'})
        with store.connect() as con:con.execute('UPDATE crm_ai_config SET next_run=NULL')
        second=self.post({'op':'claim'}).json['run']
        ident=self.post(self.candidate(second,'Another','https://another.example','5555550120')).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':second,'id':ident},False).status_code,400)

    def test_usa_and_every_qualification_box_are_required(self):
        run=self.claim();p=self.candidate(run)
        p['country']='Canada';self.assertEqual(self.post(p,False).status_code,400)
        p['country']='USA'
        for key in machine.QUALIFICATION:
            incomplete={**p,'qualification':dict(p['qualification'])}
            incomplete['qualification'].pop(key)
            self.assertEqual(self.post(incomplete,False).status_code,400)
        p['qualification']['usa_base_url']=''
        self.assertEqual(self.post(p,False).status_code,400)
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'],[])

    def sent_company(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'begin-send','run_id':run,'id':ident})
        self.post({'op':'send-result','id':ident,'state':'sent','proof':'Verified introductory message in recipient thread.'})
        return run,ident

    def inbound(self,ident,text='Can you help us get more driveway jobs?',key='visible-message-1',classification='Question'):
        return self.post({'op':'reply','id':ident,'text':text,'external_key':key,'classification':classification,'source_url':'https://www.facebook.com/messages/t/123','suggested_reply':''}).json['message_id']

    def test_us_evidence_rejects_yes_unrelated_domains_unknown_and_missing_review(self):
        import copy
        run=self.claim();base=self.candidate(run)
        for alteration in ('bare_yes','foreign_source','unknown','no_critique','wrong_city'):
            p=copy.deepcopy(base)
            if alteration=='bare_yes':p['qualification']['usa_base']='yes'
            if alteration=='foreign_source':p['qualification']['usa_base_url']='https://unrelated.example/contact'
            if alteration=='unknown':p['qualification']['checks']['usa_operations']='unknown'
            if alteration=='no_critique':p['qualification']['review_result']=''
            if alteration=='wrong_city':p['qualification']['us_city']='Toronto'
            self.assertEqual(self.post(p,False).status_code,400,alteration)

    def test_message_quality_and_ranking_are_required_and_preserved(self):
        run=self.claim();p=self.candidate(run);p['message_review']['grounded']=False
        self.assertEqual(self.post(p,False).status_code,400)
        p=self.candidate(run);p['ranking']['intent']['points']=10
        self.assertEqual(self.post(p,False).status_code,400)
        p=self.candidate(run);ident=self.post(p).json['id']
        entry=self.client.get('/api/outreach-system').json['prospects'][0]
        self.assertEqual(entry['id'],ident);self.assertGreater(entry['priority_score'],0)
        self.assertEqual(entry['variant'],'specific-ad-test')

    def test_reply_requires_new_inbound_live_check_and_deduplicates_attempts(self):
        run,ident=self.sent_company()
        action={'op':'begin-reply','id':ident,'run_id':run,'reply_to':'missing','text':'We could test driveway project ads. Which area do you serve?','grounding':'They asked for more driveway jobs; ask their current service area.'}
        self.assertEqual(self.post(action,False).status_code,400)
        incoming=self.inbound(ident);self.assertEqual(self.inbound(ident),incoming)
        action['reply_to']=incoming
        self.assertEqual(self.post(action,False).status_code,400)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Verified exact company thread and latest inbound driveway question.'})
        outbound=self.post(action).json['id']
        self.assertEqual(self.post(action,False).status_code,400)
        self.post({'op':'reply-result','message_id':outbound,'state':'sent','proof':'Exact response visible as sent in verified recipient thread.'})
        self.assertEqual(self.post(action,False).status_code,400)
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['intelligence']['needs_reply'],[])
        self.assertEqual(data['totals']['confirmed_sent'],1)
        self.assertEqual(len(data['intelligence']['messages']),2)

    def test_multiple_inbound_messages_get_one_coherent_reply(self):
        run,ident=self.sent_company();first=self.inbound(ident);last=self.inbound(ident,'We are in Phoenix. What does it cost?','visible-message-2')
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Read both new inbound messages in the verified company thread.'})
        p={'op':'begin-reply','id':ident,'run_id':run,'reply_to':first,'text':'Management is $3,000 USD/month, plus $1,500 ad spend. Open to a 15-minute call?','grounding':'Answering their actual pricing question and inviting a short discovery call.'}
        self.assertEqual(self.post(p,False).status_code,400)
        p['reply_to']=last;outbound=self.post(p).json['id']
        self.post({'op':'reply-result','message_id':outbound,'state':'sent','proof':'Verified the combined pricing response in company thread.'})
        self.assertEqual(self.client.get('/api/outreach-system').json['intelligence']['needs_reply'],[])

    def test_unconfirmed_reply_pauses_and_cannot_be_retried(self):
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Read the latest company inbound in its verified thread.'})
        p={'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'Which service area would you like more driveway jobs in?','grounding':'They asked about getting more driveway jobs in their market.'}
        outbound=self.post(p).json['id']
        self.post({'op':'reply-result','message_id':outbound,'state':'unconfirmed','proof':'Send result ambiguous; no delivery evidence visible.'})
        self.assertFalse(self.client.get('/api/outreach-system').json['config']['enabled'])
        self.assertEqual(self.post(p,False).status_code,400)

    def test_finish_without_reply_result_is_durable_pause(self):
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Read company thread and new inbound message before replying.'})
        self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'Which service area do you want more jobs in?','grounding':'Their question is about generating more jobs from advertising.'})
        self.post({'op':'finish','run_id':run,'summary':'Interrupted reply sequence.'})
        data=self.client.get('/api/outreach-system').json
        self.assertFalse(data['config']['enabled'])
        self.assertEqual(data['intelligence']['messages'][-1]['state'],'unconfirmed')

    def test_opt_out_and_auto_reply_do_not_trigger_a_reply(self):
        run,ident=self.sent_company()
        self.inbound(ident,'Thanks, we are closed today.','auto-1','Auto-reply')
        self.assertEqual(self.client.get('/api/outreach-system').json['intelligence']['needs_reply'],[])
        incoming=self.inbound(ident,'Not interested, stop messaging us.','stop-1','Not interested')
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Read explicit company opt-out and verified recipient thread.'})
        self.assertEqual(self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'Can we still talk?','grounding':'This response must be rejected because the company opted out.'},False).status_code,400)
        self.assertEqual(self.client.get('/api/outreach-system').json['intelligence']['conversations'],[])

    def test_all_open_conversations_visible_not_limited_to_latest_five(self):
        with store.connect() as con:
            machine.schema(con)
            for n in range(8):
                p=self.candidate('fixture',name='Fixture '+str(n),site='https://fixture'+str(n)+'.example',phone='55555503'+str(n).zfill(2))
                ident=machine.candidate(con,p)['id']
                con.execute("UPDATE crm_ai_prospects SET sent_at=?,state='sent' WHERE id=?",(store.now(),ident))
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(len(data['intelligence']['conversations']),8)

    def test_research_memory_sources_and_metrics_do_not_invent_bookings(self):
        run,ident=self.sent_company()
        self.post({'op':'source','run_id':run,'url':'https://www.facebook.com/agency/posts/123','label':'Contractor marketing post','channel':'Facebook','notes':'Two observed contractors asked about advertising help in recent comments.'})
        p={'op':'research','run_id':run,'identity':'small.example','company':'Too Small','source_url':'https://small.example','source_type':'public_intent','trade':'Concrete','channel':'Facebook','decision':'rejected','reason':'No current U.S. location or operating contractor evidence could be verified.'}
        self.post(p);self.post(p)
        data=self.client.get('/api/outreach-system').json['intelligence']
        self.assertEqual(len(data['sources']),1);self.assertEqual(data['funnel']['screened'],2)
        self.assertEqual(data['funnel']['rejected'],1)
        self.assertEqual(data['funnel']['segments'][0]['booked'],0)
        self.assertEqual(self.post({'op':'outcome','run_id':run,'id':ident,'outcome':'Booked','occurred_at':store.now(),'proof':'They said they might want to talk sometime tomorrow.'},False).status_code,400)

    def test_conversation_rank_history_and_identical_text_at_distinct_times(self):
        run,ident=self.sent_company();self.inbound(ident,'Yes','one','Interested');self.inbound(ident,'Yes','two','Interested')
        factors={k:{'points':2,'evidence':'Contractor described relevant advertising needs in the current dialogue.'} for k in ('need','engagement','commercial_fit','meeting_readiness')}
        p={'op':'assess','run_id':run,'id':ident,'stage':'Engaged','summary':'They want more driveway jobs but have not agreed to a meeting.','factors':factors,'markers':['more_work'],'insights':{'needs':'More driveway jobs','objections':'','value_offered':'Driveway campaign test','next_step':'Ask service area','unknowns':'Timing and capacity'}}
        self.post(p);self.post(p)
        data=self.client.get('/api/outreach-system').json['intelligence']
        self.assertEqual(len(data['messages']),2);self.assertEqual(len(data['assessments']),1)
        self.assertGreater(data['conversations'][0]['conversation_score'],0)
        p['stage']='Booked';self.assertEqual(self.post(p,False).status_code,400)

    def test_adopt_existing_prospect_without_new_intro_or_call_statistics(self):
        run=self.claim();lead=store.add_lead('Demo Concrete',phone='5555550100',stage='Prospect')
        p=self.candidate(run);p.update(op='adopt',original_sent_at=store.now(),history_proof='Original advertising introduction is visible in the verified company conversation.')
        ident=self.post(p).json['id']
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['prospects'][0]['lead_id'],lead)
        self.assertEqual(data['prospects'][0]['id'],ident)
        self.assertEqual(len(data['intelligence']['conversations']),1)
        with store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM crm_outreach_events').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM crm_call_events').fetchone()[0],0)

    def block_facebook(self,run,kind='history_missing',blocks_history=True):
        return self.post({'op':'channel-block','run_id':run,'channel':'Facebook','kind':kind,'reason':'Facebook displays Chat history is missing.','action':'Restore Messenger history with the code prompt, then select Check next run.','proof':'Observed missing-history prompt in the signed-in Messenger inbox.','blocks_history':blocks_history})

    def test_channel_block_preserves_scheduler_and_existing_other_channel_replies(self):
        run=self.claim();p=self.candidate(run);p.update(channel='Instagram',profile_url='https://www.instagram.com/democoncrete')
        ident=self.post(p).json['id'];self.post({'op':'begin-send','run_id':run,'id':ident})
        self.post({'op':'send-result','id':ident,'state':'sent','proof':'Verified Instagram intro in correct company thread.'})
        self.block_facebook(run)
        incoming=self.inbound(ident)
        self.post({'op':'thread-check','run_id':run,'id':ident,'proof':'Verified correct Instagram company thread and its new inbound question.'})
        reply=self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'Which area do you want more driveway jobs in?','grounding':'They asked about more driveway jobs in an existing verified Instagram thread.'}).json['id']
        self.post({'op':'reply-result','message_id':reply,'state':'sent','proof':'Response visibly sent in the correct Instagram recipient thread.'})
        d=self.client.get('/api/outreach-system').json
        self.assertTrue(d['config']['enabled']);self.assertTrue(d['health']['cold_outreach_held'])
        self.assertEqual(d['health']['alerts'][0]['scope'],'Facebook')

    def test_missing_cross_channel_history_blocks_new_intros_without_pausing_all(self):
        run=self.claim();self.block_facebook(run)
        p=self.candidate(run);p.update(channel='Instagram',profile_url='https://www.instagram.com/democoncrete')
        ident=self.post(p).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':ident},False).status_code,400)
        self.assertTrue(self.client.get('/api/outreach-system').json['config']['enabled'])

    def test_retry_keeps_alert_and_block_until_actual_live_verification(self):
        run=self.claim();self.block_facebook(run)
        self.post({'op':'retry-channel','channel':'Facebook'})
        d=self.client.get('/api/outreach-system').json
        fb=next(c for c in d['health']['channels'] if c['channel']=='Facebook')
        self.assertEqual(fb['state'],'needs_check');self.assertTrue(fb['blocks_history'])
        self.assertTrue(any(a['scope']=='Facebook' for a in d['health']['alerts']))
        self.assertEqual(self.post({'op':'channel-ready','channel':'Facebook','proof':'Browser looks ready.'},False).status_code,400)
        self.post({'op':'channel-ready','channel':'Facebook','run_id':run,'proof':'Verified signed-in Michael profile, restored readable history and correct company thread.'})
        d=self.client.get('/api/outreach-system').json
        self.assertFalse(d['health']['cold_outreach_held'])
        self.assertFalse(any(a['scope']=='Facebook' for a in d['health']['alerts']))

    def test_blocked_target_cannot_send_even_when_history_is_readable(self):
        run=self.claim();self.block_facebook(run,'rate_limit',False)
        ident=self.post(self.candidate(run)).json['id']
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':ident},False).status_code,400)
        d=self.client.get('/api/outreach-system').json
        self.assertFalse(d['health']['cold_outreach_held']);self.assertTrue(d['config']['enabled'])

    def test_global_reason_survives_heartbeat_and_offline_is_not_reported_as_working(self):
        run=self.claim()
        self.post({'op':'attention','reason':'Browser tool unavailable; all channels cannot be checked.','action':'Restart the active Mac session and verify the browser tool.'})
        self.post({'op':'heartbeat','state':'Mac worker connected'})
        d=self.client.get('/api/outreach-system').json
        self.assertFalse(d['config']['enabled']);self.assertIn('Browser tool unavailable',d['config']['worker_state'])
        self.assertTrue(any(a['kind']=='global_stop' for a in d['health']['alerts']))
        self.assertTrue(d['health']['heartbeat_fresh'])
        with store.connect() as con:con.execute('UPDATE crm_ai_config SET heartbeat=?',((machine.instant()-timedelta(minutes=5)).isoformat(),))
        d=self.client.get('/api/outreach-system').json
        self.assertTrue(any(a['kind']=='offline' for a in d['health']['alerts']))

    def test_uncertain_delivery_cannot_be_overridden_by_start_button(self):
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Read current company thread and latest inbound before sending.'})
        result=self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'Which service area do you want more driveway jobs in?','grounding':'The company asked for help getting more driveway jobs in their area.'}).json
        self.post({'op':'reply-result','message_id':result['id'],'state':'unconfirmed','proof':'Delivery status unclear; needs actual thread inspection.'})
        self.assertEqual(self.post({'op':'settings','enabled':True},False).status_code,400)
