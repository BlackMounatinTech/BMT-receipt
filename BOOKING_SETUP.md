# Calling and booking setup

Calling → Upload lead sheet accepts CSV and the first tab of XLSX. It recognizes
Company and Phone number headers within the first 20 rows, including the existing
BMT 100 Saturday Leads +2 workbook. Optional Contact, Email, Location, Notes,
Website and Time zone columns are imported. A preview shows new, reused, duplicate
and excluded rows before committing. Imports do not send messages. Existing lead
details/history are preserved. Imported cold contacts stay outside Active prospects.

Call outcomes save history and advance one lead. Follow up requires a date. Book
meeting opens a separate page and only marks Call booked after Zoom and Google
Calendar succeed. Booking checks Google free/busy and CRM reservations. Calendar
sends its invitation and the existing email service sends a BMT confirmation.
Booking does not scrape or auto-call numbers. The role selector is not authentication.

The top-right counter is shared across lists and users. It counts saved call
attempts, including no answer and booking attempts, rather than unique companies.
Existing Phone outcome notes are backfilled once; DMs are excluded. Booking retries
do not add another call for the same lead revision. Today follows Vancouver's
UTC−7 calendar day and rolls over at midnight. New day resets only today's count
using an event marker; the overall count and call history are retained. Each saved
outcome is counted transactionally, so rejected/stale saves cannot inflate totals.

Call notes autosave after typing pauses and before moving between leads. A Saved
indicator confirms the server write. Unsaved drafts are also kept per lead in the
browser, so a reload or failed connection does not silently discard the draft.
Notes use their own optimistic version and do not increment the cold-call counter.
Earlier notes recorded with a call outcome remain visible in Calling.

Follow up opens a date field and an explicit Save follow-up & next button. Saved
dates appear in the Follow-ups navigation tab, including future dates and cold
leads; due and overdue items are labelled. A follow-up date is a CRM reminder,
not a Zoom appointment or a Google Calendar event, and sends no email.

Production disk verified in Render November 23, 2026: 1 GB mounted at /var/data.
crm_call_notes and follow-up dates use the existing bmt_crm.sqlite3 on that disk.

## Connect the existing Render service

Keep the existing service, disk and credentials. No new paid services are needed by
this code. Existing account/provider plan restrictions still apply. Configure these
environment variables through Render; never commit real secrets:

- ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET: an activated internal
  Server-to-Server OAuth app with permission to create meetings for configured hosts.
  Each zoom_user must belong to that authorized Zoom account.
- GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET,
  GOOGLE_CALENDAR_REFRESH_TOKEN: server-side OAuth credentials authorized by the
  business calendar owner, with offline access and Calendar event write plus free/busy
  access (for example the calendar.events and calendar.events.freebusy scopes).
  Enable the Calendar API in that Google project. The token must be authorized to
  read availability and write events for every configured calendar_id.
- SMTP_USER and SMTP_PASSWORD: the existing Google Workspace mailbox and app
  password. Restore Workspace billing before attempting real sends. A regular Google
  password cannot replace the app password. Keep sender settings on the server.
- BMT_BOOKING_HOSTS: a JSON array, initially one host; add the closer later:

```json
[{"id":"michael","name":"Michael","email":"michael@blackmountaintechnologies.ca","zoom_user":"michael@blackmountaintechnologies.ca","calendar_id":"michael@blackmountaintechnologies.ca"}]
```

Use a business-owned calendar for the organizer identity in invitations. A closer
may be the Zoom host and attendee while BMT's business calendar organizes the event;
ensure that calendar includes their availability or uses their delegated calendar.
The closer must be able to host the selected Zoom user without Michael joining.
Connections shows credential presence only; validate with an explicitly authorized
test booking before sending to real prospects. Google invitations and the branded
SMTP confirmation are separate emails. Reminders use the existing worker.

## Recovery and limits

Each booking persists its successful steps. Resume retries unfinished steps and reuses
the Zoom meeting and deterministic Google event ID. A lost Zoom-create response or
interrupted in-flight process needs provider review, preventing accidental duplicates.
Check Zoom, Calendar and Sent mail before retrying an ambiguous send. In-flight jobs
are not automatically retried on startup. Inspect crm_booking_jobs on the persistent
disk and reconcile provider artifacts before clearing busy/review state manually.

Managed bookings cannot be rescheduled/cancelled from the legacy lead editor. This
version does not sync provider edits back to CRM; reconcile those manually. Complete
bookings reserve their CRM slot. No OAuth credentials are collected by the public UI.
The existing password-free access policy remains unchanged.

## Verify

`python -m unittest discover -s tests -p 'test_*.py' -v`

Provider calls in calling tests are mocked. No live Zoom meetings, Google invitations
or customer emails are created by tests.

## Production verification — November 23, 2026

Connected the internal Zoom app BMT CRM Booking with only
`meeting:write:meeting:admin`, and the internal Google OAuth client BMT CRM Booking
with Calendar event and free/busy access. All six provider credentials are in the
existing Render service's private environment. The sender is
michael@blackmountaintechnologies.ca. No credentials are stored in this repository.

One explicitly labelled internal test booked a 30-minute Zoom meeting, wrote its
Google Calendar invitation, and sent the BMT confirmation to Michael's own Gmail.
Both emails were observed in the recipient inbox. The test calendar event was then
canceled, the Zoom meeting deleted (recoverable for seven days), and the test CRM
record closed with a verification note. The test did not increase cold-call counts.
Live connection readiness verified true for Zoom, Google Calendar and email.
