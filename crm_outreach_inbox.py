"""Conversation view over confirmed outreach; viewing never marks a reply answered."""
from datetime import datetime, timezone
import crm_store as store


def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_outreach_read (
        lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id), seen_through INTEGER NOT NULL DEFAULT 0)''')


def instant(value):
    if not value:return 0
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).replace(tzinfo=timezone.utc).timestamp() if len(value)==10 else datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):return 0


def snapshot(operator=False):
    import crm_outreach_system as machine
    with store.connect() as con:
        machine.schema(con);schema(con)
        prospects=[dict(r) for r in con.execute('SELECT * FROM crm_ai_prospects WHERE sent_at IS NOT NULL AND lead_id IS NOT NULL')]
        by_lead={}
        for p in prospects:by_lead.setdefault(p['lead_id'],[]).append(p)
        seen={r['lead_id']:r['seen_through'] for r in con.execute('SELECT * FROM crm_outreach_read')}
        messages={}
        for r in con.execute('SELECT rowid AS sequence,* FROM crm_ai_messages ORDER BY rowid'):
            messages.setdefault(r['prospect_id'],[]).append(dict(r))
        pending={r['id'] for r in machine.intelligence.pending(con)}
        notes={}
        for r in con.execute('SELECT * FROM crm_notes ORDER BY id'):
            notes.setdefault(r['lead_id'],[]).append(dict(r))
        rows=[]
        for raw in con.execute('SELECT * FROM crm_leads'):
            lead=dict(raw)
            linked=by_lead.get(lead['id'],[])
            if lead['stage']!='Outreach' and not linked:continue
            timeline=[];last_check='';newest_inbound=0;needs_reply=False;uncertain=False;stopped=False
            for p in linked:
                last_check=max(last_check,p['last_thread_check'] or '')
                stopped=stopped or p['state']=='stopped' or p['conversation_stage']=='Not interested'
                timeline.append(dict(id='intro:'+p['id'],direction='outbound',text=p['message'],at=p['sent_at'],state='sent',classification='Introduction',source_url=p['profile_url']))
                for m in messages.get(p['id'],[]):
                    if m['direction']=='inbound':newest_inbound=max(newest_inbound,m['sequence'])
                    needs_reply=needs_reply or m['id'] in pending
                    uncertain=uncertain or (m['direction']=='outbound' and m['state'] in ('unconfirmed','blocked','sending'))
                    timeline.append(dict(id=m['id'],direction=m['direction'],text=m['text'],at=m['observed_at'],state=m['state'],classification=m['classification'],source_url=m['source_url']))
            if not linked:
                for n in notes.get(lead['id'],[]):
                    if '\nExact message:\n' in n['text']:
                        text=n['text'].split('\nExact message:\n',1)[1].split('\nResponse:',1)[0]
                        timeline.append(dict(id='note:'+str(n['id']),direction='outbound',text=text,at=lead['last_contacted_at'] or n['created_at'],state='sent',classification='Introduction',source_url=''))
            timeline.sort(key=lambda m:instant(m['at']))
            latest=timeline[-1] if timeline else None
            state='Needs reply' if needs_reply else 'Waiting on them'
            if uncertain:state='Needs review'
            if stopped or lead['status'] in ('Won','Lost'):state='Closed'
            elif lead['status']=='Call booked' or any(p['conversation_stage']=='Booked' for p in linked):state='Meeting booked'
            if not timeline and not lead['last_contacted_at']:state='Date not recorded'
            rows.append(dict(lead,conversation_state=state,new_reply=newest_inbound>seen.get(lead['id'],0),
                inbound_sequence=newest_inbound,last_checked_at=last_check or None,
                last_activity_at=latest['at'] if latest else lead['last_contacted_at'],
                last_message=latest,conversation=timeline,linked_to_system=bool(linked)))
        cfg=machine.config(con)
        running=con.execute("SELECT id FROM crm_ai_runs WHERE state='running' AND mode='check'").fetchone()
        return dict(conversations=rows,checked_at=store.now(),operator=operator,check_queued=bool(cfg['manual_check']),check_running=bool(running),heartbeat=cfg['heartbeat'],automation_enabled=bool(cfg['enabled']))


def mark_read(lead_id,sequence):
    if type(sequence) is not int or sequence<0:raise ValueError('Provide the displayed reply sequence.')
    import crm_outreach_system as machine
    with store.connect() as con:
        machine.schema(con);schema(con)
        valid=con.execute("SELECT MAX(m.rowid) FROM crm_ai_messages m JOIN crm_ai_prospects p ON p.id=m.prospect_id WHERE p.lead_id=? AND m.direction='inbound'",(lead_id,)).fetchone()[0] or 0
        if sequence>valid:raise ValueError('Refresh the conversation before marking it read.')
        if not con.execute('SELECT 1 FROM crm_leads WHERE id=?',(lead_id,)).fetchone():raise ValueError('Lead not found.')
        con.execute('INSERT INTO crm_outreach_read VALUES (?,?) ON CONFLICT(lead_id) DO UPDATE SET seen_through=MAX(seen_through,excluded.seen_through)',(lead_id,sequence))


def record_check(con,p):
    """Worker reports evidence from a real thread, including legacy manual sends."""
    from urllib.parse import urlparse
    import crm_outreach_system as machine
    machine.live_run(con,p.get('run_id'))
    proof=machine.intelligence.evidence(p.get('proof'),'live thread inspection')
    lead=con.execute('SELECT * FROM crm_leads WHERE id=?',(p.get('lead_id'),)).fetchone()
    if not lead:raise ValueError('Choose an existing contacted lead.')
    row=con.execute('SELECT * FROM crm_ai_prospects WHERE lead_id=? AND sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 1',(lead['id'],)).fetchone()
    if not row and lead['stage']!='Outreach':raise ValueError('Only existing outreach conversations can be checked.')
    channel=p.get('channel');source=machine.url(p.get('source_url'),'conversation')
    allowed={'Facebook':('facebook.com','messenger.com'),'Instagram':('instagram.com',),'Skool':('skool.com',)}
    host=(urlparse(source).hostname or '').removeprefix('www.')
    if channel not in allowed or not any(host==h or host.endswith('.'+h) for h in allowed[channel]):raise ValueError('Use the verified platform conversation link.')
    if row and row['channel']!=channel:raise ValueError('This conversation is tracked on a different platform.')
    incoming=p.get('messages',[])
    if not isinstance(incoming,list) or len(incoming)>50:raise ValueError('Provide up to 50 verified inbound messages.')
    if not row:
        if not lead['last_contacted_at']:raise ValueError('Record the known original contact date before importing this thread.')
        if lead['contact_method']!=channel+' DM':raise ValueError('Match the recorded contact platform.')
        pid='inbox:'+str(lead['id'])
        original=''
        for n in con.execute('SELECT text FROM crm_notes WHERE lead_id=? ORDER BY id',(lead['id'],)):
            if '\nExact message:\n' in n['text']:original=n['text'].split('\nExact message:\n',1)[1].split('\nResponse:',1)[0]
        # No new send or conversion event is generated by importing a tracked thread.
        con.execute('''INSERT INTO crm_ai_prospects(id,identity,lead_id,company,location,trade,channel,profile_url,website,phone,email,ad_url,issue,improvement,scale_evidence,evidence,checked_at,message,state,created_at,sent_at,source_type)
          VALUES(?,?,?,?,?,'',?,?,?,?,?,'','','','',?,?,?,'sent',?,?,'existing_conversation')''',
          (pid,pid,lead['id'],lead['company'],lead['location'],channel,source,lead['website'],lead['phone'],lead['email'],proof,store.now(),original,store.now(),lead['last_contacted_at']))
        row=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(pid,)).fetchone()
    added=0
    for item in incoming:
        if not isinstance(item,dict) or item.get('classification') not in ('Interested','Booking requested','Question','Not interested','Auto-reply','Other'):raise ValueError('Classify each verified inbound message.')
        text=machine.short(item,'text',10000)
        machine.intelligence.reject_outbound_echo(con,row,text)
        result=machine.intelligence.inbound(con,dict(item,text=text,source_url=source),row)
        added+=not result.get('duplicate',False)
        if not result.get('duplicate') and item['classification'] in ('Interested','Booking requested'):
            con.execute("UPDATE crm_leads SET stage='Prospect',status=CASE WHEN status IN ('New','Contacted') THEN 'Follow-up' ELSE status END,updated_at=?,revision=revision+1 WHERE id=? AND status NOT IN ('Won','Lost')",(store.now(),lead['id']))
        if item['classification']=='Not interested':con.execute("UPDATE crm_ai_prospects SET state='stopped',stop_reason='Not interested / do not contact again' WHERE id=?",(row['id'],))
    con.execute('UPDATE crm_ai_prospects SET last_thread_check=? WHERE id=?',(store.now(),row['id']))
    return dict(ok=True,new_replies=added)
