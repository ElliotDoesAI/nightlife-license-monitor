---
name: run-now
description: Start the daily collection (and email) right now on GitHub instead of waiting for 15:30 UTC, or re-run one source. Use when the owner says "run it now" or after a fix.
---

# Run the collection now

The run happens on GitHub, not on this computer. A full run also sends the
daily email if the email is set up, so the owner gets a second email that
day. Say so before starting. A one-source rerun does not send email.

1. All sources:

   ```bash
   gh workflow run daily-collect
   ```

   One source only (e.g. after fixing it):

   ```bash
   gh workflow run daily-collect -f source=fl_abt_licenses
   ```

   Source names: `ny_sla_pending`, `tx_tabc_pending`, `chicago_bacp_pending`,
   `chicago_bacp_liquor`, `wa_lcb_actions`, `ca_abc_applications`,
   `fl_abt_licenses` (the registry is `src/licmon/sources/__init__.py`).
2. Wait ~10 seconds, then watch it:

   ```bash
   gh run watch --exit-status $(gh run list --workflow daily-collect -L 1 --json databaseId -q ".[0].databaseId")
   ```

   A full run takes a few minutes.
3. Report: green or red, and each source's line from the log
   (`gh run view <id> --log | grep -E "source |FAILED|email|database size"`).
   The log has counts only. If red, use skill `fix-broken-source`.

Running twice in one day is safe: records are deduplicated, and a lead is only
queued again if it changed.
