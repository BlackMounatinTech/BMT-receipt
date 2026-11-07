"""Small persistent warm-lead store, separate from legacy profile and booking data."""
import os
import sqlite3
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
    }.items():
        if name not in columns:
            try:
                con.execute(f'ALTER TABLE crm_leads ADD COLUMN {name} {definition}')
            except sqlite3.OperationalError:
                if name not in {r['name'] for r in con.execute('PRAGMA table_info(crm_leads)')}:
                    raise
    con.commit()
    try:
        with con:
            yield con
    finally:
        con.close()


def list_leads():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM crm_leads ORDER BY created_at DESC, id DESC')]


def add_lead(company, contact='', phone='', email='', need='', follow_up=None):
    if not company.strip():
        raise ValueError('Enter the company name.')
    if not phone.strip() and not email.strip():
        raise ValueError('Add a phone number or email so the closer can contact them.')
    stamp = now()
    with connect() as con:
        cursor = con.execute('''INSERT INTO crm_leads
            (company,contact,phone,email,need,follow_up,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)''',
            (company.strip(), contact.strip(), phone.strip(), email.strip(), need.strip(), follow_up, stamp, stamp))
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
                follow_up=None, call_date=None, call_time=None, call_zone=None, note='', author='Closer', zoom_url=None):
    if not company.strip() or (not phone.strip() and not email.strip()):
        raise ValueError('Company name and a phone number or email are required.')
    if status not in STATUSES:
        raise ValueError('Choose a valid status.')
    if status == 'Call booked' and not call_date:
        raise ValueError('Add the date for the booked call.')
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute('SELECT * FROM crm_leads WHERE id=?', (lead_id,)).fetchone()
        if not previous or previous['revision'] != revision:
            raise Conflict('This lead changed in another session. Refresh the list before saving again.')
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
        if booking_changed:
            con.execute('''UPDATE crm_leads SET booking_version=booking_version+1,
                confirmation_sent_at=NULL,confirmed_at=NULL,reminder_sent_at=NULL,booked_at=? WHERE id=?''', (now() if start else None,lead_id))
        if note.strip():
            con.execute('INSERT INTO crm_notes (lead_id,author,text,created_at) VALUES (?,?,?,?)',
                        (lead_id,author,note.strip(),now()))


def counts(leads, today):
    active = [r for r in leads if r['status'] not in ('Won','Lost')]
    return {
        'new': sum(not r['seen_at'] for r in active),
        'due': sum(bool(r['follow_up']) and r['follow_up'] <= today for r in active),
        'booked': sum(r['status'] == 'Call booked' for r in active),
    }
