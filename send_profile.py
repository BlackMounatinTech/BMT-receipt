#!/usr/bin/env python3
"""
ONE COMMAND to send the Company Profile mid-call.
They say their email on the phone -> you type it -> profile fires instantly.

    python3 send_profile.py their@email.com
    python3 send_profile.py their@email.com "Evolve Dental"    # personalizes it

Requires (one-time setup): SMTP_USER + SMTP_PASSWORD in .env  (Gmail App Password).
If email isn't configured yet, it still GENERATES the PDF and opens it so you can
attach it manually from your own email.
"""
import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

from company_profile import build

SUBJECT = "Black Mountain Technologies - Company Profile"
BODY = """Hi,

Great talking with you. As promised, our company profile is attached so you can see exactly who you're working with, our BC incorporation, registered office, and the two services we run for clinics.

Everything's also on our site at blackmountaintech.ca.

Whenever you're ready to lock in your spot for this week, an e-transfer to michael@blackmountaintechnologies.ca is easiest (a card link works too, it just carries a 3% processing fee).

Talk soon,
Michael Mackrell
Owner & CEO, Black Mountain Technologies
250-254-2377 | blackmountaintech.ca
"""

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 send_profile.py their@email.com [\"Clinic Name\"]")
    to = sys.argv[1].strip()
    clinic = sys.argv[2] if len(sys.argv) > 2 else None

    pdf = build(clinic)
    print(f"Profile built: {pdf}")

    # Try to send
    try:
        from tools.email_sender import send_email, is_configured
    except Exception:
        from email_sender import send_email, is_configured  # fallback path

    if not is_configured():
        print("\n[!] Email not configured yet (need SMTP_USER + SMTP_PASSWORD in .env).")
        print("    Opening the PDF so you can attach it from your own email for now.")
        subprocess.run(["open", pdf], check=False)
        return

    try:
        result = send_email(to=to, subject=SUBJECT, body_text=BODY, attachments=[pdf])
        if isinstance(result, dict) and not result.get("ok", True):
            raise RuntimeError(result.get("reason", "unknown send error"))
        print(f"\nSENT to {to} - profile on its way.")
    except Exception as e:
        print(f"\n[!] Send failed: {e}\n    Opening PDF to attach manually.")
        subprocess.run(["open", pdf], check=False)

if __name__ == "__main__":
    main()
