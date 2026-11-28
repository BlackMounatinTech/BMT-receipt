"""Operator-controlled payment email, onboarding booking and close package."""
import hashlib,json,re,uuid,tempfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
import crm_store as store
from crm_customers import PAYMENT_LINKS

SENDER='michael@blackmountaintechnologies.ca'
DEFAULT_CONTRACT=Path(__file__).with_name('crm_documents')/'BMT_Marketing_Services_Agreement.pdf'
FIELDS={'email','payment_plan','payment_reference','payment_confirmed','host_id','date','time','zone'}

def schema(con):
 con.execute('''CREATE TABLE IF NOT EXISTS crm_sales_close (
  lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id),data TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL)''')
 con.execute('''CREATE TABLE IF NOT EXISTS crm_sales_documents (
  lead_id INTEGER NOT NULL REFERENCES crm_leads(id),kind TEXT NOT NULL,filename TEXT NOT NULL,body BLOB NOT NULL,
  updated_at TEXT NOT NULL,PRIMARY KEY(lead_id,kind))''')
 con.execute('''CREATE TABLE IF NOT EXISTS crm_sales_messages (
  lead_id INTEGER NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,updated_at TEXT NOT NULL,
  PRIMARY KEY(lead_id,kind,digest))''')
 con.execute('''CREATE TABLE IF NOT EXISTS crm_sales_onboarding_jobs (
  lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id),id TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,
  busy INTEGER NOT NULL DEFAULT 0,zoom_id TEXT,zoom_url TEXT,event_id TEXT,event_url TEXT,error TEXT,updated_at TEXT NOT NULL)''')

def eligible(con,lid):
 l=con.execute('SELECT * FROM crm_leads WHERE id=?',(lid,)).fetchone()
 if not l:raise LookupError('Company not found.')
 if l['is_test'] or l['status'] not in ('Call booked','Won') or not l['call_start_utc']:raise ValueError('Choose a booked prospect or their customer record.')
 return dict(l)

def prospect_zone(lead):
 from crm_appointments import ZONES
 aliases={'America/Boise':'America/Denver','America/Menominee':'America/Chicago'}
 zone=aliases.get(lead.get('lead_timezone'),lead.get('lead_timezone'))
 return next((label for label,iana in {**ZONES,'Vancouver':'Etc/GMT+7'}.items() if iana==zone),None) or (lead.get('call_zone') if lead.get('call_zone') in [*ZONES,'Vancouver'] else '')

def documents(con,lid):
 docs=[dict(x) for x in con.execute('SELECT * FROM crm_sales_documents WHERE lead_id=? ORDER BY kind',(lid,))]
 if not any(d['kind']=='Contract' for d in docs) and DEFAULT_CONTRACT.is_file():
  docs.append(dict(lead_id=lid,kind='Contract',filename=DEFAULT_CONTRACT.name,body=DEFAULT_CONTRACT.read_bytes(),updated_at='',default=True))
 return sorted(docs,key=lambda d:d['kind'])

def read(lid):
 from crm_booking import hosts
 with store.connect() as con:
  schema(con);l=eligible(con,lid);r=con.execute('SELECT * FROM crm_sales_close WHERE lead_id=?',(lid,)).fetchone()
  data=json.loads(r['data']) if r else {};data.setdefault('email',l['email']);data['zone']=prospect_zone(l);data.setdefault('host_id','michael')
  docs=[{k:v for k,v in d.items() if k!='body'} for d in documents(con,lid)]
  job=con.execute('SELECT * FROM crm_sales_onboarding_jobs WHERE lead_id=?',(lid,)).fetchone()
  meeting=None
  if job and job['state']=='complete':data['zone']=json.loads(job['payload'])['zone']
  if job:
   meeting={k:job[k] for k in ('state','zoom_url','event_url','error','busy')};meeting.update(json.loads(job['payload']))
  messages=[dict(x) for x in con.execute('SELECT kind,state,updated_at FROM crm_sales_messages WHERE lead_id=? ORDER BY updated_at',(lid,))]
  return dict(lead_id=lid,company=l['company'],contact=l['contact'],customer=l['status']=='Won',data=data,
   revision=r['revision'] if r else 0,documents=docs,meeting=meeting,messages=messages,hosts=hosts())

def save(lid,p):
 from crm_appointments import ZONES
 if not isinstance(p,dict) or type(p.get('revision')) is not int:raise ValueError('Reload the close details before saving.')
 data=p.get('data')
 if not isinstance(data,dict) or set(data)-FIELDS:raise ValueError('Check the close details.')
 if any(not isinstance(v,str) or len(v)>1000 for v in data.values()):raise ValueError('Check the close fields.')
 if data.get('payment_plan','') not in ['',*PAYMENT_LINKS]:raise ValueError('Choose a payment option.')
 if data.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',data['email']):raise ValueError('Enter a valid customer email.')
 if data.get('zone') and data['zone'] not in [*ZONES,'Vancouver']:raise ValueError('Choose a valid time zone.')
 # Payment confirmation is set only by the explicit confirmation endpoint.
 if 'payment_confirmed' in data:raise ValueError('Use Confirm payment after checking Stripe.')
 with store.connect() as con:
  schema(con);con.execute('BEGIN IMMEDIATE');lead=eligible(con,lid)
  known_zone=prospect_zone(lead)
  booked=con.execute("SELECT payload FROM crm_sales_onboarding_jobs WHERE lead_id=? AND state='complete'",(lid,)).fetchone()
  if known_zone or booked:data={**data,'zone':json.loads(booked['payload'])['zone'] if booked else known_zone}
  r=con.execute('SELECT * FROM crm_sales_close WHERE lead_id=?',(lid,)).fetchone();rev=r['revision'] if r else 0
  if rev!=p['revision']:raise store.Conflict('Close details changed elsewhere. Reload before saving.')
  old=json.loads(r['data']) if r else {}
  if old.get('payment_confirmed') and data.get('payment_plan',old.get('payment_plan'))!=old.get('payment_plan'):raise ValueError('Payment was confirmed for the saved plan. Keep that payment option.')
  old.update({k:v.strip() for k,v in data.items()})
  con.execute('INSERT OR REPLACE INTO crm_sales_close VALUES(?,?,?,?)',(lid,json.dumps(old),rev+1,store.now()))
 return read(lid)

def sync_documents(con,lid):
 if con.execute("SELECT status FROM crm_leads WHERE id=?",(lid,)).fetchone()[0]!='Won':return
 for doc in documents(con,lid):
  kind='Invoice' if doc['kind']=='Receipt' else 'Contract'
  if not con.execute('SELECT 1 FROM crm_customer_documents WHERE lead_id=? AND kind=? AND filename=? AND body=?',(lid,kind,doc['filename'],doc['body'])).fetchone():
   con.execute('INSERT INTO crm_customer_documents(lead_id,kind,filename,mime,body,created_at) VALUES(?,?,?,?,?,?)',(lid,kind,doc['filename'],'application/pdf',doc['body'],store.now()))

def upload(lid,kind,file):
 if kind not in ('Contract','Receipt'):raise ValueError('Choose Contract or Receipt.')
 body=file.read(4_000_001)
 if not body or len(body)>4_000_000 or not body.startswith(b'%PDF-'):raise ValueError('Choose a PDF under 4 MB.')
 name=secure_filename(file.filename or kind+'.pdf')[:150]
 if not name.lower().endswith('.pdf'):name+='.pdf'
 with store.connect() as con:
  schema(con);eligible(con,lid)
  from crm_customers import schema as customer_schema
  customer_schema(con);con.execute('BEGIN IMMEDIATE')
  paid=con.execute('SELECT data FROM crm_sales_close WHERE lead_id=?',(lid,)).fetchone()
  if kind=='Receipt' and (not paid or not json.loads(paid['data']).get('payment_confirmed')):raise ValueError('Confirm the received payment before attaching its Stripe receipt.')
  if con.execute("SELECT 1 FROM crm_sales_messages WHERE lead_id=? AND state='sending'",(lid,)).fetchone():raise ValueError('Wait for the current email before replacing attachments.')
  con.execute('INSERT OR REPLACE INTO crm_sales_documents VALUES(?,?,?,?,?)',(lid,kind,name,body,store.now()))
  sync_documents(con,lid)
 return read(lid)

def document(lid,kind):
 with store.connect() as con:
  schema(con);eligible(con,lid)
  doc=next((d for d in documents(con,lid) if d['kind']==kind),None)
  if not doc:raise LookupError('Document not found.')
  return doc


def confirm_payment(lid,p):
 import crm_customers
 if not isinstance(p,dict) or p.get('payment_received') is not True:raise ValueError('Check the payment in Stripe, then confirm it here.')
 if type(p.get('revision')) is not int:raise ValueError('Reload the close details.')
 with store.connect() as con:
  schema(con);crm_customers.schema(con);con.execute('BEGIN IMMEDIATE');l=eligible(con,lid)
  r=con.execute('SELECT * FROM crm_sales_close WHERE lead_id=?',(lid,)).fetchone()
  if not r or r['revision']!=p['revision']:raise store.Conflict('Save or reload the close details first.')
  data=json.loads(r['data'])
  if data.get('payment_confirmed'):return read_after_commit(con,lid)
  if data.get('payment_plan') not in PAYMENT_LINKS or not data.get('payment_reference'):raise ValueError('Save the payment option and Stripe payment reference first.')
  # Customer promotion and payment confirmation share one transaction.
  old=con.execute('SELECT * FROM crm_customer_profiles WHERE lead_id=?',(lid,)).fetchone();profile=json.loads(old['data']) if old else {}
  stamp=store.now();profile.update(payment_plan=data['payment_plan'],payment_url=PAYMENT_LINKS[data['payment_plan']],payment_reference=data['payment_reference'],paid_at=datetime.now(ZoneInfo('Etc/GMT+7')).date().isoformat())
  profile['notes']=(profile.get('notes','')+'\nPayment checked in Stripe by operator. Contract awaiting signature.').strip()
  con.execute('INSERT OR REPLACE INTO crm_customer_profiles VALUES(?,?,?,?)',(lid,json.dumps(profile),(old['revision'] if old else 0)+1,stamp))
  con.execute("UPDATE crm_leads SET status='Won',email=?,updated_at=?,revision=revision+1 WHERE id=?",(data.get('email',l['email']),stamp,lid))
  con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',(lid,'Michael','Payment confirmed by operator in Stripe: '+data['payment_plan']+'. Customer created; contract awaiting signature.',stamp))
  sync_documents(con,lid)
  data['payment_confirmed']=stamp
  con.execute('UPDATE crm_sales_close SET data=?,revision=revision+1,updated_at=? WHERE lead_id=?',(json.dumps(data),stamp,lid))
 return read(lid)

def read_after_commit(con,lid):
 con.commit();return read(lid)

def preview(lid,kind):
 if kind not in ('payment','package'):raise ValueError('Choose the email type.')
 current=read(lid);d=current['data'];to=d.get('email','')
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',to):raise ValueError('Save a valid recipient email first.')
 plan=d.get('payment_plan');amount=1500 if plan=='50% deposit' else 3000
 if plan not in PAYMENT_LINKS:raise ValueError('Choose and save the payment option first.')
 name=current['contact'] or 'there';docs=[]
 if kind=='payment':
  subject='Your Black Mountain Technologies payment link'
  body=f'Hey {name},\n\nHere is the payment link for your $3,000 USD advertising package'+(' — 50% deposit' if amount==1500 else '')+f':\n{PAYMENT_LINKS[plan]}\n\nAmount due now: ${amount:,} USD.\nAd spend is paid separately to Meta.\n\nYou can complete this while we are on the call. Let me know if you have any trouble.\n\nMichael\nBlack Mountain Technologies\nhttps://blackmountaintech.ca'
 else:
  if not d.get('payment_confirmed'):raise ValueError('Confirm the payment in Stripe first.')
  meeting=current['meeting']
  if not meeting or meeting['state']!='complete':raise ValueError('Book the onboarding call before sending the package.')
  with store.connect() as con:docs=documents(con,lid)
  if {x['kind'] for x in docs}!={'Contract','Receipt'}:raise ValueError('Attach the contract and actual payment receipt as PDFs first.')
  when=datetime.fromisoformat(meeting['start']).astimezone(ZoneInfo(meeting['timezone']))
  stamp=when.strftime('%A, %B %-d, %Y at %-I:%M %p')+' ('+meeting['zone']+' time)'
  subject='Your BMT receipt, contract and onboarding call'
  body=f'Hey {name},\n\nThank you for your business. We received your ${amount:,} USD payment for {current["company"]}. Your payment receipt and advertising agreement are attached.\n\nPlease complete and sign the agreement, then reply to this email with the signed copy.\n\nOur onboarding call is on {stamp}.\nLength: 20 minutes.\n\nAt the time of our meeting, click this Zoom link to join:\n{meeting["zoom_url"]}\n\nWe will connect your accounts, confirm the projects and areas to advertise, and collect what we need to create and launch your ads.\n\nTo prepare, be on your computer, logged into Meta Business Suite, with access to your Facebook Page, Instagram account, ad account and verification device. Have your best project photos and videos ready. You will log in yourself and grant access during the call.\n\nPlease reply “confirm” so we know you received this. If you need to change the time, reply to this email.\n\nMichael\nBlack Mountain Technologies\nhttps://blackmountaintech.ca'
 signature=json.dumps([to,subject,body,[(x['kind'],hashlib.sha256(x['body']).hexdigest()) for x in docs]],sort_keys=True)
 digest=hashlib.sha256(signature.encode()).hexdigest()
 return dict(to=to,sender=SENDER,subject=subject,body=body,attachments=[{'kind':x['kind'],'filename':x['filename']} for x in docs],digest=digest)

def send(lid,kind,p,sender=None):
 if not isinstance(p,dict):raise ValueError('Review the email before sending.')
 m=preview(lid,kind)
 if p.get('digest')!=m['digest']:raise store.Conflict('The email changed. Preview it again before sending.')
 if sender is None:
  from tools.email_sender import send_email,_smtp_user
  if _smtp_user().lower()!=SENDER:raise ValueError('Configure Michael’s BMT email as the sender first.')
  sender=send_email
 with store.connect() as con:
  schema(con);con.execute('BEGIN IMMEDIATE')
  if preview(lid,kind)['digest']!=m['digest']:raise store.Conflict('The email changed. Preview it again.')
  if con.execute("SELECT 1 FROM crm_sales_messages WHERE lead_id=? AND kind=? AND state='sending'",(lid,kind)).fetchone():raise ValueError('A send is unresolved. Check Sent mail before trying again.')
  r=con.execute('SELECT state FROM crm_sales_messages WHERE lead_id=? AND kind=? AND digest=?',(lid,kind,m['digest'])).fetchone()
  if r and (r['state']=='sent' or p.get('reviewed_sent_mail') is not True):raise ValueError('Already sent or attempted. Check Sent mail before explicitly retrying.')
  con.execute("INSERT OR REPLACE INTO crm_sales_messages VALUES(?,?,?,'sending',?)",(lid,kind,m['digest'],store.now()))
 try:
  attachments=[]
  with tempfile.TemporaryDirectory() as tmp:
   for item in m['attachments']:
    doc=document(lid,item['kind']);path=Path(tmp)/(item['kind'].lower()+'-'+doc['filename']);path.write_bytes(doc['body']);attachments.append(path)
   result=sender(m['to'],m['subject'],m['body'],attachments=attachments)
  ok=bool(result.get('ok'))
 except Exception:ok=False
 with store.connect() as con:
  con.execute('UPDATE crm_sales_messages SET state=?,updated_at=? WHERE lead_id=? AND kind=? AND digest=?',('sent' if ok else 'review',store.now(),lid,kind,m['digest']))
 if not ok:raise ValueError('Delivery was not confirmed. Check Sent mail before using retry.')
 return read(lid)

def book(lid,p,provider=None):
 from crm_booking import Providers,ProviderError,connection_status,hosts
 from crm_appointments import start_time,ZONES
 if not isinstance(p,dict):raise ValueError('Save the onboarding details first.')
 if provider is None and not connection_status()['ready']:raise ValueError('Connect Zoom, Google Calendar and Michael’s email first.')
 current=read(lid)
 if type(p.get('revision')) is not int or p['revision']!=current['revision']:raise store.Conflict('The onboarding details changed. Save and review them before booking.')
 d=current['data'];host=next((h for h in hosts() if h['id']==d.get('host_id')),None)
 if not d.get('payment_confirmed') or not current['customer']:raise ValueError('Confirm the received payment first.')
 if not host:raise ValueError('Choose a meeting host.')
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',d.get('email','')):raise ValueError('Save a valid customer email.')
 start=start_time(d.get('date'),d.get('time'),d.get('zone'));instant=datetime.fromisoformat(start)
 if instant<=datetime.now(timezone.utc):raise ValueError('Choose a future onboarding time.')
 end=(instant+timedelta(minutes=20)).isoformat(timespec='seconds');tz='Etc/GMT+7' if d['zone']=='Vancouver' else ZONES[d['zone']]
 details=dict(company=current['company'],contact=current['contact'],email=d['email'],host=host,start=start,end=end,duration=20,zone=d['zone'],timezone=tz,silent_invite=True,description='A 20-minute onboarding call with Black Mountain Technologies to connect advertising accounts and prepare campaign launch.')
 with store.connect() as con:
  schema(con);con.execute('BEGIN IMMEDIATE');job=con.execute('SELECT * FROM crm_sales_onboarding_jobs WHERE lead_id=?',(lid,)).fetchone()
  if job:
   if job['state']=='complete':
    if json.loads(job['payload'])!=details:raise ValueError('Onboarding is already booked. Review the existing meeting before rescheduling.')
    return read_after_commit(con,lid)
   if job['busy'] or job['state']=='review':raise ValueError('Check Zoom and Calendar before retrying this booking.')
   if json.loads(job['payload'])!=details:raise ValueError('A booking attempt exists for the saved time. Restore those details to resume it.')
   con.execute('UPDATE crm_sales_onboarding_jobs SET busy=1 WHERE lead_id=?',(lid,));job=dict(job)
  else:
   reserved=[json.loads(x['payload']) for x in con.execute('SELECT payload FROM crm_sales_onboarding_jobs')]
   if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_booking_jobs'").fetchone():
    reserved += [json.loads(x['payload']) for x in con.execute("SELECT payload FROM crm_booking_jobs WHERE state!='abandoned'")]
   if any(x['host']['id']==host['id'] and x['start']<end and x['end']>start for x in reserved):raise ValueError('This host already has a CRM meeting at that time.')
   job=dict(lead_id=lid,id=uuid.uuid4().hex,payload=json.dumps(details),state='pending',busy=1,zoom_id=None,zoom_url=None,event_id=None,event_url=None)
   con.execute("INSERT INTO crm_sales_onboarding_jobs(lead_id,id,payload,state,busy,updated_at) VALUES(?,?,?,'pending',1,?)",(lid,job['id'],job['payload'],store.now()))
 def update(**values):
  with store.connect() as con:con.execute('UPDATE crm_sales_onboarding_jobs SET '+','.join(k+'=?' for k in values)+',updated_at=? WHERE lead_id=?',(*values.values(),store.now(),lid))
  job.update(values)
 provider=provider or Providers()
 try:
  if not job['zoom_id']:
   provider.free(details);update(state='creating_zoom');zid,url=provider.zoom(details);update(zoom_id=zid,zoom_url=url,state='zoom_created')
  if not job['event_id']:
   update(state='creating_calendar');eid,url=provider.calendar(details,job['id'],job['zoom_url']);update(event_id=eid,event_url=url,state='calendar_created')
  update(state='complete',busy=0,error=None)
 except Exception as e:
  state='review' if isinstance(e,ProviderError) and e.uncertain else 'failed'
  update(state=state,busy=0,error=str(e) if isinstance(e,ValueError) else 'Booking failed. Check Zoom and Calendar.')
 return read(lid)

def appointments():
 with store.connect() as con:
  schema(con);rows=con.execute("SELECT j.*,l.company,l.contact,l.phone,l.email FROM crm_sales_onboarding_jobs j JOIN crm_leads l ON l.id=j.lead_id WHERE j.state='complete'").fetchall()
  return [dict(id=r['lead_id'],company=r['company']+' · Onboarding',contact=r['contact'],phone=r['phone'],email=r['email'],call_start_utc=json.loads(r['payload'])['start'],duration_minutes=20,onboarding=True,zoom_url=r['zoom_url']) for r in rows]
