---
name: check-health
description: Check whether the daily scraper and email are working. Use when the owner asks "is it working?", "nothing came in today", "I didn't get the email", or after any change.
---

# Health check

1. Recent GitHub runs:

   ```bash
   gh run list --workflow daily-collect -L 5
   gh workflow view daily-collect | head -5     # shows if it is disabled
   ```

   A red X means at least one source failed or the storage alarm fired.
   If the workflow is disabled, see skill `pause-resume`.
2. Per-source detail (needs skill `connect-database`):

   ```bash
   uv run licmon status
   ```

   Each source should show `success` with today's date. `baseline` on a
   source's first run is normal. `queued=0` on quiet days is normal.
3. A failed source: skill `fix-broken-source`.
4. Email: open the latest run with `gh run view <id> --log | grep -i email`.
   - `email sent` : it went out. Ask the owner to check spam.
   - `email skipped (not configured)` : secrets missing, skill `email-setup`.
   - `email failed (SMTPAuthenticationError)` : app password wrong or
     revoked. Make a new one, reset `SMTP_PASSWORD` (skill `email-setup`).
5. Database size is logged at the end of each run
   (`database size N MB (alarm at 400 MB)`). Near 400: skill `storage-alarm`.

Tell the owner the result in one or two plain sentences.
