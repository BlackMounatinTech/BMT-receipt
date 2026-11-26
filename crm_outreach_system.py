"""Persistent outreach queue and a leased, Mac-operated browser worker."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import crm_store as store
import crm_calling as calling
import crm_outreach_intelligence as intelligence
import crm_outreach_health as health

CHANNELS=('Facebook','Instagram','Skool')
TRADES=('Concrete','Excavation','Landscaping','Decks and fences')
LOCAL=timezone(timedelta(hours=-7))

def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_config (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
      daily_cap INTEGER NOT NULL, channels TEXT NOT NULL, next_run TEXT, heartbeat TEXT, worker_state TEXT NOT NULL)''')
    con.execute('INSERT OR IGNORE INTO crm_ai_config(id,enabled,daily_cap,channels,next_run,heartbeat,worker_state) VALUES(1,0,24,?,NULL,NULL,?)',(json.dumps(CHANNELS),'Not connected'))
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
      finished_at TEXT, state TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_prospects (id TEXT PRIMARY KEY, identity TEXT NOT NULL UNIQUE,
      lead_id INTEGER, company TEXT NOT NULL, location TEXT NOT NULL, trade TEXT NOT NULL, channel TEXT NOT NULL,
      profile_url TEXT NOT NULL, website TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL,
      ad_url TEXT NOT NULL, issue TEXT NOT NULL, improvement TEXT NOT NULL, scale_evidence TEXT NOT NULL,
      evidence TEXT NOT NULL, checked_at TEXT NOT NULL, message TEXT NOT NULL, state TEXT NOT NULL,
      created_at TEXT NOT NULL, attempted_at TEXT, sent_at TEXT, send_proof TEXT, run_id TEXT, stop_reason TEXT)''')
    columns={r['name'] for r in con.execute('PRAGMA table_info(crm_ai_prospects)')}
    for name,default in [('source_type','ad_issue'),('intent_quote',''),('intent_url',''),('intent_author',''),('source_published_at',''),('qualification','')]:
        if name not in columns:con.execute(f"ALTER TABLE crm_ai_prospects ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_replies (id TEXT PRIMARY KEY, prospect_id TEXT NOT NULL,
      observed_at TEXT NOT NULL, text TEXT NOT NULL, classification TEXT NOT NULL, source_url TEXT NOT NULL,
      suggested_reply TEXT NOT NULL, UNIQUE(prospect_id,text))''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_control_links (token_hash TEXT PRIMARY KEY, expires TEXT NOT NULL)''')
    calling.schema(con)
    import crm_stats
    crm_stats.schema(con)
    intelligence.schema(con)
    health.schema(con)

def stamp(): return store.now()
def instant(): return datetime.now(timezone.utc)
def day(value=None): return (value or instant()).astimezone(LOCAL).date().isoformat()
def host(url): return (urlparse(url).hostname or '').lower().removeprefix('www.')
def phone(value): return re.sub(r'\D','',value)[-10:]
def url(value, field, allow_http=False):
    if not isinstance(value,str) or len(value)>2000 or urlparse(value).scheme not in (('http','https') if allow_http else ('https',)) or not urlparse(value).hostname:
        raise ValueError('Provide a valid '+field+' URL.')
    return value.strip()
def short(p,key,limit=10000,required=True):
    value=p.get(key,'')
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):raise ValueError('Check '+key.replace('_',' ')+'.')
    return value.strip()
def config(con): return dict(con.execute('SELECT * FROM crm_ai_config WHERE id=1').fetchone())
def live_run(con, identity):
    r=con.execute("SELECT * FROM crm_ai_runs WHERE id=? AND state='running'",(identity,)).fetchone()
    if not r:raise ValueError('This run is no longer active.')
    if instant()-datetime.fromisoformat(r['started_at'])>timedelta(minutes=20):raise ValueError('This run lease expired.')
    return r

def expire(con):
    cutoff=(instant()-timedelta(minutes=20)).isoformat(timespec='seconds')
    old=con.execute("SELECT id FROM crm_ai_runs WHERE state='running' AND started_at<?",(cutoff,)).fetchall()
    for r in old:
        con.execute("UPDATE crm_ai_runs SET state='interrupted',finished_at=?,summary='Run interrupted; check any unconfirmed sends.' WHERE id=?",(stamp(),r['id']))
        con.execute("UPDATE crm_ai_prospects SET state='unconfirmed',stop_reason='Worker interrupted; inspect conversation before any retry.' WHERE run_id=? AND state='sending'",(r['id'],))
    if old:con.execute("UPDATE crm_ai_config SET enabled=0,worker_state='Paused after interrupted run' WHERE id=1")

def snapshot(operator=False):
    with store.connect() as con:
        schema(con);expire(con)
        intelligence.reconcile(con)
        details=intelligence.snapshot(con)
        health_data=health.snapshot(con)
        cfg=config(con);cfg['channels']=json.loads(cfg['channels']);cfg['operator']=operator
        prospects=[dict(r) for r in con.execute('SELECT * FROM crm_ai_prospects ORDER BY created_at DESC LIMIT 300')]
        replies=[dict(r) for r in con.execute('''SELECT r.*,p.company,p.channel,p.profile_url FROM crm_ai_replies r
            JOIN crm_ai_prospects p ON p.id=r.prospect_id ORDER BY observed_at DESC LIMIT 200''')]
        runs=[dict(r) for r in con.execute('SELECT * FROM crm_ai_runs ORDER BY started_at DESC LIMIT 30')]
        all_sent=[r['sent_at'] for r in con.execute('SELECT sent_at FROM crm_ai_prospects WHERE sent_at IS NOT NULL')]
        replied=con.execute("SELECT COUNT(DISTINCT prospect_id) FROM crm_ai_messages WHERE direction='inbound' AND classification!='Auto-reply'").fetchone()[0]
        interested=con.execute("SELECT COUNT(DISTINCT prospect_id) FROM crm_ai_messages WHERE direction='inbound' AND classification IN ('Interested','Booking requested')").fetchone()[0]
    today=day()
    return dict(config=cfg,prospects=prospects,replies=replies,runs=runs,
                health=health_data,intelligence=details,totals=dict(sent_today=sum(day(datetime.fromisoformat(v))==today for v in all_sent),
                    confirmed_sent=len(all_sent),replies=replied,interested=interested))

def existing_lead(con,p):
    matches=[]
    for row in con.execute('SELECT * FROM crm_leads'):
        same=(p['phone'] and phone(row['phone'])==phone(p['phone'])) or (p['email'] and row['email'].lower()==p['email'].lower()) or (p['website'] and row['website'] and host(p['website'])==host(row['website'])) or (row['company'].strip().lower()==p['company'].lower() and row['location'].strip().lower()==p['location'].lower())
        if same:matches.append(row)
    if len(matches)>1:raise ValueError('Multiple existing contacts match; review before contacting.')
    return matches[0] if matches else None

def clear_history(con,lead):
    if not lead:return
    if lead['stage']!='Cold' or lead['status']!='New' or lead['last_contacted_at']:
        raise ValueError('This company already has CRM contact or prospect history.')
    if con.execute('SELECT 1 FROM crm_call_events WHERE lead_id=?',(lead['id'],)).fetchone() or con.execute('SELECT 1 FROM crm_outreach_events WHERE lead_id=?',(lead['id'],)).fetchone():
        raise ValueError('This company was already contacted; do not send another cold introduction.')

def recent_source(value):
    try:
        published=datetime.fromisoformat(value.replace('Z','+00:00'))
        valid=published.tzinfo is not None and timedelta(minutes=-2)<=instant()-published<=timedelta(days=30)
    except (ValueError,TypeError,AttributeError):valid=False
    if not valid:raise ValueError('The qualifying post, comment or ad must have a verified publication date within the last 30 days.')


QUALIFICATION=('usa_base','usa_operations','trade_fit','advertising_need','scale_fit','identity_match','improvement_fit')

def qualification(value,website=None,profile=None,location=None):
    return intelligence.qualification(value,website,profile,location)


def candidate(con,p):
    adopting=p.get('op')=='adopt'
    refreshing=p.get('op')=='refresh-candidate'
    previous=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(p.get('id'),)).fetchone() if refreshing else None
    if refreshing:
        if not previous or previous['state']!='ready' or previous['attempted_at']:raise ValueError('Only an uncontacted ready candidate can be refreshed.')
        for key in ('company','location','trade','channel','profile_url','phone','email'):
            if p.get(key)!=previous[key]:raise ValueError('Refresh evidence without changing the company or recipient identity.')
        if host(p.get('website',''))!=host(previous['website']):raise ValueError('Refresh cannot change company website identity.')
    if p.get('country')!='USA' or p.get('trade') not in TRADES or p.get('channel') not in CHANNELS:
        raise ValueError('Only the approved USA contractor trades and outreach channels qualify.')
    verified=qualification(p.get('qualification'),p.get('website'),p.get('profile_url'),p.get('location'))
    source='existing_conversation' if adopting else p.get('source_type','ad_issue')
    if source not in ('ad_issue','public_intent','existing_conversation') or (source=='existing_conversation' and not adopting):raise ValueError('Choose a valid prospect source.')
    intent_quote=short(p,'intent_quote',3000,source=='public_intent')
    intent_author=short(p,'intent_author',300,source=='public_intent')
    intent_url=url(p.get('intent_url'),'post or comment permalink') if source=='public_intent' else ''
    clean={k:short(p,k,200 if k in ('company','location','phone','email') else 10000,required=k not in ('phone','email')) for k in ('company','location','phone','email','issue','improvement','scale_evidence','evidence','message','checked_at')}
    for k in ('profile_url','website','ad_url'):
        value=(p.get('conversation_url') or p.get('ad_url') or p.get('profile_url')) if adopting and k=='ad_url' else p.get(k)
        clean[k]=url(value,k,allow_http=k=='website')
    checked=datetime.fromisoformat(clean['checked_at'].replace('Z','+00:00'))
    if checked.tzinfo is None or not timedelta(minutes=-2)<=instant()-checked<=timedelta(hours=24):raise ValueError('Recheck the source evidence today before outreach.')
    published=short(p,'original_sent_at' if adopting else 'source_published_at',100)
    if not adopting:recent_source(published)
    profile_host=host(clean['profile_url'])
    if not any(profile_host==d or profile_host.endswith('.'+d) for d in {'Facebook':['facebook.com','messenger.com'],'Instagram':['instagram.com'],'Skool':['skool.com']}[p['channel']]):
        raise ValueError('Profile link does not match the selected channel.')
    if not adopting and len(clean['message'])>1800:raise ValueError('Keep the introductory message brief.')
    if adopting:
        priority,ranking,review,variant=0,'{}',json.dumps({'historical':True}),'historical-import'
    else:
        priority,ranking=intelligence.rank(p)
        review,variant=intelligence.message_review(p)
    identity=host(clean['website'])
    if not refreshing and con.execute('SELECT 1 FROM crm_ai_prospects WHERE identity=?',(identity,)).fetchone():raise ValueError('This company is already in the outreach system.')
    lead=existing_lead(con,clean)
    if not adopting:clear_history(con,lead)
    elif lead and lead['status'] in ('Won','Lost'):raise ValueError('Do not reopen a closed/customer conversation for cold outreach.')
    ident=previous['id'] if refreshing else secrets.token_hex(16)
    cols=['id','identity','lead_id','company','location','trade','channel','profile_url','website','phone','email','ad_url','issue','improvement','scale_evidence','evidence','checked_at','message','state','created_at','source_type','intent_quote','intent_url','intent_author','source_published_at','qualification']
    values=[ident,identity,lead['id'] if lead else None,clean['company'],clean['location'],p['trade'],p['channel'],clean['profile_url'],clean['website'],clean['phone'],clean['email'],clean['ad_url'],clean['issue'],clean['improvement'],clean['scale_evidence'],clean['evidence'],clean['checked_at'],clean['message'],'ready',stamp(),source,intent_quote,intent_url,intent_author,published,verified]
    for old in con.execute('SELECT * FROM crm_ai_prospects'):
        if refreshing and old['id']==ident:continue
        if (clean['phone'] and phone(clean['phone'])==phone(old['phone'])) or (clean['email'] and clean['email'].lower()==old['email'].lower()) or old['profile_url'].rstrip('/')==clean['profile_url'].rstrip('/') or (old['company'].lower()==clean['company'].lower() and old['location'].lower()==clean['location'].lower()):
            raise ValueError('This company or recipient is already tracked on another source/channel.')
    if refreshing:
        updates={k:v for k,v in zip(cols,values) if k not in ('id','identity','created_at','state')}
        con.execute('UPDATE crm_ai_prospects SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),ident))
    else:con.execute('INSERT INTO crm_ai_prospects ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',values)
    con.execute('UPDATE crm_ai_prospects SET priority_score=?,ranking=?,message_review=?,variant=? WHERE id=?',(priority,ranking,review,variant,ident))
    con.execute('''INSERT INTO crm_ai_research VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET decision='qualified',reason=excluded.reason,checked_at=excluded.checked_at,run_id=excluded.run_id''',(hashlib.sha256(identity.encode()).hexdigest(),identity,clean['company'],clean['ad_url'],source,p['trade'],p['channel'],'qualified',clean['issue'],stamp(),(instant()+timedelta(days=1)).isoformat(),'[]',p['run_id']))
    intelligence.observation(con,'qualified',identity,p)
    if adopting:
        sent_at=short(p,'original_sent_at',100);original=datetime.fromisoformat(sent_at.replace('Z','+00:00'))
        if original.tzinfo is None or original>instant():raise ValueError('Use the observed historical introduction timestamp.')
        proof=intelligence.evidence(p.get('history_proof'),'existing conversation history')
        if not lead:
            n=con.execute("INSERT INTO crm_leads(company,phone,email,need,created_at,updated_at,stage,status) VALUES(?,?,?,?,?,?,'Prospect','Follow-up')",(clean['company'],clean['phone'],clean['email'],clean['issue'],stamp(),stamp())).lastrowid
            con.execute('UPDATE crm_leads SET location=?,website=? WHERE id=?',(clean['location'],clean['website'],n))
            con.execute('UPDATE crm_ai_prospects SET lead_id=? WHERE id=?',(n,ident))
        else:n=lead['id']
        con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',(n,'Michael','Existing advertising conversation imported (no new message sent)\n'+proof,stamp()))
        con.execute("UPDATE crm_ai_prospects SET state='sent',sent_at=?,send_proof=?,conversation_stage='Engaged' WHERE id=?",(sent_at,proof,ident))
    return dict(id=ident,state='sent' if adopting else 'ready',priority_score=priority)

def action(p):
    op=p.get('op')
    with store.connect() as con:
        schema(con);con.commit();con.execute('BEGIN IMMEDIATE');expire(con);intelligence.reconcile(con)
        handled=health.dispatch(con,p)
        if handled is not None:return handled
        handled=intelligence.dispatch(con,p)
        if handled is not None:return handled
        if op=='settings':
            cfg=config(con);enabled=p.get('enabled',bool(cfg['enabled']));cap=p.get('daily_cap',cfg['daily_cap']);channels=p.get('channels',json.loads(cfg['channels']))
            if type(enabled)is not bool or type(cap)is not int or not 1<=cap<=100 or not isinstance(channels,list) or not channels or set(channels)-set(CHANNELS):raise ValueError('Check run settings.')
            if enabled and not cfg['enabled']:
                uncertain=con.execute("SELECT 1 FROM crm_ai_prospects WHERE state IN ('sending','unconfirmed','blocked')").fetchone() or con.execute("SELECT 1 FROM crm_ai_messages WHERE direction='outbound' AND state IN ('sending','unconfirmed','blocked')").fetchone()
                if uncertain:raise ValueError('Review the uncertain message delivery before resuming outreach; do not resend automatically.')
            con.execute('UPDATE crm_ai_config SET enabled=?,daily_cap=?,channels=?,next_run=? WHERE id=1',(int(enabled),cap,json.dumps(channels),stamp() if enabled and not cfg['enabled'] else cfg['next_run']))
            return dict(ok=True)
        if op=='attention':
            reason=short(p,'reason',500)
            health.alert(con,'System','global_stop',reason,short(p,'action',1500,False) or 'Review the run log, resolve the blocker, then resume outreach.','critical')
            con.execute('UPDATE crm_ai_config SET enabled=0,worker_state=? WHERE id=1',('Paused: '+reason,))
            return dict(ok=True)
        if op=='heartbeat':
            con.execute('UPDATE crm_ai_config SET heartbeat=?,worker_state=CASE WHEN enabled=1 THEN ? ELSE worker_state END WHERE id=1',(stamp(),short(p,'state',300)))
            return dict(ok=True)
        if op=='claim':
            cfg=config(con)
            if not cfg['enabled'] or (cfg['next_run'] and datetime.fromisoformat(cfg['next_run'])>instant()) or con.execute("SELECT 1 FROM crm_ai_runs WHERE state='running'").fetchone():return dict(run=None)
            ident=secrets.token_hex(16);con.execute("INSERT INTO crm_ai_runs(id,started_at,state) VALUES(?,?,'running')",(ident,stamp()))
            con.execute("UPDATE crm_ai_config SET next_run=?,worker_state='Researching and checking replies' WHERE id=1",((instant()+timedelta(minutes=30)).isoformat(timespec='seconds'),))
            return dict(run=ident)
        if op=='finish':
            live_run(con,p.get('run_id'));summary=short(p,'summary',4000)
            pending=con.execute("SELECT 1 FROM crm_ai_prospects WHERE run_id=? AND state='sending'",(p['run_id'],)).fetchone()
            if pending:
                con.execute("UPDATE crm_ai_prospects SET state='unconfirmed',stop_reason='Run ended without send confirmation; inspect the thread.' WHERE run_id=? AND state='sending'",(p['run_id'],))
                con.execute("UPDATE crm_ai_config SET enabled=0,worker_state='Paused: send confirmation missing' WHERE id=1")
            con.execute("UPDATE crm_ai_runs SET state='complete',finished_at=?,summary=? WHERE id=?",(stamp(),summary,p['run_id']))
            con.execute("UPDATE crm_ai_config SET worker_state=CASE WHEN enabled=1 THEN 'Waiting for next check' ELSE worker_state END,heartbeat=? WHERE id=1",(stamp(),))
            intelligence.reconcile(con)
            return dict(ok=True)
        if op=='refresh-candidate':
            live_run(con,p.get('run_id'))
            row=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(p.get('id'),)).fetchone()
            if not row:raise ValueError('Choose an existing ready candidate.')
            merged=dict(row)
            for field in ('qualification','ranking','message_review'):merged[field]=json.loads(merged[field])
            merged.update(country='USA');merged.update(p)
            if 'checked_at' not in p or 'evidence' not in p:raise ValueError('Reinspect the sources and provide a new check timestamp and evidence.')
            return candidate(con,merged)
        if op in ('candidate','adopt'):
            live_run(con,p.get('run_id'));return candidate(con,p)
        if op=='begin-send':
            live_run(con,p.get('run_id'));cfg=config(con)
            row=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(p.get('id'),)).fetchone()
            if not row or row['state']!='ready' or not cfg['enabled'] or row['channel'] not in json.loads(cfg['channels']):raise ValueError('Sending is paused or this prospect is not ready.')
            if instant()-datetime.fromisoformat(row['checked_at'].replace('Z','+00:00'))>timedelta(hours=24):raise ValueError('Source evidence is too old; research again.')
            qualification(row['qualification'],row['website'],row['profile_url'],row['location'])
            recent_source(row['source_published_at'])
            intelligence.message_review(dict(message=row['message'],message_review=json.loads(row['message_review']),variant=row['variant']))
            clear_history(con,existing_lead(con,dict(row)))
            run_attempts=con.execute("SELECT COUNT(*) FROM crm_ai_prospects WHERE run_id=? AND attempted_at IS NOT NULL",(p['run_id'],)).fetchone()[0]
            window_attempts=sum(datetime.fromisoformat(r['attempted_at'])>instant()-timedelta(minutes=30) for r in con.execute('SELECT attempted_at FROM crm_ai_prospects WHERE attempted_at IS NOT NULL'))
            if run_attempts>=2 or window_attempts>=2:raise ValueError('Maximum two new contacts in any 30-minute window.')
            attempts=sum(day(datetime.fromisoformat(r['attempted_at']))==day() for r in con.execute('SELECT attempted_at FROM crm_ai_prospects WHERE attempted_at IS NOT NULL'))
            health.intro_gate(con,row['channel'])
            if attempts>=cfg['daily_cap']:raise ValueError('Daily outreach cap reached; keep researching without sending.')
            con.execute("UPDATE crm_ai_prospects SET state='sending',attempted_at=?,run_id=? WHERE id=?",(stamp(),p['run_id'],row['id']))
            return dict(ok=True,message=row['message'])
        if op=='send-result':
            row=con.execute('SELECT * FROM crm_ai_prospects WHERE id=?',(p.get('id'),)).fetchone()
            if not row or row['state']!='sending':raise ValueError('No active send attempt exists for this prospect.')
            state=p.get('state');proof=short(p,'proof',6000)
            if state not in ('sent','unconfirmed','blocked'):raise ValueError('Choose a verified send result.')
            if state!='sent':
                con.execute('UPDATE crm_ai_prospects SET state=?,send_proof=?,stop_reason=? WHERE id=?',(state,proof,proof,row['id']))
                con.execute("UPDATE crm_ai_config SET enabled=0,worker_state='Paused: inspect the last send attempt' WHERE id=1")
                return dict(ok=True)
            lead=con.execute('SELECT * FROM crm_leads WHERE id=?',(row['lead_id'],)).fetchone() if row['lead_id'] else None
            if not lead:
                n=con.execute("INSERT INTO crm_leads(company,phone,email,need,created_at,updated_at,stage,status) VALUES(?,?,?,?,?,?,'Outreach','Contacted')",(row['company'],row['phone'],row['email'],row['issue']+'\n'+row['improvement'],stamp(),stamp())).lastrowid
                con.execute('UPDATE crm_leads SET location=?,website=?,instagram=? WHERE id=?',(row['location'],row['website'],row['profile_url'] if row['channel']=='Instagram' else '',n))
            else:n=lead['id']
            sent=stamp();method=row['channel']+' DM'
            con.execute('INSERT OR IGNORE INTO crm_outreach_events VALUES(?,?,?,?,?,?)',('ai:'+row['id'],n,method,'Michael',sent,row['message']))
            con.execute("UPDATE crm_leads SET stage=CASE WHEN stage='Cold' THEN 'Outreach' ELSE stage END,status=CASE WHEN status='New' THEN 'Contacted' ELSE status END,last_contacted_at=?,contact_method=?,contact_account='Michael',updated_at=?,revision=revision+1 WHERE id=?",(sent,method,sent,n))
            con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',(n,'Michael',method+' sent\n'+row['profile_url']+'\n'+row['message']+'\nSource: '+row['source_type']+'\nAd / post: '+row['ad_url']+'\n'+row['issue']+('\nPublic comment by '+row['intent_author']+': '+row['intent_quote']+'\n'+row['intent_url'] if row['source_type']=='public_intent' else ''),sent))
            con.execute("UPDATE crm_ai_prospects SET state='sent',sent_at=?,send_proof=?,lead_id=? WHERE id=?",(sent,proof,n,row['id']))
            return dict(ok=True,lead_id=n)
        if op=='reply':
            row=con.execute('SELECT * FROM crm_ai_prospects WHERE id=? AND sent_at IS NOT NULL',(p.get('id'),)).fetchone()
            if not row:raise ValueError('Choose a sent conversation.')
            classification=p.get('classification')
            if classification not in ('Interested','Booking requested','Question','Not interested','Auto-reply','Other'):raise ValueError('Choose a reply classification.')
            text=short(p,'text',10000);source=url(p.get('source_url'),'conversation link');draft=short(p,'suggested_reply',3000,False)
            if text==row['message']:raise ValueError('Do not count the outbound message as a reply.')
            ident=hashlib.sha256((row['id']+'\n'+text).encode()).hexdigest()
            result=con.execute('INSERT OR IGNORE INTO crm_ai_replies VALUES(?,?,?,?,?,?,?)',(ident,row['id'],stamp(),text,classification,source,draft))
            if result.rowcount and row['lead_id']:
                con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',(row['lead_id'],'Michael','Outreach reply ('+classification+')\n'+source+'\n'+text,stamp()))
                if classification in ('Interested','Booking requested'):
                    con.execute("UPDATE crm_leads SET stage='Prospect',status=CASE WHEN status IN ('New','Contacted') THEN 'Follow-up' ELSE status END,updated_at=?,revision=revision+1 WHERE id=? AND status NOT IN ('Won','Lost')",(stamp(),row['lead_id']))
            if classification=='Not interested':con.execute("UPDATE crm_ai_prospects SET state='stopped',stop_reason='Not interested / do not contact again' WHERE id=?",(row['id'],))
            result=intelligence.inbound(con,p,row)
            return dict(ok=True,message_id=result['id'],state=result['state'])
        if op=='skip':
            con.execute("UPDATE crm_ai_prospects SET state='stopped',stop_reason='Skipped by Michael' WHERE id=? AND state='ready'",(p.get('id'),));return dict(ok=True)
        if op=='control-link':
            token=secrets.token_urlsafe(32);con.execute('INSERT INTO crm_ai_control_links VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),(instant()+timedelta(minutes=15)).isoformat()))
            return dict(path='/outreach-connect/'+token)
        raise ValueError('Unknown outreach action.')

def connect_operator(token):
    with store.connect() as con:
        schema(con);con.commit();con.execute('BEGIN IMMEDIATE');key=hashlib.sha256(token.encode()).hexdigest()
        row=con.execute('SELECT * FROM crm_ai_control_links WHERE token_hash=?',(key,)).fetchone()
        if not row or datetime.fromisoformat(row['expires'])<instant():return False
        con.execute('DELETE FROM crm_ai_control_links WHERE token_hash=?',(key,));return True
