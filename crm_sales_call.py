"""Saved company facts for the live sales-call opening."""
import json
import crm_store as store

FIELDS=('services','service_areas','google_reviews','project_photos','sources')

def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_sales_call_facts (
        lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id),
        data TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)''')
    if 'answers' not in {r[1] for r in con.execute('PRAGMA table_info(crm_sales_call_facts)')}:
        con.execute("ALTER TABLE crm_sales_call_facts ADD COLUMN answers TEXT NOT NULL DEFAULT '{}'")

def read(lead_id):
    with store.connect() as con:
        schema(con)
        lead=con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
        if not lead:raise LookupError('Prospect not found.')
        row=con.execute('SELECT * FROM crm_sales_call_facts WHERE lead_id=?',(lead_id,)).fetchone()
        call_notes=con.execute('SELECT text FROM crm_call_notes WHERE lead_id=?',(lead_id,)).fetchone() if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_call_notes'").fetchone() else None
        return dict(call_notes=call_notes['text'] if call_notes else '',lead=dict(lead),history=[dict(n) for n in con.execute('SELECT text,created_at FROM crm_notes WHERE lead_id=? ORDER BY id',(lead_id,))],lead_id=lead_id,company=lead['company'],location=lead['location'],contact=lead['contact'],
            phone=lead['phone'],email=lead['email'],website=lead['website'],research=lead['need'],call_start_utc=lead['call_start_utc'],
            lead_timezone=lead['lead_timezone'],call_zone=lead['call_zone'],status=lead['status'],
            answers=json.loads(row['answers']) if row else {},
            data=json.loads(row['data']) if row else {key:'' for key in FIELDS},
            revision=row['revision'] if row else 0,updated_at=row['updated_at'] if row else None)

def save(lead_id,payload):
    if not isinstance(payload,dict) or type(payload.get('revision')) is not int:raise ValueError('Refresh the company facts before saving.')
    from crm_sales_questions import validate
    answers=validate(payload['answers']) if 'answers' in payload else None
    data=payload.get('data')
    if not isinstance(data,dict) or set(data)-set(FIELDS):raise ValueError('Check the company facts.')
    if any(not isinstance(v,str) or len(v)>2000 for v in data.values()):raise ValueError('Keep each company fact under 2,000 characters.')
    clean={key:data.get(key,'').strip() for key in FIELDS}
    if clean['project_photos'] not in ('','Before-and-after photos verified','Completed-project photos verified','No project photos found'):raise ValueError('Choose the project-photo status.')
    with store.connect() as con:
        schema(con);con.execute('BEGIN IMMEDIATE')
        lead=con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
        if not lead:raise LookupError('Prospect not found.')
        if lead['is_test'] or lead['status'] not in ('Call booked','Won') or not lead['call_start_utc']:raise ValueError('Choose a prospect from Booked.')
        row=con.execute('SELECT revision,answers FROM crm_sales_call_facts WHERE lead_id=?',(lead_id,)).fetchone()
        rev=row['revision'] if row else 0
        if rev!=payload['revision']:raise store.Conflict('These company facts changed elsewhere. Reload before saving.')
        con.execute('INSERT OR REPLACE INTO crm_sales_call_facts(lead_id,data,revision,updated_at,answers) VALUES(?,?,?,?,?)',
            (lead_id,json.dumps(clean),rev+1,store.now(),json.dumps(answers) if answers is not None else row['answers'] if row else '{}'))
    return read(lead_id)
