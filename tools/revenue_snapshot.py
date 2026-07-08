#!/usr/bin/env python3
"""
Revenue Snapshot generator for Black Mountain Technologies.

A market-specific value asset sent WITH the company profile on a cold call.
It sells the OUTCOME: a fuller schedule, more patients kept, a clinic that makes more money.

Design rules (from Michael):
  - Explain at the top what this is and why it helps them.
  - Build the value up in the right order: one visit -> one year -> a lifetime.
  - SHOW the math, line by line, grade-school style. Never just land on a big number.
  - Add the honest caveat: we only bring back as many as you can handle.
  - Give it room to breathe. No crowding.
  - Grade 7-8 language. Conservative, sourced numbers. Price OFF the page.

Usage:
    python3 revenue_snapshot.py dental
    python3 revenue_snapshot.py all
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOGO = ROOT / "assets_logo.png"
OUT = ROOT / "snapshots"
OUT.mkdir(exist_ok=True)

NAVY = (26, 32, 44); GREY = (90, 90, 90); INK = (20, 20, 20)
LINE = (214, 218, 220); GREEN = (34, 110, 60); FAINT = (247, 247, 247)

LEGAL_NAME = "Black Mountain Technologies  (1592763 B.C. LTD.)"
INCORP_NO = "BC1592763"
FOOTER_LINE = "515 Petersen, Campbell River, BC V9W 3H6   |   250-254-2377   |   michael@blackmountaintechnologies.ca"


def _ascii(s):
    if not s:
        return s
    repl = {"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "•": "-"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _money(n):
    return "$" + format(int(round(n)), ",")


MARKETS = {
    "dental": dict(
        label="Dental Practices", noun="patient", visit="a cleaning or checkup",
        base=1500, visit_lo=200, visit_hi=300,
        annual_lo=600, annual_hi=800, life_lo=5500, life_hi=7500,
        dorm_lo=0.11, dorm_hi=0.14, react_lo=0.18, react_hi=0.22, missed_pct="23 to 27%",
        missed_note="About a quarter of calls to a dental office never get answered. It happens at lunch, after you close, or when the front desk is busy. Most people who reach a voicemail do not call back. They just call the next clinic.",
        sources=["Jarvis Analytics - Active Patient Benchmarks", "Clerri - Dental Revenue Stats",
                 "Dandy - Lifetime Value of a Dental Patient", "Peerlogic - Missed Dental Calls (2026)"],
    ),
    "chiropractic": dict(
        label="Chiropractic Clinics", noun="patient", visit="an adjustment",
        base=500, visit_lo=60, visit_hi=90,
        annual_lo=1000, annual_hi=1542, life_lo=3000, life_hi=5000,
        dorm_lo=0.14, dorm_hi=0.18, react_lo=0.11, react_hi=0.15, missed_pct="24 to 28%",
        missed_note="Small clinics miss a big share of their calls during the day, and chiropractic is one of the worst hit. Most people who reach a voicemail do not leave one. They move on.",
        sources=["Chiropractic Economics - 2023 Salary & Expense Survey", "The Evidence Based Chiropractor - Patient LTV",
                 "American Chiropractic Assoc. (Invoca) - Missed Calls", "Dialog Health - Reactivation Stats"],
    ),
    "physiotherapy": dict(
        label="Physiotherapy Clinics", noun="patient", visit="a treatment session",
        base=250, visit_lo=100, visit_hi=150,
        annual_lo=850, annual_hi=1150, life_lo=1500, life_hi=4500,
        dorm_lo=0.18, dorm_hi=0.23, react_lo=0.13, react_hi=0.17, missed_pct="24 to 28%",
        missed_note="Physio clinics miss a good share of their calls, and a lot of those callers are new patients. Most who reach a voicemail just try the next clinic on the list.",
        sources=["NCDS - PT Clinic Patient Volume", "U.S. Physical Therapy - FY2024 Net Rate",
                 "AC Health - Lifetime Patient Value", "Dialog Health - Reactivation Stats"],
    ),
    "optometry": dict(
        label="Optometry & Eye Care Clinics", noun="patient", visit="an eye exam",
        base=1800, visit_lo=100, visit_hi=200,
        annual_lo=285, annual_hi=400, life_lo=3200, life_hi=4000,
        dorm_lo=0.15, dorm_hi=0.19, react_lo=0.11, react_hi=0.14, missed_pct="22 to 26%",
        missed_note="Clinics with no set way to handle calls miss a big share of them. Most people who reach a voicemail leave nothing. They book their eye exam somewhere else.",
        sources=["Review of Optometric Business - Patient Count & LTV", "Review of Optometric Business - Return Rate",
                 "MyBCAT - Call Management for Optometry", "Cira - Missed Call Statistics (2026)"],
    ),
    "veterinary": dict(
        label="Veterinary Clinics", noun="client", visit="a checkup",
        base=1500, visit_lo=60, visit_hi=120,
        annual_lo=450, annual_hi=620, life_lo=2500, life_hi=5000,
        dorm_lo=0.17, dorm_hi=0.21, react_lo=0.11, react_hi=0.15, missed_pct="23 to 27%",
        missed_note="The average vet clinic misses about a quarter of its calls, more when it is busy. And around 85% of the people they miss never call back. They find another clinic.",
        sources=["Vetsource - Stop Your Patients From Lapsing", "AVMA (Vetsource, 2024) - Revenue per Patient",
                 "Practice Life - Lifetime Value of a Vet Client", "Puppilot - The Cost of Missed Calls"],
    ),
    "rmt": dict(
        label="Registered Massage Therapy Clinics", noun="client", visit="a massage",
        base=400, visit_lo=90, visit_hi=140,
        annual_lo=340, annual_hi=510, life_lo=1200, life_hi=4000,
        dorm_lo=0.21, dorm_hi=0.26, react_lo=0.15, react_hi=0.19, missed_pct="24 to 29%",
        missed_note="Small clinics miss a lot of their calls during the day, and a booked table cannot wait. Most people who reach a voicemail do not leave one. They book with the next therapist.",
        sources=["AMTA / Back In Action - Massage Client Retention", "RMTAO - Average Massage Fees (2026)",
                 "Massage Therapist Business School - Client LTV", "Dialog Health - Reactivation Stats"],
    ),
    "naturopath": dict(
        label="Naturopathic Clinics", noun="patient", visit="a follow-up visit",
        base=500, visit_lo=90, visit_hi=250,
        annual_lo=350, annual_hi=950, life_lo=1400, life_hi=3800,
        dorm_lo=0.16, dorm_hi=0.20, react_lo=0.13, react_hi=0.17, missed_pct="23 to 27%",
        missed_note="Small clinics miss a good share of their calls, and naturopathic care is mostly paid out of pocket. So every missed call is a booking that walks straight to another practitioner.",
        sources=["Noble Naturopathic - Cost to See a Naturopath in BC (2025)", "Bradley et al. - ND Visit Frequency (PMC)",
                 "Dental Economics - Attrition Benchmarks", "Dialog Health / MyBCAT - Reactivation Stats"],
    ),
}


def build(key, path=None):
    from fpdf import FPDF

    m = MARKETS[key]
    if path is None:
        path = OUT / f"Revenue_Snapshot_{key.capitalize()}.pdf"
    path = Path(path)

    noun = m["noun"]
    base = m["base"]
    dorm_hi_pct = m["dorm_hi"] * 100
    leave = round(base * m["dorm_hi"])          # use the high end of dormancy for the worked example
    life = m["life_lo"]                          # use the LOW lifetime value so the total is conservative
    lost = leave * life                          # dollars walking out (worked, single clear number)
    react_pct = m["react_hi"] * 100
    back = round(leave * m["react_hi"])           # patients we bring back (honest single pass)
    recovered = back * life                       # dollars recovered

    pdf = FPDF("P", "mm", "A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    W, M = 210, 20
    RIGHT = W - M

    # ---- Header ----
    if LOGO.exists():
        lw = 46
        pdf.image(str(LOGO), x=(W - lw) / 2, y=11, w=lw)
        y = 11 + (lw * 943 / 1668) + 4
    else:
        y = 26
    pdf.set_y(y)
    pdf.set_font("Helvetica", "B", 16); pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, "REVENUE SNAPSHOT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5); pdf.set_text_color(*GREY)
    pdf.cell(0, 5.5, _ascii(f"For {m['label'].lower()}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ---- What this is (framing) ----
    pdf.set_x(M); pdf.set_font("Helvetica", "", 9.8); pdf.set_text_color(*GREY)
    pdf.multi_cell(W - 2 * M, 4.8, _ascii(
        "This is a quick look at the money most clinics lose without ever seeing it - patients who quietly stop "
        "booking, and calls that never get answered. The numbers below are honest industry averages. It shows you "
        "what that costs, and what a simple system gets back for you."), align="C")
    pdf.ln(3)
    pdf.set_draw_color(*LINE); pdf.set_line_width(0.3); pdf.line(M, pdf.get_y(), RIGHT, pdf.get_y()); pdf.ln(5)

    def section(title):
        pdf.set_x(M); pdf.set_font("Helvetica", "B", 12); pdf.set_text_color(*NAVY)
        pdf.cell(0, 6, _ascii(title), new_x="LMARGIN", new_y="NEXT"); pdf.ln(1.5)

    def line(txt, bold=False, color=INK, size=10):
        pdf.set_x(M); pdf.set_font("Helvetica", "B" if bold else "", size); pdf.set_text_color(*color)
        pdf.multi_cell(W - 2 * M, 5, _ascii(txt));

    def mathrow(left, right, bold=False):
        pdf.set_x(M)
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.set_text_color(*(NAVY if bold else INK))
        pdf.cell(W - 2 * M - 42, 6, _ascii(left))
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*(GREEN if bold else INK))
        pdf.cell(42, 6, _ascii(right), align="R", new_x="LMARGIN", new_y="NEXT")

    # ---- 1. What one patient is worth (built up in the right order) ----
    section(f"1.  What one {noun} is worth to you")
    line(f"One visit for {m['visit']} is about {_money(m['visit_lo'])} to {_money(m['visit_hi'])}. "
         f"But nobody comes just once.", size=10)
    pdf.ln(1)
    mathrow(f"Over a full year, one {noun} is worth about", f"{_money(m['annual_lo'])} - {_money(m['annual_hi'])}")
    mathrow(f"Across all the years they stay with you", f"{_money(m['life_lo'])} - {_money(m['life_hi'])}", bold=True)
    pdf.ln(1)
    line(f"So losing one {noun} is not losing one visit. It is losing thousands.", size=9.5, color=GREY)
    pdf.ln(4)

    # ---- 2. What is leaving (SHOW the math) ----
    section("2.  What that costs you every year")
    line(f"Here is the math on a clinic about your size:", size=10)
    pdf.ln(1)
    mathrow(f"Your {noun} list, about", f"{base:,}")
    mathrow(f"That go quiet each year ({dorm_hi_pct:.0f}%)", f"{leave} {noun}s")
    mathrow(f"Each one worth (over their life)", f"{_money(life)}")
    pdf.set_x(M); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y()+1, RIGHT, pdf.get_y()+1); pdf.ln(2)
    mathrow(f"Future revenue walking out the door", f"{_money(lost)} / yr", bold=True)
    pdf.ln(4)

    # ---- 3. Missed calls ----
    section("3.  The calls you never hear about")
    line(f"On top of that, about {m['missed_pct']} of your calls go unanswered.", bold=True, size=10.5, color=GREEN)
    pdf.ln(0.5)
    line(m["missed_note"], size=9.8)
    pdf.ln(4)

    # ---- 4. The outcome (the sell) + caveat ----
    section("4.  What we get back for you")
    line(f"We text your quiet list back in, in your name, and catch every missed call the moment it happens.", size=10)
    pdf.ln(1)
    mathrow(f"Of the {leave} who left, we bring back about ({react_pct:.0f}%)", f"{back} {noun}s")
    mathrow(f"Each one worth (over their life)", f"{_money(life)}")
    pdf.set_x(M); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y()+1, RIGHT, pdf.get_y()+1); pdf.ln(2)
    mathrow(f"Revenue we bring back to you", f"{_money(recovered)}", bold=True)
    pdf.ln(2)
    line("And we only ever bring back as many as your schedule can handle. This fills your calendar, it does not "
         "flood it. A fuller book, more of your people kept, and a clinic that quietly makes more - without you "
         "lifting a finger.", size=9.5, color=GREY)

    # ================= PAGE 2 : how the two systems actually work =================
    pdf.add_page()
    pdf.set_y(20)
    pdf.set_font("Helvetica", "B", 15); pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, "How the two systems work", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(*GREY)
    pdf.cell(0, 5.5, "Plain and simple, here is exactly what we set up for you.", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y(), RIGHT, pdf.get_y()); pdf.ln(8)

    def subhead(txt):
        pdf.set_x(M); pdf.set_font("Helvetica", "B", 12.5); pdf.set_text_color(*NAVY)
        pdf.cell(0, 6, _ascii(txt), new_x="LMARGIN", new_y="NEXT"); pdf.ln(2.5)

    def para(txt, size=10, color=INK):
        pdf.set_x(M); pdf.set_font("Helvetica", "", size); pdf.set_text_color(*color)
        pdf.multi_cell(W - 2 * M, 5.2, _ascii(txt)); pdf.ln(3)

    def statbar(txt):
        # measure how many lines the text needs so the box wraps it with even padding
        pdf.set_font("Helvetica", "B", 9.8)
        lines = pdf.multi_cell(W - 2 * M - 12, 4.6, _ascii(txt), dry_run=True, output="LINES")
        box_h = len(lines) * 4.6 + 5
        yy = pdf.get_y()
        pdf.set_fill_color(*FAINT); pdf.rect(M, yy, W - 2 * M, box_h, "F")
        # slim green accent bar on the left edge
        pdf.set_fill_color(*GREEN); pdf.rect(M, yy, 1.6, box_h, "F")
        pdf.set_xy(M + 6, yy + 2.5); pdf.set_text_color(*GREEN)
        pdf.multi_cell(W - 2 * M - 12, 4.6, _ascii(txt))
        pdf.set_y(yy + box_h); pdf.ln(8)

    # --- Missed-call text-back ---
    subhead("Missed-Call Text-Back")
    para("When someone calls and you cannot pick up - you are with a patient, it is after hours, the front desk is "
         "buried - our system sees the missed call and sends them a text right away, in your clinic's name. "
         "Something like: \"Hi, this is your clinic, sorry we missed you. How can we help?\" They text back, and you "
         "have caught them before they call anyone else. It runs 24 hours a day, 7 days a week, on its own.")
    para("Why it works: about 85% of people who reach a voicemail never call back. They call the next clinic within "
         "minutes. A text lands different. Texts get opened 98% of the time, and 9 out of 10 are read within three "
         "minutes. So instead of losing that person, you are the first to reply.")
    statbar("Clinics that add missed-call text-back turn roughly 30% or more of their missed calls into booked "
            "appointments. People who would have been gone for good.")

    # --- Patient reactivation ---
    subhead("Patient Reactivation")
    para(f"You already have a list of {noun}s who have not been in for a while. They are not upset, they just drifted "
         f"off. Life got busy and nobody reminded them. We take that list and send a friendly text in your name, "
         f"inviting them back in, and it books straight into your calendar. Their information never leaves your "
         f"office, and there is almost nothing for your team to do.")
    para("Why it works: a text is personal and it gets read, where a letter or an email gets ignored. So a simple, "
         "well-timed message brings a real share of your quiet list back through the door.")
    statbar(f"A done-for-you reactivation campaign typically brings back {int(round(m['react_lo']*100))} to "
            f"{int(round(m['react_hi']*100))}% of your dormant {noun}s. Money that was just sitting in your files.")

    # --- What it means for the clinic ---
    subhead("What this means for your clinic")
    para("Put together, these two systems plug the two biggest leaks you have. You stop losing new callers to the "
         "clinic down the street, and you quietly win back the people you already earned once. That means a fuller "
         "schedule, steadier income, and more of your patients kept for the long run. All running in the "
         "background while you focus on care. We set it up, we manage it, and it is live within the week.")

    # ---- sources ----
    pdf.ln(2)
    pdf.set_x(M); pdf.set_font("Helvetica", "I", 7); pdf.set_text_color(*GREY)
    pdf.multi_cell(W - 2 * M, 3.3, _ascii(
        "Figures are honest industry averages for this field. Sources: " + "; ".join(m["sources"]) +
        "; SMS open/response rates: Kenect, Notifyre (2025); missed-call recovery: NetPartners, SchedulingKit (2026)."))

    # ---- footer (both pages) ----
    for pg in (1, 2):
        pdf.page = pg
        pdf.set_y(-17); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y(), RIGHT, pdf.get_y()); pdf.ln(1.5)
        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(*GREY)
        pdf.cell(0, 3.6, _ascii(LEGAL_NAME + "   Incorporation No. " + INCORP_NO), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 3.6, _ascii(FOOTER_LINE), align="C")

    pdf.output(str(path))
    return str(path)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    keys = list(MARKETS.keys()) if arg == "all" else [arg]
    for k in keys:
        print("wrote:", build(k))
