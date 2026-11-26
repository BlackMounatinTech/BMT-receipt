import unittest
import test_outreach_system as base
import crm_outreach_inbox as inbox
import crm_store as store
import crm_outreach_system as machine

class InboxTests(unittest.TestCase):
    setUp=base.OutreachSystemTests.setUp
    tearDown=base.OutreachSystemTests.tearDown
    post=base.OutreachSystemTests.post
    claim=base.OutreachSystemTests.claim
    candidate=base.OutreachSystemTests.candidate
    # Reuse isolated app setup, without inheriting the entire system test suite.
    def test_legacy_check_unread_and_answered_are_separate(self):
        n=store.add_lead('Demo',phone='5555550100',stage='Outreach',contact_method='Facebook DM',last_contacted_at='2026-11-24')
        self.post({'op':'request-inbox-check'})
        claim=self.post({'op':'claim'}).json
        self.assertEqual(claim['mode'],'check')
        self.assertFalse(machine.snapshot()['config']['enabled'])
        payload=dict(op='inbox-check-result',run_id=claim['run'],lead_id=n,channel='Facebook',source_url='https://www.facebook.com/demo',proof='Verified complete live company thread and incoming speaker.',messages=[dict(text='Can you explain the advertising fee?',classification='Question',external_key='real-message-1')])
        self.assertEqual(self.post(payload).json['new_replies'],1)
        self.assertEqual(self.post(payload).json['new_replies'],0)
        row=inbox.snapshot()['conversations'][0]
        self.assertEqual(row['conversation_state'],'Needs reply');self.assertTrue(row['new_reply'])
        self.assertTrue(row['last_checked_at'])
        inbox.mark_read(n,row['inbound_sequence'])
        row=inbox.snapshot()['conversations'][0]
        self.assertFalse(row['new_reply']);self.assertEqual(row['conversation_state'],'Needs reply')
        rejected=self.post({'op':'begin-reply','run_id':claim['run'],'id':'inbox:'+str(n)},ok=False)
        self.assertEqual(rejected.status_code,400);self.assertIn('read-only',rejected.json['error'])
        with store.connect() as con:
            con.execute("UPDATE crm_ai_messages SET state='answered' WHERE direction='inbound'")
        self.assertEqual(inbox.snapshot()['conversations'][0]['conversation_state'],'Waiting on them')
        self.post({'op':'finish','run_id':claim['run'],'summary':'Checked one thread; no outbound messages sent.'})
        self.assertFalse(machine.snapshot()['config']['enabled'])

    def test_open_cannot_hide_a_reply_arriving_after_snapshot(self):
        n=store.add_lead('Demo',phone='5555550100',stage='Outreach',contact_method='Facebook DM',last_contacted_at='2026-11-24')
        self.post({'op':'request-inbox-check'});run=self.post({'op':'claim'}).json['run']
        p=dict(op='inbox-check-result',run_id=run,lead_id=n,channel='Facebook',source_url='https://www.facebook.com/demo',proof='Read the correct live conversation.',messages=[dict(text='First question',classification='Question',external_key='1')])
        self.post(p);old=inbox.snapshot()['conversations'][0]
        p['messages']=[dict(text='Second question',classification='Question',external_key='2')];self.post(p)
        inbox.mark_read(n,old['inbound_sequence'])
        self.assertTrue(inbox.snapshot()['conversations'][0]['new_reply'])

    def test_confirmed_intro_enters_inbox_and_booking_keeps_conversation(self):
        run=self.claim();p=self.candidate(run);pid=self.post(p).json['id']
        self.post({'op':'begin-send','id':pid,'run_id':run})
        n=self.post({'op':'send-result','id':pid,'state':'sent','proof':'Verified outgoing message in live thread.'}).json['lead_id']
        row=inbox.snapshot()['conversations'][0]
        self.assertEqual(row['id'],n);self.assertEqual(row['conversation_state'],'Waiting on them')
        with store.connect() as con:con.execute("UPDATE crm_leads SET stage='Prospect',status='Call booked' WHERE id=?",(n,))
        row=inbox.snapshot()['conversations'][0]
        self.assertEqual(row['conversation_state'],'Meeting booked');self.assertTrue(row['conversation'])

    def test_booked_customer_question_still_needs_reply_and_check_stays_read_only(self):
        n=store.add_lead('Demo',phone='5555550100',stage='Outreach',contact_method='Facebook DM',last_contacted_at='2026-11-24')
        self.post({'op':'request-inbox-check'});run=self.post({'op':'claim'}).json['run']
        p=dict(op='inbox-check-result',run_id=run,lead_id=n,channel='Facebook',source_url='https://www.facebook.com/demo',proof='Read the correct live conversation.',messages=[dict(text='What should I bring to our meeting?',classification='Question',external_key='1')])
        self.post(p)
        with store.connect() as con:con.execute("UPDATE crm_leads SET status='Call booked' WHERE id=?",(n,))
        self.assertEqual(inbox.snapshot()['conversations'][0]['conversation_state'],'Needs reply')
        self.assertEqual(self.post({'op':'settings','enabled':True},ok=False).status_code,400)
        self.assertFalse(machine.snapshot()['config']['enabled'])
        self.assertEqual(self.client.post(f'/api/outreach-inbox/{n}/read',json=['invalid'],headers=self.csrf).status_code,400)

    def test_optout_is_not_reopened_by_later_batch_message(self):
        n=store.add_lead('Demo',phone='5555550100',stage='Outreach',contact_method='Facebook DM',last_contacted_at='2026-11-24')
        self.post({'op':'request-inbox-check'});run=self.post({'op':'claim'}).json['run']
        p=dict(op='inbox-check-result',run_id=run,lead_id=n,channel='Facebook',source_url='https://www.facebook.com/demo',proof='Read the correct live conversation.',messages=[dict(text='Do not contact me again.',classification='Not interested',external_key='1'),dict(text='Old question from earlier',classification='Interested',external_key='2')])
        self.post(p)
        with store.connect() as con:
            prospect=con.execute('SELECT * FROM crm_ai_prospects WHERE lead_id=?',(n,)).fetchone()
            self.assertEqual(prospect['state'],'stopped');self.assertEqual(prospect['conversation_stage'],'Not interested')
        self.assertEqual(store.list_leads()[0]['stage'],'Outreach')
        self.assertEqual(inbox.snapshot()['conversations'][0]['conversation_state'],'Closed')

    def test_manual_check_request_retry_does_not_queue_a_second_run(self):
        self.post({'op':'request-inbox-check'})
        run=self.post({'op':'claim'}).json['run']
        retry=self.post({'op':'request-inbox-check'}).json
        self.assertTrue(retry['running']);self.assertFalse(retry['queued'])
        self.post({'op':'finish','run_id':run,'summary':'Read-only test completed.'})
        self.assertIsNone(self.post({'op':'claim'}).json['run'])
