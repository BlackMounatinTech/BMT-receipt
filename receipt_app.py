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


def make_receipt_pdf(service_desc, amount, monthly, clinic, payer, date_str, method, path, service_detail=""):
    service_desc = _ascii(service_desc); clinic = _ascii(clinic); payer = _ascii(payer)
    service_detail = _ascii(service_detail)
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
        pdf.set_x(M); pdf.cell(W-2*M, 5.5, payer, align="R", new_x="LMARGIN", new_y="NEXT")
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


# ---------------- UI ----------------
st.set_page_config(page_title="BMT Receipt", page_icon="🧾")
st.title("BMT Receipt")
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

clinic = st.text_input("Business / clinic name", placeholder="Smith Family Dental")
payer = st.text_input("Paid by (contact name)", placeholder="Dr. Jane Smith")
to_email = st.text_input("Send receipt to (their email)", placeholder="jane@smithdental.ca")
c1, c2 = st.columns(2)
date_str = c1.date_input("Date", dt.date.today()).strftime("%Y-%m-%d")
method = c2.selectbox("Payment method", ["E-transfer", "Cash", "Card (Stripe)", "Cheque"])

st.divider()

if st.button("Generate receipt", type="primary", use_container_width=True):
    path = OUT / "receipt_preview.pdf"
    inv = make_receipt_pdf(service_desc, amount, monthly, clinic, payer, date_str, method, path, service_detail)
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
            st.success(f"Sent to {to_email} ✅")
        else:
            st.error(f"Could not send: {res.get('reason','unknown error')}")
    if method_active == "none":
        st.caption("Email sending isn't set up yet. Once the Gmail app password is added on Render, the Send button goes live.")
