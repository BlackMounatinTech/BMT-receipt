# BMT CRM

This extends the existing BMT Receipt Tool service. Keep its service ID, compute plan, disk, booking API, provider credentials and existing CSV contacts.

- Main view: manually entered warm leads. Company, contact, phone/email, conversation, status, follow-up, booked-call details and closer note history.
- New means an active lead not yet marked as seen by the closer. Select Working as Closer to mark it seen. The role selector is a workflow label, not a separate user account.
- Due follow-ups include overdue dates. Closed Won/Lost records remain available in their own view.
- Use Refresh list to load changes from another session. Conflicting saves are rejected rather than overwriting newer lead details or notes.
- Tools retains the existing company profiles, legacy sent-profile contacts, receipts and meeting reminders. No cold list or legacy CSV is automatically imported as warm leads.
- Michael explicitly approved password-free access on November 6, 2026 after being informed that anyone with the URL can read/change leads and use the email tools. Leave BMT_CRM_PASSWORD unset for public access. Setting it later enables shared login. Never commit passwords or put them in the vault.
- Database: BMT_DATA_DIR/bmt_crm.sqlite3 (production /var/data/bmt_crm.sqlite3). Production requires the existing mounted disk. Lead timestamps are stored in UTC and displayed in Vancouver time.
- Existing /consultation/* public booking API and health check are unchanged.
- No paid resources are added or resized.

Verification: python3 -m unittest discover -s tests -p test_crm.py -v

The CRM was developed in an isolated worktree so pre-existing edits to profile PDFs and construction_snapshot.py were not included.
