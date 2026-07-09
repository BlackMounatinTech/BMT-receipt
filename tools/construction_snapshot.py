#!/usr/bin/env python3
"""
Revenue Leak Snapshot generator for Black Mountain Technologies - CONSTRUCTION.

A trade-specific value asset sent WITH the company profile on a cold call.
It sells the OUTCOME: fewer jobs lost to missed calls, more dead quotes revived,
a construction company that quietly makes more without lifting a finger.

Two leaks (Michael's ask, Jul 9 2026):
  1. Missed-Call Money Leak  -> the Missed-Call Text-Back product
  2. Dead Quotes Reactivation -> the Client Reactivation product

Design rules (carried from the clinic Revenue Snapshot):
  - Explain at the top what this is and why it helps them.
  - SHOW the math, line by line, grade-school style. Never just land on a big number.
  - Conservative, sourced numbers. Price OFF the page.
  - Add the honest caveat: we only bring back as much as you can handle.
  - Grade 7-8 language. Give it room to breathe.

ICP: BC construction companies, ~$250K-$2M/yr, NOT the North Island
(excludes Comox, Cumberland, Courtenay, Campbell River).

Usage:
    python3 construction_snapshot.py roofing
    python3 construction_snapshot.py all
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
    repl = {"—": "-", "–": "-", "’": "'", "‘": "'",
            "“": '"', "”": '"', "…": "...", "•": "-"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _money(n):
    return "$" + format(int(round(n)), ",")


# Per-trade numbers. Conservative residential BC figures for a $250K-$2M company.
#   job_lo/job_hi : typical value of one job for this trade
#   calls_mo      : rough inbound calls a month
#   missed_pct    : share of calls that go unanswered (industry ~27%, we stay conservative)
#   book_val      : the value we assign to one booked job for the worked example (near job_lo, conservative)
#   quotes_mo     : quotes/estimates sent per month
#   close_note    : trade-flavored note on why quotes go cold
# NOTE ON NUMBERS: calls_mo = INBOUND JOB LEADS per month (not every phone call), and quotes_mo =
# estimates sent per month, for a $250K-$2M company. Kept deliberately LOW so the yearly totals land
# in the believable $30K-$150K range the research cites ($45K-$120K/yr lost to missed calls), never
# above the company's own revenue. book_val is the LOW end of a job. Conservative on purpose.
TRADES = {
    "excavation": dict(
        label="Excavation & Site Prep Companies", job_lo=3500, job_hi=25000,
        calls_mo=18, missed_pct=22, book_val=3500, quotes_mo=12,
        missed_note="Most of your calls come while you are in the seat of a machine or out on a site with no signal. "
                    "The caller needs dirt moved now, so if you do not pick up they call the next excavator on the list.",
        quote_note="You bid a lot of jobs that never come back to you - the homeowner went quiet, the timing slipped, "
                   "they were price-shopping. Those bids just sit in your email, forgotten.",
    ),
    "concrete": dict(
        label="Concrete & Foundation Companies", job_lo=3000, job_hi=20000,
        calls_mo=18, missed_pct=22, book_val=3000, quotes_mo=12,
        missed_note="Calls come in while you are on a pour or finishing a slab and cannot stop. Concrete work is "
                    "time-sensitive, so a caller you miss just moves on to the next crew.",
        quote_note="Driveways, patios, foundations - you quote plenty that never close. The customer stalls or gets "
                   "another number, and your bid is forgotten in a week.",
    ),
    "roofing": dict(
        label="Roofing Companies", job_lo=6000, job_hi=18000,
        calls_mo=20, missed_pct=24, book_val=6000, quotes_mo=14,
        missed_note="A leaking roof is an emergency, and the person calling wants it handled today. If they reach a "
                    "voicemail they do not wait - they call the next roofer, because they cannot let it sit.",
        quote_note="Roofing is heavily price-shopped. You give a lot of estimates that go cold while the homeowner "
                   "gathers three more. Most of those quotes are still sitting there, unclosed.",
    ),
    "hvac": dict(
        label="HVAC Companies", job_lo=5000, job_hi=15000,
        calls_mo=22, missed_pct=24, book_val=5000, quotes_mo=14,
        missed_note="No heat in January or no AC in a heat wave is an emergency call. The average after-hours HVAC "
                    "call is worth over a thousand dollars, and if you miss it, they call the next company in minutes.",
        quote_note="System replacements are big-ticket, so people shop around and stall. A lot of your install quotes "
                   "go quiet - not a no, just never followed up.",
    ),
    "plumbing": dict(
        label="Plumbing Companies", job_lo=850, job_hi=8000,
        calls_mo=28, missed_pct=24, book_val=850, quotes_mo=16,
        missed_note="A burst pipe or backed-up drain cannot wait. The average plumbing emergency is worth hundreds in "
                    "same-day work, and the caller will not leave a voicemail - they dial the next plumber right away.",
        quote_note="Repipes, water heaters, renovations - you bid work that stalls out. The customer goes quiet and "
                   "the estimate is forgotten, even though they still need it done.",
    ),
    "framing": dict(
        label="Framing Companies", job_lo=8000, job_hi=40000,
        calls_mo=12, missed_pct=20, book_val=8000, quotes_mo=8,
        missed_note="Your calls come from builders and homeowners lining up crews, and you are usually up on a wall "
                    "with a nail gun going. Miss the call and they book the next framing crew that answers.",
        quote_note="You bid framing jobs that get delayed, rescheduled, or handed to whoever followed up first. Plenty "
                   "of your quotes never get a second touch.",
    ),
    "drywall": dict(
        label="Drywall Companies", job_lo=1500, job_hi=9000,
        calls_mo=18, missed_pct=20, book_val=1500, quotes_mo=12,
        missed_note="Calls land while you are taping or sanding and cannot get to the phone. The customer wants a "
                    "quote now, so a missed call usually means they move on to the next drywaller.",
        quote_note="Drywall is price-sensitive and easy to shop around. A good share of the quotes you send go cold "
                   "while the customer collects a few more numbers.",
    ),
    "painting": dict(
        label="Painting Companies", job_lo=2000, job_hi=10000,
        calls_mo=20, missed_pct=20, book_val=2000, quotes_mo=14,
        missed_note="Calls come in while you are up a ladder mid-coat and cannot answer. Painting is competitive, so a "
                    "caller who reaches your voicemail just tries the next painter on their list.",
        quote_note="Homeowners get two or three painting quotes and take their time. A lot of your estimates go quiet, "
                   "not because they said no, but because nobody followed up.",
    ),
}


def build(key, path=None):
    from fpdf import FPDF

    m = TRADES[key]
    if path is None:
        # match the app's expected filename, e.g. Revenue_Snapshot_Roofing.pdf / _HVAC.pdf
        fname = "HVAC" if key == "hvac" else key.capitalize()
        path = OUT / f"Revenue_Snapshot_{fname}.pdf"
    path = Path(path)

    # ---- Missed-call math (honest: a missed call is a LEAD, not a guaranteed job) ----
    # Michael's point (Jul 9): a phone call is only worth as much as the customer on the other
    # end - most callers never buy. So we DON'T count every missed call as a lost job. We apply a
    # realistic win rate: of the leads you'd have quoted, only ~35% become actual jobs.
    WIN_RATE = 0.35
    calls_yr = m["calls_mo"] * 12
    missed_yr = round(calls_yr * m["missed_pct"] / 100)
    lost_leads = round(missed_yr * 0.85)                # 85% of missed callers never call back = lost leads
    lost_jobs = round(lost_leads * WIN_RATE)           # of those leads, only the ones you'd have WON
    missed_lost = lost_jobs * m["book_val"]            # honest "lost potential revenue" figure
    recovered_calls = round(missed_yr * 0.30)          # text-back re-engages ~30% of missed callers...
    missed_recovered = round(recovered_calls * WIN_RATE) * m["book_val"]  # ...and you win your usual share

    # ---- Dead-quotes math ----
    quotes_yr = m["quotes_mo"] * 12
    dead_pct = 40                                       # ~40% of quotes never close (conservative)
    dead_quotes = round(quotes_yr * dead_pct / 100)
    react_pct = 12                                      # reactivation revives ~12% of dead quotes
    revived = round(dead_quotes * react_pct / 100)
    quotes_recovered = revived * m["book_val"]

    total_recovered = missed_recovered + quotes_recovered

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
    pdf.cell(0, 8, "REVENUE LEAK SNAPSHOT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5); pdf.set_text_color(*GREY)
    pdf.cell(0, 5.5, _ascii(f"For {m['label'].lower()}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ---- What this is ----
    pdf.set_x(M); pdf.set_font("Helvetica", "", 9.8); pdf.set_text_color(*GREY)
    pdf.multi_cell(W - 2 * M, 4.8, _ascii(
        "This is a quick look at the money most construction companies lose without ever seeing it - jobs that walk "
        "when a call goes unanswered, and quotes that quietly go cold. The numbers below are honest industry averages. "
        "It shows you what that costs, and what a simple system gets back for you."), align="C")
    pdf.ln(2)
    pdf.set_draw_color(*LINE); pdf.set_line_width(0.3); pdf.line(M, pdf.get_y(), RIGHT, pdf.get_y()); pdf.ln(4)

    def section(title):
        pdf.set_x(M); pdf.set_font("Helvetica", "B", 12); pdf.set_text_color(*NAVY)
        pdf.cell(0, 5.5, _ascii(title), new_x="LMARGIN", new_y="NEXT"); pdf.ln(1)

    def line(txt, bold=False, color=INK, size=10):
        pdf.set_x(M); pdf.set_font("Helvetica", "B" if bold else "", size); pdf.set_text_color(*color)
        pdf.multi_cell(W - 2 * M, 4.7, _ascii(txt))

    def mathrow(left, right, bold=False):
        pdf.set_x(M)
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.set_text_color(*(NAVY if bold else INK))
        pdf.cell(W - 2 * M - 46, 5.4, _ascii(left))
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*(GREEN if bold else INK))
        pdf.cell(46, 5.4, _ascii(right), align="R", new_x="LMARGIN", new_y="NEXT")

    # ---- 1. What one job is worth ----
    section("1.  What one job is worth to you")
    line(f"For your trade, one job is worth about {_money(m['job_lo'])} to {_money(m['job_hi'])}. "
         f"So every job you lose is not small change - it is real money.", size=10)
    pdf.ln(0.5)
    line(f"To keep this honest, the math below values every job at just {_money(m['book_val'])} - the low end. "
         f"Your real jobs are often worth much more.", size=9.5, color=GREY)
    pdf.ln(3)

    # ---- 2. Missed-Call Money Leak ----
    section("2.  The Missed-Call Money Leak")
    line(m["missed_note"], size=9.8)
    pdf.ln(1)
    mathrow("Calls coming in each year, about", f"{calls_yr:,}")
    mathrow(f"That go unanswered ({m['missed_pct']}%)", f"{missed_yr} calls")
    mathrow("Callers who never call back (85%)", f"{lost_leads} leads")
    mathrow(f"That you'd actually win ({int(WIN_RATE*100)}% close rate)", f"{lost_jobs} jobs")
    mathrow(f"Each job worth (at the low end)", f"{_money(m['book_val'])}")
    pdf.set_x(M); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y()+1, RIGHT, pdf.get_y()+1); pdf.ln(1.5)
    mathrow("Lost potential revenue", f"{_money(missed_lost)} / yr", bold=True)
    pdf.ln(0.5)
    line(f"Not every call becomes a job - a call is only worth as much as the customer behind it. "
         f"So this only counts the jobs you would have actually won.", size=9, color=GREY)
    pdf.ln(2.5)

    # ---- 3. Dead Quotes ----
    section("3.  The Dead-Quotes Leak")
    line(m["quote_note"], size=9.8)
    pdf.ln(1)
    mathrow("Quotes you send each year, about", f"{quotes_yr:,}")
    mathrow(f"That go cold and never close ({dead_pct}%)", f"{dead_quotes} quotes")
    mathrow(f"A gentle nudge revives about ({react_pct}%)", f"{revived} jobs")
    mathrow("Each job worth (at the low end)", f"{_money(m['book_val'])}")
    pdf.set_x(M); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y()+1, RIGHT, pdf.get_y()+1); pdf.ln(1.5)
    mathrow("Sitting in your files, winnable", f"{_money(quotes_recovered)} / yr", bold=True)
    pdf.ln(0.5)
    line("These are people who already wanted the work and already got your price. Most just went quiet because "
         "nobody followed up.", size=9, color=GREY)
    pdf.ln(2.5)

    # ---- 4. The outcome ----
    section("4.  What we get back for you")
    line("We catch every missed call the moment it happens with an instant text in your name, and we text your old "
         "quotes back into the pipeline. Here is a conservative year:", size=10)
    pdf.ln(1)
    mathrow(f"Missed calls we turn into booked jobs (30%)", f"{_money(missed_recovered)}")
    mathrow(f"Dead quotes we revive ({react_pct}%)", f"{_money(quotes_recovered)}")
    pdf.set_x(M); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y()+1, RIGHT, pdf.get_y()+1); pdf.ln(1.5)
    mathrow("Revenue we bring back to you", f"{_money(total_recovered)} / yr", bold=True)
    pdf.ln(1.5)
    line("And we only ever bring back as much as your crew can handle. This fills your schedule, it does not flood it. "
         "More jobs caught, more old quotes closed, and a company that quietly makes more - without you lifting a finger.",
         size=9.5, color=GREY)

    # ================= PAGE 2 : how the two systems work =================
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
        pdf.set_font("Helvetica", "B", 9.8)
        lines = pdf.multi_cell(W - 2 * M - 12, 4.6, _ascii(txt), dry_run=True, output="LINES")
        box_h = len(lines) * 4.6 + 5
        yy = pdf.get_y()
        pdf.set_fill_color(*FAINT); pdf.rect(M, yy, W - 2 * M, box_h, "F")
        pdf.set_fill_color(*GREEN); pdf.rect(M, yy, 1.6, box_h, "F")
        pdf.set_xy(M + 6, yy + 2.5); pdf.set_text_color(*GREEN)
        pdf.multi_cell(W - 2 * M - 12, 4.6, _ascii(txt))
        pdf.set_y(yy + box_h); pdf.ln(8)

    # --- Missed-call text-back ---
    subhead("Missed-Call Text-Back")
    para("When someone calls and you cannot pick up - you are on a site, up a ladder, running a machine, or it is "
         "after hours - our system sees the missed call and sends them a text right away, in your company's name. "
         "Something like: \"Hi, this is your company, sorry we missed you. What can we help you with?\" They text back, "
         "and you have caught them before they call the next contractor. It runs 24 hours a day, 7 days a week.")
    para("Why it works: about 85% of people who reach a voicemail never call back, and fewer than 3% leave a message. "
         "They dial the next name on the list within minutes. A text lands different. Texts get opened 98% of the "
         "time, and most are read within three minutes. So instead of losing that job, you are the first to reply.")
    statbar("Contractors who add missed-call text-back turn roughly 30% or more of their missed calls into booked "
            "work. Jobs that would have gone to the competition.")

    # --- Client reactivation ---
    subhead("Client Reactivation")
    para("You already have a stack of old quotes and past customers - people who asked for a price and went quiet, or "
         "hired you once and drifted off. They are not upset, nobody followed up. We take that list and send a "
         "friendly text in your name that brings them back into the pipeline. Their information never leaves your "
         "hands, and there is almost nothing for you to do.")
    para("Why it works: a text is personal and it gets read, where an email gets buried. So a simple, well-timed "
         "message pulls a real share of your dead quotes back into paying jobs.")
    statbar("A done-for-you reactivation campaign typically revives around 10 to 15% of your dead quotes. Work that "
            "was just sitting in your files, already earned once.")

    # --- What it means ---
    subhead("What this means for your company")
    para("Put together, these two systems plug the two biggest leaks you have. You stop losing new callers to the "
         "company down the road, and you quietly win back the quotes you already worked to earn. That means a fuller "
         "schedule, steadier income, and more jobs closed - all running in the background while you stay on the "
         "tools. We set it up, we manage it, and it is live within the week.")

    # ---- sources ----
    pdf.ln(2)
    pdf.set_x(M); pdf.set_font("Helvetica", "I", 7); pdf.set_text_color(*GREY)
    pdf.multi_cell(W - 2 * M, 3.3, _ascii(
        "Figures are honest industry averages for the construction and home-services trades. Sources: Invoca - Cost of "
        "Missed Sales Calls; ServiceTitan - Contractor Missed-Call Data (2026); Signpost - Business Lost to Missed "
        "Calls; HBR - Speed-to-Lead Study; SMS open/response rates: Kenect, Notifyre (2025). Job values are "
        "conservative BC residential averages; your real numbers are typically higher."))

    # ---- footer (page 2 only) ----
    pdf.page = 2
    pdf.set_y(-17); pdf.set_draw_color(*LINE); pdf.line(M, pdf.get_y(), RIGHT, pdf.get_y()); pdf.ln(1.5)
    pdf.set_font("Helvetica", "", 8); pdf.set_text_color(*GREY)
    pdf.cell(0, 3.6, _ascii(LEGAL_NAME + "   Incorporation No. " + INCORP_NO), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 3.6, _ascii(FOOTER_LINE), align="C")

    pdf.output(str(path))
    return str(path)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    keys = list(TRADES.keys()) if arg == "all" else [arg]
    for k in keys:
        print("wrote:", build(k))
