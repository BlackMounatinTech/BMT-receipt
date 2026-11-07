"""Check once a minute for tomorrow's call reminders on the existing instance."""
import logging
import time
from crm_appointments import run_reminders

while True:
    try:
        run_reminders()
    except Exception:
        logging.exception('Appointment reminder check failed')
    time.sleep(60)
