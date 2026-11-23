"""Small, plain CRM. Shares the existing lead database and disk."""
import os
import secrets
import hmac
from datetime import date
from flask import Flask, jsonify, render_template, request, session
import crm_store as store

app = Flask(__name__, template_folder='crm_templates', static_folder='crm_static', static_url_path='/crm-assets')
app.secret_key = os.environ.get('CRM_SESSION_SECRET') or secrets.token_hex(32)
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
                           p.get('email', ''), p.get('need', ''), p.get('follow_up') or None,
                           **{k:p.get(k,'Prospect' if k=='stage' else '') for k in
                              ['instagram','location','stage','contact_method','contact_account']})
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
                          **{k:p.get(k) for k in ['instagram','location','stage','contact_method','contact_account']})
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
    return jsonify(crm_calling.call_counts())


@app.post('/api/calling/new-day')
def reset_call_day():
    import crm_calling
    return jsonify(crm_calling.call_counts(reset=True))


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
            crm_calling.rows_from_file(file),commit=request.form.get('commit')=='true')
        return jsonify(result)
    except (ValueError,UnicodeError,TypeError) as e:
        return jsonify(error=str(e)),400
    except Exception:
        app.logger.exception('Sheet import failed')
        return jsonify(error='Could not read that file. Export the lead tab as CSV and try again.'),400


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


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8518)
