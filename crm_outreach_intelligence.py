"""Evidence-backed qualification, research memory and durable two-way outreach."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

STATES=set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())
CHECKS=('usa_base','usa_operations','trade_fit','advertising_need','scale_fit','identity_match','improvement_fit')
STAGES=('Awaiting reply','Engaged','Meeting requested','Booked','Human needed','Not interested','Closed')
MARKERS=('more_work','poor_lead_quality','wasted_ad_spend','no_tracking','slow_followup','budget_objection','timing_objection','trust_objection','already_has_agency','capacity_available','capacity_full','seasonal','needs_details','meeting_interest')

def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_research (
      id TEXT PRIMARY KEY, identity TEXT NOT NULL UNIQUE, company TEXT NOT NULL, source_url TEXT NOT NULL,
      source_type TEXT NOT NULL, trade TEXT NOT NULL, channel TEXT NOT NULL, decision TEXT NOT NULL,
      reason TEXT NOT NULL, checked_at TEXT NOT NULL, next_review TEXT NOT NULL, markers TEXT NOT NULL, run_id TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_observations (id TEXT PRIMARY KEY,kind TEXT NOT NULL,identity TEXT NOT NULL,observed_at TEXT NOT NULL,payload TEXT NOT NULL,run_id TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_sources (id TEXT PRIMARY KEY,url TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL,channel TEXT NOT NULL,last_checked TEXT NOT NULL,notes TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_messages (id TEXT PRIMARY KEY,prospect_id TEXT NOT NULL,
      external_key TEXT NOT NULL, direction TEXT NOT NULL,text TEXT NOT NULL,observed_at TEXT NOT NULL,
      source_url TEXT NOT NULL,classification TEXT NOT NULL,reply_to TEXT UNIQUE,state TEXT NOT NULL,
      proof TEXT NOT NULL DEFAULT '',run_id TEXT NOT NULL DEFAULT '',UNIQUE(prospect_id,direction,external_key))''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_assessments (id TEXT PRIMARY KEY,prospect_id TEXT NOT NULL,
      created_at TEXT NOT NULL,score INTEGER NOT NULL,stage TEXT NOT NULL,summary TEXT NOT NULL,
      markers TEXT NOT NULL,evidence TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_outcomes (id TEXT PRIMARY KEY,prospect_id TEXT NOT NULL,
      outcome TEXT NOT NULL,occurred_at TEXT NOT NULL,proof TEXT NOT NULL,UNIQUE(prospect_id,outcome))''')
    cols={r['name'] for r in con.execute('PRAGMA table_info(crm_ai_prospects)')}
    for name,definition in [('priority_score','INTEGER NOT NULL DEFAULT 0'),('ranking',"TEXT NOT NULL DEFAULT '{}'"),('message_review',"TEXT NOT NULL DEFAULT '{}'"),('variant',"TEXT NOT NULL DEFAULT 'unclassified'"),('last_thread_check',"TEXT NOT NULL DEFAULT ''"),('conversation_stage',"TEXT NOT NULL DEFAULT 'Awaiting reply'"),('conversation_score','INTEGER NOT NULL DEFAULT 0'),('conversation_summary',"TEXT NOT NULL DEFAULT ''")]:
        if name not in cols:con.execute('ALTER TABLE crm_ai_prospects ADD COLUMN '+name+' '+definition)
    cols={r['name'] for r in con.execute('PRAGMA table_info(crm_ai_config)')}
    for name in ('browser_checked_at','browser_state'):
        if name not in cols:con.execute("ALTER TABLE crm_ai_config ADD COLUMN "+name+" TEXT NOT NULL DEFAULT ''")

def m():
    import crm_outreach_system
    return crm_outreach_system

def evidence(value,label):
    if not isinstance(value,str) or len(value.strip())<20 or len(value)>4000 or len(value.split())<4:
        raise ValueError('Save specific observed evidence for '+label+'.')
    return value.strip()

def qualification(value,website=None,profile=None,location=None):
    api=m()
    if isinstance(value,str):
        try:value=json.loads(value)
        except (ValueError,TypeError):value=None
    if not isinstance(value,dict):raise ValueError('Save the complete evidence-based qualification.')
    clean={k:evidence(value.get(k),k) for k in CHECKS}
    outcomes=value.get('checks',{})
    if not isinstance(outcomes,dict) or any(outcomes.get(k)!='pass' for k in CHECKS):raise ValueError('Every qualification check must explicitly pass; unknown or failed means skip.')
    clean['checks']={k:'pass' for k in CHECKS}
    city=api.short(value,'us_city',100);state=api.short(value,'us_state',2)
    if value.get('country')!='USA' or state not in STATES:raise ValueError('Verify the actual U.S. business city and state.')
    clean.update(country='USA',us_city=city,us_state=state)
    if location and (city.lower() not in location.lower() or not re.search(r'\b'+state+r'\b',location)):
        raise ValueError('Company location must match the verified U.S. city and state.')
    for key in ('usa_base','usa_operations'):
        clean[key+'_url']=api.url(value.get(key+'_url'),key+' source',allow_http=True)
        clean[key+'_quote']=evidence(value.get(key+'_quote'),key+' exact source excerpt')
        kind=value.get(key+'_source_kind')
        if kind not in ('official_website','official_business_profile'):raise ValueError('U.S. verification needs the official company website or linked business profile.')
        clean[key+'_source_kind']=kind
        target=urlparse(clean[key+'_url']);official=urlparse(website or '');social=urlparse(profile or '')
        if website and kind=='official_website' and api.host(clean[key+'_url'])!=api.host(website):raise ValueError('U.S. evidence must come from this company’s official website.')
        if profile and kind=='official_business_profile' and (target.hostname!=social.hostname or target.path.rstrip('/')!=social.path.rstrip('/') or target.query!=social.query):raise ValueError('Business-profile evidence must match the verified company profile.')
    if city.lower() not in clean['usa_base_quote'].lower() or not re.search(r'\b'+state+r'\b',clean['usa_base_quote']):
        raise ValueError('Save the actual city/state location excerpt, not a conclusion.')
    if value.get('review_result')!='pass':raise ValueError('A separate evidence critique must pass before qualification.')
    clean['review_result']='pass';clean['review_reason']=evidence(value.get('review_reason'),'independent evidence critique')
    return json.dumps(clean)

def rank(p):
    api=m();r=p.get('ranking')
    if not isinstance(r,dict):raise ValueError('Save prospect ranking with supporting observations.')
    result={};points=0
    for key in ('intent','commercial_fit','specific_gap','readiness'):
        item=r.get(key,{})
        if not isinstance(item,dict) or type(item.get('points')) is not int or not 0<=item['points']<=3:raise ValueError('Rank each prospect factor from 0 to 3.')
        result[key]=dict(points=item['points'],evidence=evidence(item.get('evidence'),key));points+=item['points']
    age=(api.instant()-datetime.fromisoformat(p['source_published_at'].replace('Z','+00:00'))).total_seconds()/86400
    recency=3 if age<=7 else 2 if age<=14 else 1
    result['recency']=dict(points=recency,evidence='Verified signal age: '+str(round(age,1))+' days')
    return round((points+recency)*100/15),json.dumps(result)

def message_review(p):
    api=m();message=api.short(p,'message',900);review=p.get('message_review')
    if len(message.split())>120 or message.count('?')>1:raise ValueError('Use one short message with one question at most.')
    if not isinstance(review,dict) or review.get('grounded') is not True:raise ValueError('Review message claims against the saved evidence.')
    for key in ('observation','approach','cta'):
        part=api.short(review,key,600)
        if part.lower() not in message.lower():raise ValueError('Message must contain its reviewed observation, advertising approach and meeting CTA.')
    if not re.search(r'15[ -]?minute',review['cta'],re.I):raise ValueError('Use a clear 15-minute meeting invitation.')
    review={k:review[k] for k in ('observation','approach','cta','grounded')}
    review['reason']=evidence(p['message_review'].get('reason'),'message grounding')
    if re.search(r'(guarantee.*(jobs|revenue)|not (getting|converting).*leads|know.*not converting)',message,re.I):raise ValueError('Remove unsupported results or conversion claims.')
    variant=api.short(p,'variant',80)
    return json.dumps(review),variant

def pending(con,pid=None):
    clause=' AND i.prospect_id=?' if pid else ''
    return [dict(r) for r in con.execute('''SELECT i.*,p.company,p.channel,p.profile_url,p.conversation_score,p.conversation_stage
      FROM crm_ai_messages i JOIN crm_ai_prospects p ON p.id=i.prospect_id
      WHERE i.direction='inbound' AND i.state='received' AND p.state NOT IN ('stopped','unconfirmed','blocked')
      AND NOT EXISTS(SELECT 1 FROM crm_ai_messages o WHERE o.reply_to=i.id AND o.state IN ('sending','sent','unconfirmed','blocked'))'''+clause+''' ORDER BY CASE i.classification WHEN 'Booking requested' THEN 0 WHEN 'Interested' THEN 1 ELSE 2 END,p.conversation_score DESC,i.observed_at''', (pid,) if pid else ())]

def inbound(con,p,row):
    api=m();key=api.short(p,'external_key',1000,False) or hashlib.sha256((p['text']+'\n'+p['source_url']).encode()).hexdigest()
    ident=hashlib.sha256((row['id']+'\ninbound\n'+key).encode()).hexdigest()
    classification=p['classification'];state='ignored' if classification in ('Auto-reply','Not interested') else 'received'
    con.execute('INSERT OR IGNORE INTO crm_ai_messages(id,prospect_id,external_key,direction,text,observed_at,source_url,classification,state) VALUES(?,?,?,\'inbound\',?,?,?,?,?)',(ident,row['id'],key,p['text'],api.stamp(),p['source_url'],classification,state))
    if classification=='Not interested':con.execute("UPDATE crm_ai_prospects SET conversation_stage='Not interested',conversation_score=0 WHERE id=?",(row['id'],))
    elif classification!='Auto-reply':
        stage='Meeting requested' if classification=='Booking requested' else 'Engaged'
        con.execute('UPDATE crm_ai_prospects SET conversation_stage=? WHERE id=?',(stage,row['id']))
    return dict(id=ident,state=state)

def assessment(con,p):
    api=m();row=prospect(con,p);stage=p.get('stage')
    if stage not in STAGES:raise ValueError('Choose a valid conversation stage.')
    if stage=='Booked' and not con.execute('SELECT 1 FROM crm_stats_bookings WHERE lead_id=? AND created_at>=?',(row['lead_id'],row['sent_at'])).fetchone():raise ValueError('A booked rank requires an actual calendar booking.')
    if row['state']=='stopped' and stage!='Not interested':raise ValueError('Do not reopen an opted-out conversation.')
    factors=p.get('factors',{});score=0
    for key in ('need','engagement','commercial_fit','meeting_readiness'):
        item=factors.get(key,{})
        if not isinstance(item,dict) or type(item.get('points')) is not int or not 0<=item['points']<=3:raise ValueError('Conversation ranking requires four evidence-backed 0–3 factors.')
        evidence(item.get('evidence'),key);score+=item['points']
    score=round(score*100/12)
    if stage in ('Not interested','Closed'):score=0
    summary=evidence(p.get('summary'),'conversation summary');tags=p.get('markers',[])
    if not isinstance(tags,list) or set(tags)-set(MARKERS):raise ValueError('Use the documented conversation markers.')
    details=p.get('insights')
    if not isinstance(details,dict):raise ValueError('Save observed needs, objections, useful value and next step.')
    insights={k:api.short(details,k,2000,False) for k in ('needs','objections','value_offered','next_step','unknowns')}
    proofs=json.dumps(dict(factors=factors,insights=insights))
    last=con.execute('SELECT * FROM crm_ai_assessments WHERE prospect_id=? ORDER BY rowid DESC LIMIT 1',(row['id'],)).fetchone()
    if not last or (last['stage'],last['summary'],last['markers'],last['evidence'])!=(stage,summary,json.dumps(tags),proofs):
        con.execute('INSERT INTO crm_ai_assessments VALUES(?,?,?,?,?,?,?,?)',(secrets.token_hex(16),row['id'],api.stamp(),score,stage,summary,json.dumps(tags),proofs))
    con.execute('UPDATE crm_ai_prospects SET conversation_stage=?,conversation_score=?,conversation_summary=? WHERE id=?',(stage,score,summary,row['id']))
    return dict(ok=True,score=score)

def prospect(con,p):
    row=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(p.get('id'),)).fetchone()
    if not row:raise ValueError('Choose an existing outreach company.')
    return row

def observation(con,kind,identity,p):
    api=m();payload=json.dumps(p,sort_keys=True)
    ident=hashlib.sha256((kind+identity+p.get('run_id','')+payload).encode()).hexdigest()
    con.execute('INSERT OR IGNORE INTO crm_ai_observations VALUES(?,?,?,?,?,?)',(ident,kind,identity,api.stamp(),payload,p.get('run_id','')))


def dispatch(con,p):
    api=m();op=p.get('op')
    if op=='browser-health':
        api.live_run(con,p.get('run_id'));state=api.short(p,'state',300)
        con.execute('UPDATE crm_ai_config SET browser_checked_at=?,browser_state=? WHERE id=1',(api.stamp(),state));return dict(ok=True)
    if op=='source':
        api.live_run(con,p.get('run_id'));link=api.url(p.get('url'),'research source');channel=p.get('channel')
        if channel not in api.CHANNELS:raise ValueError('Choose a supported source channel.')
        con.execute('INSERT INTO crm_ai_sources VALUES(?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET label=excluded.label,last_checked=excluded.last_checked,notes=excluded.notes',(hashlib.sha256(link.encode()).hexdigest(),link,api.short(p,'label',200),channel,api.stamp(),api.short(p,'notes',2000)))
        observation(con,'source',link,p)
        return dict(ok=True)
    if op=='research':
        api.live_run(con,p.get('run_id'));decision=p.get('decision')
        if decision not in ('rejected','deferred'):raise ValueError('Use rejected or deferred; qualified is recorded by candidate validation.')
        source=api.url(p.get('source_url'),'reviewed source');identity=api.short(p,'identity',500).lower()
        con.execute('''INSERT INTO crm_ai_research VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET decision=excluded.decision,reason=excluded.reason,checked_at=excluded.checked_at,next_review=excluded.next_review,run_id=excluded.run_id,markers=excluded.markers''',(hashlib.sha256(identity.encode()).hexdigest(),identity,api.short(p,'company',200),source,api.short(p,'source_type',100),api.short(p,'trade',100,False),api.short(p,'channel',30),decision,evidence(p.get('reason'),'research decision'),api.stamp(),(api.instant()+timedelta(days=7 if decision=='rejected' else 1)).isoformat(),json.dumps(p.get('markers',[])),p['run_id']))
        observation(con,'research',identity,p)
        return dict(ok=True)
    if op=='thread-check':
        api.live_run(con,p.get('run_id'));row=prospect(con,p)
        evidence(p.get('proof'),'live thread check')
        con.execute('UPDATE crm_ai_prospects SET last_thread_check=? WHERE id=?',(api.stamp(),row['id']))
        return dict(ok=True)
    if op=='assess':
        api.live_run(con,p.get('run_id'));return assessment(con,p)
    if op=='no-reply':
        api.live_run(con,p.get('run_id'));row=prospect(con,p);reason=evidence(p.get('reason'),'why no reply is needed')
        con.execute("UPDATE crm_ai_messages SET state='ignored',proof=? WHERE id=? AND prospect_id=? AND direction='inbound' AND state='received'",(reason,p.get('message_id'),row['id']))
        return dict(ok=True)
    if op=='begin-reply':
        api.live_run(con,p.get('run_id'));cfg=api.config(con);row=prospect(con,p)
        if not cfg['enabled'] or row['channel'] not in json.loads(cfg['channels']) or not row['sent_at'] or row['state'] in ('stopped','blocked','unconfirmed') or row['conversation_stage'] in ('Not interested','Closed','Human needed'):raise ValueError('This conversation cannot receive an automatic reply.')
        if not row['last_thread_check'] or api.instant()-datetime.fromisoformat(row['last_thread_check'])>timedelta(minutes=5):raise ValueError('Inspect the live thread immediately before replying.')
        incoming=con.execute("SELECT * FROM crm_ai_messages WHERE id=? AND prospect_id=? AND direction='inbound' AND state='received'",(p.get('reply_to'),row['id'])).fetchone()
        if not incoming:raise ValueError('Reply only to a new unanswered inbound message.')
        latest=con.execute("SELECT id FROM crm_ai_messages WHERE prospect_id=? AND direction='inbound' AND state='received' ORDER BY rowid DESC LIMIT 1",(row['id'],)).fetchone()
        if latest['id']!=incoming['id']:raise ValueError('Respond to the latest inbound messages together.')
        if con.execute('SELECT 1 FROM crm_ai_messages WHERE reply_to=?',(incoming['id'],)).fetchone():raise ValueError('A reply was already attempted; inspect the thread.')
        if con.execute("SELECT 1 FROM crm_ai_messages WHERE prospect_id=? AND direction='outbound' AND state IN ('sending','unconfirmed','blocked')",(row['id'],)).fetchone():raise ValueError('Resolve the previous reply attempt first.')
        text=api.short(p,'text',900)
        if len(text.split())>120 or text.count('?')>1:raise ValueError('Keep the reply short with at most one question.')
        evidence(p.get('grounding'),'reply context and useful next step')
        ident=secrets.token_hex(16)
        con.execute("INSERT INTO crm_ai_messages(id,prospect_id,external_key,direction,text,observed_at,source_url,classification,reply_to,state,proof,run_id) VALUES(?,?,?,'outbound',?,?,?,'Reply',?,'sending',?,?)",(ident,row['id'],ident,text,api.stamp(),incoming['source_url'],incoming['id'],p['grounding'],p['run_id']))
        return dict(id=ident,message=text)
    if op=='reply-result':
        row=con.execute("SELECT * FROM crm_ai_messages WHERE id=? AND direction='outbound' AND state='sending'",(p.get('message_id'),)).fetchone()
        if not row:raise ValueError('No pending reply attempt.')
        state=p.get('state');proof=api.short(p,'proof',6000)
        if state not in ('sent','unconfirmed','blocked'):raise ValueError('Choose a verified reply result.')
        con.execute('UPDATE crm_ai_messages SET state=?,proof=? WHERE id=?',(state,proof,row['id']))
        if state=='sent':
            incoming=con.execute('SELECT rowid FROM crm_ai_messages WHERE id=?',(row['reply_to'],)).fetchone()
            con.execute("UPDATE crm_ai_messages SET state='answered' WHERE prospect_id=? AND direction='inbound' AND state='received' AND rowid<=?",(row['prospect_id'],incoming['rowid']))
            company=prospect(con,{'id':row['prospect_id']})
            if company['lead_id']:con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',(company['lead_id'],'Michael','Outreach reply sent\n'+row['source_url']+'\n'+row['text'],api.stamp()))
        else:con.execute("UPDATE crm_ai_config SET enabled=0,worker_state='Paused: reply send needs review' WHERE id=1")
        return dict(ok=True)
    if op=='outcome':
        if p.get('run_id'):api.live_run(con,p['run_id'])
        row=prospect(con,p);outcome=p.get('outcome')
        if outcome not in ('Booked','Held','Closed','Lost','No-show'):raise ValueError('Choose an observed meeting or sales outcome.')
        proof=evidence(p.get('proof'),'actual outcome');occurred=api.short(p,'occurred_at',100)
        parsed=datetime.fromisoformat(occurred.replace('Z','+00:00'))
        if not parsed.tzinfo or parsed>api.instant()+timedelta(minutes=2):raise ValueError('Use the actual observed outcome date.')
        if outcome=='Booked':
            booking=con.execute("SELECT 1 FROM crm_stats_bookings WHERE lead_id=? AND created_at>=?",(row['lead_id'],row['sent_at'])).fetchone() if row['lead_id'] else None
            if not booking:raise ValueError('Book through the actual CRM calendar flow first; an agreed time is not a booking.')
        con.execute('INSERT OR IGNORE INTO crm_ai_outcomes VALUES(?,?,?,?,?)',(secrets.token_hex(16),row['id'],outcome,occurred,proof))
        if outcome in ('Booked','Closed','Lost'):con.execute('UPDATE crm_ai_prospects SET conversation_stage=? WHERE id=?',('Closed' if outcome in ('Closed','Lost') else 'Booked',row['id']))
        return dict(ok=True)
    return None

def reconcile(con):
    """Surface unconfirmed replies after a run dies, before allowing more sends."""
    pending_rows=con.execute("SELECT o.id FROM crm_ai_messages o JOIN crm_ai_runs r ON r.id=o.run_id WHERE o.state='sending' AND r.state!='running'").fetchall()
    if pending_rows:
        con.executemany("UPDATE crm_ai_messages SET state='unconfirmed',proof='Run ended without confirmation; inspect thread before continuing.' WHERE id=?",[(r['id'],) for r in pending_rows])
        con.execute("UPDATE crm_ai_config SET enabled=0,worker_state='Paused: reply confirmation missing' WHERE id=1")

def snapshot(con):
    api=m();reconcile(con)
    conversations=[dict(r) for r in con.execute("SELECT * FROM crm_ai_prospects WHERE sent_at IS NOT NULL AND state!='stopped' AND conversation_stage NOT IN ('Closed','Not interested') ORDER BY CASE WHEN last_thread_check='' THEN 0 ELSE 1 END,last_thread_check,conversation_score DESC")]
    archive=[dict(r) for r in con.execute("SELECT * FROM crm_ai_prospects WHERE sent_at IS NOT NULL ORDER BY conversation_score DESC")]
    messages=[dict(r) for r in con.execute('SELECT * FROM crm_ai_messages ORDER BY rowid')]
    assessments=[dict(r) for r in con.execute('SELECT * FROM crm_ai_assessments ORDER BY rowid DESC')]
    research=[dict(r) for r in con.execute('SELECT * FROM crm_ai_research ORDER BY checked_at DESC')]
    sources=[dict(r) for r in con.execute('SELECT * FROM crm_ai_sources ORDER BY last_checked')]
    observations=[dict(r) for r in con.execute('SELECT * FROM crm_ai_observations ORDER BY observed_at DESC')]
    outcomes=[dict(r) for r in con.execute('SELECT * FROM crm_ai_outcomes ORDER BY occurred_at DESC')]
    segments={}
    for r in con.execute('SELECT * FROM crm_ai_prospects'):
        key=(r['source_type'],r['trade'],r['variant']);item=segments.setdefault(key,dict(source=key[0],trade=key[1],variant=key[2],qualified=0,attempted=0,sent=0,replied=0,interested=0,booked=0,held=0,closed=0))
        item['qualified']+=1;item['attempted']+=bool(r['attempted_at']);item['sent']+=bool(r['sent_at'])
        rs=con.execute("SELECT classification FROM crm_ai_messages WHERE prospect_id=? AND direction='inbound'",(r['id'],)).fetchall()
        item['replied']+=any(x['classification']!='Auto-reply' for x in rs)
        item['interested']+=any(x['classification'] in ('Interested','Booking requested') for x in rs)
        actual_booking=con.execute("SELECT 1 FROM crm_stats_bookings WHERE lead_id=? AND created_at>=?",(r['lead_id'],r['sent_at'])).fetchone() if r['sent_at'] else None
        item['booked']+=bool(actual_booking)
        for outcome in ('Held','Closed'):item[outcome.lower()]+=any(o['prospect_id']==r['id'] and o['outcome']==outcome for o in outcomes)
    screening_segments={}
    for r in research:
        key=(r['source_type'],r['trade']);item=screening_segments.setdefault(key,dict(source=key[0],trade=key[1],screened=0,rejected=0,deferred=0,qualified=0))
        item['screened']+=1;item[r['decision']]+=1
    learning={}
    for a in reversed(assessments):learning[a['prospect_id']]=a
    marker_stats={}
    for pid,a in learning.items():
        row=con.execute('SELECT sent_at FROM crm_ai_prospects WHERE id=?',(pid,)).fetchone()
        for tag in json.loads(a['markers']):
            item=marker_stats.setdefault(tag,dict(marker=tag,companies=0,interested=0,booked=0,closed=0));item['companies']+=1;item['interested']+=a['stage'] in ('Meeting requested','Booked')
            p=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(pid,)).fetchone()
            item['booked']+=bool(p['sent_at'] and con.execute('SELECT 1 FROM crm_stats_bookings WHERE lead_id=? AND created_at>=?',(p['lead_id'],p['sent_at'])).fetchone())
            item['closed']+=any(o['prospect_id']==pid and o['outcome']=='Closed' for o in outcomes)
    for source in sources:
        matched=con.execute('SELECT id,lead_id,sent_at FROM crm_ai_prospects WHERE ad_url=? OR intent_url=?',(source['url'],source['url'])).fetchall()
        source['qualified']=len(matched)
        source['sent']=sum(bool(p['sent_at']) for p in matched)
        source['replied']=sum(bool(con.execute("SELECT 1 FROM crm_ai_messages WHERE prospect_id=? AND direction='inbound' AND classification!='Auto-reply'",(p['id'],)).fetchone()) for p in matched)
        source['booked']=sum(bool(p['sent_at'] and con.execute('SELECT 1 FROM crm_stats_bookings WHERE lead_id=? AND created_at>=?',(p['lead_id'],p['sent_at'])).fetchone()) for p in matched)
    return dict(conversations=conversations,conversation_archive=archive,needs_reply=pending(con),messages=messages,assessments=assessments,research=research,sources=sources,outcomes=outcomes,
      observations=observations,funnel=dict(screening_segments=list(screening_segments.values()),screened=len(research),rejected=sum(r['decision']=='rejected' for r in research),deferred=sum(r['decision']=='deferred' for r in research),qualified=sum(r['qualified'] for r in segments.values()),segments=list(segments.values())),marker_stats=list(marker_stats.values()),markers=list(MARKERS))
