"""Durable Zoom → Calendar → confirmation workflow; no provider secrets in the UI."""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import requests
import crm_store as store
from crm_appointments import start_time


class ProviderError(ValueError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def hosts():
    try:
        default = [{'id':'michael','name':'Michael','email':'michael@blackmountaintechnologies.ca',
                    'zoom_user':'michael@blackmountaintechnologies.ca','calendar_id':'michael@blackmountaintechnologies.ca'}]
        configured = json.loads(os.environ.get('BMT_BOOKING_HOSTS',json.dumps(default)))
        if not isinstance(configured,list): raise ValueError()
        result = []
        for h in configured:
            if not all(isinstance(h.get(k),str) and h[k].strip() for k in ('id','name','email','zoom_user','calendar_id')):
                raise ValueError()
            result.append({k:h[k].strip() for k in ('id','name','email','zoom_user','calendar_id')})
        if len({h['id'] for h in result}) != len(result): raise ValueError()
        return result
    except (ValueError,TypeError,AttributeError):
        return []


def connection_status():
    from tools.email_sender import is_configured, _smtp_user
    zoom = all(os.environ.get(k) for k in ('ZOOM_ACCOUNT_ID','ZOOM_CLIENT_ID','ZOOM_CLIENT_SECRET'))
    google = all(os.environ.get(k) for k in ('GOOGLE_CALENDAR_CLIENT_ID','GOOGLE_CALENDAR_CLIENT_SECRET','GOOGLE_CALENDAR_REFRESH_TOKEN'))
    email = is_configured()
    configured_hosts = hosts()
    return dict(zoom=zoom,google=google,email=email,sender=_smtp_user(),hosts=configured_hosts,
                ready=bool(zoom and google and email and configured_hosts))


def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_booking_jobs (
      id TEXT PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
      payload TEXT NOT NULL, state TEXT NOT NULL, busy INTEGER NOT NULL DEFAULT 0,
      zoom_id TEXT, zoom_url TEXT, event_id TEXT, event_url TEXT, error TEXT,
      updated_at TEXT NOT NULL)''')


def get_job(job_id):
    with store.connect() as con:
        schema(con)
        row = con.execute('SELECT * FROM crm_booking_jobs WHERE id=?',(job_id,)).fetchone()
        if not row: raise ValueError('Booking not found.')
        return dict(row)


def save_job(job_id, **fields):
    with store.connect() as con:
        schema(con)
        con.execute('UPDATE crm_booking_jobs SET '+','.join(k+'=?' for k in fields)+',updated_at=? WHERE id=?',
                    (*fields.values(),store.now(),job_id))


def public_job(job):
    details = json.loads(job['payload'])
    return {**{k:job[k] for k in ('id','lead_id','state','zoom_url','event_url','error','busy')},
            'start':details['start'],'host':details['host']['name']}


def request_json(method, url, *, mutation=False, **kwargs):
    try:
        response = requests.request(method,url,timeout=25,**kwargs)
    except requests.RequestException:
        raise ProviderError('Provider connection interrupted. '+('Check the provider before trying again.' if mutation else 'Try again.'),uncertain=mutation)
    if response.status_code >= 400:
        raise ProviderError('Provider rejected the request. Check account permissions and connection settings.',
                            uncertain=mutation and response.status_code >= 500)
    try:
        return response.json()
    except ValueError:
        raise ProviderError('Provider returned an unreadable response. Check the provider before trying again.',uncertain=mutation)


class Providers:
    def __init__(self):
        self.google_token = None

    def google_headers(self):
        if not self.google_token:
            result = request_json('POST','https://oauth2.googleapis.com/token',data={
                'grant_type':'refresh_token','client_id':os.environ.get('GOOGLE_CALENDAR_CLIENT_ID'),
                'client_secret':os.environ.get('GOOGLE_CALENDAR_CLIENT_SECRET'),
                'refresh_token':os.environ.get('GOOGLE_CALENDAR_REFRESH_TOKEN')})
            self.google_token = result['access_token']
        return {'Authorization':'Bearer '+self.google_token}

    def free(self, details):
        calendar_id = details['host']['calendar_id']
        result = request_json('POST','https://www.googleapis.com/calendar/v3/freeBusy',
            headers=self.google_headers(),json={'timeMin':details['start'],'timeMax':details['end'],
                                              'items':[{'id':calendar_id}]})
        calendar = result.get('calendars',{}).get(calendar_id,{})
        if 'busy' not in calendar or calendar.get('errors'):
            raise ProviderError('Cannot read the closer’s calendar. Check calendar access.')
        if calendar['busy']:
            raise ValueError('The closer is busy at that time. Choose a different slot.')

    def zoom(self, details):
        token = request_json('POST','https://zoom.us/oauth/token',
            auth=(os.environ.get('ZOOM_CLIENT_ID'),os.environ.get('ZOOM_CLIENT_SECRET')),
            data={'grant_type':'account_credentials','account_id':os.environ.get('ZOOM_ACCOUNT_ID')})
        result = request_json('POST','https://api.zoom.us/v2/users/'+quote(details['host']['zoom_user'],safe='')+'/meetings',
            mutation=True,headers={'Authorization':'Bearer '+token['access_token']},json={
                'topic':'BMT × '+details['company']+' — Online Presence Call','type':2,
                'start_time':details['start'],'duration':30,'timezone':'UTC',
                'settings':{'waiting_room':True,'join_before_host':False,'use_pmi':False}})
        if not result.get('id') or not result.get('join_url'):
            raise ProviderError('Zoom did not return meeting details. Check Zoom before retrying.',uncertain=True)
        return str(result['id']), result['join_url']

    def calendar(self, details, job_id, zoom_url):
        event_id = 'bmt'+job_id  # Google event IDs accept base32hex characters.
        url = 'https://www.googleapis.com/calendar/v3/calendars/'+quote(details['host']['calendar_id'],safe='')+'/events'
        # Recover an insert whose response was lost without creating a duplicate invitation.
        try:
            response = requests.get(url+'/'+event_id,headers=self.google_headers(),timeout=25)
        except requests.RequestException:
            raise ProviderError('Calendar connection interrupted. Try again.')
        if response.status_code == 200:
            event = response.json()
        elif response.status_code == 404:
            event = request_json('POST',url,mutation=True,headers=self.google_headers(),params={'sendUpdates':'all'},json={
                'id':event_id,'summary':'BMT × '+details['company']+' — Online Presence Call',
                'description':details['description']+'\n\nJoin Zoom: '+zoom_url+'\n\nTo reschedule, reply to the invitation.',
                'location':zoom_url,'start':{'dateTime':details['start']},'end':{'dateTime':details['end']},
                'attendees':[{'email':details['email']},{'email':details['host']['email']}],
                'guestsCanModify':False,'reminders':{'useDefault':True}})
        else:
            raise ProviderError('Cannot access the closer’s calendar. Check the Google connection.')
        return event_id,event.get('htmlLink','')


def create(lead_id, data):
    if not connection_status()['ready']:
        raise ValueError('Connect Zoom, Google Calendar and email, and add a meeting host before booking.')
    host = next((h for h in hosts() if h['id']==data.get('host_id')),None)
    if not host: raise ValueError('Choose a meeting host.')
    contact, email = data.get('contact','').strip(),data.get('email','').strip()
    if not contact or len(contact)>200 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>250:
        raise ValueError('Add the customer’s name and valid email.')
    start = start_time(data.get('date'),data.get('time'),data.get('zone'))
    instant = datetime.fromisoformat(start)
    if instant <= datetime.now(timezone.utc): raise ValueError('Choose a future appointment time.')
    note = data.get('note','')
    if not isinstance(note,str) or len(note)>10000: raise ValueError('Check the call notes.')
    with store.connect() as con:
        schema(con)
        con.execute('BEGIN IMMEDIATE')
        lead = con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
        if not lead or lead['revision'] != data.get('revision'):
            raise store.Conflict('This lead changed. Refresh before booking.')
        if lead['status'] in ('Call booked','Won','Lost'):
            raise ValueError('This lead is already booked or closed. Open the lead to review it.')
        if con.execute("SELECT 1 FROM crm_booking_jobs WHERE lead_id=? AND state NOT IN ('complete','abandoned')",(lead_id,)).fetchone():
            raise ValueError('This lead already has a booking in progress. Resume it instead.')
        for row in con.execute('SELECT payload,state,lead_id FROM crm_booking_jobs'):
            if row['state']=='abandoned': continue
            if row['state']=='complete' and con.execute('SELECT status FROM crm_leads WHERE id=?',(row['lead_id'],)).fetchone()[0]!='Call booked':
                continue
            other = json.loads(row['payload'])
            if other['host']['id']==host['id'] and abs((datetime.fromisoformat(other['start'])-instant).total_seconds())<1800:
                raise ValueError('That closer already has a CRM booking in this slot.')
        for row in con.execute("SELECT call_start_utc FROM crm_leads WHERE status='Call booked' AND call_start_utc IS NOT NULL AND id NOT IN (SELECT lead_id FROM crm_booking_jobs WHERE state!='abandoned')"):
            if abs((datetime.fromisoformat(row['call_start_utc'])-instant).total_seconds())<1800:
                raise ValueError('An existing CRM appointment occupies that slot. Choose a different time.')
        details = dict(company=lead['company'],contact=contact,email=email,host=host,start=start,
            end=(instant+timedelta(minutes=30)).isoformat(timespec='seconds'),zone=data['zone'],
            date=data['date'],time=data['time'],note=note,list_id=data.get('list_id'),
            description='A 30-minute call with Black Mountain Technologies to discuss your online presence, project photos and how we can help showcase your work.')
        job_id = uuid.uuid4().hex
        con.execute('INSERT INTO crm_booking_jobs(id,lead_id,payload,state,updated_at) VALUES(?,?,?,\'pending\',?)',
                    (job_id,lead_id,json.dumps(details),store.now()))
        if details.get('list_id'):
            from crm_calling import schema as calling_schema, record_event
            calling_schema(con)
            if not con.execute('SELECT 1 FROM crm_call_items WHERE list_id=? AND lead_id=?',(details['list_id'],lead_id)).fetchone():
                raise ValueError('This lead is not in the selected calling list.')
            record_event(con,f"booking:{details['list_id']}:{lead_id}:{lead['revision']}",lead_id,'Book meeting',store.now())
    return resume(job_id)


def resume(job_id, provider=None, sender=None):
    with store.connect() as con:
        schema(con)
        con.execute('BEGIN IMMEDIATE')
        job = con.execute('SELECT * FROM crm_booking_jobs WHERE id=?',(job_id,)).fetchone()
        if not job: raise ValueError('Booking not found.')
        if job['state']=='complete': return public_job(dict(job))
        if job['state']=='abandoned': raise ValueError('This draft was abandoned. Start a new booking.')
        if job['busy'] or job['state']=='review':
            raise ValueError('This booking needs provider review before another attempt. Check Zoom, Calendar and Sent mail.')
        con.execute('UPDATE crm_booking_jobs SET busy=1,error=NULL WHERE id=?',(job_id,))
    job = dict(job)
    details = json.loads(job['payload'])
    provider = provider or Providers()
    try:
        if not job['zoom_id']:
            provider.free(details)
            # A process crash after this point must not automatically create another Zoom meeting.
            save_job(job_id,state='creating_zoom')
            meeting_id, zoom_url = provider.zoom(details)
            save_job(job_id,zoom_id=meeting_id,zoom_url=zoom_url,state='zoom_created')
            job.update(zoom_id=meeting_id,zoom_url=zoom_url)
        if not job['event_id']:
            save_job(job_id,state='creating_calendar')
            event_id,event_url = provider.calendar(details,job_id,job['zoom_url'])
            save_job(job_id,event_id=event_id,event_url=event_url,state='calendar_created')
        # Only now is this a booked appointment. Invitation sending failures remain visible.
        with store.connect() as con:
            lead = con.execute('SELECT * FROM crm_leads WHERE id=?',(job['lead_id'],)).fetchone()
            if lead['zoom_url'] != job['zoom_url'] or lead['status'] != 'Call booked':
                con.execute('''UPDATE crm_leads SET contact=?,email=?,status='Call booked',stage='Prospect',
                    call_date=?,call_time=?,call_zone=?,call_start_utc=?,zoom_url=?,
                    booking_version=booking_version+1,confirmation_sent_at=NULL,confirmed_at=NULL,
                    reminder_sent_at=NULL,booked_at=?,updated_at=?,revision=revision+1 WHERE id=?''',
                    (details['contact'],details['email'],details['date'],details['time'],details['zone'],details['start'],
                     job['zoom_url'],store.now(),store.now(),job['lead_id']))
                con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',
                    (job['lead_id'],'Michael','Meeting booked with '+details['host']['name']+
                     ('\n'+details['note'] if details['note'] else ''),store.now()))
            version = con.execute('SELECT booking_version FROM crm_leads WHERE id=?',(job['lead_id'],)).fetchone()[0]
            if details.get('list_id'):
                from crm_calling import schema as calling_schema
                calling_schema(con)
                con.execute("UPDATE crm_call_items SET outcome='Booked',called_at=? WHERE list_id=? AND lead_id=?",
                            (store.now(),details['list_id'],job['lead_id']))
        save_job(job_id,state='sending_confirmation')
        from crm_appointments import send
        with store.connect() as con:
            sent = con.execute('SELECT confirmation_sent_at FROM crm_leads WHERE id=?',(job['lead_id'],)).fetchone()[0]
        if not sent:
            send(job['lead_id'],version,sender=sender,retry=True)
        save_job(job_id,state='complete',busy=0,error=None)
    except Exception as exc:
        current = get_job(job_id)
        state = 'review' if isinstance(exc,ProviderError) and exc.uncertain and current['state']=='creating_zoom' else 'failed'
        if current['state']=='sending_confirmation': state='confirmation_failed'
        safe = str(exc) if isinstance(exc,(ValueError,store.Conflict)) else 'Booking interrupted. Check the provider connection.'
        save_job(job_id,state=state,busy=0,error=safe)
    return public_job(get_job(job_id))


def abandon(job_id):
    """Only release a draft known not to have created any external artifacts."""
    with store.connect() as con:
        schema(con)
        changed=con.execute("UPDATE crm_booking_jobs SET state='abandoned',updated_at=? WHERE id=? AND state='failed' AND busy=0 AND zoom_id IS NULL AND event_id IS NULL",(store.now(),job_id))
        if changed.rowcount!=1:
            raise ValueError('This booking may already have a meeting. Review it before changing anything.')
