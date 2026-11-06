"""Simple shared workspace for Michael and the closer."""
import csv
import hashlib
import hmac
import io
import os
import time
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import crm_store as store

ZONES = {'Eastern': 'America/New_York', 'Central': 'America/Chicago',
         'Mountain': 'America/Denver', 'Pacific (US)': 'America/Los_Angeles',
         'Arizona': 'America/Phoenix', 'Vancouver': 'America/Vancouver'}


def require_login():
    password = os.environ.get('BMT_CRM_PASSWORD', '')
    if not password:
        # Owner explicitly approved public CRM and Tools access on November 6, 2026.
        return
    fingerprint = hashlib.sha256(password.encode()).hexdigest()
    if st.session_state.get('_crm_authenticated') == fingerprint:
        return
    st.title('BMT CRM')
    st.caption('Warm leads, follow-ups and sales tools.')
    with st.form('crm_login'):
        entered = st.text_input('Shared password', type='password')
        submitted = st.form_submit_button('Open CRM', use_container_width=True)
    if submitted:
        if hmac.compare_digest(entered, password):
            st.session_state['_crm_authenticated'] = fingerprint
            st.rerun()
        time.sleep(1)
        st.error('That password did not match.')
    st.stop()


def day_value(value):
    return date.fromisoformat(value) if value else None


def display_stamp(value):
    if not value:
        return ''
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=-7))).strftime('%b %d, %Y %-I:%M %p Vancouver')


def render():
    if st.session_state.pop('crm_clear_new',False):
        for key in ['crm_add_company','crm_add_contact','crm_add_phone','crm_add_email','crm_add_need','crm_add_follow_up']:
            st.session_state.pop(key,None)
    who = st.selectbox('Working as', ['Michael', 'Closer'], key='crm_working_as')
    today = datetime.now(timezone(timedelta(hours=-7))).date().isoformat()
    leads = store.list_leads()
    numbers = store.counts(leads, today)
    a,b,c = st.columns(3)
    a.metric('New leads', numbers['new'])
    b.metric('Follow-ups due', numbers['due'])
    c.metric('Calls booked', numbers['booked'])
    if st.session_state.pop('crm_saved', False):
        st.success('Saved.')
    with st.expander('Add warm lead'):
        with st.form('crm_add'):
            company = st.text_input('Company name *', max_chars=200, key='crm_add_company')
            contact = st.text_input('Contact name', max_chars=200, key='crm_add_contact')
            left,right = st.columns(2)
            phone = left.text_input('Phone', max_chars=80, key='crm_add_phone')
            email = right.text_input('Email', max_chars=250, key='crm_add_email')
            need = st.text_area('Their need / your conversation', max_chars=10000, key='crm_add_need')
            follow_up = st.date_input('Next follow-up (optional)', value=None, key='crm_add_follow_up')
            add = st.form_submit_button('Add lead', use_container_width=True)
        if add:
            try:
                store.add_lead(company,contact,phone,email,need,follow_up.isoformat() if follow_up else None)
                st.session_state.crm_clear_new = True
                st.session_state.crm_saved = True
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    view = st.selectbox('Show', ['All open', 'New leads', 'Follow-ups due', 'Calls booked', 'Won / Lost'])
    search = st.text_input('Search leads', placeholder='Company, contact, phone or email').strip().lower()
    if st.button('Refresh list'):
        for key in list(st.session_state):
            if key.startswith('crm_loaded_revision_'):
                del st.session_state[key]
        st.rerun()
    shown = []
    for lead in leads:
        closed = lead['status'] in ('Won','Lost')
        if view == 'All open' and closed: continue
        if view == 'New leads' and (lead['seen_at'] or closed): continue
        if view == 'Follow-ups due' and (closed or not lead['follow_up'] or lead['follow_up'] > today): continue
        if view == 'Calls booked' and lead['status'] != 'Call booked': continue
        if view == 'Won / Lost' and not closed: continue
        if search and search not in ' '.join(str(lead[k]) for k in ['company','contact','phone','email','need']).lower(): continue
        shown.append(lead)
    st.caption(f'{len(shown)} lead(s) shown. New means not marked as seen. Follow-ups include overdue dates.')
    if not shown:
        st.info('No leads in this view yet.')
    for lead in shown:
        n = lead['id']
        version_key = f'crm_loaded_revision_{n}'
        if version_key not in st.session_state:
            st.session_state[version_key] = lead['revision']
        badge = 'NEW - ' if not lead['seen_at'] else ''
        with st.expander(f"{badge}{lead['company']} - {lead['status']}"):
            st.write(lead['contact'] or 'Contact name not added')
            st.write(' | '.join(v for v in [lead['phone'],lead['email']] if v))
            st.write(lead['need'] or 'No conversation notes yet.')
            if lead['follow_up']:
                st.write('Next follow-up: '+lead['follow_up'])
            if lead['call_date']:
                st.write('Booked call: '+' '.join(x for x in [lead['call_date'],lead['call_time'],lead['call_zone']] if x))
            st.caption('Added '+display_stamp(lead['created_at'])+' · Updated '+display_stamp(lead['updated_at']))
            if lead['seen_at']:
                st.caption('Seen by '+lead['seen_by']+' · '+display_stamp(lead['seen_at']))
            elif who == 'Closer':
                if st.button('Mark as seen', key=f'seen_{n}'):
                    store.mark_seen(n,who)
                    st.session_state.pop(version_key,None)
                    st.rerun()
            else:
                st.caption('Not yet seen by the closer.')
            with st.form(f'lead_{n}'):
                company = st.text_input('Company', value=lead['company'])
                contact = st.text_input('Contact', value=lead['contact'])
                phone = st.text_input('Phone', value=lead['phone'])
                email = st.text_input('Email', value=lead['email'])
                need = st.text_area('Their need / conversation', value=lead['need'])
                status = st.selectbox('Status', store.STATUSES, index=store.STATUSES.index(lead['status']))
                follow_up = st.date_input('Next follow-up', value=day_value(lead['follow_up']))
                call_date = st.date_input('Booked call date (optional)', value=day_value(lead['call_date']))
                call_time = st.text_input('Booked call time (optional)', value=lead['call_time'] or '', placeholder='10:30 AM')
                zone_names = list(ZONES)
                current_zone = lead['call_zone'] if lead['call_zone'] in zone_names else 'Eastern'
                call_zone = st.selectbox('Call time zone',zone_names,index=zone_names.index(current_zone))
                note = st.text_area('Add closer note / next step', key=f'new_note_{n}')
                save = st.form_submit_button('Save update',use_container_width=True)
            if save:
                try:
                    store.update_lead(n,st.session_state[version_key],company=company,contact=contact,phone=phone,email=email,
                        need=need,status=status,follow_up=follow_up.isoformat() if follow_up else None,
                        call_date=call_date.isoformat() if call_date else None,call_time=call_time.strip() or None,
                        call_zone=call_zone if call_date else None,note=note,author=who)
                    st.session_state.pop(f'new_note_{n}',None)
                    st.session_state.pop(version_key,None)
                    st.session_state.crm_saved = True
                    st.rerun()
                except (ValueError,store.Conflict) as e:
                    st.error(str(e))
            for note in store.notes_for(n):
                st.caption(note['author']+' · '+display_stamp(note['created_at']))
                st.write(note['text'])
    if leads:
        fields = ['company','contact','phone','email','need','status','follow_up','call_date','call_time','call_zone','seen_by','seen_at','created_at','updated_at']
        output = io.StringIO()
        writer = csv.DictWriter(output,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for lead in leads:
            # Keep user-entered text literal if opened in a spreadsheet.
            writer.writerow({k:("'"+str(lead[k]) if str(lead[k] or '').startswith(('=','+','-','@')) else lead[k]) for k in fields})
        st.download_button('Download leads (CSV)',output.getvalue(),'BMT_CRM_leads.csv','text/csv')
