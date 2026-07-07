"""
BMT Receipt Tool — Streamlit app (like the BMDW quoting software).
Pick a service, fill in the client, GENERATE to preview the branded receipt PDF,
then SEND to email it one-click from the company Gmail (same setup as BMDW).
"""
import datetime as dt
from pathlib import Path

import streamlit as st
from fpdf import FPDF

from tools.email_sender import send_email, configured_method

HERE = Path(__file__).resolve().parent
LOGO = HERE / "assets_logo.png"
OUT = HERE / ".tmp"
OUT.mkdir(exist_ok=True)

# --- simple CRM log (email -> prospect/client) ---
import csv as _csv
LEADS = HERE / "leads_log.csv"

def _load_leads():
    if not LEADS.exists():
        return []
    with open(LEADS, newline="", encoding="utf-8") as f:
        return list(_csv.DictReader(f))

def _save_leads(rows):
    with open(LEADS, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=["email", "clinic", "status", "first_contact", "notes"])
        w.writeheader(); w.writerows(rows)

def log_lead(email, clinic="", status="prospect"):
    email = (email or "").strip().lower()
    if not email:
        return
    rows = _load_leads()
    for r in rows:
        if r["email"] == email:
            if clinic and not r.get("clinic"):
                r["clinic"] = clinic
            _save_leads(rows); return
    rows.append({"email": email, "clinic": clinic, "status": status,
                 "first_contact": dt.datetime.now().strftime("%Y-%m-%d"), "notes": ""})
    _save_leads(rows)

def set_status(email, status):
    rows = _load_leads()
    for r in rows:
        if r["email"] == email.strip().lower():
            r["status"] = status
    _save_leads(rows)

NAVY = (26, 32, 44); GREY = (90, 90, 90); INK = (20, 20, 20)
LINE = (214, 218, 220); GREEN = (34, 110, 60)

# The services + pricing (matches the contract + one-pager)
SERVICES = {
    "Patient Reactivation Campaign (one-time)": {"amount": 1500, "monthly": 0,
        "desc": "A done-for-you campaign that reaches your past customers in your name and invites them back in. Their data stays in your office. Set up and live within the week."},
    "Missed-Call Text-Back (setup)": {"amount": 1500, "monthly": 250,
        "desc": "An AI system that automatically texts back anyone whose call you miss, in your name, so they hear from you before they try the next place."},
    "Package AI - Reactivation + Missed-Call Text-Back (setup)": {"amount": 2500, "monthly": 250,
        "desc": "Both systems together: win back your past customers and catch every missed call. Set up done for you, live within the week."},
    "AI Walkthrough ($500 session)": {"amount": 500, "monthly": 0,
        "desc": "A one-session walkthrough mapping exactly where your front desk is leaking time and money, with a written plan of what AI can do for your business. You keep the plan."},
    "AI Walkthrough ($300 session)": {"amount": 300, "monthly": 0,
        "desc": "A one-session walkthrough mapping exactly where your front desk is leaking time and money, with a written plan of what AI can do for your business. You keep the plan."},
    "Custom": {"amount": 0, "monthly": 0, "desc": ""},
}


def _ascii(s):
    """Scrub characters the basic PDF font can't render (em dashes, smart quotes, etc.)."""
    if not s:
        return s
    repl = {"—": "-", "–": "-", "’": "'", "‘": "'",
            "“": '"', "”": '"', "…": "...", "•": "-"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def receipt_no():
    d = dt.datetime.now()
    return "BMT-" + d.strftime("%y%m%d-%H%M")


def make_receipt_pdf(service_desc, amount, monthly, clinic, payer, date_str, method, path,
                     service_detail="", company_address="", company_email="", company_phone=""):
    service_desc = _ascii(service_desc); clinic = _ascii(clinic); payer = _ascii(payer)
    service_detail = _ascii(service_detail)
    company_address = _ascii(company_address); company_email = _ascii(company_email); company_phone = _ascii(company_phone)
    pdf = FPDF("P", "mm", "A4")
    pdf.set_auto_page_break(False)  # keep it to ONE page, footer pinned at bottom
    pdf.add_page()
    W, M = 210, 20
    inv = receipt_no()

    if LOGO.exists():
        pdf.image(str(LOGO), x=(W - 46) / 2, y=14, w=46)
    pdf.set_y(46)
    pdf.set_font("Helvetica", "B", 16); pdf.set_text_color(*NAVY)
    pdf.cell(0, 9, "RECEIPT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*LINE); pdf.set_line_width(0.4); pdf.line(M, pdf.get_y()+1, W-M, pdf.get_y()+1)
    pdf.ln(6)

    # meta left / billed-to right
    y0 = pdf.get_y()
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(*GREY)
    pdf.set_xy(M, y0); pdf.cell(0, 5.5, f"Receipt #: {inv}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(M); pdf.cell(0, 5.5, f"Date: {date_str}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(M); pdf.cell(0, 5.5, f"Payment method: {method}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(M, y0)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(*NAVY)
    pdf.cell(W-2*M, 5.5, "BILLED TO", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(M); pdf.set_font("Helvetica", "", 10); pdf.set_text_color(*INK)
    pdf.cell(W-2*M, 5.5, clinic or "________________", align="R", new_x="LMARGIN", new_y="NEXT")
    if payer:
        pdf.set_x(M); pdf.cell(W-2*M, 5.5, "Authorized by: " + payer, align="R", new_x="LMARGIN", new_y="NEXT")
    if company_address:
        pdf.set_x(M); pdf.cell(W-2*M, 5.5, company_address, align="R", new_x="LMARGIN", new_y="NEXT")
    if company_email:
        pdf.set_x(M); pdf.cell(W-2*M, 5.5, company_email, align="R", new_x="LMARGIN", new_y="NEXT")
    if company_phone:
        pdf.set_x(M); pdf.cell(W-2*M, 5.5, company_phone, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # table header
    pdf.set_fill_color(244, 245, 247); pdf.rect(M, pdf.get_y(), W-2*M, 9, "F")
    pdf.set_xy(M+3, pdf.get_y()+2.5); pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(*NAVY)
    pdf.cell(W-2*M-30, 5, "DESCRIPTION")
    pdf.cell(24, 5, "AMOUNT", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_x(M+3); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*INK)
    pdf.cell(W-2*M-30, 6, service_desc)
    pdf.cell(24, 6, f"${amount:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")
    if service_detail:
        pdf.set_x(M+3); pdf.set_font("Helvetica", "", 9); pdf.set_text_color(*GREY)
        pdf.multi_cell(W-2*M-6, 4.4, service_detail)
    pdf.ln(1); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y(), W-M, pdf.get_y()); pdf.ln(5)

    # total
    pdf.set_x(M+3); pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(*NAVY)
    pdf.cell(W-2*M-30, 7, "TOTAL PAID TODAY")
    pdf.cell(24, 7, f"${amount:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_x(M+3); pdf.set_font("Helvetica", "", 8.5); pdf.set_text_color(*GREY)
    pdf.cell(0, 4, "No GST charged.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # recurring note (only when there's a monthly)
    if monthly:
        pdf.set_fill_color(244, 245, 247); box_y = pdf.get_y(); pdf.rect(M, box_y, W-2*M, 18, "F")
        pdf.set_xy(M+3, box_y+2.5); pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(*NAVY)
        pdf.cell(0, 5, "Ongoing monthly service", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(M+3); pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(*INK)
        pdf.multi_cell(W-2*M-6, 4.6,
            f"A recurring payment of ${monthly:,.2f}/month for the Missed-Call Text-Back service "
            f"begins one month after this setup date ({date_str}) and recurs monthly on that date. "
            "The setup amount above is what was paid today.")
        pdf.set_y(box_y + 18); pdf.ln(3)

    # thank you
    pdf.set_x(M+3); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*GREEN)
    pdf.cell(0, 6, "Paid in full. Thank you for your business.", new_x="LMARGIN", new_y="NEXT")

    # footer
    pdf.set_y(-22); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y(), W-M, pdf.get_y()); pdf.ln(2)
    pdf.set_font("Helvetica", "", 8.5); pdf.set_text_color(*GREY)
    pdf.cell(0, 4, "Black Mountain Technologies  (1592763 B.C. LTD.)   Incorporation No. BC1592763", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 4, "515 Petersen, Campbell River, BC V9W 3H6   |   250-254-2377   |   michael@blackmountaintechnologies.ca", align="C")

    pdf.output(str(path))
    return inv


def make_profile_pdf(path):
    """The Company Profile one-pager — the trust doc sent the moment a clinic wants to see who they're dealing with."""
    pdf = FPDF("P", "mm", "A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    W, M = 210, 20

    # Logo, centered, bigger
    if LOGO.exists():
        lw = 85
        pdf.image(str(LOGO), x=(W - lw) / 2, y=14, w=lw)
        y = 14 + (lw * 943 / 1668) + 5
    else:
        y = 30
    pdf.set_y(y); pdf.set_font("Helvetica", "", 12); pdf.set_text_color(*GREY)
    pdf.cell(0, 6, "Company Profile", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2); pdf.set_draw_color(*LINE); pdf.set_line_width(0.3)
    pdf.line(M, pdf.get_y(), W-M, pdf.get_y()); pdf.ln(6)

    # Who we are
    pdf.set_x(M); pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(*INK)
    pdf.cell(0, 7, "Who We Are", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(M); pdf.set_font("Helvetica", "", 11); pdf.set_text_color(*INK)
    pdf.multi_cell(W-2*M, 6, _ascii(
        "Black Mountain Technologies is an artificial intelligence software company out of British Columbia. "
        "We build AI technologies for appointment-based clinics to retain and reactivate clients, and to recover "
        "the revenue they quietly lose through missed calls and patients who drift away. Everything is fully "
        "managed by us, in-house. Nothing is outsourced, and we keep none of your information."))
    pdf.ln(4)

    # What we do
    pdf.set_x(M); pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(*INK)
    pdf.cell(0, 7, "What We Do", new_x="LMARGIN", new_y="NEXT")
    for title, body in [
        ("Patient Reactivation",
         "We text your dormant patient list back into the chair, in your clinic's name. Booked straight into your calendar. $1,500 one-time, no monthly."),
        ("Missed-Call Text-Back",
         "The moment a call is missed, the caller gets an instant text from you and books, instead of calling the next clinic. Runs 24/7. $1,500 setup + $250/month."),
    ]:
        pdf.set_x(M); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*INK)
        pdf.cell(0, 6, f"-  {title}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(M+4); pdf.set_font("Helvetica", "", 10.5); pdf.set_text_color(*GREY)
        pdf.multi_cell(W-2*M-4, 5.5, _ascii(body)); pdf.ln(2)
    pdf.set_x(M); pdf.set_font("Helvetica", "B", 10.5); pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Both services together: $2,500  (reactivation one-time + missed-call $250/month).", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_x(M); pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(*GREY)
    pdf.multi_cell(W-2*M, 5, "Full privacy policies and terms are available on our website at blackmountaintech.ca.")
    pdf.ln(4)

    # Company details box
    box_y = pdf.get_y()
    pdf.set_fill_color(247, 247, 247); pdf.rect(M, box_y, W-2*M, 54, "F")
    pdf.set_xy(M+4, box_y+4); pdf.set_font("Helvetica", "B", 12); pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Company Details", new_x="LMARGIN", new_y="NEXT")
    details = [
        ("Legal name", "Black Mountain Technologies (1592763 B.C. LTD.)"),
        ("Incorporation No.", "BC1592763  (Province of British Columbia)"),
        ("Registered office", "515 Petersen, Campbell River, BC V9W 3H6"),
        ("Owner / CEO", "Michael Mackrell, Owner & Chief Executive Officer"),
        ("Phone", "250-254-2377"),
        ("Email", "michael@blackmountaintechnologies.ca"),
        ("Website", "blackmountaintech.ca"),
    ]
    ry = box_y + 12
    for label, val in details:
        pdf.set_xy(M+4, ry); pdf.set_font("Helvetica", "B", 9.5); pdf.set_text_color(*GREY)
        pdf.cell(38, 5.4, label)
        pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(*INK)
        pdf.cell(0, 5.4, _ascii(val)); ry += 5.6

    # footer
    pdf.set_y(-22); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y(), W-M, pdf.get_y()); pdf.ln(2)
    pdf.set_font("Helvetica", "", 8.5); pdf.set_text_color(*GREY)
    pdf.cell(0, 4, "Black Mountain Technologies  (1592763 B.C. LTD.)   Incorporation No. BC1592763", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 4, "515 Petersen, Campbell River, BC V9W 3H6   |   250-254-2377   |   michael@blackmountaintechnologies.ca", align="C")
    pdf.output(str(path))


# ---------------- UI ----------------
st.set_page_config(page_title="BMT Tools", page_icon="🧾")
st.title("BMT Tools")

mode = st.radio("What do you need?", ["Receipt", "Company Profile", "Prospects"], horizontal=True)
st.divider()

if mode == "Prospects":
    rows = _load_leads()
    prospects = [r for r in rows if r["status"] == "prospect"]
    clients = [r for r in rows if r["status"] == "client"]
    c1, c2 = st.columns(2)
    c1.metric("Prospects", len(prospects))
    c2.metric("Clients", len(clients))
    if rows:
        with open(LEADS, "rb") as f:
            st.download_button("Download full list (CSV)", f, file_name="BMT_leads.csv",
                               mime="text/csv", use_container_width=True)
    st.subheader("Prospects")
    if not prospects:
        st.caption("No prospects yet. Every company profile you send lands here.")
    for r in prospects:
        cols = st.columns([3, 2, 1.4])
        cols[0].write(r["email"])
        cols[1].write(r.get("clinic") or "—")
        if cols[2].button("→ Client", key="c_" + r["email"]):
            set_status(r["email"], "client"); st.rerun()
    if clients:
        st.subheader("Clients")
        for r in clients:
            cols = st.columns([3, 2, 1.4])
            cols[0].write("✅ " + r["email"])
            cols[1].write(r.get("clinic") or "—")
            if cols[2].button("↩ Prospect", key="p_" + r["email"]):
                set_status(r["email"], "prospect"); st.rerun()
    st.stop()

if mode == "Company Profile":
    st.caption("Send the company profile the second they say yes. Just an email — it fires instantly.")
    prof_email = st.text_input("Their email", placeholder="jane@smithdental.ca")
    if st.button("Generate profile", type="primary", use_container_width=True):
        ppath = OUT / "company_profile.pdf"
        make_profile_pdf(ppath)
        st.session_state["prof_path"] = str(ppath)
        st.success("Company profile generated.")
    if st.session_state.get("prof_path"):
        ppath = Path(st.session_state["prof_path"])
        with open(ppath, "rb") as f:
            st.download_button("View / download PDF", f, file_name="Black_Mountain_Technologies_Profile.pdf",
                               mime="application/pdf", use_container_width=True)
        method_active = configured_method()
        send_label = "Send profile" if method_active != "none" else "Send (email not configured)"
        if st.button(send_label, use_container_width=True, disabled=(method_active == "none" or not prof_email)):
            body = (
                "Hi,\n\n"
                "Great talking with you. As promised, our company profile is attached so you can see exactly who "
                "you're working with, our BC incorporation, registered office, and the two services we run for clinics.\n\n"
                "Everything's also on our site at blackmountaintech.ca.\n\n"
                "To lock in your spot for this week, an e-transfer to "
                "michael@blackmountaintechnologies.ca is easiest. A card link works too, it just carries a 3% fee.\n\n"
                "Talk soon,\n"
                "Michael Mackrell\n"
                "Owner & CEO, Black Mountain Technologies\n"
                "250-254-2377  |  blackmountaintech.ca"
            )
            res = send_email(
                to=prof_email,
                subject="Black Mountain Technologies - Company Profile",
                body_text=body,
                attachments=[ppath],
            )
            if res.get("ok"):
                log_lead(prof_email, status="prospect")
                st.success(f"Sent to {prof_email} ✅  (logged as a prospect)")
            else:
                st.error(f"Could not send: {res.get('reason','unknown error')}")
        if method_active == "none":
            st.caption("Email sending isn't set up yet. Once the Gmail app password is on Render, Send goes live.")
    st.stop()

st.caption("Black Mountain Technologies — generate a branded receipt and email it on the spot.")

col1, col2 = st.columns(2)
service_name = st.selectbox("Service", list(SERVICES.keys()))
svc = SERVICES[service_name]

if service_name == "Custom":
    custom_desc = st.text_input("Custom description", "")
    amount = st.number_input("Amount ($)", min_value=0.0, value=1000.0, step=50.0)
    monthly = st.number_input("Monthly recurring ($, 0 if none)", min_value=0.0, value=0.0, step=50.0)
    service_desc = custom_desc or "Custom service"
    service_detail = st.text_input("Description line (optional)", "")
else:
    amount = float(svc["amount"]); monthly = float(svc["monthly"])
    service_desc = service_name
    service_detail = svc.get("desc", "")
    st.info(f"Amount: ${amount:,.2f}" + (f"  •  then ${monthly:,.0f}/mo" if monthly else ""))

clinic = st.text_input("Company name", placeholder="Smith Family Dental")
payer = st.text_input("Name of person who authorized payment", placeholder="Dr. Jane Smith")
company_address = st.text_input("Company address", placeholder="123 Main St, Campbell River, BC")
to_email = st.text_input("Company email", placeholder="jane@smithdental.ca")
company_phone = st.text_input("Company phone", placeholder="250-555-1234")
c1, c2 = st.columns(2)
date_str = c1.date_input("Date", dt.date.today()).strftime("%Y-%m-%d")
method = c2.selectbox("Payment method", ["E-transfer", "Cash", "Card (Stripe)", "Cheque"])

st.divider()

if st.button("Generate receipt", type="primary", use_container_width=True):
    path = OUT / "receipt_preview.pdf"
    inv = make_receipt_pdf(service_desc, amount, monthly, clinic, payer, date_str, method, path,
                           service_detail, company_address, to_email, company_phone)
    st.session_state["pdf_path"] = str(path)
    st.session_state["inv"] = inv
    st.session_state["pdf_clinic"] = clinic
    st.success(f"Generated receipt {inv}.")

if st.session_state.get("pdf_path"):
    path = Path(st.session_state["pdf_path"])
    with open(path, "rb") as f:
        st.download_button("View / download PDF", f, file_name=f"BMT_Receipt_{(clinic or 'client').replace(' ','_')}.pdf",
                           mime="application/pdf", use_container_width=True)

    method_active = configured_method()
    send_label = "Send to client" if method_active != "none" else "Send (email not configured)"
    if st.button(send_label, use_container_width=True, disabled=(method_active == "none" or not to_email)):
        body = (
            f"Hi{(' ' + payer) if payer else ''},\n\n"
            f"Thank you. Please find your receipt attached for {service_desc}.\n\n"
            "If you have any questions just reply to this email.\n\n"
            "Michael Mackrell\n"
            "Black Mountain Technologies\n"
            "250-254-2377  |  michael@blackmountaintechnologies.ca"
        )
        res = send_email(
            to=to_email,
            subject=f"Your receipt from Black Mountain Technologies ({st.session_state.get('inv','')})",
            body_text=body,
            attachments=[path],
        )
        if res.get("ok"):
            log_lead(to_email, clinic=clinic, status="client")
            st.success(f"Sent to {to_email} ✅  (logged as a client)")
        else:
            st.error(f"Could not send: {res.get('reason','unknown error')}")
    if method_active == "none":
        st.caption("Email sending isn't set up yet. Once the Gmail app password is added on Render, the Send button goes live.")
