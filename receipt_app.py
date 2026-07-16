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

# --- Persistent data dir (so contacts survive Render deploys, same as the BMDW estimator) ---
# Resolution order: BMT_DATA_DIR env -> /var/data (Render persistent disk) -> ./data (local dev).
def _data_dir() -> Path:
    import os as _os
    env = _os.environ.get("BMT_DATA_DIR", "").strip()
    if env:
        p = Path(env)
    else:
        var_data = Path("/var/data")
        try:
            usable = var_data.exists() and _os.access(str(var_data), _os.W_OK)
        except Exception:
            usable = False
        p = var_data if usable else (HERE / "data")
    p.mkdir(parents=True, exist_ok=True)
    return p

DATA_DIR = _data_dir()

# --- CRM: company profiles (email -> full record + history) ---
import csv as _csv
LEADS = DATA_DIR / "leads_log.csv"

# One-time migration: if an old leads_log.csv sits in the repo root (ephemeral),
# copy it into the persistent data dir so nothing already saved is lost.
_OLD_LEADS = HERE / "leads_log.csv"
if _OLD_LEADS.exists() and not LEADS.exists():
    try:
        import shutil as _shutil
        _shutil.copy2(_OLD_LEADS, LEADS)
    except Exception:
        pass

FIELDS = ["email", "clinic", "contact_name", "trade", "status",
          "meeting_date", "meeting_time", "first_contact", "history", "notes"]

def _load_leads():
    if not LEADS.exists():
        return []
    with open(LEADS, newline="", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    # backfill any new columns on old rows so nothing breaks
    for r in rows:
        for k in FIELDS:
            r.setdefault(k, "")
    return rows

def _save_leads(rows):
    with open(LEADS, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})

def _today():
    return dt.datetime.now().strftime("%Y-%m-%d")

# Clean list of times (every 15 min, 6am-8pm) for a simple dropdown — no clunky time_input box.
TIME_CHOICES = []
for _h in range(6, 21):
    for _m in (0, 15, 30, 45):
        TIME_CHOICES.append(dt.time(_h, _m))
def _fmt_time(t):
    return t.strftime("%-I:%M %p")
def _nearest_time_index(t):
    """Index of the closest choice to a given time (for prefill)."""
    best_i, best_d = 0, 10**9
    for i, c in enumerate(TIME_CHOICES):
        d = abs((c.hour*60+c.minute) - (t.hour*60+t.minute))
        if d < best_d: best_i, best_d = i, d
    return best_i

def get_lead(email):
    email = (email or "").strip().lower()
    for r in _load_leads():
        if r["email"] == email:
            return r
    return None

def log_lead(email, clinic="", status="prospect", contact_name="", trade="",
             meeting_date="", meeting_time="", event=""):
    """Upsert a company profile. `event` gets appended to the history timeline."""
    email = (email or "").strip().lower()
    if not email:
        return
    rows = _load_leads()
    stamp = _today()
    for r in rows:
        if r["email"] == email:
            if clinic and not r.get("clinic"): r["clinic"] = clinic
            if contact_name and not r.get("contact_name"): r["contact_name"] = contact_name
            if trade: r["trade"] = trade
            if meeting_date: r["meeting_date"] = meeting_date
            if meeting_time: r["meeting_time"] = meeting_time
            if status: r["status"] = status
            if event:
                r["history"] = ((r.get("history", "") + " | ") if r.get("history") else "") + f"{stamp}: {event}"
            _save_leads(rows); return
    rows.append({"email": email, "clinic": clinic, "contact_name": contact_name,
                 "trade": trade, "status": status, "meeting_date": meeting_date,
                 "meeting_time": meeting_time, "first_contact": stamp,
                 "history": (f"{stamp}: {event}" if event else ""), "notes": ""})
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
    "Client Reactivation Campaign (one-time)": {"amount": 1500, "monthly": 0,
        "desc": "A done-for-you campaign that reaches your old quotes and past clients in your name and invites them back in. Their data stays with you. Set up and live within the week."},
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
        "We build AI technologies for construction companies to win back and reactivate clients, and to recover "
        "the revenue they quietly lose through missed calls and quotes that never close. Everything is fully "
        "managed by us, in-house. Nothing is outsourced, and we keep none of your information."))
    pdf.ln(4)

    # What we do
    pdf.set_x(M); pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(*INK)
    pdf.cell(0, 7, "What We Do", new_x="LMARGIN", new_y="NEXT")
    for title, body in [
        ("Client Reactivation",
         "We text your old quotes and past clients back into the pipeline, in your company's name. Booked straight onto your calendar, with almost nothing on your end."),
        ("Missed-Call Text-Back",
         "The moment a call is missed, the caller gets an instant text from you and books an estimate, instead of calling the next contractor. Runs 24/7."),
    ]:
        pdf.set_x(M); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*INK)
        pdf.cell(0, 6, f"-  {title}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(M+4); pdf.set_font("Helvetica", "", 10.5); pdf.set_text_color(*GREY)
        pdf.multi_cell(W-2*M-4, 5.5, _ascii(body)); pdf.ln(2)
    pdf.ln(1)
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
st.set_page_config(page_title="BMT Tools", page_icon="⛰️", layout="centered",
                   initial_sidebar_state="collapsed")

# --- Sleek DARK mobile-first theme with tactile buttons (forced dark so text always reads) ---
st.markdown("""
<style>
:root {
  --blue:#3b82f6; --blue-d:#2563eb;
  --bg:#0d1017; --bg2:#12161f; --card:#1a1f2b; --card2:#20263400;
  --ink:#f2f5f9; --muted:#9aa4b2; --line:#2b3444;
}
/* force everything dark + light text */
.stApp, body { background: var(--bg) !important; color: var(--ink) !important; }
.block-container { padding-top: 1.1rem; padding-bottom: 4rem; max-width: 640px; }
#MainMenu, footer, header { visibility: hidden; }
html, body, [class*="css"] { -webkit-tap-highlight-color: transparent; }
/* make ALL default text light so nothing is invisible */
.stApp, .stMarkdown, .stMarkdown p, label, .stCaption, p, span, div,
h1,h2,h3,h4,h5,h6, .stRadio label, [data-testid="stWidgetLabel"] { color: var(--ink) !important; }
.stCaption, small, [data-testid="stCaptionContainer"] { color: var(--muted) !important; }

/* hero header */
.bmt-hero {
  background: linear-gradient(135deg, #1a2234 0%, #10151f 100%);
  color:#fff; border-radius:18px; padding:20px 22px; margin-bottom:18px;
  border:1px solid var(--line);
  box-shadow:0 10px 30px rgba(0,0,0,.45);
}
.bmt-hero h1 { font-size:1.35rem; font-weight:800; margin:0; letter-spacing:-.01em; color:#fff !important; }
.bmt-hero p { margin:.25rem 0 0; font-size:.85rem; color:#aab3c2 !important; }

/* inputs — dark fields, light text, big tap targets */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input {
  border-radius:12px !important; border:1.5px solid var(--line) !important;
  padding:12px 14px !important; font-size:16px !important;
  background:var(--card) !important; color:var(--ink) !important;
  transition:border-color .15s ease, box-shadow .15s ease;
}
.stTextInput input::placeholder, .stNumberInput input::placeholder { color:#6b7688 !important; }
.stTextInput input:focus, .stNumberInput input:focus {
  border-color:var(--blue) !important; box-shadow:0 0 0 3px rgba(59,130,246,.22) !important;
}
/* selectbox / time / date FIELDS — dark bg, light text (the value shown in the closed box) */
div[data-baseweb="select"] > div,
div[data-baseweb="select"] > div > div,
div[data-baseweb="input"] {
  border-radius:12px !important; border:1.5px solid var(--line) !important;
  background:var(--card) !important; color:var(--ink) !important; font-size:16px !important;
}
div[data-baseweb="select"] *, div[data-baseweb="input"] * { color:var(--ink) !important; }
/* make time/date/select inputs fill their column — kill the wasted empty box */
.stTimeInput div[data-baseweb="select"],
.stDateInput div[data-baseweb="input"],
.stSelectbox div[data-baseweb="select"],
.stTimeInput > div, .stDateInput > div, .stSelectbox > div { width:100% !important; }

/* ANY popup/dropdown/menu that overlays the page — force light text on dark.
   Streamlit renders these in a portal at the END of the body, so target broadly. */
div[data-baseweb="popover"] *,
div[data-baseweb="menu"] *,
div[data-baseweb="calendar"] *,
ul[role="listbox"] *,
[role="option"],
[data-baseweb="popover"] li,
[data-baseweb="menu"] li {
  color:#f2f5f9 !important;
}
div[data-baseweb="popover"] > div,
div[data-baseweb="menu"],
ul[role="listbox"],
div[data-baseweb="calendar"] {
  background:#1a1f2b !important;
}
[role="option"]:hover, ul[role="listbox"] li:hover, [data-baseweb="menu"] li:hover {
  background:#2a3345 !important;
}
div[data-baseweb="calendar"] [aria-selected="true"] { background:#3b82f6 !important; color:#fff !important; }

/* BUTTONS — tactile / clicky, dark base, press-down on tap */
.stButton > button, .stDownloadButton > button {
  border-radius:13px !important; font-weight:700 !important; font-size:15px !important;
  padding:13px 18px !important; border:1.5px solid var(--line) !important;
  background:var(--card) !important; color:var(--ink) !important;
  box-shadow:0 3px 0 #0a0d13, 0 6px 16px rgba(0,0,0,.4) !important;
  transition:transform .06s ease, box-shadow .12s ease, background .15s ease !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  transform:translateY(-1px); border-color:#3a4658 !important;
  box-shadow:0 5px 0 #0a0d13, 0 10px 22px rgba(0,0,0,.5) !important;
}
.stButton > button:active, .stDownloadButton > button:active {
  transform:translateY(3px);
  box-shadow:0 0 0 #0a0d13, inset 0 2px 8px rgba(0,0,0,.5) !important;
}
/* primary = blue gradient, clicky */
.stButton > button[kind="primary"], .stButton > button[data-testid="baseButton-primary"] {
  background:linear-gradient(180deg,var(--blue) 0%,var(--blue-d) 100%) !important;
  color:#fff !important; border:none !important;
  box-shadow:0 4px 0 #1e4fb8, 0 10px 24px rgba(37,99,235,.5) !important;
}
.stButton > button[kind="primary"]:active {
  transform:translateY(4px);
  box-shadow:0 0 0 #1e4fb8, inset 0 3px 10px rgba(0,0,0,.4) !important;
}

/* profile cards */
.bmt-card {
  background:var(--card); border:1.5px solid var(--line); border-radius:15px;
  padding:15px 16px; margin-bottom:12px; box-shadow:0 2px 12px rgba(0,0,0,.35);
}
.bmt-card .nm { font-weight:800; font-size:1rem; color:var(--ink) !important; }
.bmt-card .em { font-size:.83rem; color:var(--muted) !important; }
.bmt-chip { display:inline-block; background:#22304d; color:#8fb4ff !important;
  font-size:.72rem; font-weight:700; padding:3px 9px; border-radius:999px; margin-right:6px; }
.bmt-chip.win { background:#16351f; color:#5fd98a !important; }
.bmt-hist { font-size:.78rem; color:var(--muted) !important; margin-top:8px; line-height:1.5; }

/* metrics */
div[data-testid="stMetricValue"] { font-size:1.6rem; font-weight:800; color:var(--ink) !important; }
div[data-testid="stMetricLabel"] { color:var(--muted) !important; }
div[data-testid="stMetric"] { background:var(--card); border:1px solid var(--line);
  border-radius:14px; padding:12px 14px; }

/* top nav radio = pill tabs */
div[role="radiogroup"] { gap:8px; flex-wrap:wrap; }
div[role="radiogroup"] label {
  background:var(--card) !important; border:1.5px solid var(--line); border-radius:11px;
  padding:9px 14px; font-weight:700; font-size:14px; transition:all .12s ease;
}
div[role="radiogroup"] label:hover { border-color:var(--blue); }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="bmt-hero"><h1>⛰️ Black Mountain Tools</h1>'
    '<p>Profiles · receipts · meeting reminders — send in one tap</p></div>',
    unsafe_allow_html=True)

mode = st.radio("What do you need?", ["Company Profile", "Meeting Reminder", "Receipt", "Profiles"],
                horizontal=True, label_visibility="collapsed")
st.write("")

def _profile_card(r, key_prefix):
    """Render one company profile as a card with name, trade, meeting, and history."""
    name = r.get("contact_name") or ""
    company = r.get("clinic") or ""
    title = company or name or r["email"]
    sub = (name + "  ·  " if name and company else "") + r["email"]
    is_client = r.get("status") == "client"
    chips = ""
    if r.get("trade"):
        chips += f'<span class="bmt-chip">{r["trade"]}</span>'
    if r.get("meeting_date"):
        mt = r.get("meeting_time", "")
        chips += f'<span class="bmt-chip">📅 {r["meeting_date"]}{(" " + mt) if mt else ""}</span>'
    chips += (f'<span class="bmt-chip win">Client</span>' if is_client
              else '<span class="bmt-chip">Prospect</span>')
    hist = r.get("history", "")
    hist_html = f'<div class="bmt-hist">{hist.replace(" | ", "<br>")}</div>' if hist else ""
    st.markdown(
        f'<div class="bmt-card"><div class="nm">{title}</div>'
        f'<div class="em">{sub}</div><div style="margin-top:8px">{chips}</div>'
        f'{hist_html}</div>', unsafe_allow_html=True)
    if is_client:
        if st.button("↩ Back to prospect", key=key_prefix + "_p", use_container_width=True):
            set_status(r["email"], "prospect"); st.rerun()
    else:
        if st.button("✓ Mark as client", key=key_prefix + "_c", use_container_width=True):
            set_status(r["email"], "client"); st.rerun()

if mode == "Profiles":
    rows = _load_leads()
    prospects = [r for r in rows if r.get("status") != "client"]
    clients = [r for r in rows if r.get("status") == "client"]
    c1, c2 = st.columns(2)
    c1.metric("Prospects", len(prospects))
    c2.metric("Clients", len(clients))

    q = st.text_input("Search", placeholder="Search by name, company, or email")
    if rows:
        with open(LEADS, "rb") as f:
            st.download_button("⬇ Download all (CSV)", f, file_name="BMT_profiles.csv",
                               mime="text/csv", use_container_width=True)

    def _match(r):
        if not q: return True
        blob = " ".join([r.get("email",""), r.get("clinic",""), r.get("contact_name",""), r.get("trade","")]).lower()
        return q.lower() in blob

    st.write("")
    st.markdown("**Prospects**")
    shown = [r for r in prospects if _match(r)]
    if not shown:
        st.caption("No prospects yet. Every profile or reminder you send lands here.")
    for i, r in enumerate(shown):
        _profile_card(r, f"pros_{i}")
    if clients:
        st.markdown("**Clients**")
        for i, r in enumerate([r for r in clients if _match(r)]):
            _profile_card(r, f"cli_{i}")
    st.stop()

if mode == "Company Profile":
    st.caption("Send the company profile with the matching Revenue Snapshot. Pick their market, drop in the email, send.")

    # --- Market pick (drives which Revenue Snapshot gets attached) ---
    SNAP_DIR = HERE / "snapshots"
    # ICP: BC construction companies, ~$250K-$2M/yr, NOT the North Island
    # (excludes Comox, Cumberland, Courtenay, Campbell River). Buttons = trades.
    MARKETS = {
        "Excavation": "Revenue_Snapshot_Excavation.pdf",
        "Concrete": "Revenue_Snapshot_Concrete.pdf",
        "Roofing": "Revenue_Snapshot_Roofing.pdf",
        "HVAC": "Revenue_Snapshot_HVAC.pdf",
        "Plumbing": "Revenue_Snapshot_Plumbing.pdf",
        "Framing": "Revenue_Snapshot_Framing.pdf",
        "Drywall": "Revenue_Snapshot_Drywall.pdf",
        "Painting": "Revenue_Snapshot_Painting.pdf",
    }
    st.write("**Their market**")
    mcols = st.columns(4)
    for i, name in enumerate(MARKETS):
        if mcols[i % 4].button(name, key="mkt_" + name, use_container_width=True,
                               type=("primary" if st.session_state.get("prof_market") == name else "secondary")):
            st.session_state["prof_market"] = name
    chosen_market = st.session_state.get("prof_market")
    if chosen_market:
        snap_path = SNAP_DIR / MARKETS[chosen_market]
        if snap_path.exists():
            st.success(f"Market: {chosen_market}  —  snapshot will be attached.")
        else:
            st.warning(f"Market: {chosen_market}  —  snapshot file not found ({MARKETS[chosen_market]}). Profile only.")
    else:
        st.caption("No market selected — the email will send the profile only, no snapshot.")

    prof_email = st.text_input("Their email", placeholder="jane@smithcontracting.ca")

    # --- WHO am I sending to? Owner (already sold, confirm the meeting) vs Gatekeeper (arm them to push it up the chain) ---
    st.write("**Who are you sending to?**")
    wcols = st.columns(2)
    if wcols[0].button("Owner", key="aud_owner", use_container_width=True,
                       type=("primary" if st.session_state.get("prof_audience") == "owner" else "secondary")):
        st.session_state["prof_audience"] = "owner"
    if wcols[1].button("Gatekeeper", key="aud_gate", use_container_width=True,
                       type=("primary" if st.session_state.get("prof_audience") == "gatekeeper" else "secondary")):
        st.session_state["prof_audience"] = "gatekeeper"
    audience = st.session_state.get("prof_audience", "owner")
    st.caption(f"Sending the **{audience}** version.")

    # Company name (both paths); owner path always gets a name field for a personal greeting
    owner_name = company_name = None
    if audience == "gatekeeper":
        gc1, gc2 = st.columns(2)
        owner_name = gc1.text_input("Owner's name (optional)", placeholder="Dave")
        company_name = gc2.text_input("Company name (optional)", placeholder="Smith Contracting")

    # --- Their name — ALWAYS available on the owner path so even a no-meeting email opens "Hey Dave," ---
    meet_name = meet_date = meet_time = None
    meet_link = None  # link never sent from the profile email — reminder mode handles it
    if audience == "owner":
        meet_name = st.text_input("Their name (for the greeting)", placeholder="Dave")
        company_name = st.text_input("Company name (optional)", placeholder="Smith Contracting")

    # --- Optionally lock in a meeting date + time. If they didn't book, leave it off —
    #     the email still goes out personally addressed, just without a meeting line. ---
    add_meeting = st.checkbox("Lock in a meeting time", value=False)
    if add_meeting:
        mc1, mc2 = st.columns(2)
        meet_date = mc1.date_input("Meeting date")
        meet_time = mc2.selectbox("Meeting time", TIME_CHOICES,
                                  index=_nearest_time_index(dt.time(10, 30)), format_func=_fmt_time)
        st.caption("The Zoom/Meet link is NOT sent now — it goes out the day before from the Meeting Reminder tab.")

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
            attachments = [ppath]
            # Gatekeeper always carries the trade snapshot (it's their ammo upstairs); owner carries it only if a market's picked.
            snap_attached = False
            if chosen_market:
                sp = SNAP_DIR / MARKETS[chosen_market]
                if sp.exists():
                    attachments.append(sp)
                    snap_attached = True

            SIG = (
                "Regards,\n"
                "Michael Mackrell\n"
                "Owner, Black Mountain Technologies\n"
                "250-254-2377\n"
                "blackmountaintech.ca\n"
                "michael@blackmountaintechnologies.ca"
            )
            greet_name = (meet_name or "").strip() if audience == "owner" else ""
            hi = f"Hey {greet_name}," if greet_name else "Hey,"
            opener = f"{hi}\n\nThis is Michael at Black Mountain Technologies. Nice talking with you today.\n\n"

            if audience == "gatekeeper":
                # --- GATEKEEPER VERSION: arm them to push it up the chain ---
                subject = (f"For {owner_name.strip()} whenever he has a minute"
                           if owner_name and owner_name.strip()
                           else "Black Mountain Technologies - for the owner whenever he has a minute")
                trade = (chosen_market or "construction").lower()
                who = owner_name.strip() if (owner_name and owner_name.strip()) else "the owner"
                whose = company_name.strip() if (company_name and company_name.strip()) else "your company"
                body = (
                    opener +
                    "Attached is our company profile so you can see exactly who you are going to be working with.\n\n"
                    f"Here is the short version so you know what it is. Companies in {trade} miss roughly 1 in 5 of "
                    "their job calls because the crew is out on a site, and every missed caller just phones the next "
                    "company. Over a year that adds up to tens of thousands of dollars walking out the door, and the "
                    "attached sheet shows the exact numbers.\n\n"
                    f"We fix it with a system that texts every missed caller back in seconds, so the job books with "
                    f"{whose} instead of the competition, and it runs completely on its own. No management or IT skills "
                    "required at the company. This is an extremely easy and proven way to increase revenue, build "
                    "reputation, take work off everyone's plate, and add some peace of mind. The setup and onboarding "
                    "are simple, and the value far outweighs the cost.\n\n"
                    f"Getting this in front of {who} would be a smart move, whoever brings this to the table is going "
                    "to look very good for it.\n\n"
                    "If you would like to talk to us, you can book a meeting on our website, reply to this email, or "
                    "give us a call.\n\n"
                    + SIG
                )
            else:
                # --- OWNER VERSION: meeting already booked, confirm it and get out. No re-selling.
                #     NO link here — the day-before reminder (separate mode) carries the link. ---
                subject = "Black Mountain Technologies - Company Profile"
                if add_meeting and meet_date and meet_time:
                    # meeting booked → confirm it, no re-selling
                    when = f"{meet_date.strftime('%A, %B %-d')} at {meet_time.strftime('%-I:%M %p')}"
                    subject = f"Confirmed, {when}"
                    close_line = (f"Here is the day and time we locked in for that quick meeting: {when}. "
                                  "I will send you the meeting link the day before.\n\n")
                else:
                    # NO meeting booked (warm owner who said "send me an email") → invite them to book
                    close_line = ("If you would like to talk it through, you can book a meeting on our website, "
                                  "reply to this email, or give me a call.\n\n")
                body = (
                    opener +
                    "Attached is our company profile so you can see exactly who you are going to be working with.\n\n"
                    + close_line
                    + SIG
                )
            res = send_email(
                to=prof_email,
                subject=subject,
                body_text=body,
                attachments=attachments,
            )
            if res.get("ok"):
                # save the full profile + history so this company shows in Profiles + the reminder dropdown
                md = meet_date.strftime("%Y-%m-%d") if (add_meeting and meet_date) else ""
                mtm = meet_time.strftime("%-I:%M %p") if (add_meeting and meet_time) else ""
                nm = (meet_name or owner_name or "").strip()
                ev = ("Sent profile + booked meeting" if md else
                      ("Sent gatekeeper profile" if audience == "gatekeeper" else "Sent profile"))
                log_lead(prof_email, status="prospect", contact_name=nm,
                         trade=(chosen_market or ""), meeting_date=md, meeting_time=mtm,
                         clinic=(company_name or ""), event=ev)
                st.success(f"Sent to {prof_email} ✅  (saved to Profiles)")
            else:
                st.error(f"Could not send: {res.get('reason','unknown error')}")
        if method_active == "none":
            st.caption("Email sending isn't set up yet. Once the Gmail app password is on Render, Send goes live.")
    st.stop()

# ==================== MEETING REMINDER + INVITE ====================
if mode == "Meeting Reminder":
    st.caption("Send the day-before reminder with the Zoom/Meet link. Pick a saved contact or type a new one.")
    rows = _load_leads()
    # anyone with a meeting booked floats to the top of the picker
    booked = [r for r in rows if r.get("meeting_date")]
    others = [r for r in rows if not r.get("meeting_date")]
    picker = ["— New / type manually —"] + [
        f'{(r.get("contact_name") or r.get("clinic") or r["email"])}  ·  {r["email"]}'
        for r in (booked + others)
    ]
    pick = st.selectbox("Who are you reminding?", picker)

    # prefill from the chosen saved contact
    pre_email = pre_name = ""
    pre_date = dt.date.today() + dt.timedelta(days=1)
    pre_time = dt.time(10, 30)
    if pick != picker[0]:
        r = (booked + others)[picker.index(pick) - 1]
        pre_email = r["email"]
        pre_name = r.get("contact_name") or ""
        if r.get("meeting_date"):
            try: pre_date = dt.datetime.strptime(r["meeting_date"], "%Y-%m-%d").date()
            except Exception: pass
        if r.get("meeting_time"):
            for fmt in ("%I:%M %p", "%-I:%M %p", "%H:%M"):
                try: pre_time = dt.datetime.strptime(r["meeting_time"], fmt).time(); break
                except Exception: pass

    rem_name = st.text_input("Their name", value=pre_name, placeholder="Harmon")
    rem_email = st.text_input("Their email", value=pre_email, placeholder="harmon@company.ca")
    rc1, rc2 = st.columns(2)
    rem_date = rc1.date_input("Meeting date", value=pre_date)
    rem_time = rc2.selectbox("Meeting time", TIME_CHOICES, index=_nearest_time_index(pre_time),
                             format_func=_fmt_time)
    rem_link = st.text_input("Meeting link (Zoom / Google Meet)",
                             placeholder="https://meet.google.com/xxx  or  https://zoom.us/j/xxxx")

    # tomorrow vs a dated day, phrased naturally
    days_out = (rem_date - dt.date.today()).days
    if days_out == 1: whenword = "tomorrow"
    elif days_out == 0: whenword = "today"
    else: whenword = rem_date.strftime("%A, %B %-d")
    time_str = rem_time.strftime("%-I:%M %p")

    method_active = configured_method()
    send_label = "Send reminder + link" if method_active != "none" else "Send (email not configured)"
    disabled = (method_active == "none" or not rem_email or not rem_link)
    if not rem_link and rem_email:
        st.caption("Add the meeting link to enable send.")

    if st.button(send_label, type="primary", use_container_width=True, disabled=disabled):
        hi = f"Hey {rem_name.strip()}," if rem_name.strip() else "Hey,"
        subject = f"Reminder - our meeting {whenword} at {time_str}"
        body = (
            f"{hi}\n\n"
            f"It's Michael at Black Mountain Technologies. Just reminding you of our meeting {whenword} "
            f"at {time_str}. Looking forward to speaking with you.\n\n"
            f"Here is the link to join: {rem_link}\n\n"
            "Regards,\n"
            "Michael Mackrell\n"
            "Owner, Black Mountain Technologies\n"
            "250-254-2377\n"
            "blackmountaintech.ca\n"
            "michael@blackmountaintechnologies.ca"
        )
        res = send_email(to=rem_email, subject=subject, body_text=body, attachments=[])
        if res.get("ok"):
            log_lead(rem_email, contact_name=rem_name.strip(),
                     meeting_date=rem_date.strftime("%Y-%m-%d"), meeting_time=time_str,
                     event=f"Sent meeting reminder + link ({whenword} {time_str})")
            st.success(f"Reminder sent to {rem_email} ✅")
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

clinic = st.text_input("Company name", placeholder="Smith Contracting Ltd.")
payer = st.text_input("Name of person who authorized payment", placeholder="Dr. Jane Smith")
company_address = st.text_input("Company address", placeholder="123 Main St, Campbell River, BC")
to_email = st.text_input("Company email", placeholder="jane@smithcontracting.ca")
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
            log_lead(to_email, clinic=clinic, status="client",
                     contact_name=(payer or ""),
                     event=f"Sent receipt {st.session_state.get('inv','')} for {service_desc}")
            st.success(f"Sent to {to_email} ✅  (logged as a client)")
        else:
            st.error(f"Could not send: {res.get('reason','unknown error')}")
    if method_active == "none":
        st.caption("Email sending isn't set up yet. Once the Gmail app password is added on Render, the Send button goes live.")
