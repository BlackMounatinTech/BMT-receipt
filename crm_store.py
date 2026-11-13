"""Small persistent warm-lead store, separate from legacy profile and booking data."""
import os
import sqlite3
import hashlib
from urllib.parse import urlparse
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ['New', 'Contacted', 'Call booked', 'Follow-up', 'Won', 'Lost']


class Conflict(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connect():
    root = Path(os.environ.get('BMT_DATA_DIR', '/var/data' if os.environ.get('RENDER') else Path(__file__).parent / 'data'))
    if os.environ.get('RENDER') and not os.path.ismount(root):
        raise RuntimeError('The CRM requires the existing persistent disk at BMT_DATA_DIR.')
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / 'bmt_crm.sqlite3', timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
        CREATE TABLE IF NOT EXISTS crm_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            need TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'New',
            follow_up TEXT, call_date TEXT, call_time TEXT, call_zone TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            seen_at TEXT, seen_by TEXT, revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS crm_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
            author TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL
        );
    ''')
    columns = {r['name'] for r in con.execute('PRAGMA table_info(crm_leads)')}
    for name, definition in {
        'zoom_url': "TEXT NOT NULL DEFAULT ''", 'booking_version': 'INTEGER NOT NULL DEFAULT 0',
        'call_start_utc': 'TEXT', 'confirmation_sent_at': 'TEXT', 'confirmed_at': 'TEXT',
        'reminder_sent_at': 'TEXT', 'booked_at': 'TEXT',
        'stage': "TEXT NOT NULL DEFAULT 'Prospect'", 'instagram': "TEXT NOT NULL DEFAULT ''",
        'location': "TEXT NOT NULL DEFAULT ''", 'contact_method': "TEXT NOT NULL DEFAULT ''",
        'contact_account': "TEXT NOT NULL DEFAULT ''", 'last_contacted_at': 'TEXT',
    }.items():
        if name not in columns:
            try:
                con.execute(f'ALTER TABLE crm_leads ADD COLUMN {name} {definition}')
            except sqlite3.OperationalError:
                if name not in {r['name'] for r in con.execute('PRAGMA table_info(crm_leads)')}:
                    raise
    con.execute('''CREATE TABLE IF NOT EXISTS crm_outreach_events (
        event_key TEXT PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
        method TEXT NOT NULL, account TEXT NOT NULL, sent_at TEXT NOT NULL, message TEXT NOT NULL
    )''')
    con.commit()
    try:
        with con:
            yield con
    finally:
        con.close()


def list_leads():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM crm_leads ORDER BY created_at DESC, id DESC')]


def instagram_url(value):
    value = (value or '').strip()
    if not value:
        return ''
    parsed = urlparse(value)
    parts = parsed.path.strip('/').split('/')
    if parsed.scheme != 'https' or parsed.netloc.lower() not in ('instagram.com', 'www.instagram.com') or len(parts) != 1 or not parts[0] or not all(c.isascii() and (c.isalnum() or c in '._') for c in parts[0]):
        raise ValueError('Use the Instagram profile link, starting with https://www.instagram.com/.')
    return 'https://www.instagram.com/' + parts[0].lower() + '/'


def add_lead(company, contact='', phone='', email='', need='', follow_up=None, *,
             instagram='', location='', stage='Prospect', contact_method='', contact_account=''):
    if not company.strip():
        raise ValueError('Enter the company name.')
    instagram = instagram_url(instagram)
    if not phone.strip() and not email.strip() and not instagram:
        raise ValueError('Add a phone number, email or Instagram profile.')
    if stage not in ('Outreach', 'Prospect'):
        raise ValueError('Choose Outreach or Active prospect.')
    stamp = now()
    with connect() as con:
        cursor = con.execute('''INSERT INTO crm_leads
            (company,contact,phone,email,need,follow_up,created_at,updated_at,instagram,location,stage,contact_method,contact_account)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (company.strip(), contact.strip(), phone.strip(), email.strip(), need.strip(), follow_up, stamp, stamp,
             instagram,location.strip(),stage,contact_method.strip(),contact_account.strip()))
        return cursor.lastrowid


def mark_seen(lead_id, author):
    with connect() as con:
        stamp = now()
        con.execute('''UPDATE crm_leads SET seen_at=?,seen_by=?,updated_at=?,revision=revision+1
                       WHERE id=? AND seen_at IS NULL''', (stamp, author, stamp, lead_id))


def notes_for(lead_id):
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM crm_notes WHERE lead_id=? ORDER BY id DESC', (lead_id,))]


def update_lead(lead_id, revision, *, company, contact, phone, email, need, status,
                follow_up=None, call_date=None, call_time=None, call_zone=None, note='', author='Closer', zoom_url=None,
                instagram=None, location=None, stage=None, contact_method=None, contact_account=None):
    if not company.strip():
        raise ValueError('Company name is required.')
    if status not in STATUSES:
        raise ValueError('Choose a valid status.')
    if status == 'Call booked' and not call_date:
        raise ValueError('Add the date for the booked call.')
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute('SELECT * FROM crm_leads WHERE id=?', (lead_id,)).fetchone()
        if not previous or previous['revision'] != revision:
            raise Conflict('This lead changed in another session. Refresh the list before saving again.')
        instagram = previous['instagram'] if instagram is None else instagram_url(instagram)
        stage = previous['stage'] if stage is None else stage
        if status in ('Call booked', 'Won'):
            stage = 'Prospect'
        if stage not in ('Outreach', 'Prospect'):
            raise ValueError('Choose Outreach or Active prospect.')
        if not phone.strip() and not email.strip() and not instagram:
            raise ValueError('Add a phone number, email or Instagram profile.')
        zoom_url = previous['zoom_url'] if zoom_url is None else zoom_url.strip()
        from crm_appointments import start_time, valid_zoom
        valid_zoom(zoom_url)
        start = start_time(call_date, call_time, call_zone) if status == 'Call booked' and call_time else None
        if start:
            instant = datetime.fromisoformat(start)
            for other in con.execute("SELECT call_start_utc FROM crm_leads WHERE id != ? AND status='Call booked' AND call_start_utc IS NOT NULL",(lead_id,)):
                if abs((datetime.fromisoformat(other['call_start_utc'])-instant).total_seconds()) < 1800:
                    raise ValueError('Another appointment already occupies that 30-minute slot. Choose a different time.')
        booking_changed = any(previous[k] != v for k, v in [
            ('call_date',call_date),('call_time',call_time),('call_zone',call_zone),('zoom_url',zoom_url),('email',email.strip())
        ]) or ((previous['status'] == 'Call booked') != (status == 'Call booked'))
        result = con.execute('''UPDATE crm_leads SET company=?,contact=?,phone=?,email=?,need=?,status=?,
            follow_up=?,call_date=?,call_time=?,call_zone=?,updated_at=?,revision=revision+1
            WHERE id=? AND revision=?''',
            (company.strip(),contact.strip(),phone.strip(),email.strip(),need.strip(),status,
             follow_up,call_date,call_time,call_zone,now(),lead_id,revision))
        if result.rowcount != 1:
            raise Conflict('This lead changed in another session. Refresh the list before saving again.')
        con.execute('UPDATE crm_leads SET zoom_url=?,call_start_utc=? WHERE id=?', (zoom_url,start,lead_id))
        con.execute('UPDATE crm_leads SET instagram=?,location=?,stage=?,contact_method=?,contact_account=? WHERE id=?',
                    (instagram,previous['location'] if location is None else location.strip(),stage,
                     previous['contact_method'] if contact_method is None else contact_method.strip(),
                     previous['contact_account'] if contact_account is None else contact_account.strip(),lead_id))
        if booking_changed:
            con.execute('''UPDATE crm_leads SET booking_version=booking_version+1,
                confirmation_sent_at=NULL,confirmed_at=NULL,reminder_sent_at=NULL,booked_at=? WHERE id=?''', (now() if start else None,lead_id))
        if note.strip():
            con.execute('INSERT INTO crm_notes (lead_id,author,text,created_at) VALUES (?,?,?,?)',
                        (lead_id,author,note.strip(),now()))


def counts(leads, today):
    active = [r for r in leads if r['status'] not in ('Won','Lost') and r.get('stage', 'Prospect') != 'Outreach']
    return {
        'new': sum(not r['seen_at'] for r in active),
        'due': sum(bool(r['follow_up']) and r['follow_up'] <= today for r in active),
        'booked': sum(r['status'] == 'Call booked' for r in active),
    }


def import_instagram_contacts(records):
    """Record confirmed sends only. Retry-safe and does not send any messages."""
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError('Import between 1 and 100 confirmed sends.')
    clean = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid contact record.')
        fields = ['company', 'instagram', 'sender', 'confirmed_utc', 'message', 'location', 'focus']
        if any(not isinstance(record.get(k, ''), str) or len(record.get(k, '')) > 10000 for k in fields):
            raise ValueError('Invalid contact details.')
        if record.get('status') != 'sent' or not all(record.get(k, '').strip() for k in fields[:5]):
            raise ValueError('Only confirmed sends with company, profile, sender, date and message can be imported.')
        url = instagram_url(record['instagram'])
        stamp = datetime.fromisoformat(record['confirmed_utc'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Contact time must include the time zone.')
        sent_at = stamp.astimezone(timezone.utc).isoformat()
        key = hashlib.sha256((url+'\n'+sent_at+'\n'+record['message']).encode()).hexdigest()
        clean.append((record,url,sent_at,key))
    imported = skipped = created = 0
    ids = []
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for record,url,sent_at,key in clean:
            event = con.execute('SELECT lead_id FROM crm_outreach_events WHERE event_key=?',(key,)).fetchone()
            if event:
                skipped += 1
                ids.append(event['lead_id'])
                continue
            existing = con.execute('SELECT * FROM crm_leads WHERE instagram=?',(url,)).fetchone()
            if existing:
                lead_id = existing['id']
            else:
                cursor = con.execute('''INSERT INTO crm_leads
                    (company,instagram,location,need,status,stage,contact_method,contact_account,
                     last_contacted_at,created_at,updated_at)
                    VALUES (?,?,?,?,'Contacted','Outreach','Instagram DM',?,?,?,?)''',
                    (record['company'].strip(),url,record.get('location',''),
                     'Outreach focus: '+record.get('focus','Website and social media'),
                     record['sender'],sent_at,now(),now()))
                lead_id = cursor.lastrowid
                created += 1
            con.execute('INSERT INTO crm_outreach_events VALUES (?,?,?,?,?,?)',
                        (key,lead_id,'Instagram DM',record['sender'],sent_at,record['message']))
            note = 'Instagram DM sent from @'+record['sender']+'\n'+sent_at+'\n'+url+'\n\n'+record['message']
            if record.get('automatic_reply'):
                note += '\n\nAutomatic office-hours reply received. No buying interest confirmed.'
            con.execute('INSERT INTO crm_notes (lead_id,author,text,created_at) VALUES (?,?,?,?)',
                        (lead_id,'Michael',note,sent_at))
            if not existing or not existing['last_contacted_at'] or sent_at > existing['last_contacted_at']:
                con.execute('UPDATE crm_leads SET last_contacted_at=?,contact_method=?,contact_account=?,updated_at=?,revision=revision+1 WHERE id=?',
                            (sent_at,'Instagram DM',record['sender'],now(),lead_id))
            ids.append(lead_id)
            imported += 1
    return dict(imported=imported,created=created,skipped=skipped,lead_ids=ids)
