# BMT paid consultation

Runs beside the existing Streamlit receipt tool on the existing Render Starter instance and persistent disk. Caddy routes `/consultation/*` to Flask on localhost:8502 and all other traffic to the unchanged receipt app on localhost:8501. No additional hosting plan or disk.

## Flow
Questionnaire → Stripe Checkout ($100 CAD, price allowlisted) → verified payment → available times → one calendar booking. Browser receives an opaque HttpOnly cookie; payment secrets remain server-side. SQLite database `/var/data/bmt_booking.sqlite` survives deploys and uses the existing disk snapshots. Do not move it to ephemeral app storage.

## Calendar access control
Cal.com event 7230455 has a CLOSED historical public booking window and requires authenticated API requests. Keep it that way. Public scheduling must not be reopened. Server reads selected Google calendar busy times and enforces Mon–Fri 07:00–21:00 America/Vancouver, four hours' notice, maximum 60 days. Only after verifying payment and claiming the slot does the owner-authenticated API request use `allowBookingOutOfBounds: true` to override the deliberately closed public window. Conflicts remain disallowed. Never expose the Cal key, event booking URL, or an override endpoint in the frontend.

## Recovery
A `review` or `booking` order after a network timeout must NOT be retried blindly. Check Cal bookings for metadata `bmtOrderId` matching the order ID and verify Stripe session payment. If a booking exists, reconcile its UID/time/meeting URL into the order. If it provably does not, an operator can reset the order to paid and release its reserved slot. Never charge again to fix a booking failure. Lost-browser sessions require Michael to verify the payment email/session and assist; there is no insecure client-controlled paid flag.

## Deploy / rollback
Render build: `bash build.sh`. Start: `python serve.py`. Health: `/consultation/health`. `BOOKING_ENABLED=false` prevents checkout and booking during maintenance. Keep SMTP environment variables and existing receipt data unchanged. To restore only the receipt app, use the previous Streamlit start command from git history; preserve the booking database, and temporarily remove the website booking CTA while investigating. Existing customer appointments are not deleted by a deployment rollback.

## Checks
`PYTHONPATH=booking_service pytest booking_service/tests -q`. No test bypass exists in production. Live integration checks must use Michael's own email and cancel test appointments. Never use a real customer's card for testing.
