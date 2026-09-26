"""Payment-first consultation funnel. All authorization stays on the server."""
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, select, update
from sqlalchemy.exc import IntegrityError

AMOUNT = 10000
CURRENCY = 'cad'
PRODUCT = 'bmt-consultation-v1'
COOKIE = 'bmt_consultation'
metadata = MetaData()
orders = Table('bmt_consultation_orders', metadata,
    Column('id', String(64), primary_key=True),
    Column('token_hash', String(64), unique=True, nullable=False),
    Column('details', Text, nullable=False),
    Column('state', String(20), nullable=False),
    Column('session_id', String(255), unique=True),
    Column('checkout_url', Text),
    Column('booking_uid', String(255), unique=True),
    Column('booking', Text),
    Column('created_at', Integer, nullable=False),
    Column('updated_at', Integer, nullable=False))
reservations = Table('bmt_consultation_reservations', metadata,
    Column('start', String(64), primary_key=True), Column('order_id', String(64), unique=True, nullable=False))
limits = Table('bmt_consultation_limits', metadata,
    Column('id', String(80), primary_key=True), Column('count', Integer, nullable=False))

class FlowError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status

class Providers:
    def __init__(self, config):
        self.c = config
    def stripe(self, method, path, data=None, params=None, idem=None):
        headers = {'Authorization': 'Bearer '+self.c['STRIPE_SECRET_KEY']}
        if idem:
            headers['Idempotency-Key'] = idem
        try:
            r = requests.request(method, 'https://api.stripe.com/v1/'+path,
                headers=headers, data=data, params=params, timeout=(5, 25))
        except requests.RequestException:
            raise FlowError('Payment service is temporarily unavailable. Please try again.', 503)
        if not r.ok:
            # Never expose provider bodies: they may contain customer data or credentials.
            raise FlowError('Payment service is unavailable. Please contact Michael if this continues.', 503)
        return r.json()
    def create_checkout(self, order):
        d = json.loads(order['details'])
        return self.stripe('POST', 'checkout/sessions', data={
            'mode': 'payment', 'line_items[0][price]': self.c['STRIPE_PRICE_ID'],
            'line_items[0][quantity]': '1', 'customer_email': d['email'],
            'client_reference_id': order['id'], 'metadata[order_id]': order['id'],
            'metadata[product]': PRODUCT, 'payment_intent_data[metadata][order_id]': order['id'],
            'payment_method_types[0]': 'card',
            'success_url': self.c['PUBLIC_BASE_URL']+'/book.html',
            'cancel_url': self.c['PUBLIC_BASE_URL']+'/?checkout=cancelled',
            'custom_text[submit][message]': 'After payment, choose your 30-minute consultation time. $100 CAD, one time.'
        }, idem='bmt-consultation-'+order['id'])
    def payment(self, session_id):
        return self.stripe('GET', 'checkout/sessions/'+session_id,
            params=[('expand[]','payment_intent.latest_charge'), ('expand[]','line_items')])
    def cal(self, method, path, data=None, params=None, version='2026-02-25'):
        try:
            r = requests.request(method, 'https://api.cal.com/v2/'+path,
                headers={'Authorization':'Bearer '+self.c['CAL_API_KEY'], 'cal-api-version':version},
                json=data, params=params, timeout=(5, 35))
        except requests.RequestException:
            raise FlowError('The calendar did not respond. Your payment is safe; do not pay again.', 503)
        if not r.ok:
            # A server failure during booking may have committed. Caller keeps the order locked.
            raise FlowError('We could not confirm the calendar response. Do not pay again; contact Michael.', 503)
        return r.json()['data']
    def slots(self, start, end, zone):
        # Public Cal event windows remain closed. Only our paid server can book.
        # Read real Google busy times; never expose calendar event descriptions.
        calendars = self.cal('GET', 'calendars', version='2024-08-13')
        params = {'timeZone':zone, 'dateFrom':start, 'dateTo':end}
        selected = [c for account in calendars['connectedCalendars']
                    for c in account['calendars'] if c.get('isSelected')]
        if not selected: raise FlowError('The calendar is not connected. Please contact Michael.', 503)
        for i, calendar in enumerate(selected):
            params[f'calendarsToLoad[{i}][credentialId]'] = calendar['credentialId']
            params[f'calendarsToLoad[{i}][externalId]'] = calendar['externalId']
        busy = self.cal('GET', 'calendars/busy-times', params=params, version='2024-08-13')
        spans = [(datetime.fromisoformat(x['start'].replace('Z','+00:00')),
                  datetime.fromisoformat(x['end'].replace('Z','+00:00'))) for x in busy]
        visitor, host = ZoneInfo(zone), ZoneInfo('America/Vancouver')
        left = datetime.fromisoformat(start).replace(tzinfo=visitor)
        right = datetime.fromisoformat(end).replace(tzinfo=visitor)
        day = left.astimezone(host).replace(hour=0, minute=0, second=0, microsecond=0)
        now = datetime.now(timezone.utc)
        result = {}
        while day < right:
            if day.weekday() < 5:
                for n in range(28):
                    t = day.replace(hour=7) + timedelta(minutes=30*n)
                    finish = t + timedelta(minutes=30)
                    if left <= t < right and now+timedelta(hours=4) <= t <= now+timedelta(days=60):
                        if not any(t < b and finish > a for a,b in spans):
                            local = t.astimezone(visitor)
                            result.setdefault(local.date().isoformat(), []).append({'start':local.isoformat()})
            day += timedelta(days=1)
        return result
    def book(self, order, start):
        d = json.loads(order['details'])
        labels = {'business':'Business','trade':'Trade','location':'Location','revenue':'Monthly revenue',
                  'team':'Team size','sources':'Lead sources','challenge':'Main challenge',
                  'goals':'90-day goals','website':'Website'}
        notes = '\n'.join(f'{label}: {d.get(key) or "Not provided"}' for key,label in labels.items())
        return self.cal('POST','bookings',data={
            'eventTypeId':int(self.c['CAL_EVENT_TYPE_ID']), 'start':start,
            'attendee':{'name':d['name'],'email':d['email'],'timeZone':d['timezone'],'language':'en'},
            'bookingFieldsResponses':{'notes':notes},
            'metadata':{'bmtOrderId':order['id'],'paymentVerified':'true'},
            'allowConflicts':False,'allowBookingOutOfBounds':True,'skipBookingLimits':False})


def payment_valid(session, order, config):
    """Do not accept an arbitrary successful charge, wrong product, refund, or test payment."""
    pi = session.get('payment_intent') or {}
    if not isinstance(pi, dict): return False
    charge = pi.get('latest_charge') or {}
    if not isinstance(charge, dict): return False
    items = (session.get('line_items') or {}).get('data', [])
    return all([
        session.get('id') == order['session_id'],
        session.get('status') == 'complete', session.get('payment_status') == 'paid',
        session.get('mode') == 'payment', session.get('currency') == CURRENCY,
        session.get('amount_total') == AMOUNT,
        session.get('livemode') is config['PAYMENTS_LIVE'],
        session.get('client_reference_id') == order['id'],
        session.get('metadata',{}).get('order_id') == order['id'],
        session.get('metadata',{}).get('product') == PRODUCT,
        len(items) == 1 and items[0].get('quantity') == 1 and
            (items[0].get('price') or {}).get('id') == config['STRIPE_PRICE_ID'],
        pi.get('status') == 'succeeded', pi.get('currency') == CURRENCY,
        pi.get('amount_received',0) >= AMOUNT,
        charge.get('paid') is True, charge.get('status') == 'succeeded',
        charge.get('refunded') is False, charge.get('amount_refunded') == 0,
        charge.get('disputed') is False])


def validate_details(data):
    if not isinstance(data,dict): raise FlowError('Please complete the questionnaire.')
    required = {'name':120,'email':254,'business':180,'trade':100,'location':180,
                'challenge':2000,'goals':2000,'timezone':80}
    optional = {'revenue':100,'team':80,'sources':600,'website':300}
    out={}
    for k,n in {**required,**optional}.items():
        v=data.get(k,'')
        if not isinstance(v,str) or len(v)>n or (k in required and not v.strip()):
            raise FlowError('Please check the '+k+' field.')
        out[k]=v.strip()
    out['email']=out['email'].lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',out['email']): raise FlowError('Enter a valid email address.')
    try: ZoneInfo(out['timezone'])
    except (ValueError,ZoneInfoNotFoundError): raise FlowError('Choose a valid time zone.')
    return out


def create_app(overrides=None, providers=None):
    app=Flask(__name__,static_folder=None)
    app.config.update({k:os.environ.get(k,'') for k in
        ['STRIPE_SECRET_KEY','STRIPE_PRICE_ID','CAL_API_KEY','CAL_EVENT_TYPE_ID','PUBLIC_BASE_URL','DATABASE_URL']})
    app.config.update(PAYMENTS_LIVE=True,COOKIE_SECURE=True,MAX_CONTENT_LENGTH=20000,BOOKING_ENABLED=False)
    app.config['BOOKING_ENABLED']=os.environ.get('BOOKING_ENABLED')=='true'
    if overrides: app.config.update(overrides)
    c=app.config
    dburl=c['DATABASE_URL']
    if not dburl: raise RuntimeError('DATABASE_URL is required; production must use persistent storage.')
    if dburl.startswith('postgres://'): dburl=dburl.replace('postgres://','postgresql+psycopg://',1)
    if dburl.startswith('postgresql://'): dburl=dburl.replace('postgresql://','postgresql+psycopg://',1)
    if not c.get('TESTING'):
        for k in ['STRIPE_SECRET_KEY','STRIPE_PRICE_ID','CAL_API_KEY','CAL_EVENT_TYPE_ID','PUBLIC_BASE_URL']:
            if not c[k]: raise RuntimeError(k+' is required')
        if not c['PUBLIC_BASE_URL'].startswith('https://'): raise RuntimeError('Production requires HTTPS')
        if dburl.startswith('sqlite') and not os.environ.get('PERSISTENT_SQLITE_CONFIRMED')=='true':
            raise RuntimeError('SQLite production requires an explicitly configured persistent disk')
    engine=create_engine(dburl,connect_args={'check_same_thread':False,'timeout':15} if dburl.startswith('sqlite') else {},pool_pre_ping=True)
    metadata.create_all(engine)
    api=providers or Providers(c)
    app.extensions['booking_engine']=engine
    def now(): return int(time.time())
    def load_order():
        token=request.cookies.get(COOKIE,'')
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,64}',token): raise FlowError('Complete your questionnaire and payment first.',401)
        with engine.connect() as conn:
            row=conn.execute(select(orders).where(orders.c.token_hash==hashlib.sha256(token.encode()).hexdigest())).mappings().first()
        if not row: raise FlowError('Booking session not found. If you already paid, contact Michael; do not pay again.',401)
        return dict(row)
    def write(oid, **fields):
        fields['updated_at']=now()
        with engine.begin() as conn: conn.execute(update(orders).where(orders.c.id==oid).values(**fields))
    def require_paid(order):
        if not order['session_id']: raise FlowError('Payment is required before booking.',402)
        session=api.payment(order['session_id'])
        if not payment_valid(session,order,c): raise FlowError('Payment has not been verified. Complete the $100 CAD payment before choosing a time.',402)
        with engine.begin() as conn:
            conn.execute(update(orders).where(orders.c.id==order['id'],orders.c.state=='checkout').values(state='paid',updated_at=now()))
    def enabled():
        if not c['BOOKING_ENABLED']: raise FlowError('Online booking is being updated. Email michael@blackmountaintechnologies.ca for help.',503)
    def throttle(limit):
        # Render's trusted proxy appends the client address. Never log raw IP or customer details.
        addr=request.headers.get('X-Forwarded-For','').split(',')[-1].strip() or request.remote_addr or ''
        ident=hashlib.sha256(addr.encode()).hexdigest()+':'+str(now()//3600)
        try:
            with engine.begin() as conn: conn.execute(limits.insert().values(id=ident,count=0))
        except IntegrityError: pass
        with engine.begin() as conn:
            result=conn.execute(update(limits).where(limits.c.id==ident,limits.c.count<limit).values(count=limits.c.count+1))
            if result.rowcount!=1: raise FlowError('Too many attempts. Please try later or contact Michael.',429)
    @app.before_request
    def guard():
        if request.method=='POST':
            if request.headers.get('Origin') != (urlparse(c['PUBLIC_BASE_URL']).scheme+'://'+urlparse(c['PUBLIC_BASE_URL']).netloc):
                raise FlowError('Please use the booking page to continue.',403)
            if request.mimetype!='application/json': raise FlowError('Expected a JSON request.',415)
    @app.after_request
    def headers(r):
        r.headers['Cache-Control']='no-store'
        r.headers['Referrer-Policy']='no-referrer'
        r.headers['X-Content-Type-Options']='nosniff'
        r.headers['X-Frame-Options']='DENY'
        r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return r
    @app.errorhandler(FlowError)
    def flow_error(e): return jsonify(error=e.message),e.status
    @app.get('/health')
    def health():
        with engine.connect() as conn: conn.execute(select(orders.c.id).limit(1))
        return jsonify(ok=True,bookingEnabled=c['BOOKING_ENABLED'])
    @app.get('/')
    def index(): return send_from_directory('public','index.html')
    @app.get('/<path:name>')
    def public(name):
        if name not in ['book.html','funnel.js','book.js','style.css','logo.png']:return '',404
        return send_from_directory('public',name)
    @app.get('/api/status')
    def status():
        order=load_order()
        if order['state']=='booked': return jsonify(state='booked',booking=json.loads(order['booking']))
        if order['state'] in ['booking','review']: return jsonify(state='review')
        require_paid(order)
        return jsonify(state='paid',name=json.loads(order['details'])['name'],timezone=json.loads(order['details'])['timezone'])
    @app.post('/api/checkout')
    def checkout():
        enabled()
        # Retrying the same browser must reuse its checkout rather than charge twice.
        existing=None
        try: existing=load_order()
        except FlowError: pass
        if existing:
            if existing['state'] in ['paid','booking','review','booked']:
                return jsonify(url=c['PUBLIC_BASE_URL']+'/book.html')
            if existing.get('session_id'):
                session=api.payment(existing['session_id'])
                if session.get('payment_status')=='paid': return jsonify(url=c['PUBLIC_BASE_URL']+'/book.html')
                if session.get('status')=='open' and session.get('url'): return jsonify(url=session['url'])
        throttle(10)
        details=validate_details(request.get_json())
        oid=secrets.token_hex(20);token=secrets.token_urlsafe(32)
        order={'id':oid,'token_hash':hashlib.sha256(token.encode()).hexdigest(),'details':json.dumps(details),
            'state':'checkout','created_at':now(),'updated_at':now()}
        with engine.begin() as conn: conn.execute(orders.insert().values(**order))
        session=api.create_checkout(order)
        if not str(session.get('url','')).startswith('https://checkout.stripe.com/'):
            raise FlowError('Unable to open secure checkout. Please contact Michael.',503)
        write(oid,session_id=session['id'],checkout_url=session['url'])
        response=jsonify(url=session['url'])
        response.set_cookie(COOKIE,token,secure=c['COOKIE_SECURE'],httponly=True,samesite='Lax',max_age=180*86400,path=(urlparse(c['PUBLIC_BASE_URL']).path.rstrip('/') or '')+'/')
        return response
    @app.get('/api/slots')
    def slots():
        enabled();order=load_order();require_paid(order)
        if order['state'] in ['booked','booking','review']:raise FlowError('This consultation already has a booking or a pending confirmation.',409)
        try:
            start=datetime.fromisoformat(request.args.get('start',''))
            end=datetime.fromisoformat(request.args.get('end',''))
        except ValueError: raise FlowError('Choose a valid date range.')
        today=datetime.now(timezone.utc).date()
        if start.date()<today or end<=start or (end-start).days>14 or end.date()>today+timedelta(days=61):
            raise FlowError('Choose a date within the next 60 days.')
        zone=json.loads(order['details'])['timezone']
        available=api.slots(start.date().isoformat(),end.date().isoformat(),zone)
        with engine.connect() as conn: held=set(conn.execute(select(reservations.c.start)).scalars())
        for day,items in available.items():
            available[day]=[x for x in items if datetime.fromisoformat(x['start'].replace('Z','+00:00')).astimezone(timezone.utc).isoformat() not in held]
        return jsonify(slots=available,timezone=zone)
    @app.post('/api/book')
    def book():
        enabled();order=load_order()
        if order['state']=='booked':return jsonify(state='booked',booking=json.loads(order['booking']))
        if order['state'] in ['booking','review']:raise FlowError('Your booking is being checked. Do not pay or book again. Contact Michael for help.',409)
        require_paid(order)
        data=request.get_json();start=data.get('start') if isinstance(data,dict) else None
        try:dt=datetime.fromisoformat(start.replace('Z','+00:00'))
        except (AttributeError,ValueError):raise FlowError('Choose an available time.')
        utcnow=datetime.now(timezone.utc)
        if dt.tzinfo is None or dt<utcnow+timedelta(hours=4) or dt>utcnow+timedelta(days=60):raise FlowError('Choose a time at least four hours ahead and within 60 days.')
        start=dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        d=json.loads(order['details']);local=dt.astimezone(ZoneInfo(d['timezone']))
        day=local.date();available=api.slots(day.isoformat(),(day+timedelta(days=1)).isoformat(),d['timezone'])
        allslots=[x.get('start') for v in available.values() for x in v]
        def normal(x):return datetime.fromisoformat(x.replace('Z','+00:00'))
        if not any(normal(x)==dt for x in allslots):raise FlowError('That time is no longer available. Please choose another.',409)
        # Atomic durable claim: concurrent tabs, retries, and restarts cannot spend a payment twice.
        try:
            with engine.begin() as conn:
                claimed=conn.execute(update(orders).where(orders.c.id==order['id'],orders.c.state=='paid').values(state='booking',updated_at=now()))
                if claimed.rowcount!=1:raise FlowError('This payment already has a booking in progress.',409)
                conn.execute(reservations.insert().values(start=dt.astimezone(timezone.utc).isoformat(),order_id=order['id']))
        except IntegrityError:
            raise FlowError('That time was just reserved. Please choose another time; do not pay again.',409)
        try:
            b=api.book(order,start)
            if not isinstance(b,dict) or not b.get('uid') or b.get('status','').lower()!='accepted':
                raise FlowError('Your payment was received, but the appointment needs confirmation. Please contact Michael.',503)
            result={'uid':b['uid'],'start':b.get('start',start),'end':b.get('end'),'meetingUrl':b.get('meetingUrl','')}
            write(order['id'],state='booked',booking_uid=b['uid'],booking=json.dumps(result))
        except Exception:
            # Never retry an ambiguous create automatically: it might already exist at the provider.
            write(order['id'],state='review')
            raise FlowError('Your payment was received. We need to check the calendar confirmation. Do not pay again; email Michael.',503)
        return jsonify(state='booked',booking=result)
    return app
