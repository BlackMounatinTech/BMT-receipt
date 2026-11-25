"""Sheet imports and persistent, one-company-at-a-time calling queues."""
import csv
import io
import re
import uuid
from datetime import date, datetime, timezone, timedelta
import crm_store as store


def schema(con):
    con.execute('''
      CREATE TABLE IF NOT EXISTS crm_call_lists (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)''')
    con.execute('''
      CREATE TABLE IF NOT EXISTS crm_call_items (
        list_id TEXT NOT NULL REFERENCES crm_call_lists(id),
        lead_id INTEGER NOT NULL REFERENCES crm_leads(id), position INTEGER NOT NULL,
        outcome TEXT, called_at TEXT, PRIMARY KEY(list_id,lead_id))
    ''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_call_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
        lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
        outcome TEXT NOT NULL, created_at TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_call_day_reset (
        day TEXT PRIMARY KEY, after_event_id INTEGER NOT NULL, reset_at TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_call_notes (
        lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id), text TEXT NOT NULL,
        version INTEGER NOT NULL, updated_at TEXT NOT NULL)''')


def record_event(con, key, lead_id, result, stamp):
    con.execute('INSERT OR IGNORE INTO crm_call_events(event_key,lead_id,outcome,created_at) VALUES(?,?,?,?)',
                (key,lead_id,result,stamp))


def call_counts(reset=False, instant=None):
    instant = instant or datetime.now(timezone.utc)
    local = instant.astimezone(timezone(timedelta(hours=-7)))
    day = local.date().isoformat()
    start = local.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat(timespec='seconds')
    end = (local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec='seconds')
    with store.connect() as con:
        schema(con)
        con.execute('BEGIN IMMEDIATE')
        # Recover calls already recorded by the first release, without counting DMs.
        for note in con.execute("SELECT id,lead_id,text,created_at FROM crm_notes WHERE text LIKE 'Phone: %'"):
            result=note['text'].split('\n',1)[0][7:]
            if result in ('Called','No answer','Not interested','Follow up'):
                record_event(con,'note:'+str(note['id']),note['lead_id'],result,note['created_at'])
        if reset:
            maximum=con.execute('SELECT COALESCE(MAX(id),0) FROM crm_call_events').fetchone()[0]
            con.execute('INSERT OR REPLACE INTO crm_call_day_reset VALUES(?,?,?)',(day,maximum,store.now()))
        marker=con.execute('SELECT after_event_id FROM crm_call_day_reset WHERE day=?',(day,)).fetchone()
        total=con.execute('SELECT COUNT(*) FROM crm_call_events').fetchone()[0]
        daily=con.execute('SELECT COUNT(*) FROM crm_call_events WHERE created_at>=? AND created_at<? AND id>?',
                          (start,end,marker[0] if marker else 0)).fetchone()[0]
    return dict(total=total,today=daily,day=day)


def pipeline_counts():
    """Count booked companies (including wins) and successful closes, excluding losses."""
    with store.connect() as con:
        row = con.execute("""SELECT
            SUM(CASE WHEN status='Call booked' OR (status='Won' AND booked_at IS NOT NULL) THEN 1 ELSE 0 END) AS booked,
            SUM(CASE WHEN status='Won' THEN 1 ELSE 0 END) AS closes
            FROM crm_leads""").fetchone()
    return dict(booked=row['booked'] or 0, closes=row['closes'] or 0)


def phone_key(value):
    digits = re.sub(r'\D', '', value)
    return digits[1:] if len(digits) == 11 and digits.startswith('1') else digits


def rows_from_file(file):
    if file.filename.lower().endswith('.xlsx'):
        from openpyxl import load_workbook
        # XLSX is a ZIP container. Bound expanded size before loading it.
        import zipfile
        raw = file.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 25_000_000:
                raise ValueError('This workbook is too large. Export the lead tab as CSV.')
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            rows = []
            for row in book.active.iter_rows(values_only=True):
                rows.append(list(row[:40]))
                if len(rows) > 5100:
                    raise ValueError('Import up to 5,000 leads at a time.')
        finally:
            book.close()
    elif file.filename.lower().endswith('.csv'):
        rows = list(csv.reader(io.StringIO(file.read().decode('utf-8-sig'))))
    else:
        raise ValueError('Upload a CSV or XLSX lead sheet.')
    aliases = {
        'company': ['company', 'company name', 'business', 'business name'],
        'phone': ['phone', 'phone number', 'number', 'telephone'],
        'email': ['email', 'email address'], 'contact': ['contact', 'contact name', 'owner'],
        'location': ['location', 'city state', 'city, state'],
        'need': ['notes', 'need', 'research', 'research notes'],
        'website': ['website', 'website url'], 'call_zone': ['time zone', 'timezone', 'call zone'],
    }
    for header_index, row in enumerate(rows[:20]):
        headers = [str(v or '').strip().lower() for v in row]
        mapping = {key: next((headers.index(v) for v in names if v in headers), None)
                   for key, names in aliases.items()}
        if mapping['company'] is not None and mapping['phone'] is not None:
            break
    else:
        raise ValueError('The sheet needs Company and Phone number columns. Use the first tab for XLSX.')
    clean = []
    for number, row in enumerate(rows[header_index+1:], header_index+2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        item = {key: str(row[index] or '').strip() if index is not None and index < len(row) else ''
                for key, index in mapping.items()}
        if not item['company'] or not 7 <= len(phone_key(item['phone'])) <= 15:
            raise ValueError(f'Row {number}: add a company and valid phone number.')
        if any(len(v) > 10000 for v in item.values()):
            raise ValueError(f'Row {number}: one of the fields is too long.')
        if item['call_zone'] and item['call_zone'] not in ('Eastern','Central','Mountain','Pacific (US)','Arizona','Vancouver'):
            raise ValueError(f'Row {number}: use Eastern, Central, Mountain, Pacific (US), Arizona or Vancouver for the time zone.')
        clean.append(item)
    if not 1 <= len(clean) <= 5000:
        raise ValueError('Import between 1 and 5,000 leads.')
    return clean


def import_list(name, rows, commit=False):
    name = (name or 'Imported leads').strip()[:200]
    with store.connect() as con:
        schema(con)
        if commit:
            con.execute('BEGIN IMMEDIATE')
        existing = [dict(r) for r in con.execute('SELECT * FROM crm_leads')]
        phones = {phone_key(r['phone']): r for r in existing if phone_key(r['phone'])}
        names = {(r['company'].strip().casefold(), r['location'].strip().casefold()): r for r in existing}
        emails = {r['email'].strip().casefold(): r for r in existing if r['email'].strip()}
        seen = set()
        summary = dict(new=0, existing=0, duplicates=0, excluded=0, total=0)
        list_id = uuid.uuid4().hex
        if commit:
            con.execute('INSERT INTO crm_call_lists VALUES(?,?,?)', (list_id,name,store.now()))
        for item in rows:
            key = phone_key(item['phone'])
            name_key = (item['company'].casefold(), item['location'].casefold())
            email_key = item['email'].casefold()
            match = phones.get(key) or names.get(name_key) or (emails.get(email_key) if email_key else None)
            # Company identity and phone checks apply within the file too.
            identity = match['id'] if match else key
            if identity in seen:
                summary['duplicates'] += 1
                continue
            seen.add(identity)
            if match and match['status'] in ('Won','Lost','Call booked'):
                summary['excluded'] += 1
                continue
            summary['existing' if match else 'new'] += 1
            summary['total'] += 1
            if not commit:
                sentinel = match or dict(id=key,status='New')
                phones[key] = sentinel
                names[name_key] = sentinel
                if email_key: emails[email_key] = sentinel
                continue
            if match:
                lead_id = match['id']
            else:
                notes = item['need'] + ('\nWebsite: '+item['website'] if item['website'] else '')
                lead_id = con.execute('''INSERT INTO crm_leads
                  (company,phone,email,contact,location,need,stage,call_zone,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,'Cold',?,?,?)''',
                  (item['company'],item['phone'],item['email'],item['contact'],item['location'],notes.strip(),
                   item['call_zone'] or None,store.now(),store.now())).lastrowid
                record = dict(id=lead_id,status='New')
                phones[key] = record
                names[name_key] = record
                if email_key: emails[email_key] = record
                # Remember both the initial key and the database identity.
                seen.add(lead_id)
            con.execute('INSERT INTO crm_call_items VALUES(?,?,?,NULL,NULL)', (list_id,lead_id,summary['total']))
        if not summary['total']:
            raise ValueError('No callable leads remain. Won, lost and already-booked leads are excluded.')
    return dict(**summary, list_id=list_id if commit else None, name=name)


def lists():
    with store.connect() as con:
        schema(con)
        return [dict(r) for r in con.execute('''SELECT l.*, COUNT(i.lead_id) AS total,
            SUM(CASE WHEN i.outcome IS NOT NULL THEN 1 ELSE 0 END) AS completed
            FROM crm_call_lists l LEFT JOIN crm_call_items i ON i.list_id=l.id
            GROUP BY l.id ORDER BY l.created_at DESC, l.rowid DESC''')]


def items(list_id):
    with store.connect() as con:
        schema(con)
        return [dict(r) for r in con.execute('''SELECT l.*,i.position,i.outcome,i.called_at,
            COALESCE(n.text,(SELECT SUBSTR(text,INSTR(text,CHAR(10))+1) FROM crm_notes
                WHERE lead_id=l.id AND text LIKE 'Phone: %' AND INSTR(text,CHAR(10))>0 ORDER BY id DESC LIMIT 1),'') AS call_notes,
            COALESCE(n.version,0) AS note_version
            FROM crm_call_items i JOIN crm_leads l ON l.id=i.lead_id
            LEFT JOIN crm_call_notes n ON n.lead_id=l.id
            WHERE i.list_id=? ORDER BY i.position''', (list_id,))]


def save_notes(lead_id, text, version):
    if not isinstance(text,str) or len(text)>10000 or type(version) is not int:
        raise ValueError('Check the call notes and refresh if needed.')
    with store.connect() as con:
        schema(con)
        con.execute('BEGIN IMMEDIATE')
        if not con.execute('SELECT 1 FROM crm_leads WHERE id=?',(lead_id,)).fetchone():
            raise ValueError('Lead not found.')
        previous=con.execute('SELECT * FROM crm_call_notes WHERE lead_id=?',(lead_id,)).fetchone()
        current_version=previous['version'] if previous else 0
        # A retry after a lost response is safe, including a keepalive on navigation.
        if previous and previous['text']==text:
            return dict(version=current_version,text=text)
        if current_version!=version:
            raise store.Conflict('These call notes changed in another session. Your draft is kept in this browser. Refresh and review before replacing them.')
        con.execute('INSERT OR REPLACE INTO crm_call_notes VALUES(?,?,?,?)',
                    (lead_id,text,current_version+1,store.now()))
        return dict(version=current_version+1,text=text)


def outcome(list_id, lead_id, revision, result, note='', follow_up=None):
    if result not in ('Called','No answer','Not interested','Follow up'):
        raise ValueError('Choose a call outcome.')
    if not isinstance(note,str) or len(note)>10000:
        raise ValueError('Check the call notes.')
    follow_up = follow_up or None
    if result == 'Follow up':
        if follow_up:
            date.fromisoformat(follow_up)
    with store.connect() as con:
        schema(con)
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM crm_leads WHERE id=?', (lead_id,)).fetchone()
        item = con.execute('SELECT * FROM crm_call_items WHERE list_id=? AND lead_id=?',(list_id,lead_id)).fetchone()
        if not row or not item or row['revision'] != revision:
            raise store.Conflict('This lead changed. Refresh before recording the call.')
        if row['status'] in ('Won','Lost','Call booked'):
            raise ValueError('This lead is already closed or booked. Open the lead to review it.')
        from crm_booking import schema as booking_schema
        booking_schema(con)
        if con.execute("SELECT 1 FROM crm_booking_jobs WHERE lead_id=? AND state!='abandoned'",(lead_id,)).fetchone():
            raise ValueError('Review the existing booking before recording another call outcome.')
        status = {'Not interested':'Lost','Follow up':'Follow-up'}.get(result,'Contacted')
        stamp = store.now()
        con.execute('''UPDATE crm_leads SET status=?,follow_up=?,last_contacted_at=?,
            contact_method='Phone',updated_at=?,revision=revision+1 WHERE id=?''',
            (status,follow_up if result=='Follow up' else None,stamp,stamp,lead_id))
        con.execute('UPDATE crm_call_items SET outcome=?,called_at=? WHERE list_id=? AND lead_id=?',
                    (result,stamp,list_id,lead_id))
        note_id=con.execute('INSERT INTO crm_notes(lead_id,author,text,created_at) VALUES(?,?,?,?)',
                    (lead_id,'Michael','Phone: '+result+ ('\n'+note.strip() if note.strip() else ''),stamp)).lastrowid
        record_event(con,'note:'+str(note_id),lead_id,result,stamp)

