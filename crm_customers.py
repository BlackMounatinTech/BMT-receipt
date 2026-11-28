"""Customer profiles, sale confirmation, documents and manually recorded results."""
import json
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
import crm_store as store

PAYMENT_LINKS = {
    '50% deposit': 'https://buy.stripe.com/3cI28rcNq7qO6mLdif3cc0g',
    'Full upfront': 'https://buy.stripe.com/eVqaEX9BeeTg7qPdif3cc0h',
}
FIELDS=['contract_url','invoice_url','payment_url','payment_reference','payment_plan','paid_at',
        'notes','results_from','results_to','ad_spend','qualified_leads','quotes_sent','jobs_won','job_revenue']


def schema(con):
    con.executescript('''CREATE TABLE IF NOT EXISTS crm_customer_profiles (
        lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id),data TEXT NOT NULL,
        revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS crm_customer_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,lead_id INTEGER NOT NULL REFERENCES crm_leads(id),
        kind TEXT NOT NULL,filename TEXT NOT NULL,mime TEXT NOT NULL,body BLOB NOT NULL,created_at TEXT NOT NULL);''')


def customer(con,lead_id):
    row=con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
    if not row: raise LookupError('Company not found.')
    if row['status']!='Won': raise ValueError('This company is not a customer. Confirm their purchase after the sales call first.')
    return dict(row)


def list_customers():
    return [l for l in store.list_leads() if l['status']=='Won']


def read(lead_id):
    with store.connect() as con:
        schema(con);lead=customer(con,lead_id)
        row=con.execute('SELECT * FROM crm_customer_profiles WHERE lead_id=?',(lead_id,)).fetchone()
        profile=json.loads(row['data']) if row else {}
        docs=[dict(r) for r in con.execute('SELECT id,kind,filename,created_at FROM crm_customer_documents WHERE lead_id=? ORDER BY id DESC',(lead_id,))]
        calls=0
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_call_events'").fetchone():
            calls=con.execute('SELECT COUNT(*) FROM crm_call_events WHERE lead_id=?',(lead_id,)).fetchone()[0]
        onboard=None
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_onboarding'").fetchone():
            r=con.execute('SELECT data,updated_at FROM crm_onboarding WHERE lead_id=?',(lead_id,)).fetchone()
            if r: onboard={'data':json.loads(r['data']),'updated_at':r['updated_at']}
        discovery=None
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_sales_call_facts'").fetchone() and 'answers' in {r[1] for r in con.execute('PRAGMA table_info(crm_sales_call_facts)')}:
            sales=con.execute('SELECT answers FROM crm_sales_call_facts WHERE lead_id=?',(lead_id,)).fetchone()
            if sales:discovery=json.loads(sales['answers'])
        return dict(discovery=discovery,lead=lead,data=profile,revision=row['revision'] if row else 0,
                    updated_at=row['updated_at'] if row else None,documents=docs,calls=calls,onboarding=onboard)


def validate(data):
    if not isinstance(data,dict) or set(data)-set(FIELDS): raise ValueError('Check the customer profile fields.')
    for k,v in data.items():
        if not isinstance(v,str) or len(v)>10000: raise ValueError('Check '+k+'.')
        if v and k.endswith('_url'):
            p=urlparse(v)
            if p.scheme not in ('http','https') or not p.netloc: raise ValueError('Use a full web link.')
        if v and k in ('paid_at','results_from','results_to'):date.fromisoformat(v)
        if v and k in ('ad_spend','qualified_leads','quotes_sent','jobs_won','job_revenue'):
            n=float(v)
            if not math.isfinite(n) or n<0 or (k in ('qualified_leads','quotes_sent','jobs_won') and not n.is_integer()):raise ValueError('Use valid nonnegative results.')
    if data.get('results_from') and data.get('results_to') and data['results_from']>data['results_to']:raise ValueError('Results end date must follow the start date.')
    if data.get('payment_plan') and data['payment_plan'] not in PAYMENT_LINKS:raise ValueError('Choose a payment option.')


def save(lead_id,p):
    data=p.get('data');validate(data)
    if type(p.get('revision')) is not int:raise ValueError('Reload before saving.')
    with store.connect() as con:
        schema(con);con.execute('BEGIN IMMEDIATE');customer(con,lead_id)
        row=con.execute('SELECT revision FROM crm_customer_profiles WHERE lead_id=?',(lead_id,)).fetchone()
        revision=row['revision'] if row else 0
        if revision!=p['revision']:raise store.Conflict('Profile changed elsewhere. Close and reopen it before saving.')
        con.execute('''INSERT INTO crm_customer_profiles VALUES (?,?,?,?) ON CONFLICT(lead_id)
            DO UPDATE SET data=excluded.data,revision=excluded.revision,updated_at=excluded.updated_at''',
            (lead_id,json.dumps(data),revision+1,store.now()))
    return read(lead_id)


def confirm_sale(lead_id,p):
    if p.get('payment_received') is not True or p.get('contract_signed') is not True:
        raise ValueError('Confirm the signed contract and received payment first.')
    plan=p.get('payment_plan')
    if plan not in PAYMENT_LINKS:raise ValueError('Choose the payment option they purchased.')
    if type(p.get('revision')) is not int:raise ValueError('Refresh the company record.')
    with store.connect() as con:
        schema(con);con.execute('BEGIN IMMEDIATE')
        lead=con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
        if not lead:raise LookupError('Company not found.')
        if lead['revision']!=p['revision']:raise store.Conflict('Company changed elsewhere. Refresh and try again.')
        if lead['status']=='Won':raise ValueError('This company is already a customer.')
        stamp=store.now()
        existing=con.execute('SELECT * FROM crm_customer_profiles WHERE lead_id=?',(lead_id,)).fetchone()
        data=json.loads(existing['data']) if existing else {}
        data.update(payment_plan=plan,payment_url=PAYMENT_LINKS[plan],paid_at=datetime.now(ZoneInfo("America/Vancouver")).date().isoformat())
        con.execute('''INSERT INTO crm_customer_profiles VALUES (?,?,?,?) ON CONFLICT(lead_id)
            DO UPDATE SET data=excluded.data,revision=excluded.revision,updated_at=excluded.updated_at''',
            (lead_id,json.dumps(data),(existing['revision'] if existing else 0)+1,stamp))
        con.execute("UPDATE crm_leads SET status='Won',updated_at=?,revision=revision+1 WHERE id=?",(stamp,lead_id))
        con.execute('INSERT INTO crm_notes (lead_id,author,text,created_at) VALUES (?,?,?,?)',
            (lead_id,'Michael','Purchase confirmed by operator: signed contract and '+plan+' payment received. Moved to Customers.',stamp))
    return read(lead_id)


def attach(lead_id,kind,upload):
    if kind not in ('Contract','Invoice','Other'):raise ValueError('Choose a document type.')
    body=upload.read(4_000_001)
    if not body or len(body)>4_000_000:raise ValueError('Choose a document under 4 MB.')
    mime='application/pdf' if body.startswith(b'%PDF-') else 'image/png' if body.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if body.startswith(b'\xff\xd8\xff') else None
    if not mime:raise ValueError('Upload a PDF, PNG, or JPEG document.')
    name=secure_filename(upload.filename or 'document')[:180] or 'document'
    with store.connect() as con:
        schema(con);customer(con,lead_id)
        con.execute('INSERT INTO crm_customer_documents (lead_id,kind,filename,mime,body,created_at) VALUES (?,?,?,?,?,?)',
                    (lead_id,kind,name,mime,body,store.now()))
    return read(lead_id)


def document(lead_id,doc_id):
    with store.connect() as con:
        schema(con);customer(con,lead_id)
        row=con.execute('SELECT * FROM crm_customer_documents WHERE id=? AND lead_id=?',(doc_id,lead_id)).fetchone()
        if not row:raise LookupError('Document not found.')
        return dict(row)
