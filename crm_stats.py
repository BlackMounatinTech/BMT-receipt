"""Calendar-day funnel reporting; manual logs never alter calling or lead records."""
import math
import uuid
from datetime import date, datetime, timedelta, timezone
import crm_store as store
import crm_calling as calling

LOCAL = timezone(timedelta(hours=-7))
OUTCOMES = ('Closed', 'Follow-up', 'Not a fit', 'No sale', 'No-show')

def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_stats_bookings (
      lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id), created_at TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_stats_outreach (
      day TEXT NOT NULL, channel TEXT NOT NULL, sent INTEGER NOT NULL, replies INTEGER NOT NULL,
      booked INTEGER NOT NULL, notes TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(day,channel))''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_stats_discovery (
      id TEXT PRIMARY KEY, day TEXT NOT NULL, company TEXT NOT NULL, minutes INTEGER NOT NULL,
      outcome TEXT NOT NULL, rating INTEGER, offer_presented INTEGER NOT NULL,
      collected_usd REAL NOT NULL, notes TEXT NOT NULL, revision INTEGER NOT NULL)''')

def record_booking(con, lead_id, stamp):
    schema(con)
    con.execute('INSERT OR IGNORE INTO crm_stats_bookings VALUES (?,?)', (lead_id, stamp))

def valid_day(value):
    if not isinstance(value, str):
        raise ValueError('Choose a valid date.')
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value: raise ValueError()
    except ValueError:
        raise ValueError('Choose a valid date.')
    return value

def integer(value, label, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError('Check ' + label + '.')
    return value

def text(value, label, limit=10000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError('Check ' + label + '.')
    return value.strip()

def outreach_row(day, channel):
    valid_day(day)
    if channel not in ('Facebook', 'Instagram'): raise ValueError('Choose Facebook or Instagram.')
    with store.connect() as con:
        schema(con)
        row = con.execute('SELECT * FROM crm_stats_outreach WHERE day=? AND channel=?', (day,channel)).fetchone()
        return dict(row) if row else dict(day=day, channel=channel, sent=0, replies=0, booked=0, notes='', revision=0)

def save_outreach(p):
    day=valid_day(p.get('day')); channel=p.get('channel')
    if channel not in ('Facebook','Instagram'): raise ValueError('Choose Facebook or Instagram.')
    values=[integer(p.get(k), k) for k in ('sent','replies','booked')]
    notes=text(p.get('notes',''), 'notes'); revision=integer(p.get('revision'), 'revision')
    with store.connect() as con:
        schema(con); con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT revision FROM crm_stats_outreach WHERE day=? AND channel=?',(day,channel)).fetchone()
        if (row['revision'] if row else 0) != revision: raise store.Conflict('This daily entry changed. Reload it before saving.')
        con.execute('INSERT OR REPLACE INTO crm_stats_outreach VALUES (?,?,?,?,?,?,?)', (day,channel,*values,notes,revision+1))
    return dict(revision=revision+1)

def save_discovery(p):
    day=valid_day(p.get('day')); company=text(p.get('company'), 'company', 200, True)
    minutes=integer(p.get('minutes'), 'duration',1440); outcome=p.get('outcome')
    if outcome not in OUTCOMES: raise ValueError('Choose a discovery outcome.')
    if outcome != 'No-show' and minutes < 1: raise ValueError('Enter the call duration in minutes.')
    if outcome == 'No-show': minutes=0
    rating=p.get('rating')
    if rating is not None and (integer(rating,'self-rating',5)<1): raise ValueError('Choose a rating from 1 to 5.')
    if not isinstance(p.get('offer_presented'), bool): raise ValueError('Check whether you presented the offer.')
    money=p.get('collected_usd',0)
    if isinstance(money,bool) or not isinstance(money,(float,int)) or not math.isfinite(money) or not 0<=money<=10000000:
        raise ValueError('Check money collected.')
    notes=text(p.get('notes',''),'notes'); revision=integer(p.get('revision',0),'revision')
    identity=p.get('id') or uuid.uuid4().hex
    if not isinstance(identity,str) or len(identity)>80: raise ValueError('Invalid discovery record.')
    with store.connect() as con:
        schema(con); con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT revision FROM crm_stats_discovery WHERE id=?',(identity,)).fetchone()
        if (row['revision'] if row else 0)!=revision: raise store.Conflict('This discovery record changed. Reload it before editing.')
        con.execute('INSERT OR REPLACE INTO crm_stats_discovery VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (identity,day,company,minutes,outcome,rating,int(p['offer_presented']),round(money,2),notes,revision+1))
    return dict(id=identity,revision=revision+1)

def local_day(stamp):
    try:
        parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL).date().isoformat()
    except (ValueError,TypeError,AttributeError): return None

def report(start, end):
    valid_day(start); valid_day(end)
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if not 0 <= (last-first).days <= 365: raise ValueError('Choose a date range of up to 366 days.')
    # Existing idempotent backfill recovers legacy Phone notes, never outreach DMs.
    calling.call_counts()
    days={}
    for n in range((last-first).days+1):
        day=(first+timedelta(days=n)).isoformat()
        days[day]=dict(day=day,calls=0,answered=0,no_answer=0,not_interested=0,follow_up=0,booking_outcomes=0,unknown=0,meetings_booked=0,discoveries=0,no_shows=0,closes=0,minutes=0,collected_usd=0,offers=0)
    with store.connect() as con:
        schema(con)
        # Preserve original booking dates, even after status changes or rescheduling.
        for row in con.execute('SELECT id,booked_at FROM crm_leads WHERE booked_at IS NOT NULL'):
            record_booking(con,row['id'],row['booked_at'])
        for row in con.execute('SELECT outcome,created_at FROM crm_call_events'):
            d=days.get(local_day(row['created_at']))
            if d is None: continue
            d['calls']+=1
            key={'No answer':'no_answer','Not interested':'not_interested','Follow up':'follow_up','Book meeting':'booking_outcomes'}.get(row['outcome'],'unknown')
            d[key]+=1
            if key not in ('no_answer','unknown'): d['answered']+=1
        for row in con.execute('SELECT created_at FROM crm_stats_bookings'):
            d=days.get(local_day(row['created_at']))
            if d is not None: d['meetings_booked']+=1
        outreach=[dict(r) for r in con.execute('SELECT * FROM crm_stats_outreach WHERE day>=? AND day<=? ORDER BY day DESC,channel',(start,end))]
        discovery=[dict(r) for r in con.execute('SELECT * FROM crm_stats_discovery WHERE day>=? AND day<=? ORDER BY day DESC,rowid DESC',(start,end))]
    for row in discovery:
        d=days[row['day']]
        d['no_shows']+=row['outcome']=='No-show'
        d['discoveries']+=row['outcome']!='No-show'
        d['closes']+=row['outcome']=='Closed'
        d['minutes']+=row['minutes']; d['offers']+=row['offer_presented']; d['collected_usd']+=row['collected_usd']
    automatic={}
    with store.connect() as con:
        for r in con.execute("SELECT method,sent_at FROM crm_outreach_events WHERE event_key LIKE 'ai:%'"):
            d=local_day(r['sent_at'])
            if d and start<=d<=end:
                key=(d,r['method'].removesuffix(' DM'))
                automatic.setdefault(key,dict(day=d,channel=key[1],sent=0,replies=0,interested=0,booked=0))['sent']+=1
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_ai_replies'").fetchone()
        if exists:
            for r in con.execute("SELECT p.channel,r.prospect_id,MIN(r.observed_at) AS observed_at,MAX(CASE WHEN r.classification IN ('Interested','Booking requested') THEN 1 ELSE 0 END) AS interested FROM crm_ai_replies r JOIN crm_ai_prospects p ON p.id=r.prospect_id WHERE r.classification!='Auto-reply' GROUP BY r.prospect_id"):
                d=local_day(r['observed_at'])
                if d and start<=d<=end:
                    key=(d,r['channel']);entry=automatic.setdefault(key,dict(day=d,channel=key[1],sent=0,replies=0,interested=0,booked=0));entry['replies']+=1;entry['interested']+=r['interested']
            for r in con.execute("SELECT p.channel,b.created_at FROM crm_ai_prospects p JOIN crm_stats_bookings b ON b.lead_id=p.lead_id WHERE p.sent_at IS NOT NULL AND b.created_at>=p.sent_at"):
                d=local_day(r['created_at'])
                if d and start<=d<=end:
                    key=(d,r['channel']);automatic.setdefault(key,dict(day=d,channel=key[1],sent=0,replies=0,interested=0,booked=0))['booked']+=1
    totals={k:sum(d[k] for d in days.values()) for k in next(iter(days.values())) if k!='day'}
    totals['collected_usd']=round(totals['collected_usd'],2)
    return dict(days=list(reversed(list(days.values()))),totals=totals,outreach=outreach,automatic_outreach=sorted(automatic.values(),key=lambda r:(r['day'],r['channel']),reverse=True),discovery=discovery,timezone='Vancouver (UTC−7)')
