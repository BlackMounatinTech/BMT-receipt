"""Simple shared workspace for Michael and the closer."""
import csv
from html import escape
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
    heading, identity = st.columns([4, 1.35], vertical_alignment='center')
    with heading:
        st.markdown('<div class="page-kicker">BMT / LEAD WORKSPACE</div><h1>Your pipeline.</h1><p class="page-intro">Warm leads, booked calls, and the next step for every conversation.</p>', unsafe_allow_html=True)
    with identity:
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
    with st.columns([3, 1])[1]:
        with st.popover('＋ Add warm lead', use_container_width=True):
            with st.form('crm_add'):
                company = st.text_input('Company name *', max_chars=200, key='crm_add_company')
                contact = st.text_input('Contact name', max_chars=200, key='crm_add_contact')
                left,right = st.columns(2)
                phone = left.text_input('Phone', max_chars=80, key='crm_add_phone')
                email = right.text_input('Email', max_chars=250, key='crm_add_email')
                need = st.text_area('Their need / your conversation', max_chars=10000, key='crm_add_need')
                follow_up = st.date_input('Next follow-up (optional)', value=None, key='crm_add_follow_up')
                add = st.form_submit_button('Add lead', use_container_width=True, type='primary')
            if add:
                try:
                    store.add_lead(company,contact,phone,email,need,follow_up.isoformat() if follow_up else None)
                    st.session_state.crm_clear_new = True
                    st.session_state.crm_saved = True
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    st.markdown('### Lead inbox')
    view = st.radio('Show', ['All open', 'New leads', 'Follow-ups due', 'Calls booked', 'Won / Lost'], horizontal=True, label_visibility='collapsed')
    search_col, refresh_col = st.columns([5, 1], vertical_alignment='bottom')
    search = search_col.text_input('Search leads', placeholder='Find a company, person or phone number…', label_visibility='collapsed').strip().lower()
    if refresh_col.button('Refresh list', use_container_width=True):
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
    st.caption(f'{len(shown)} {"conversation" if len(shown) == 1 else "conversations"} · {view}')
    if not shown:
        title = 'Your next client starts here.' if not leads else 'All clear in this view.'
        hint = 'Add a warm lead after a good call. Your closer can take it from there.' if not leads else 'Try another view or search to find the conversation you need.'
        st.markdown(f'<div class="empty-state"><div class="empty-symbol">↗</div><h3>{title}</h3><p>{hint}</p></div>', unsafe_allow_html=True)
    for lead in shown:
        n = lead['id']
        version_key = f'crm_loaded_revision_{n}'
        if version_key not in st.session_state:
            st.session_state[version_key] = lead['revision']
        with st.container(border=True):
            is_new = not lead['seen_at']
            tag = 'NEW LEAD' if is_new else lead['status'].upper()
            tag_class = 'fresh' if is_new else 'won' if lead['status'] == 'Won' else ''
            details = ' · '.join(v for v in [lead['contact'], lead['phone'], lead['email']] if v)
            st.markdown(f'<div class="lead-head"><div><div class="lead-name">{escape(lead["company"])}</div><div class="lead-contact">{escape(details or "Contact details pending")}</div></div><span class="status-tag {tag_class}">{escape(tag)}</span></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="lead-need">{escape(lead["need"] or "Add the conversation and what they need help with.")}</div>', unsafe_allow_html=True)
            next_steps = []
            if lead['follow_up']:
                next_steps.append('Follow up · ' + date.fromisoformat(lead['follow_up']).strftime('%b %-d'))
            if lead['call_date']:
                next_steps.append('Call · ' + ' '.join(x for x in [lead['call_date'],lead['call_time'],lead['call_zone']] if x))
            if next_steps:
                st.markdown('<div class="lead-next">' + escape('   /   '.join(next_steps)) + '</div>', unsafe_allow_html=True)
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
            with st.expander('Open lead / update next step'):
                with st.form(f'lead_{n}'):
                    left, right = st.columns(2)
                    company = left.text_input('Company', value=lead['company'])
                    contact = right.text_input('Contact', value=lead['contact'])
                    phone = left.text_input('Phone', value=lead['phone'])
                    email = right.text_input('Email', value=lead['email'])
                    need = st.text_area('Their need / conversation', value=lead['need'])
                    status = st.selectbox('Status', store.STATUSES, index=store.STATUSES.index(lead['status']))
                    follow_up = st.date_input('Next follow-up', value=day_value(lead['follow_up']))
                    call_date = st.date_input('Booked call date (optional)', value=day_value(lead['call_date']))
                    call_time = st.text_input('Booked call time (optional)', value=lead['call_time'] or '', placeholder='10:30 AM')
                    zone_names = list(ZONES)
                    current_zone = lead['call_zone'] if lead['call_zone'] in zone_names else 'Eastern'
                    call_zone = st.selectbox('Call time zone',zone_names,index=zone_names.index(current_zone))
                    note = st.text_area('Add closer note / next step', key=f'new_note_{n}')
                    save = st.form_submit_button('Save update',use_container_width=True, type='primary')
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
