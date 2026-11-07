"""Appointment times, confirmation emails and a persistent reminder queue."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
import crm_store as store

ZONES = {'Eastern':'America/New_York','Central':'America/Chicago','Mountain':'America/Denver',
         'Pacific (US)':'America/Los_Angeles','Arizona':'America/Phoenix'}

def start_time(day, clock, zone):
    if not day or not clock:
        raise ValueError('Add a date and time for the appointment.')
    local = None
    for fmt in ['%Y-%m-%d %H:%M','%Y-%m-%d %I:%M %p','%Y-%m-%d %I %p']:
        try:
            local = datetime.strptime(day+' '+clock.strip().upper(), fmt)
            break
        except ValueError:
            pass
    if local is None:
        raise ValueError('Enter a valid appointment time.')
    if zone != 'Vancouver' and zone not in ZONES:
        raise ValueError('Choose the customer’s time zone.')
    tz = timezone(timedelta(hours=-7)) if zone == 'Vancouver' else ZoneInfo(ZONES[zone])
    aware = local.replace(tzinfo=tz)
    utc = aware.astimezone(timezone.utc)
    if utc.astimezone(tz).replace(tzinfo=None) != local:
        raise ValueError('That time falls in a daylight-saving clock change. Choose another time.')
    return utc.isoformat(timespec='seconds')

def valid_zoom(url):
    if url:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in url):
            raise ValueError('Use the full Zoom link, starting with https://.')

def preview(lead, kind='confirmation'):
    if lead['status'] != 'Call booked' or not lead['call_start_utc']:
        raise ValueError('Save the appointment date, time and customer time zone first.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',lead['email']):
        raise ValueError('Add the customer’s email before sending.')
    if not lead['zoom_url']:
        raise ValueError('Add the Zoom link before sending.')
    valid_zoom(lead['zoom_url'])
    zone = lead['call_zone']
    tz = timezone(timedelta(hours=-7)) if zone == 'Vancouver' else ZoneInfo(ZONES[zone])
    when = datetime.fromisoformat(lead['call_start_utc']).astimezone(tz)
    stamp = when.strftime('%A, %B %-d at %-I:%M %p') + ' (' + zone + ' time)'
    reminder = kind == 'reminder'
    subject = ('Reminder: ' if reminder else 'Your BMT call — ') + when.strftime('%b %-d at %-I:%M %p') + ' ' + zone
    body = (f"Hi {lead['contact'] or 'there'},\n\n" +
            ('A quick reminder about our call.\n\n' if reminder else 'Great speaking with you. Here are the details for our call:\n\n') +
            f"Date and time: {stamp}\nLength: 30 minutes\nZoom link: {lead['zoom_url']}\n\n" +
            "We’ll walk through your website and social media, and how BMT can help your business.\n\n" +
            ('' if lead['confirmed_at'] else 'Please reply “confirmed” so we know you received this.\n\n') +
            'If you need to change the time, just reply to this email.\n\nMichael\nBlack Mountain Technologies')
    return dict(to=lead['email'],subject=subject,body=body)

def messages_table(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_appointment_messages (
        lead_id INTEGER NOT NULL, booking_version INTEGER NOT NULL, kind TEXT NOT NULL,
        state TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY(lead_id,booking_version,kind))''')

def send(lead_id, version, kind='confirmation', sender=None, retry=False):
    # Claim once before contacting SMTP. An interrupted send is never automatically retried.
    with store.connect() as con:
        messages_table(con)
        lead = con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
        if not lead or lead['booking_version'] != version:
            raise store.Conflict('This appointment changed. Reopen it before sending.')
        if datetime.fromisoformat(lead['call_start_utc'] or '2000-01-01T00:00:00+00:00') <= datetime.now(timezone.utc):
            raise ValueError('Choose a future appointment time before sending.')
        message = preview(dict(lead),kind)
        existing = con.execute('SELECT state FROM crm_appointment_messages WHERE lead_id=? AND booking_version=? AND kind=?',(lead_id,version,kind)).fetchone()
        if existing and not (existing['state'] == 'failed' and retry):
            raise ValueError('This email was already sent or attempted. Check its status before trying again.')
        if existing:
            claim = con.execute("UPDATE crm_appointment_messages SET state='sending',error=NULL,updated_at=? WHERE lead_id=? AND booking_version=? AND kind=? AND state='failed'",(store.now(),lead_id,version,kind))
        else:
            claim = con.execute('INSERT OR IGNORE INTO crm_appointment_messages VALUES(?,?,?,\'sending\',NULL,?)',(lead_id,version,kind,store.now()))
        if claim.rowcount != 1:
            raise ValueError('This email is already being sent.')
    if sender is None:
        from tools.email_sender import send_email
        sender = send_email
    try:
        result = sender(message['to'],message['subject'],message['body'])
    except Exception:
        result = {'ok':False}
    with store.connect() as con:
        messages_table(con)
        con.execute('UPDATE crm_appointment_messages SET state=?,error=?,updated_at=? WHERE lead_id=? AND booking_version=? AND kind=?',
                    ('sent' if result.get('ok') else 'failed',None if result.get('ok') else 'Email delivery failed. Check the sender settings.',store.now(),lead_id,version,kind))
        if result.get('ok'):
            column = 'confirmation_sent_at' if kind == 'confirmation' else 'reminder_sent_at'
            con.execute(f'UPDATE crm_leads SET {column}=? WHERE id=? AND booking_version=?',(store.now(),lead_id,version))
    if not result.get('ok'):
        raise ValueError('Email delivery failed. Your appointment is saved. Check the sender settings before retrying.')
    return {'ok':True}

def run_reminders(sender=None, now=None):
    now = now or datetime.now(timezone.utc)
    for lead in store.list_leads():
        if lead['status'] != 'Call booked' or not lead['call_start_utc'] or not lead['confirmation_sent_at'] or lead['reminder_sent_at']:
            continue
        start = datetime.fromisoformat(lead['call_start_utc'])
        due = start-timedelta(hours=24)
        # If booked inside 24 hours, the confirmation already contains the link.
        if due <= now < start and datetime.fromisoformat(lead['confirmation_sent_at']) <= due:
            try:
                send(lead['id'],lead['booking_version'],'reminder',sender)
            except (ValueError,store.Conflict):
                pass
