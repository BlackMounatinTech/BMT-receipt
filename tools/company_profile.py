#!/usr/bin/env python3
"""
Company Profile generator for Black Mountain Technologies.
The trust one-pager sent the moment a clinic says yes on a cold call.
States the real incorporation + registered office so the buyer feels safe to e-transfer.

Usage:
    python3 company_profile.py                    # generates the generic profile
    python3 company_profile.py "Evolve Dental"    # personalizes "Prepared for: Evolve Dental"
Output: Company_Profile.pdf  (open it, attach to the email)
"""
import sys, os

# --- REAL COMPANY FACTS (from BMT incorporation) ---
LEGAL_NAME   = "Black Mountain Technologies (1592763 B.C. LTD.)"
TRADE_NAME   = "Black Mountain Technologies"
INCORP_NO    = "BC1592763"
OFFICE       = "515 Petersen, Campbell River, BC V9W 3H6"
PHONE        = "250-254-2377"
EMAIL        = "michael@blackmountaintechnologies.ca"
WEBSITE      = "blackmountaintech.ca"
OWNER        = "Michael Mackrell"
TITLE        = "Owner & Chief Executive Officer"

def build(prepared_for=None):
    try:
        from fpdf import FPDF
    except ImportError:
        sys.exit("Need fpdf2:  pip install fpdf2")

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    W = pdf.w
    DARK = (20, 20, 20)
    GRAY = (105, 105, 105)
    LINE = (210, 210, 210)
    LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets_logo.png")

    # --- Logo, centered at top ---
    try:
        lw = 60  # mm (bigger)
        lh = lw * 943 / 1668
        pdf.image(LOGO, x=(W - lw) / 2, y=14, w=lw)
        y = 14 + lh + 5
    except Exception:
        pdf.set_xy(0, 18); pdf.set_font("Helvetica", "B", 20); pdf.set_text_color(*DARK)
        pdf.cell(0, 8, "BLACK MOUNTAIN TECHNOLOGIES", align="C"); y = 34

    pdf.set_xy(0, y)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*GRAY)
    pdf.cell(W, 6, "Company Profile", align="C")
    y += 8
    # thin rule
    pdf.set_draw_color(*LINE); pdf.set_line_width(0.3)
    pdf.line(20, y, W - 20, y)
    y += 8

    # --- Who we are ---
    pdf.set_xy(20, y)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 7, "Who We Are")
    y += 9
    pdf.set_xy(20, y)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(W - 40, 6,
        "Black Mountain Technologies is an artificial intelligence software company out of British Columbia. "
        "We build AI technologies for appointment-based clinics to retain and reactivate clients, and to recover "
        "the revenue they quietly lose through missed calls and patients who drift away. Everything is fully "
        "managed by us, in-house. Nothing is outsourced, and we keep none of your information.")
    y = pdf.get_y() + 7

    # --- The two services ---
    pdf.set_xy(20, y)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 7, "What We Do")
    y += 9
    for title, body in [
        ("Patient Reactivation",
         "We text your dormant patient list back into the chair, in your clinic's name. Booked straight into your calendar. $1,500 one-time, no monthly."),
        ("Missed-Call Text-Back",
         "The moment a call is missed, the caller gets an instant text from you and books, instead of calling the next clinic. Runs 24/7. $1,500 setup + $250/month."),
    ]:
        pdf.set_xy(20, y)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*DARK)
        pdf.cell(0, 6, f"-  {title}")
        y += 6
        pdf.set_xy(24, y)
        pdf.set_font("Helvetica", "", 10.5)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(W - 46, 5.5, body)
        y = pdf.get_y() + 4
    pdf.set_xy(20, y)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 6, "Both services together: $2,500  (reactivation one-time + missed-call $250/month).")
    y += 8
    pdf.set_xy(20, y)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(W - 40, 5,
        "Full privacy policies and terms are available on our website at blackmountaintech.ca.")
    y = pdf.get_y() + 6

    # --- Company details / the trust box ---
    box_y = y
    pdf.set_fill_color(247, 247, 247)
    pdf.rect(20, box_y, W - 40, 54, style="F")
    pdf.set_xy(26, box_y + 5)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 6, "Company Details")
    details = [
        ("Legal name", LEGAL_NAME),
        ("Incorporation No.", INCORP_NO + "  (Province of British Columbia)"),
        ("Registered office", OFFICE),
        ("Owner / CEO", f"{OWNER}, {TITLE}"),
        ("Phone", PHONE),
        ("Email", EMAIL),
        ("Website", WEBSITE),
    ]
    ry = box_y + 13
    for label, val in details:
        pdf.set_xy(26, ry)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(38, 5.4, label)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*DARK)
        pdf.cell(0, 5.4, val)
        ry += 5.6

    # --- Footer ---
    pdf.set_draw_color(*LINE); pdf.line(20, 270, W - 20, 270)
    pdf.set_xy(0, 273)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, f"{LEGAL_NAME}   |   Incorporation No. {INCORP_NO}", align="C")
    pdf.set_xy(0, 279)
    pdf.cell(0, 5, f"{OFFICE}   |   {PHONE}   |   {EMAIL}", align="C")
    pdf.set_xy(0, 285)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 5, WEBSITE, align="C")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Company_Profile.pdf")
    out = os.path.abspath(out)
    pdf.output(out)
    return out

if __name__ == "__main__":
    prepared = sys.argv[1] if len(sys.argv) > 1 else None
    path = build(prepared)
    print("Wrote:", path)
