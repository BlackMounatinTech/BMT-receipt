"""Read-only, evidence-backed company research queued for the connected Mac worker."""
import json,uuid
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse
import crm_store as store

PHOTO_STATES=('verified','unavailable','not_found')

def schema(con):
 con.execute('''CREATE TABLE IF NOT EXISTS crm_booked_research (
  id TEXT PRIMARY KEY,lead_id INTEGER NOT NULL REFERENCES crm_leads(id),state TEXT NOT NULL,
  requested_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,heartbeat TEXT,phase TEXT NOT NULL DEFAULT '',
  report TEXT,baseline TEXT NOT NULL,error TEXT)''')
 con.execute('CREATE TABLE IF NOT EXISTS crm_booked_research_worker(id INTEGER PRIMARY KEY,last_seen TEXT NOT NULL)')

def company(con,lid,booked_only=False):
 r=con.execute('SELECT * FROM crm_leads WHERE id=?',(lid,)).fetchone()
 if not r:raise LookupError('Company not found.')
 if r['is_test'] or (booked_only and r['status']!='Call booked') or r['status'] not in ('Call booked','Won') or not r['call_start_utc']:raise ValueError('Choose a company from Booked.')
 return dict(r)

def public(job):
 return {**{k:job[k] for k in ('id','lead_id','state','requested_at','started_at','finished_at','phase','error')},'report':json.loads(job['report']) if job['report'] else None}

def status(lid):
 with store.connect() as con:
  schema(con);company(con,lid)
  row=con.execute('SELECT * FROM crm_booked_research WHERE lead_id=? ORDER BY requested_at DESC,rowid DESC LIMIT 1',(lid,)).fetchone()
  done=con.execute("SELECT * FROM crm_booked_research WHERE lead_id=? AND report IS NOT NULL ORDER BY finished_at DESC,rowid DESC LIMIT 1",(lid,)).fetchone()
  worker=con.execute('SELECT last_seen FROM crm_booked_research_worker WHERE id=1').fetchone()
  online=bool(worker and datetime.now(timezone.utc)-datetime.fromisoformat(worker['last_seen'])<timedelta(minutes=3))
  return dict(job=public(row) if row else None,report=json.loads(done['report']) if done else None,
   checked_at=done['finished_at'] if done else None,worker_online=online)

def request(lid):
 from crm_sales_call import read
 facts=read(lid)['data']
 with store.connect() as con:
  schema(con);con.execute('BEGIN IMMEDIATE');company(con,lid,booked_only=True)
  active=con.execute("SELECT * FROM crm_booked_research WHERE lead_id=? AND state IN ('queued','running') ORDER BY requested_at DESC LIMIT 1",(lid,)).fetchone()
  if not active:
   con.execute("INSERT INTO crm_booked_research(id,lead_id,state,requested_at,phase,baseline) VALUES(?,?,'queued',?,'Waiting for Mac worker',?)",(uuid.uuid4().hex,lid,store.now(),json.dumps(facts)))
 return status(lid)

def text(value,limit=2000):
 if not isinstance(value,str) or len(value)>limit:raise ValueError('Check the research text.')
 return value.strip()

def url(value):
 value=text(value)
 p=urlparse(value)
 if value and (p.scheme not in ('http','https') or not p.netloc or p.username or p.password):raise ValueError('Use a public source link.')
 return value

def checked(value,start):
 text(value,100)
 try:t=datetime.fromisoformat(value.replace('Z','+00:00'))
 except ValueError:raise ValueError('Add the actual time the source was checked.')
 if t.tzinfo is None or t<datetime.fromisoformat(start)-timedelta(minutes=2) or t>datetime.now(timezone.utc)+timedelta(minutes=2):raise ValueError('Source time must be from this research run.')
 return value

def strings(value,limit=30):
 if not isinstance(value,list) or len(value)>limit:raise ValueError('Check the research list.')
 return [text(x) for x in value]

def validate(report,started):
 if not isinstance(report,dict) or not {'company','facebook','ads','google','talking_points'}<=set(report) or set(report)-{'company','facebook','instagram','ads','google','talking_points'}:raise ValueError('Include company details, Facebook project photos, Meta ads and Google reputation.')
 if len(json.dumps(report))>50000:raise ValueError('Keep the research brief concise.')
 c=report['company']
 if not isinstance(c,dict):raise ValueError('Check the company research.')
 c={k:text(c.get(k,'')) for k in ('location','identity_notes')}|{k:strings(c.get(k,[])) for k in ('services','service_areas')}
 sources=report['company'].get('sources',[])
 if not isinstance(sources,list) or not sources:raise ValueError('Include company identity sources.')
 c['sources']=[dict(url=url(s.get('url','')),checked_at=checked(s.get('checked_at',''),started),observation=text(s.get('observation',''))) for s in sources]
 if not c['identity_notes'] or not all(s['url'] and s['observation'] for s in c['sources']):raise ValueError('Explain how the company identity was matched.')
 result={'company':c}
 for channel in ('facebook',):
  p=report[channel]
  if not isinstance(p,dict) or p.get('status') not in PHOTO_STATES:raise ValueError('Check the photo research status.')
  seen=p.get('usable_photos_seen');reviewed=p.get('photos_reviewed')
  if p['status']=='verified':
   if type(seen) is not int or type(reviewed) is not int or not 0<=seen<=reviewed<=200:raise ValueError('Use actual observed photo counts.')
   bucket='20+' if seen>=20 else '10+' if seen>=10 else '5+' if seen>=5 else '1–4' if seen else '0'
  else:seen=reviewed=None;bucket='Unknown'
  before=p.get('before_after','unverified')
  if before not in ('yes','no','unverified') or (p['status']!='verified' and before!='unverified'):raise ValueError('Do not assert unverified before-and-after photos.')
  source=url(p.get('source_url',''));notes=text(p.get('notes',''))
  if not notes or (p['status']=='verified' and not source):raise ValueError('Add the photo source and what was actually observed.')
  if p['status']=='verified' and (urlparse(source).hostname or '').removeprefix('www.').removeprefix('m.') not in (('facebook.com',) if channel=='facebook' else ('instagram.com',)):raise ValueError('Photo counts need a source on the matching social platform.')
  result[channel]=dict(status=p['status'],photo_bucket=bucket,usable_photos_seen=seen,photos_reviewed=reviewed,before_after=before,source_url=source,notes=notes,checked_at=checked(p.get('checked_at',''),started))
 a=report['ads']
 if not isinstance(a,dict) or a.get('status') not in ('running','none_found','unverified'):raise ValueError('Check the ad status.')
 source=url(a.get('source_url',''));ids=strings(a.get('ad_ids',[]));notes=text(a.get('notes',''))
 if not notes or (a['status']!='unverified' and not source) or (a['status']=='running' and not ids):raise ValueError('Active ads need an Ads Library source and ad IDs.')
 if a['status']!='unverified' and ((urlparse(source).hostname or '').removeprefix('www.')!='facebook.com' or '/ads/library' not in urlparse(source).path):raise ValueError('Use the Meta Ads Library source for ad verification.')
 result['ads']=dict(status=a['status'],source_url=source,ad_ids=ids,notes=notes,checked_at=checked(a.get('checked_at',''),started))
 g=report['google']
 if not isinstance(g,dict) or g.get('status') not in ('verified','unverified'):raise ValueError('Check the Google profile status.')
 rating=g.get('rating');reviews=g.get('reviews');quality=g.get('profile_quality','Unverified');source=url(g.get('source_url',''));notes=text(g.get('notes',''))
 if quality not in ('Strong','Some gaps','Unverified'):raise ValueError('Check the profile assessment.')
 if g['status']=='verified':
  if type(reviews) is not int or reviews<0 or (reviews and (type(rating) not in (int,float) or not 1<=rating<=5)) or not source:raise ValueError('Use the verified Google rating, count and profile URL.')
  if not reviews:rating=None
 else:rating=reviews=None;quality='Unverified'
 if not notes:raise ValueError('Explain the profile assessment or access limitation.')
 result['google']=dict(status=g['status'],rating=rating,reviews=reviews,profile_quality=quality,source_url=source,notes=notes,checked_at=checked(g.get('checked_at',''),started))
 result['talking_points']=strings(report['talking_points'],10)
 return result

def worker(p):
 if not isinstance(p,dict):raise ValueError('Provide a research action.')
 op=p.get('op');now=datetime.now(timezone.utc);stamp=store.now()
 with store.connect() as con:
  schema(con);con.execute('BEGIN IMMEDIATE')
  con.execute('INSERT OR REPLACE INTO crm_booked_research_worker VALUES(1,?)',(stamp,))
  # Expired work is shown as interrupted, never silently completed or re-run.
  con.execute("UPDATE crm_booked_research SET state='interrupted',error='Mac research stopped before completion. Review and request another check.',finished_at=? WHERE state='running' AND started_at<?",(stamp,(now-timedelta(minutes=22)).isoformat()))
  if op=='heartbeat':return dict(ok=True)
  if op=='claim':
   if con.execute("SELECT 1 FROM crm_booked_research WHERE state='running'").fetchone():return dict(job=None)
   row=con.execute("SELECT * FROM crm_booked_research WHERE state='queued' ORDER BY requested_at,rowid LIMIT 1").fetchone()
   if not row:return dict(job=None)
   try:lead=company(con,row['lead_id'],booked_only=True)
   except (ValueError,LookupError):
    con.execute("UPDATE crm_booked_research SET state='cancelled',finished_at=?,phase='Company is no longer booked' WHERE id=?",(stamp,row['id']));return dict(job=None)
   con.execute("UPDATE crm_booked_research SET state='running',started_at=?,heartbeat=?,phase='Checking company identity' WHERE id=?",(stamp,stamp,row['id']))
   return dict(job=dict(id=row['id'],lead_id=row['lead_id'],company=lead['company'],contact=lead['contact'],location=lead['location'],phone=lead['phone'],website=lead['website'],research=lead['need'],started_at=stamp,work_minutes=15))
  row=con.execute('SELECT * FROM crm_booked_research WHERE id=?',(p.get('job_id'),)).fetchone()
  if not row or row['state']!='running':raise ValueError('This research job is not running.')
  if op=='progress':
   con.execute('UPDATE crm_booked_research SET phase=?,heartbeat=? WHERE id=?',(text(p.get('phase',''),200),stamp,row['id']));return dict(ok=True)
  if op=='fail':
   con.execute("UPDATE crm_booked_research SET state='blocked',error=?,finished_at=?,phase='Research needs attention' WHERE id=?",(text(p.get('reason','Could not inspect sources.')),stamp,row['id']));return dict(ok=True)
  if op!='finish':raise ValueError('Choose a valid research action.')
  report=validate(p.get('report'),row['started_at'])
  partial=any(report[k]['status'] in ('unavailable','unverified') for k in ('facebook','ads','google'))
  from crm_sales_call import schema as facts_schema
  facts_schema(con)
  facts=con.execute('SELECT * FROM crm_sales_call_facts WHERE lead_id=?',(row['lead_id'],)).fetchone()
  current=json.loads(facts['data']) if facts else {};baseline=json.loads(row['baseline']);updates={}
  if report['company']['services']:updates['services']=', '.join(report['company']['services'])[:2000]
  if report['company']['service_areas']:updates['service_areas']=', '.join(report['company']['service_areas'])[:2000]
  g=report['google']
  if g['status']=='verified':updates['google_reviews']=f'{g["rating"]:g} stars from {g["reviews"]} reviews' if g['rating'] is not None else '0 reviews'
  photos=[report[k] for k in ('facebook',) if report[k]['status']=='verified']
  if any(x['before_after']=='yes' for x in photos):updates['project_photos']='Before-and-after photos verified'
  elif any(x['usable_photos_seen'] for x in photos):updates['project_photos']='Completed-project photos verified'
  for k,v in updates.items():
   if current.get(k,'')==baseline.get(k,''):current[k]=v
  current['sources']=('Research checked '+stamp+'\n'+'\n'.join(x['url'] for x in report['company']['sources'])+'\n'+current.get('sources',''))[:2000]
  if facts:con.execute('UPDATE crm_sales_call_facts SET data=?,revision=revision+1,updated_at=? WHERE lead_id=?',(json.dumps(current),stamp,row['lead_id']))
  else:con.execute("INSERT INTO crm_sales_call_facts(lead_id,data,revision,updated_at,answers) VALUES(?,?,1,?,'{}')",(row['lead_id'],json.dumps(current),stamp))
  con.execute('UPDATE crm_booked_research SET state=?,phase=?,report=?,finished_at=?,heartbeat=? WHERE id=?',('partial' if partial else 'complete','Research saved',json.dumps(report),stamp,stamp,row['id']))
 return dict(ok=True)
