"""Per-customer onboarding worksheets on the CRM's existing persistent disk."""
import json
from datetime import date
import crm_store as store


def field(key, label, prompt, section, options=None, kind='text'):
    return dict(key=key, label=label, prompt=prompt, section=section,
                type='choice' if options else kind, options=options or [])


FIELDS = [
    field('contact', 'Main contact', 'Who will be our main contact?', '1. Confirm the plan'),
    field('email', 'Contact email', 'Which email should we use?', '1. Confirm the plan', kind='email'),
    field('phone', 'Contact phone', 'What is the best phone number?', '1. Confirm the plan', kind='tel'),
    field('address', 'Business address', 'What is your business address?', '1. Confirm the plan'),
    field('service', 'First service to advertise', 'Which type of work do you want more of first?', '1. Confirm the plan', ['Concrete', 'Excavation', 'Landscaping / hardscaping', 'Decks', 'Fences', 'Other']),
    field('project', 'Specific project', 'Within that service, what exact project should we focus on?', '1. Confirm the plan'),
    field('area', 'Service area', 'Which cities, ZIP codes, or radius should we cover?', '1. Confirm the plan', kind='textarea'),
    field('minimum', 'Minimum project value (USD)', 'What is the smallest project you want us to bring you?', '1. Confirm the plan', kind='number'),
    field('capacity', 'Additional projects per month', 'How many additional projects can you handle?', '1. Confirm the plan', ['1–2', '3–5', '6–10', 'More than 10', 'Need to confirm']),
    field('excluded', 'Work / locations to exclude', 'What jobs or locations should we avoid?', '1. Confirm the plan', kind='textarea'),
    field('meta_setup', 'Meta setup', 'Are your Page, Instagram, and ad account in your business portfolio?', '2. Connect Meta accounts', ['All ready', 'Partly set up', 'Needs setup', 'Ownership / access issue']),
    field('portfolio_id', 'Client business portfolio ID', 'Open your business settings and confirm the business portfolio ID.', '2. Connect Meta accounts'),
    field('ad_account_id', 'Client ad account ID', 'Which ad account will we use?', '2. Connect Meta accounts'),
    field('page_url', 'Facebook Page link', 'Which Facebook Page will the ads run from?', '2. Connect Meta accounts', kind='url'),
    field('instagram', 'Instagram handle', 'Which Instagram account will the ads run from?', '2. Connect Meta accounts'),
    *[field(k, label, prompt, '2. Connect Meta accounts', ['Not started', 'Client granted access', 'Verified from BMT', 'Blocked / needs help', 'Not applicable']) for k, label, prompt in [
        ('page_access', 'Facebook Page access', 'Have them share Page advertising access with BMT, then check it from your side.'),
        ('instagram_access', 'Instagram access', 'Have them share the connected Instagram asset, then check it from your side.'),
        ('ad_access', 'Ad account access', 'Have them grant BMT permission to manage campaigns in their ad account, then verify it.'),
        ('lead_access', 'Lead form access', 'Confirm BMT can retrieve leads from the Page’s instant forms.'),
        ('tracking_access', 'Pixel / dataset access', 'If using website tracking, confirm access to the existing pixel / dataset.')]],
    field('billing', 'Meta billing method', 'Is a working payment method on their own ad account?', '2. Connect Meta accounts', ['Confirmed ready', 'Client will add it', 'Billing issue']),
    field('budget', 'Monthly ad budget (USD)', 'Confirm the approved ad spend, paid directly to Meta.', '2. Connect Meta accounts', kind='number'),
    field('materials', 'Creative materials', 'Are their best completed projects, before-and-afters, videos, and logo available?', '3. Collect advertising materials', ['Received', 'Some received', 'Client will upload', 'Need help collecting']),
    field('folder', 'Shared materials folder', 'Where will they upload their project photos and videos?', '3. Collect advertising materials', kind='url'),
    field('hero_project', 'Best example project', 'Which completed job best represents the work they want more of?', '3. Collect advertising materials', kind='textarea'),
    field('claims', 'Approved claims / offers', 'Confirm any warranties, financing, certifications, testimonials, or promotions before using them.', '3. Collect advertising materials', kind='textarea'),
    field('materials_due', 'Materials due date', 'When will the remaining materials be uploaded?', '3. Collect advertising materials', kind='date'),
    field('lead_owner', 'Lead follow-up owner', 'Who is responsible for contacting new enquiries?', '4. Lead delivery & qualification'),
    field('lead_email', 'Lead notification email', 'Which email should receive new lead notifications?', '4. Lead delivery & qualification', kind='email'),
    field('lead_phone', 'Lead notification phone', 'Which phone should receive notifications, if used?', '4. Lead delivery & qualification', kind='tel'),
    field('delivery', 'Lead delivery method', 'How should their team receive enquiries?', '4. Lead delivery & qualification', ['Email', 'CRM', 'Email + CRM', 'Text + email', 'Other / to arrange']),
    field('response', 'Expected response time', 'How quickly can their team contact a new enquiry?', '4. Lead delivery & qualification', ['Within 5 minutes', 'Within 15 minutes', 'Within 1 hour', 'Same business day', 'Need a follow-up plan']),
    field('after_hours', 'After-hours enquiries', 'Who handles enquiries outside working hours?', '4. Lead delivery & qualification', ['Owner responds', 'Team / answering service', 'Next business morning', 'Need a plan']),
    field('qualification', 'Agreed qualification criteria', 'Confirm the service, location, project requirements, and readiness for a quote under the signed contract.', '4. Lead delivery & qualification', kind='textarea'),
    field('test_lead', 'Test enquiry', 'Send a clearly labelled test through the actual lead delivery setup before launch. Did they receive it?', '4. Lead delivery & qualification', ['Not tested', 'Received and confirmed', 'Delivery issue']),
    field('approver', 'Ad approval contact', 'Who gives final approval on the ad previews?', '5. Approval & next steps'),
    field('approval_channel', 'Approval channel', 'Where should we send the ad previews?', '5. Approval & next steps', ['Email', 'Text', 'CRM', 'Other']),
    field('preview_due', 'Ad previews due', 'When will we send the first previews?', '5. Approval & next steps', kind='date'),
    field('launch_date', 'Target launch date', 'Agree on a launch date after access, billing, materials, and approvals are ready.', '5. Approval & next steps', kind='date'),
    field('guarantee_start', 'Agreed guarantee start date', 'Confirm the start date under the signed agreement; do not assume it is today.', '5. Approval & next steps', kind='date'),
    field('next_steps', 'Missing items / owners / deadlines', 'Recap what is still needed, who owes it, and by when.', '5. Approval & next steps', kind='textarea'),
    field('contract', 'Signed contract', 'Has the service agreement been signed?', 'Customer & call record', ['Yes', 'No', 'Pending']),
    field('payment', 'Initial payment received', 'Confirm payment in Stripe before marking this as paid.', 'Customer & call record', ['$1,500 USD deposit received', '$3,000 USD upfront received', 'Not received', 'Other / verify']),
    field('onboarding_date', 'Onboarding call date', 'Record the booked onboarding date.', 'Customer & call record', kind='date'),
    field('onboarding_time', 'Onboarding call time', 'Record the booked time.', 'Customer & call record', kind='time'),
    field('onboarding_zone', 'Call time zone', 'Which time zone is that time in?', 'Customer & call record', ['Pacific', 'Mountain', 'Central', 'Eastern', 'Arizona', 'Other']),
    field('onboarding_zoom', 'Onboarding Zoom link', 'Record the existing meeting link.', 'Customer & call record', kind='url'),
    field('progress', 'Onboarding status', 'Where did we leave the setup?', 'Customer & call record', ['Booked', 'In progress', 'Waiting on client', 'Ready for ad build', 'Complete']),
]


def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_onboarding (
        lead_id INTEGER PRIMARY KEY REFERENCES crm_leads(id),
        data TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)''')


def read(lead_id):
    with store.connect() as con:
        schema(con)
        lead = con.execute('SELECT * FROM crm_leads WHERE id=?', (lead_id,)).fetchone()
        if not lead:
            raise LookupError('Customer not found.')
        row = con.execute('SELECT * FROM crm_onboarding WHERE lead_id=?', (lead_id,)).fetchone()
        defaults = {k: lead[k] for k in ('contact', 'email', 'phone')}
        defaults.update(area=lead['location'], budget='1500', lead_owner=lead['contact'],
                        lead_email=lead['email'], lead_phone=lead['phone'], approver=lead['contact'])
        if row:
            defaults.update(json.loads(row['data']))
        return dict(lead_id=lead_id, company=lead['company'], customer=lead['status']=='Won',
                    lead_revision=lead['revision'], data=defaults, revision=row['revision'] if row else 0,
                    updated_at=row['updated_at'] if row else None)


def save(lead_id, payload):
    if type(payload.get('revision')) is not int or not isinstance(payload.get('data'), dict):
        raise ValueError('Reload the worksheet and try again.')
    allowed = {f['key']: f for f in FIELDS}
    data = payload['data']
    if set(data)-set(allowed):
        raise ValueError('Unknown worksheet field.')
    for key, value in data.items():
        f = allowed[key]
        if not isinstance(value, str) or len(value)>5000:
            raise ValueError('Check '+f['label']+'.')
        if value and f['options'] and value not in f['options']:
            raise ValueError('Choose a listed answer for '+f['label']+'.')
        if value and f['type']=='date': date.fromisoformat(value)
        if value and f['type']=='time':
            from datetime import time
            time.fromisoformat(value)
        if value and f['type']=='email':
            import re
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value): raise ValueError('Enter a valid email for '+f['label']+'.')
        if value and f['type']=='number':
            import math
            if not math.isfinite(float(value)) or float(value)<0: raise ValueError('Use a positive amount.')
        if value and f['type']=='url':
            from urllib.parse import urlparse
            parsed=urlparse(value)
            if parsed.scheme not in ('http','https') or not parsed.netloc: raise ValueError('Use a full web link for '+f['label']+'.')
    promote=payload.get('mark_customer') is True
    if promote and not (data.get('contract')=='Yes' and data.get('payment') in (
            '$1,500 USD deposit received','$3,000 USD upfront received') and
            all(data.get(k) for k in ('onboarding_date','onboarding_time','onboarding_zone'))):
        raise ValueError('Confirm the signed contract, received payment, and booked onboarding date, time, and time zone first.')
    with store.connect() as con:
        schema(con)
        con.execute('BEGIN IMMEDIATE')
        lead=con.execute('SELECT * FROM crm_leads WHERE id=?',(lead_id,)).fetchone()
        if not lead: raise LookupError('Customer not found.')
        row=con.execute('SELECT revision FROM crm_onboarding WHERE lead_id=?',(lead_id,)).fetchone()
        revision=row['revision'] if row else 0
        if payload['revision']!=revision: raise store.Conflict('This worksheet changed elsewhere. Reload it before saving; your draft is still available.')
        if promote and payload.get('lead_revision')!=lead['revision']:
            raise store.Conflict('This customer record changed elsewhere. Reload before moving it to Customers.')
        stamp=store.now()
        con.execute('''INSERT INTO crm_onboarding VALUES (?,?,?,?) ON CONFLICT(lead_id)
            DO UPDATE SET data=excluded.data, revision=excluded.revision, updated_at=excluded.updated_at''',
            (lead_id,json.dumps(data),revision+1,stamp))
        if promote and lead['status']!='Won':
            con.execute("UPDATE crm_leads SET status='Won',updated_at=?,revision=revision+1 WHERE id=?",(stamp,lead_id))
            con.execute('INSERT INTO crm_notes (lead_id,author,text,created_at) VALUES (?,?,?,?)',
                        (lead_id,'Michael','Marked customer after operator confirmed signed contract, initial payment received, and onboarding call booked.',stamp))
    return read(lead_id)
