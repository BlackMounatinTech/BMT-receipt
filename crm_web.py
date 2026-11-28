"""Small, plain CRM. Shares the existing lead database and disk."""
import os
import secrets
import hmac
from datetime import date
from flask import Flask, jsonify, render_template, request, session, send_file
import crm_store as store

def session_secret():
    configured=os.environ.get('CRM_SESSION_SECRET')
    if configured:return configured
    if not os.environ.get('RENDER'):return secrets.token_hex(32)
    # The existing persistent disk keeps signed owner sessions valid across deploys.
    with store.connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS crm_runtime_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        con.execute('INSERT OR IGNORE INTO crm_runtime_settings VALUES (?,?)',('session_secret',secrets.token_hex(32)))
        return con.execute("SELECT value FROM crm_runtime_settings WHERE key='session_secret'").fetchone()[0]

app = Flask(__name__, template_folder='crm_templates', static_folder='crm_static', static_url_path='/crm-assets')
app.secret_key = session_secret()
app.config.update(MAX_CONTENT_LENGTH=5_000_000, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')),
                  SESSION_COOKIE_NAME='bmt_crm')

@app.before_request
def protect():
    if request.method in ('POST', 'PATCH'):
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', '!')):
            return jsonify(error='Refresh the page and try again.'), 403

@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.get('/')
def index():
    session.setdefault('csrf', secrets.token_hex(24))
    return render_template('crm.html', csrf=session['csrf'])

@app.get('/healthz')
def health():
    return {'status': 'ok'}

@app.get('/closer-hiring')
def closer_hiring():
    return render_template('hiring/interview.html')

@app.get('/closer-questionnaire')
def closer_questionnaire():
    return render_template('hiring/questionnaire.html')

@app.get('/api/leads')
def leads():
    return jsonify(leads=store.list_leads())

@app.route('/api/leads/<int:n>/sales-call',methods=['GET','POST'])
def sales_call_facts(n):
    import crm_sales_call
    try:
        return jsonify(crm_sales_call.read(n) if request.method=='GET' else crm_sales_call.save(n,request.get_json(silent=True)))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400


@app.route('/api/leads/<int:n>/sales-close',methods=['GET','POST'])
def sales_close_record(n):
    import crm_sales_close as close
    try:return jsonify(close.read(n) if request.method=='GET' else close.save(n,request.get_json(silent=True)))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.route('/api/leads/<int:n>/sales-close/email/<kind>',methods=['GET','POST'])
def sales_close_email(n,kind):
    import crm_sales_close as close
    try:return jsonify(close.preview(n,kind) if request.method=='GET' else close.send(n,kind,request.get_json(silent=True)))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.post('/api/leads/<int:n>/sales-close/payment')
def sales_close_payment(n):
    import crm_sales_close as close
    try:return jsonify(close.confirm_payment(n,request.get_json(silent=True)))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.post('/api/leads/<int:n>/sales-close/book')
def sales_close_book(n):
    import crm_sales_close as close
    try:return jsonify(close.book(n,request.get_json(silent=True)))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.route('/api/leads/<int:n>/sales-close/document/<kind>',methods=['GET','POST'])
def sales_close_document(n,kind):
    import crm_sales_close as close
    try:
        if request.method=='GET':
            import io
            doc=close.document(n,kind)
            return send_file(io.BytesIO(doc['body']),mimetype='application/pdf',download_name=doc['filename'],as_attachment=True)
        file=request.files.get('file')
        if not file:raise ValueError('Choose a PDF file.')
        return jsonify(close.upload(n,kind,file))
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.get('/api/sales-close/appointments')
def sales_onboarding_appointments():
    from crm_sales_close import appointments
    return jsonify(appointments=appointments())

@app.get('/api/sales-call/questions')
def sales_questions():
    from crm_sales_questions import definition
    return jsonify(definition())


@app.get('/api/onboarding/fields')
def onboarding_fields():
    from crm_onboarding import FIELDS
    return jsonify(fields=FIELDS)

@app.get('/api/customers')
def customers_list():
    import crm_customers
    return jsonify(customers=crm_customers.list_customers())

@app.route('/api/customers/<int:n>', methods=['GET','POST'])
def customer_profile(n):
    import crm_customers
    try:
        if request.method=='GET':return jsonify(crm_customers.read(n))
        p=request.get_json(silent=True)
        if not isinstance(p,dict):raise ValueError('Provide the profile details.')
        return jsonify(crm_customers.save(n,p))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.post('/api/leads/<int:n>/confirm-sale')
def customer_confirm_sale(n):
    import crm_customers
    try:
        p=request.get_json(silent=True)
        if not isinstance(p,dict):raise ValueError('Provide the purchase confirmation.')
        return jsonify(crm_customers.confirm_sale(n,p))
    except store.Conflict as e:return jsonify(error=str(e)),409
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.post('/api/customers/<int:n>/documents')
def customer_document_upload(n):
    import crm_customers
    try:
        upload=request.files.get('file')
        if not upload:raise ValueError('Choose a document.')
        return jsonify(crm_customers.attach(n,request.form.get('kind'),upload))
    except LookupError as e:return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.get('/api/customers/<int:n>/documents/<int:doc_id>')
def customer_document_download(n,doc_id):
    import crm_customers
    from flask import send_file
    from io import BytesIO
    try:
        d=crm_customers.document(n,doc_id)
        return send_file(BytesIO(d['body']),mimetype=d['mime'],as_attachment=True,download_name=d['filename'])
    except LookupError as e:return jsonify(error=str(e)),404
    except ValueError as e:return jsonify(error=str(e)),400

@app.route('/api/leads/<int:n>/onboarding', methods=['GET','POST'])
def onboarding_record(n):
    import crm_onboarding
    try:
        if request.method=='GET': return jsonify(crm_onboarding.read(n))
        p=request.get_json(silent=True)
        if not isinstance(p,dict): raise ValueError('Provide the worksheet answers.')
        return jsonify(crm_onboarding.save(n,p))
    except store.Conflict as e: return jsonify(error=str(e)),409
    except LookupError as e: return jsonify(error=str(e)),404
    except (ValueError,TypeError) as e: return jsonify(error=str(e)),400

@app.get('/api/outreach-inbox')
def outreach_inbox():
    import crm_outreach_inbox
    return jsonify(crm_outreach_inbox.snapshot(outreach_operator()))

@app.post('/api/outreach-inbox/<int:n>/read')
def outreach_read(n):
    import crm_outreach_inbox
    try:
        p=request.get_json(silent=True) or {}
        if not isinstance(p,dict):raise ValueError('Provide the displayed reply sequence.')
        crm_outreach_inbox.mark_read(n,p.get('sequence'))
        return jsonify(ok=True)
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.get('/api/leads/<int:n>/notes')
def notes(n):
    return jsonify(notes=store.notes_for(n))

@app.post('/api/leads/<int:n>/seen')
def seen(n):
    store.mark_seen(n, 'Closer')
    return {'ok': True}

def payload():
    p = request.get_json(silent=True)
    if not isinstance(p, dict):
        raise ValueError('Please fill in the lead details.')
    fields = ['company', 'contact', 'phone', 'email', 'need', 'note', 'status', 'call_time', 'call_zone', 'zoom_url',
              'instagram', 'location', 'stage', 'contact_method', 'contact_account']
    for key in fields:
        if key in ('call_time', 'call_zone') and p.get(key) is None:
            continue
        if key in p and (not isinstance(p[key], str) or len(p[key]) > 10000):
            raise ValueError('Please check the lead details.')
    for key in ['follow_up', 'call_date']:
        if p.get(key):
            date.fromisoformat(p[key])
    return p

@app.post('/api/leads')
def add():
    try:
        p = payload()
        n = store.add_lead(p.get('company', ''), p.get('contact', ''), p.get('phone', ''),
                           p.get('email', ''), p.get('need', ''), p.get('follow_up') or None, is_test=p.get('is_test',False),
                           **{k:p.get(k,'Prospect' if k=='stage' else '') for k in
                              ['instagram','location','stage','contact_method','contact_account','last_contacted_at']})
        return jsonify(id=n), 201
    except (ValueError, TypeError):
        return jsonify(error='Add a company and a phone number, email or valid Instagram profile. Check any dates.'), 400

@app.post('/api/outreach/import-instagram')
def import_instagram():
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise ValueError('Provide confirmed contact records.')
        return jsonify(store.import_instagram_contacts(data.get('records')))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400

@app.patch('/api/leads/<int:n>')
def update(n):
    try:
        p = payload()
        if type(p.get('revision')) is not int:
            raise ValueError('Refresh this lead before saving.')
        store.update_lead(n, p['revision'], **{k: p.get(k, '') for k in ['company', 'contact', 'phone', 'email', 'need', 'status']},
                          follow_up=p.get('follow_up') or None, call_date=p.get('call_date') or None,
                          call_time=p.get('call_time') or None, call_zone=p.get('call_zone') or None,
                          note=p.get('note', ''), author='Closer' if p.get('author') == 'Closer' else 'Michael', zoom_url=p.get('zoom_url'),
                          **{k:p.get(k) for k in ['instagram','location','stage','contact_method','contact_account','last_contacted_at']})
        return {'ok': True}
    except store.Conflict as e:
        return jsonify(error=str(e)), 409
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400

@app.get('/api/leads/<int:n>/appointment-email')
def appointment_email(n):
    from crm_appointments import preview, messages_table
    lead = next((lead for lead in store.list_leads() if lead['id'] == n),None)
    if not lead:
        return jsonify(error='Lead not found.'),404
    try:
        with store.connect() as con:
            messages_table(con)
            states={row['kind']:row['state'] for row in con.execute('SELECT kind,state FROM crm_appointment_messages WHERE lead_id=? AND booking_version=?',(n,lead['booking_version']))}
        return jsonify(**preview(lead),version=lead['booking_version'],sent_at=lead['confirmation_sent_at'],confirmed_at=lead['confirmed_at'],reminder_sent_at=lead['reminder_sent_at'],send_states=states)
    except ValueError as e:
        return jsonify(error=str(e)),400

@app.post('/api/leads/<int:n>/appointment-email')
def send_appointment_email(n):
    from crm_appointments import send
    p = request.get_json(silent=True) or {}
    try:
        kind='reminder' if p.get('kind') == 'reminder' else 'confirmation'
        return send(n,p.get('version'),kind=kind,retry=p.get('retry') is True)
    except store.Conflict as e:
        return jsonify(error=str(e)),409
    except ValueError as e:
        return jsonify(error=str(e)),400

@app.post('/api/leads/<int:n>/booking-email')
def correct_booking_email(n):
    import crm_booking
    p=request.get_json(silent=True) or {}
    try:
        if not isinstance(p,dict) or type(p.get('version')) is not int:
            raise ValueError('Reopen this appointment before correcting its email.')
        return jsonify(crm_booking.correct_email(n,p['version'],p.get('email')))
    except store.Conflict as e:
        return jsonify(error=str(e)),409
    except ValueError as e:
        return jsonify(error=str(e)),400

@app.post('/api/leads/<int:n>/confirm-appointment')
def confirm_appointment(n):
    p = request.get_json(silent=True) or {}
    with store.connect() as con:
        result=con.execute('UPDATE crm_leads SET confirmed_at=? WHERE id=? AND booking_version=? AND status=\'Call booked\' AND confirmation_sent_at IS NOT NULL', (store.now(),n,p.get('version')))
        if result.rowcount != 1:
            return jsonify(error='Send the confirmation first, or refresh if the appointment changed.'),409
    return {'ok':True}

@app.get('/api/calling/lists')
def call_lists():
    import crm_calling
    return jsonify(lists=crm_calling.lists())


@app.get('/api/calling/counts')
def call_counts():
    import crm_calling
    return jsonify(**crm_calling.call_counts(), **crm_calling.pipeline_counts())


@app.post('/api/calling/new-day')
def reset_call_day():
    import crm_calling
    return jsonify(**crm_calling.call_counts(reset=True), **crm_calling.pipeline_counts())


@app.get('/api/calling/lists/<list_id>')
def call_list(list_id):
    import crm_calling
    return jsonify(leads=crm_calling.items(list_id))


@app.post('/api/calling/import')
def import_call_sheet():
    import crm_calling
    try:
        file = request.files.get('file')
        if not file or not file.filename:
            raise ValueError('Choose a lead sheet.')
        result = crm_calling.import_list(request.form.get('name') or file.filename,
            crm_calling.rows_from_file(file),commit=request.form.get('commit')=='true',
            priority_schedule=request.form.get('priority_schedule',''))
        return jsonify(result)
    except (ValueError,UnicodeError,TypeError) as e:
        return jsonify(error=str(e)),400
    except Exception:
        app.logger.exception('Sheet import failed')
        return jsonify(error='Could not read that file. Export the lead tab as CSV and try again.'),400


@app.get('/api/calling/called')
def called_leads():
    import crm_calling
    return jsonify(leads=crm_calling.called())


@app.post('/api/calling/lists/<list_id>/<int:lead_id>/outcome')
def record_call(list_id,lead_id):
    import crm_calling
    try:
        p = request.get_json(silent=True) or {}
        crm_calling.outcome(list_id,lead_id,p.get('revision'),p.get('outcome'),p.get('note',''),p.get('follow_up'))
        return {'ok':True}
    except store.Conflict as e:
        return jsonify(error=str(e)),409
    except (ValueError,TypeError) as e:
        return jsonify(error=str(e)),400


@app.post('/api/calling/leads/<int:lead_id>/notes')
def save_call_notes(lead_id):
    import crm_calling
    try:
        p=request.get_json(silent=True)
        if not isinstance(p,dict): raise ValueError('Add the call notes to save.')
        return jsonify(crm_calling.save_notes(lead_id,p.get('text'),p.get('version')))
    except store.Conflict as e:
        return jsonify(error=str(e)),409
    except (ValueError,TypeError) as e:
        return jsonify(error=str(e)),400


@app.post('/api/calling/leads/<int:lead_id>/timezone')
def save_lead_timezone(lead_id):
    from crm_appointments import ZONES
    data=request.get_json(silent=True) or {}
    zone=data.get('zone') if isinstance(data,dict) else None
    if zone not in [*ZONES.values(),'Etc/GMT+7']:
        return jsonify(error='Choose a valid company time zone.'),400
    with store.connect() as con:
        result=con.execute('UPDATE crm_leads SET lead_timezone=? WHERE id=?',(zone,lead_id))
        if result.rowcount!=1:return jsonify(error='Lead not found.'),404
    return jsonify(zone=zone)


@app.post('/api/calling/leads/<int:lead_id>/research')
def save_lead_research(lead_id):
    import crm_research
    p = request.get_json(silent=True)
    if not isinstance(p, dict):
        return jsonify(error='Provide the lead research.'),400
    try:
        return jsonify(crm_research.save(lead_id,p.get('revision'),p.get('need'),
                                        p.get('website',''),p.get('business_hours',{})))
    except store.Conflict as e:
        return jsonify(error=str(e)),409
    except (ValueError,TypeError) as e:
        return jsonify(error=str(e)),400


@app.get('/api/booking/connections')
def booking_connections():
    import crm_booking
    return jsonify(crm_booking.connection_status())


@app.get('/api/booking/jobs')
def booking_jobs():
    import crm_booking
    with store.connect() as con:
        crm_booking.schema(con)
        return jsonify(jobs=[crm_booking.public_job(dict(r)) for r in con.execute("SELECT * FROM crm_booking_jobs WHERE state!='abandoned' ORDER BY updated_at DESC")])


@app.post('/api/leads/<int:lead_id>/book')
def book_call(lead_id):
    import crm_booking
    try:
        p = request.get_json(silent=True)
        if not isinstance(p,dict): raise ValueError('Fill in the booking details.')
        return jsonify(crm_booking.create(lead_id,p))
    except store.Conflict as e:
        return jsonify(error=str(e)),409
    except (ValueError,TypeError,AttributeError) as e:
        return jsonify(error=str(e)),400


@app.post('/api/booking/jobs/<job_id>/resume')
def resume_booking(job_id):
    import crm_booking
    try:
        return jsonify(crm_booking.resume(job_id))
    except (ValueError,TypeError) as e:
        return jsonify(error=str(e)),400


@app.post('/api/booking/jobs/<job_id>/abandon')
def abandon_booking(job_id):
    import crm_booking
    try:
        crm_booking.abandon(job_id)
        return {'ok':True}
    except ValueError as e:
        return jsonify(error=str(e)),400


@app.get('/api/stats')
def stats_report():
    import crm_stats
    from datetime import datetime, timedelta
    day = datetime.now(crm_stats.LOCAL).date()
    try:
        return jsonify(crm_stats.report(request.args.get('start',(day-timedelta(days=29)).isoformat()), request.args.get('end',day.isoformat())))
    except ValueError as e:
        return jsonify(error=str(e)),400

@app.route('/api/stats/outreach', methods=['GET','POST'])
def stats_outreach():
    import crm_stats
    try:
        if request.method=='GET':
            return jsonify(crm_stats.outreach_row(request.args.get('day'),request.args.get('channel')))
        p=request.get_json(silent=True)
        if not isinstance(p,dict): raise ValueError('Check your outreach entry.')
        return jsonify(crm_stats.save_outreach(p))
    except store.Conflict as e: return jsonify(error=str(e)),409
    except ValueError as e: return jsonify(error=str(e)),400

@app.post('/api/stats/discovery')
def stats_discovery():
    import crm_stats
    try:
        p=request.get_json(silent=True)
        if not isinstance(p,dict): raise ValueError('Check your discovery entry.')
        return jsonify(crm_stats.save_discovery(p))
    except store.Conflict as e: return jsonify(error=str(e)),409
    except ValueError as e: return jsonify(error=str(e)),400

def outreach_operator():
    import hashlib
    from pathlib import Path
    expected=app.config.get('OUTREACH_WORKER_HASH')
    if expected is None:
        path=Path(__file__).with_name('crm_outreach_worker.sha256')
        expected=path.read_text().strip() if path.exists() else ''
    supplied=request.headers.get('X-BMT-Outreach-Key','')
    return bool(session.get('outreach_operator')) or bool(expected and supplied and hmac.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(),expected))

@app.route('/api/outreach-system', methods=['GET','POST'])
def outreach_system():
    import crm_outreach_system as machine
    if request.method=='GET':return jsonify(machine.snapshot(outreach_operator()))
    if not outreach_operator():return jsonify(error='Connect this browser to the Mac worker before changing outreach controls.'),403
    p=request.get_json(silent=True)
    if not isinstance(p,dict):return jsonify(error='Provide an outreach action.'),400
    try:return jsonify(machine.action(p,owner=bool(session.get('outreach_operator'))))
    except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.get('/outreach-connect/<token>')
def outreach_connect(token):
    import crm_outreach_system as machine
    from flask import redirect
    if not machine.connect_operator(token):return 'This connection link expired or was already used.',403
    session['outreach_operator']=True
    session.permanent=True
    return redirect('/#system')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5056)))
