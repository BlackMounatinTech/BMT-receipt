import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from app import create_app,orders,PRODUCT,COOKIE

BASE='https://booking.example.com'
DETAILS={'name':'Test Contractor','email':'contractor@example.com','business':'Test Business','trade':'Concrete','location':'Comox, Canada','challenge':'Need a quoting process','goals':'More profitable work','timezone':'America/Vancouver'}
START=(datetime.now(timezone.utc)+timedelta(days=3)).replace(hour=18,minute=0,second=0,microsecond=0).isoformat().replace('+00:00','Z')
class Fake:
    def __init__(self):self.sessions={};self.bookings=[];self.paid=False;self.change=lambda x:x;self.fail=False
    def create_checkout(self,order):
        sid='cs_live_'+order['id'];self.sessions[sid]={'id':sid,'url':'https://checkout.stripe.com/c/pay/'+sid,'client_reference_id':order['id'],'metadata':{'order_id':order['id'],'product':PRODUCT}}
        return self.sessions[sid]
    def payment(self,sid):
        s=copy.deepcopy(self.sessions[sid]);s.update(status='complete' if self.paid else 'open',payment_status='paid' if self.paid else 'unpaid',mode='payment',currency='cad',amount_total=10000,livemode=True,line_items={'data':[{'quantity':1,'price':{'id':'price_consult'}}]},payment_intent={'status':'succeeded','currency':'cad','amount_received':10000,'latest_charge':{'paid':True,'status':'succeeded','refunded':False,'amount_refunded':0,'disputed':False}})
        self.change(s);return s
    def slots(self,*args):return {START[:10]:[{'start':START}]}
    def book(self,order,start):
        self.bookings.append(order['id']);time.sleep(.04)
        if self.fail:raise TimeoutError('unknown provider result')
        return {'uid':'booking_'+order['id'],'status':'accepted','start':start,'end':None,'meetingUrl':'https://meet.google.com/test'}
@pytest.fixture
def setup(tmp_path):
    fake=Fake();config={'TESTING':True,'DATABASE_URL':'sqlite:///'+str(tmp_path/'book.db'),'PUBLIC_BASE_URL':BASE,'STRIPE_PRICE_ID':'price_consult','PAYMENTS_LIVE':True,'COOKIE_SECURE':False,'BOOKING_ENABLED':True}
    app=create_app(config,fake);return app,app.test_client(),fake,config

def checkout(client):return client.post('/api/checkout',json=DETAILS,headers={'Origin':BASE})
def book(client):return client.post('/api/book',json={'start':START},headers={'Origin':BASE})
def slots(client):
    start=datetime.now(timezone.utc).date();return client.get('/api/slots',query_string={'start':str(start),'end':str(start+timedelta(days=7))})

def test_direct_calendar_and_fake_flags_do_not_authorize(setup):
    _,c,f,_=setup
    assert c.get('/book.html?paid=true').status_code==200 # shell contains no availability or booking permission
    assert c.get('/api/status?paid=true&session_id=cs_fake').status_code==401
    assert slots(c).status_code==401
    assert book(c).status_code==401
    assert not f.bookings

def test_cancelled_or_unpaid_checkout_cannot_book(setup):
    _,c,f,_=setup;assert checkout(c).status_code==200
    assert c.get('/api/status').status_code==402
    assert slots(c).status_code==402
    assert book(c).status_code==402
    assert not f.bookings

@pytest.mark.parametrize('change',[
 lambda x:x.update(amount_total=1),lambda x:x.update(currency='usd'),lambda x:x.update(livemode=False),
 lambda x:x.update(mode='subscription'),lambda x:x.update(client_reference_id='other-order'),
 lambda x:x['metadata'].update(product='other-product'),lambda x:x['metadata'].update(order_id='other'),
 lambda x:x['line_items']['data'][0]['price'].update(id='other-price'),
 lambda x:x['line_items']['data'][0].update(quantity=2),
 lambda x:x['payment_intent']['latest_charge'].update(refunded=True),
 lambda x:x['payment_intent']['latest_charge'].update(amount_refunded=1),
 lambda x:x['payment_intent']['latest_charge'].update(disputed=True),
 lambda x:x['payment_intent'].update(status='processing'),lambda x:x.update(payment_status='no_payment_required')])
def test_invalid_payment_never_unlocks(setup,change):
    _,c,f,_=setup;checkout(c);f.paid=True;f.change=change
    assert slots(c).status_code==402;assert book(c).status_code==402;assert not f.bookings

def test_paid_order_books_once_and_survives_restart(setup):
    a,c,f,config=setup;checkout(c);f.paid=True
    assert slots(c).status_code==200
    first=book(c);assert first.status_code==200
    assert book(c).json==first.json
    assert len(f.bookings)==1
    a2=create_app(config,f);c2=a2.test_client();c2.set_cookie(COOKIE,c.get_cookie(COOKIE).value)
    assert book(c2).json==first.json;assert len(f.bookings)==1

def test_concurrent_tabs_spend_payment_once(setup):
    a,c,f,_=setup;checkout(c);f.paid=True;token=c.get_cookie(COOKIE).value
    def call():
        cl=a.test_client();cl.set_cookie(COOKIE,token);return book(cl).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:call(),range(2)))
    assert 200 in results;assert set(results)<= {200,409};assert len(f.bookings)==1

def test_ambiguous_provider_failure_does_not_retry(setup):
    _,c,f,_=setup;checkout(c);f.paid=True;f.fail=True
    assert book(c).status_code==503
    assert book(c).status_code==409
    assert c.get('/api/status').json['state']=='review'
    assert len(f.bookings)==1

def test_no_cross_order_access(setup):
    a,c,f,_=setup;checkout(c);f.paid=True
    other=a.test_client();assert other.get('/api/status').status_code==401
    other.set_cookie(COOKIE,'A'*43);assert slots(other).status_code==401

def test_csrf_and_input_checks(setup):
    _,c,f,_=setup
    assert c.post('/api/checkout',json=DETAILS,headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/checkout',data='x',headers={'Origin':BASE}).status_code==415
    assert c.post('/api/checkout',json={**DETAILS,'timezone':'bogus'},headers={'Origin':BASE}).status_code==400
    assert c.post('/api/checkout',json={**DETAILS,'challenge':''},headers={'Origin':BASE}).status_code==400

def test_slot_recheck_and_boundaries(setup):
    _,c,f,_=setup;checkout(c);f.paid=True
    assert c.post('/api/book',json={'start':'2000-01-01T00:00:00Z'},headers={'Origin':BASE}).status_code==400
    f.slots=lambda *args:{}
    assert book(c).status_code==409;assert not f.bookings

def test_refund_after_unlock_blocks_booking(setup):
    _,c,f,_=setup;checkout(c);f.paid=True;assert slots(c).status_code==200
    f.change=lambda x:x['payment_intent']['latest_charge'].update(amount_refunded=10000)
    assert book(c).status_code==402

def test_disabled_system_does_not_accept_new_payments(setup):
    a,c,f,_=setup;a.config['BOOKING_ENABLED']=False
    assert checkout(c).status_code==503;assert not f.sessions

def test_checkout_reuses_open_session_and_resumes_paid_session(setup):
    _,c,f,_=setup;r=checkout(c);assert checkout(c).json==r.json;assert len(f.sessions)==1
    f.paid=True;assert checkout(c).json['url']==BASE+'/book.html';assert len(f.sessions)==1


def test_two_paid_customers_cannot_claim_same_slot(setup):
    app,c,f,_=setup
    other=app.test_client()
    checkout(c); checkout(other); f.paid=True
    assert book(c).status_code==200
    assert book(other).status_code==409
    assert len(f.bookings)==1
    assert other.get('/api/status').json['state']=='paid'

def test_path_prefix_origin_uses_host_not_path(setup):
    app,_,f,config=setup
    config=dict(config,PUBLIC_BASE_URL=BASE+'/book')
    mounted=create_app(config,f); c=mounted.test_client()
    r=c.post('/api/checkout',json=DETAILS,headers={'Origin':BASE})
    assert r.status_code==200
    assert 'Path=/book/' in r.headers['Set-Cookie']

def test_provider_availability_respects_busy_hours_and_timezones():
    from app import Providers
    provider=Providers({})
    def cal(method,path,**kwargs):
        if path=='calendars':return {'connectedCalendars':[{'calendars':[{'isSelected':True,'credentialId':1,'externalId':'test'}]}]}
        return [{'start':'2030-01-07T20:00:00Z','end':'2030-01-07T20:30:00Z'}]
    provider.cal=cal
    # Use a future Monday within the actual booking window, then verify every slot.
    day=datetime.now(timezone.utc).date()+timedelta(days=7)
    while day.weekday()!=0:day+=timedelta(days=1)
    available=provider.slots(str(day),str(day+timedelta(days=7)),'America/New_York')
    from zoneinfo import ZoneInfo
    for values in available.values():
        for value in values:
            t=datetime.fromisoformat(value['start']).astimezone(ZoneInfo('America/Vancouver'))
            assert t.weekday()<5 and 7<=t.hour<21 and t.minute in (0,30)
    assert sum(map(len,available.values()))==140
