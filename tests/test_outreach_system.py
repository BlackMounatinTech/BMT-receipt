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
    def owner_session(self):
        with self.client.session_transaction() as session:session['outreach_operator']=True

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
        self.owner_session()
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

    def test_new_channel_error_cannot_erase_an_unresolved_history_block(self):
        run=self.claim();self.block_facebook(run)
        self.block_facebook(run,'rate_limit',False)
        data=self.client.get('/api/outreach-system').json
        self.assertTrue(data['health']['cold_outreach_held'])

    def test_unknown_or_stale_enabled_channel_prevents_new_contact(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        for state in ('unknown','needs_check'):
            with store.connect() as con:con.execute('UPDATE crm_ai_channel_health SET state=?,blocks_history=0 WHERE channel=?',(state,'Instagram'))
            self.assertEqual(self.post({'op':'begin-send','id':ident,'run_id':run},False).status_code,400)
            self.assertTrue(self.client.get('/api/outreach-system').json['health']['cold_outreach_held'])
        with store.connect() as con:con.execute("UPDATE crm_ai_channel_health SET state='ready',checked_at=? WHERE channel='Instagram'",((machine.instant()-timedelta(hours=25)).isoformat(),))
        self.assertEqual(self.post({'op':'begin-send','id':ident,'run_id':run},False).status_code,400)
        self.post({'op':'channel-ready','run_id':run,'channel':'Instagram','proof':'Rechecked signed-in account and complete readable relevant conversation history.'})
        self.post({'op':'begin-send','id':ident,'run_id':run})

    def test_readable_rate_limited_other_channel_does_not_block_safe_intro(self):
        run=self.claim();self.block_facebook(run,'rate_limit',False)
        p=self.candidate(run);p.update(channel='Instagram',profile_url='https://www.instagram.com/democoncrete')
        ident=self.post(p).json['id']
        self.post({'op':'begin-send','id':ident,'run_id':run})

    def test_duplicate_inbound_preserves_handoff_booking_and_closed_stage(self):
        run,ident=self.sent_company();self.inbound(ident)
        for stage in ('Human needed','Booked','Closed'):
            with store.connect() as con:con.execute('UPDATE crm_ai_prospects SET conversation_stage=?,conversation_summary=? WHERE id=?',(stage,'Preserve the current human decision.',ident))
            before=len(self.client.get('/api/outreach-system').json['intelligence']['messages'])
            self.inbound(ident)
            d=self.client.get('/api/outreach-system').json
            self.assertEqual(d['prospects'][0]['conversation_stage'],stage)
            self.assertEqual(len(d['intelligence']['messages']),before)
            self.inbound(ident,'Another question about service areas.',key='new-'+stage)
            d=self.client.get('/api/outreach-system').json
            self.assertEqual(d['prospects'][0]['conversation_stage'],stage)

    def test_adopt_historical_message_without_new_pitch_requirements(self):
        run=self.claim();p=self.candidate(run)
        original='We create advertising for concrete companies. Open to a 10-minute call?'
        p.update(op='adopt',message=original,original_sent_at=(machine.instant()-timedelta(days=60)).isoformat(),history_proof='Observed the original contractor advertising message and sent date in this verified company thread.')
        for field in ('ranking','message_review','variant','source_published_at','ad_url'):p.pop(field)
        ident=self.post(p).json['id']
        entry=self.client.get('/api/outreach-system').json['prospects'][0]
        self.assertEqual(entry['id'],ident);self.assertEqual(entry['message'],original)
        self.assertEqual(entry['variant'],'historical-import')
        self.assertEqual(entry['source_type'],'existing_conversation')
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':ident},False).status_code,400)
        with store.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM crm_outreach_events').fetchone()[0],0)

    def test_full_state_names_are_normalized_without_rewriting_quote(self):
        run=self.claim();p=self.candidate(run)
        quote='Our operating concrete company is based in Phoenix, Arizona.'
        p['qualification'].update(us_state='Arizona',usa_base_quote=quote)
        p['location']='Phoenix, Arizona'
        self.post(p)
        entry=self.client.get('/api/outreach-system').json['prospects'][0]
        q=json.loads(entry['qualification'])
        self.assertEqual(q['us_state'],'AZ');self.assertEqual(q['usa_base_quote'],quote)
        for state in ('Ontario','British Columbia','Canada'):
            p=self.candidate(run,name='Foreign '+state,site='https://foreign.example')
            p['qualification']['us_state']=state
            self.assertEqual(self.post(p,False).status_code,400)

    def test_refresh_reuses_ready_record_but_never_changes_contact_identity(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        with store.connect() as con:con.execute('UPDATE crm_ai_prospects SET checked_at=? WHERE id=?',((machine.instant()-timedelta(hours=25)).isoformat(),ident))
        self.assertEqual(self.post({'op':'begin-send','id':ident,'run_id':run},False).status_code,400)
        p={'op':'refresh-candidate','run_id':run,'id':ident,'checked_at':store.now(),'evidence':'Reopened the same current source and verified all saved company facts remain accurate.'}
        self.assertEqual(self.post({**p,'phone':'5555559999'},False).status_code,400)
        self.post(p)
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(len(d['prospects']),1);self.assertEqual(d['prospects'][0]['id'],ident)
        self.post({'op':'begin-send','id':ident,'run_id':run})
        self.assertEqual(self.post(p,False).status_code,400)

    def test_existing_conversation_source_cannot_bypass_new_intro_rules(self):
        run=self.claim();p=self.candidate(run);p['source_type']='existing_conversation'
        self.assertEqual(self.post(p,False).status_code,400)

    def assessment_payload(self,run,ident,stage='Engaged'):
        return {'op':'assess','run_id':run,'id':ident,'stage':stage,'summary':'The company described its advertising question and needs an accurate next step.','factors':{k:{'points':2,'evidence':'Observed company dialogue supports this specific conversation assessment.'} for k in ('need','engagement','commercial_fit','meeting_readiness')},'markers':['needs_details'],'insights':{'next_step':'Answer the actual question after checking the live thread.'}}

    def test_known_outbound_reply_cannot_be_logged_as_inbound_echo(self):
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Verified company thread and latest inbound before responding.'})
        text='A driveway campaign could help. Which service area should it target?'
        out=self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':text,'grounding':'Answering their actual request about attracting more driveway jobs.'}).json['id']
        self.post({'op':'reply-result','message_id':out,'state':'sent','proof':'Verified sent response in the correct company thread.'})
        for echo in (text,'  '+text.upper().replace(' ','\n')+'  '):
            r=self.post({'op':'reply','id':ident,'text':echo,'external_key':'echo','classification':'Not interested','source_url':'https://www.facebook.com/messages/t/123','suggested_reply':''},False)
            self.assertEqual(r.status_code,400)
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['intelligence']['needs_reply'],[])
        self.assertEqual(len(data['intelligence']['messages']),2)
        self.assertNotEqual(data['prospects'][0]['state'],'stopped')

    def test_second_intro_waits_for_first_delivery_result(self):
        run=self.claim();a=self.post(self.candidate(run)).json['id']
        b=self.post(self.candidate(run,'Other Fence','https://other.example','5555550191')).json['id']
        self.post({'op':'begin-send','id':a,'run_id':run})
        self.assertEqual(self.post({'op':'begin-send','id':b,'run_id':run},False).status_code,400)
        self.post({'op':'send-result','id':a,'state':'sent','proof':'Confirmed first intro in the verified company thread.'})
        self.post({'op':'begin-send','id':b,'run_id':run})

    def test_reply_waits_for_pending_intro_delivery_result(self):
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Read exact company thread and current new inbound question.'})
        a=self.post(self.candidate(run,'Other Fence','https://other.example','5555550191')).json['id']
        self.post({'op':'begin-send','id':a,'run_id':run})
        reply={'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'Which area do you want more driveway jobs in?','grounding':'They asked about more driveway jobs in their existing verified conversation.'}
        self.assertEqual(self.post(reply,False).status_code,400)
        self.post({'op':'send-result','id':a,'state':'sent','proof':'Verified second intro sent before moving to a conversation reply.'})
        self.post(reply)

    def test_reassessment_cannot_release_protected_stage(self):
        run,ident=self.sent_company();self.inbound(ident)
        for stage in ('Human needed','Booked','Closed'):
            with store.connect() as con:con.execute('UPDATE crm_ai_prospects SET conversation_stage=? WHERE id=?',(stage,ident))
            self.assertEqual(self.post(self.assessment_payload(run,ident),False).status_code,400)
            self.inbound(ident,'Another actual inbound question about advertising.',key='after-'+stage)
            self.assertEqual(self.post(self.assessment_payload(run,ident),False).status_code,400)
            self.assertEqual(self.client.get('/api/outreach-system').json['prospects'][0]['conversation_stage'],stage)

    def test_handoff_release_requires_real_owner_session_not_worker_claim(self):
        run,ident=self.sent_company();self.post(self.assessment_payload(run,ident,'Human needed'))
        p={'op':'release-handoff','id':ident,'proof':'Michael has reviewed the complaint and resolved the outstanding question.'}
        self.assertEqual(self.post({**p,'owner':True},False).status_code,400)
        self.owner_session()
        path=self.post({'op':'control-link'}).json['path'];self.client.get(path)
        self.post(p)
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(d['prospects'][0]['conversation_stage'],'Engaged')
        self.assertTrue(any(o['kind']=='handoff_resolved' for o in d['intelligence']['observations']))

    def test_booking_outcome_does_not_release_unresolved_handoff(self):
        run,ident=self.sent_company();self.post(self.assessment_payload(run,ident,'Human needed'))
        lead=self.client.get('/api/outreach-system').json['prospects'][0]['lead_id']
        with store.connect() as con:con.execute('INSERT INTO crm_stats_bookings VALUES(?,?)',(lead,store.now()))
        self.post({'op':'outcome','id':ident,'run_id':run,'outcome':'Booked','occurred_at':store.now(),'proof':'Actual isolated CRM booking exists, but the complaint is still unresolved.'})
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'][0]['conversation_stage'],'Human needed')
        self.owner_session()
        path=self.post({'op':'control-link'}).json['path'];self.client.get(path)
        self.post({'op':'release-handoff','id':ident,'proof':'Michael resolved the question while preserving the existing calendar booking.'})
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'][0]['conversation_stage'],'Booked')

    def test_imported_history_not_counted_as_new_automatic_intro(self):
        run=self.claim();p=self.candidate(run);p.update(op='adopt',original_sent_at=store.now(),history_proof='The original manual advertising pitch is visible in the verified company history.')
        self.post(p)
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(d['totals']['confirmed_sent'],0);self.assertEqual(d['totals']['sent_today'],0)
        self.assertEqual(d['totals']['imported_conversations'],1)
        self.assertFalse(d['prospects'][0]['automatic_intro'])
        self.assertEqual(d['intelligence']['funnel']['segments'][0]['sent'],0)
        self.assertEqual(d['intelligence']['funnel']['segments'][0]['imported'],1)

    def test_replayed_booking_cannot_reopen_lost_conversation(self):
        run,ident=self.sent_company();lead=self.client.get('/api/outreach-system').json['prospects'][0]['lead_id']
        with store.connect() as con:con.execute('INSERT INTO crm_stats_bookings VALUES(?,?)',(lead,store.now()))
        p={'op':'outcome','run_id':run,'id':ident,'occurred_at':store.now(),'proof':'Actual outcome verified from the isolated company booking record.'}
        self.post({**p,'outcome':'Booked'});self.post({**p,'outcome':'Lost'})
        self.assertTrue(self.post({**p,'outcome':'Booked'}).json['duplicate'])
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'][0]['conversation_stage'],'Closed')
        with store.connect() as con:con.execute("DELETE FROM crm_ai_outcomes WHERE prospect_id=? AND outcome='Booked'",(ident,))
        self.assertEqual(self.post({**p,'outcome':'Booked'},False).status_code,400)

    def test_older_outcome_is_recorded_without_overwriting_newer_state(self):
        run,ident=self.sent_company();lead=self.client.get('/api/outreach-system').json['prospects'][0]['lead_id']
        with store.connect() as con:
            con.execute('UPDATE crm_ai_prospects SET sent_at=? WHERE id=?',((machine.instant()-timedelta(days=3)).isoformat(),ident))
            con.execute('INSERT INTO crm_stats_bookings VALUES(?,?)',(lead,store.now()))
        p={'op':'outcome','run_id':run,'id':ident,'proof':'Observed historical meeting outcome with its actual recorded date.'}
        self.post({**p,'outcome':'Booked','occurred_at':store.now()})
        result=self.post({**p,'outcome':'Lost','occurred_at':(machine.instant()-timedelta(days=1)).isoformat()}).json
        self.assertTrue(result['historical'])
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'][0]['conversation_stage'],'Booked')
        self.assertEqual(self.post({**p,'outcome':'Held','occurred_at':(machine.instant()-timedelta(days=4)).isoformat()},False).status_code,400)

    def test_conflicting_platform_id_does_not_mutate_message_or_company(self):
        run,ident=self.sent_company();self.inbound(ident,'Can we discuss the driveway campaign?','stable-id','Interested')
        before=self.client.get('/api/outreach-system').json
        note_count=len(store.notes_for(before['prospects'][0]['lead_id']))
        p={'op':'reply','id':ident,'external_key':'stable-id','text':'Stop contacting me.','classification':'Not interested','source_url':'https://www.facebook.com/messages/t/123','suggested_reply':''}
        self.assertEqual(self.post(p,False).status_code,400)
        after=self.client.get('/api/outreach-system').json
        self.assertEqual(len(after['intelligence']['messages']),1)
        self.assertEqual(after['prospects'][0]['state'],before['prospects'][0]['state'])
        self.assertEqual(after['prospects'][0]['conversation_stage'],before['prospects'][0]['conversation_stage'])
        self.assertEqual(len(store.notes_for(after['prospects'][0]['lead_id'])),note_count)

    def test_duplicate_inbound_does_not_repeat_crm_note_or_revision(self):
        run,ident=self.sent_company();self.inbound(ident)
        lead=self.client.get('/api/outreach-system').json['prospects'][0]['lead_id']
        before=store.list_leads()[0];notes=len(store.notes_for(lead))
        self.inbound(ident)
        self.assertEqual(len(store.notes_for(lead)),notes)
        self.assertEqual(store.list_leads()[0]['revision'],before['revision'])

    def test_rate_limit_cannot_be_cleared_by_healthy_history_or_retry(self):
        run=self.claim();self.block_facebook(run,'rate_limit',False)
        p={'op':'channel-ready','run_id':run,'channel':'Facebook','proof':'The account is signed in and history is readable, but the send cooldown remains.'}
        self.assertEqual(self.post(p,False).status_code,400)
        self.post({'op':'retry-channel','channel':'Facebook'})
        self.assertEqual(self.post(p,False).status_code,400)
        d=self.client.get('/api/outreach-system').json
        fb=next(c for c in d['health']['channels'] if c['channel']=='Facebook')
        self.assertEqual(fb['next_check'],fb['rate_limited_until'])
        with store.connect() as con:con.execute('UPDATE crm_ai_channel_health SET rate_limited_until=? WHERE channel=?',((machine.instant()-timedelta(seconds=1)).isoformat(),'Facebook'))
        self.post(p)

    def test_worker_cannot_mint_owner_session_to_release_handoff(self):
        run,ident=self.sent_company();self.post(self.assessment_payload(run,ident,'Human needed'))
        self.assertEqual(self.post({'op':'control-link','owner':True},False).status_code,400)
        self.assertEqual(self.post({'op':'release-handoff','id':ident,'owner':True,'proof':'The worker must not be able to claim that it is the owner.'},False).status_code,400)
        self.assertEqual(self.client.get('/api/outreach-system').json['prospects'][0]['conversation_stage'],'Human needed')
        self.owner_session();path=self.post({'op':'control-link'}).json['path']
        self.assertEqual(self.client.get(path).status_code,302)

    def test_sales_outcome_does_not_hide_an_existing_opt_out(self):
        run,ident=self.sent_company();self.inbound(ident,'Stop contacting us.','optout-1','Not interested')
        self.post({'op':'outcome','run_id':run,'id':ident,'outcome':'Lost','occurred_at':store.now(),'proof':'The company declined and explicitly asked not to receive more messages.'})
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(d['prospects'][0]['state'],'stopped')
        self.assertEqual(d['prospects'][0]['conversation_stage'],'Not interested')

    def test_delivery_review_is_owner_only_and_waits_for_run_end(self):
        run=self.claim();ident=self.post(self.candidate(run)).json['id']
        self.post({'op':'begin-send','run_id':run,'id':ident})
        self.post({'op':'send-result','id':ident,'state':'unconfirmed','proof':'Composer closed but message delivery was not visible.'})
        review={'op':'review-delivery','kind':'intro','id':ident,'verdict':'sent','proof':'Exact introduction visible in the correct recipient thread after inspection.'}
        self.assertEqual(self.post(review,False).status_code,400)
        self.owner_session();self.assertEqual(self.post(review,False).status_code,400)
        self.post({'op':'finish','run_id':run,'summary':'Waiting for owner inspection of uncertain delivery.'})
        self.post(review)
        data=self.client.get('/api/outreach-system').json
        self.assertFalse(data['config']['enabled']);self.assertEqual(data['totals']['confirmed_sent'],1)
        self.assertEqual(data['delivery_reviews'],[])
        self.assertEqual(self.post(review,False).status_code,400)
        self.post({'op':'settings','enabled':True})

    def test_retired_intro_stays_in_contact_history_and_attempt_limits(self):
        run=self.claim();p=self.candidate(run);ident=self.post(p).json['id']
        self.post({'op':'begin-send','run_id':run,'id':ident})
        self.post({'op':'finish','run_id':run,'summary':'Interrupted after begin-send, before delivery confirmation.'})
        self.owner_session();self.post({'op':'review-delivery','kind':'intro','id':ident,'verdict':'not_sent','proof':'Correct conversation inspected; exact message is absent. Retired without retry.'})
        d=self.client.get('/api/outreach-system').json
        self.assertFalse(d['config']['enabled']);self.assertEqual(d['totals']['confirmed_sent'],0)
        self.assertEqual(d['prospects'][0]['state'],'stopped');self.assertTrue(d['prospects'][0]['attempted_at'])
        self.post({'op':'settings','enabled':True})
        self.assertEqual(self.post({'op':'begin-send','run_id':run,'id':ident},False).status_code,400)

    def uncertain_reply(self):
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','run_id':run,'id':ident,'proof':'Verified latest inbound in the exact recipient conversation.'})
        msg=self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'We can build a driveway campaign. Open to a quick call?','grounding':'The company asked about getting more driveway jobs; offer a relevant campaign and call.'}).json['id']
        self.post({'op':'reply-result','message_id':msg,'state':'unconfirmed','proof':'Delivery unclear after composer disappeared; no retry attempted.'})
        self.post({'op':'finish','run_id':run,'summary':'Paused for owner review of uncertain reply.'})
        return ident,incoming,msg

    def test_confirmed_reply_review_answers_inbound_without_resending(self):
        ident,incoming,msg=self.uncertain_reply();self.owner_session()
        self.post({'op':'review-delivery','kind':'reply','id':msg,'verdict':'sent','proof':'Exact reply visibly sent in the correct recipient thread after inspection.'})
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(d['delivery_reviews'],[]);self.assertFalse(d['config']['enabled'])
        self.assertEqual(d['intelligence']['needs_reply'],[])
        self.assertEqual(next(x for x in d['intelligence']['messages'] if x['id']==msg)['state'],'sent')

    def test_retired_reply_cannot_be_automatically_retried(self):
        ident,incoming,msg=self.uncertain_reply();self.owner_session()
        self.post({'op':'review-delivery','kind':'reply','id':msg,'verdict':'not_sent','proof':'Correct recipient thread checked; reply absent. Retired with no automatic retry.'})
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(d['intelligence']['needs_reply'],[])
        self.assertEqual(next(x for x in d['intelligence']['messages'] if x['id']==msg)['state'],'not_sent')
        self.assertEqual(d['delivery_reviews'],[])
        self.post({'op':'settings','enabled':True})

    def test_confirmation_replay_does_not_duplicate_notes_or_counts(self):
        run,ident=self.sent_company()
        with store.connect() as con:before=con.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0]
        self.assertTrue(self.post({'op':'send-result','id':ident,'state':'sent','proof':'Retry after HTTP timeout; exact intro was already confirmed.'}).json['duplicate'])
        with store.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0],before)
        incoming=self.inbound(ident)
        self.post({'op':'thread-check','run_id':run,'id':ident,'proof':'Latest company message inspected in the exact recipient thread.'})
        msg=self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'We can discuss driveway advertising. Open to a quick call?','grounding':'The company asked about driveway jobs; offer a relevant discussion.'}).json['id']
        self.post({'op':'reply-result','message_id':msg,'state':'sent','proof':'Exact reply visible in correct recipient thread.'})
        with store.connect() as con:before=con.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0]
        self.assertTrue(self.post({'op':'reply-result','message_id':msg,'state':'sent','proof':'Retry after HTTP timeout; exact reply already confirmed.'}).json['duplicate'])
        with store.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0],before)

    def test_concurrent_intro_attempts_allow_only_one_outbound(self):
        from concurrent.futures import ThreadPoolExecutor
        run=self.claim()
        ids=[self.post(self.candidate(run,'Concurrent '+str(n),'https://concurrent'+str(n)+'.example','555555011'+str(n))).json['id'] for n in range(2)]
        def begin(ident):
            try:machine.action({'op':'begin-send','run_id':run,'id':ident});return 'allowed'
            except ValueError:return 'held'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(begin,ids))
        self.assertCountEqual(results,['allowed','held'])
        d=self.client.get('/api/outreach-system').json
        self.assertEqual(sum(x['state']=='sending' for x in d['prospects']),1)

    def test_concurrent_inbound_polling_records_one_message_and_note(self):
        from concurrent.futures import ThreadPoolExecutor
        run,ident=self.sent_company()
        payload={'op':'reply','id':ident,'external_key':'concurrent-visible-id','text':'Can you explain your driveway advertising service?','classification':'Question','source_url':'https://www.facebook.com/messages/t/123'}
        with store.connect() as con:before=con.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0]
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:machine.action(payload),range(2)))
        self.assertEqual(sum(bool(x.get('duplicate')) for x in results),1)
        with store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM crm_notes').fetchone()[0],before+1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM crm_ai_messages WHERE direction='inbound'").fetchone()[0],1)

    def test_outreach_to_booking_full_crm_path_recovers_provider_failure(self):
        """Real CRM endpoints/database; only external Zoom/calendar/email are simulated."""
        from unittest.mock import Mock
        import crm_booking as booking
        run,ident=self.sent_company();incoming=self.inbound(ident)
        self.post({'op':'thread-check','id':ident,'run_id':run,'proof':'Verified recipient thread and latest actual company question.'})
        reply=self.post({'op':'begin-reply','id':ident,'run_id':run,'reply_to':incoming,'text':'We could test a driveway-specific campaign. Open to a 15-minute Zoom call?','grounding':'The company asked about driveway jobs; propose a focused advertising discussion.'}).json['id']
        self.post({'op':'reply-result','message_id':reply,'state':'sent','proof':'Exact response visible as sent in the verified contractor conversation.'})
        self.inbound(ident,'Yes, January 2 at 9 AM Eastern works. Email pat@example.com.','meeting-details','Booking requested')
        self.post(self.assessment_payload(run,ident,'Human needed'))
        snap=self.client.get('/api/outreach-system').json
        self.assertEqual(snap['totals']['booked'],0)
        lead=next(r for r in store.list_leads() if r['id']==snap['prospects'][0]['lead_id'])
        host=dict(id='michael',name='Michael',email='michael@example.com',zoom_user='michael@example.com',calendar_id='michael@example.com')
        provider=Mock();provider.zoom.return_value=('test-meeting','https://example.zoom.us/j/123')
        provider.calendar.side_effect=[booking.ProviderError('Simulated temporary calendar outage'),('test-event','https://calendar.google.com/test-event')]
        sender=Mock(return_value={'ok':True})
        payload=dict(revision=lead['revision'],contact='Pat',email='pat@example.com',date='2030-01-02',time='09:00',zone='Eastern',host_id='michael',note='Advertising discussion requested via Facebook.')
        with patch.object(booking,'connection_status',return_value={'ready':True}),patch.object(booking,'hosts',return_value=[host]),patch.object(booking,'Providers',return_value=provider),patch('tools.email_sender.send_email',sender):
            response=self.client.post('/api/leads/'+str(lead['id'])+'/book',json=payload,headers=self.headers)
            self.assertEqual(response.status_code,200,response.json);job=response.json
            self.assertEqual(job['state'],'failed')
            self.assertEqual(self.client.get('/api/outreach-system').json['totals']['booked'],0)
            job=booking.resume(job['id'],provider,sender)
            self.assertEqual(job['state'],'complete')
            booking.resume(job['id'],provider,sender)
        provider.zoom.assert_called_once();self.assertEqual(provider.calendar.call_count,2);sender.assert_called_once()
        self.assertIn('advertising',provider.zoom.call_args.args[0]['description'])
        self.assertEqual(sender.call_args.args[0],'pat@example.com')
        self.assertIn('https://example.zoom.us/j/123',sender.call_args.args[2])
        self.owner_session();self.post({'op':'release-handoff','id':ident,'proof':'Actual CRM booking completed and recipient email and Eastern time verified.'})
        self.post({'op':'outcome','id':ident,'run_id':run,'outcome':'Booked','occurred_at':store.now(),'proof':'Actual isolated CRM booking completed with Zoom, calendar and confirmation.'})
        data=self.client.get('/api/outreach-system').json
        self.assertEqual(data['totals']['confirmed_sent'],1);self.assertEqual(data['totals']['replies'],1)
        self.assertEqual(data['totals']['booked'],1);self.assertEqual(data['prospects'][0]['conversation_stage'],'Booked')
        self.assertEqual(data['intelligence']['funnel']['segments'][0]['booked'],1)
        self.assertEqual(__import__('crm_calling').call_counts()['total'],0)
