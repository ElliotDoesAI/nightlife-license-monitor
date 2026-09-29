---
name: fix-broken-source
description: Diagnose and repair a source that failed in the daily run (red run, FAILED line, SourceSanityError, parse or HTTP error). Use when a GitHub failure email arrives or check-health shows a failed source.
---

# Fix a broken source

One failed source does not stop the others. Fix calmly.

1. Find which source and what error type:

   ```bash
   gh run list --workflow daily-collect -L 3
   gh run view <id> --log | grep -E "FAILED|STORAGE ALARM"
   ```

   Details stay in the database (skill `connect-database`):

   ```sql
   SELECT source, started_at, error_type, left(error_detail, 2000)
   FROM source_runs WHERE status = 'failed'
   ORDER BY started_at DESC LIMIT 5;
   ```

   Read the traceback yourself. Do not paste record values into commits,
   issues or logs.
2. Classify:
   - `SourceHTTPError` with 5xx, timeouts, DNS: the state site is down.
     Wait a day. If it fails 3 days in a row, probe it (step 3).
   - 403 / 429 / a CAPTCHA or "verify you are human" page: we are blocked.
     **Do not work around it** (no fake browsers, proxies or disguises).
     Tell the owner which source is blocked; it may need a free API token
     (`SOCRATA_APP_TOKEN` for NY/TX/Chicago) or a data request to the agency.
   - `SourceSanityError` (fewer records than `min_records`), `KeyError`,
     `ValueError`, parse errors: the source changed its format. Continue.
3. Probe locally (no database, counts only):

   ```bash
   uv run licmon probe --source <name>
   ```

   Download the raw file into a temp folder outside the repo and compare its
   columns/layout with the parser in `src/licmon/sources/<file>.py`
   (`ny_sla.py`, `tx_tabc.py`, `chicago_pending.py`, `chicago_bacp.py`,
   `wa_lcb.py`, `ca_abc.py`, `fl_abt.py`). The official homepage is the
   `homepage` attribute on the source class.
4. Fix the parser. Update the synthetic fixture in `tests/fixtures/` to the
   new layout with **made-up** names and addresses. Never copy real rows.
5. Test with the disposable database (AGENTS.md, "Developing"):

   ```bash
   TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/licmon_test uv run pytest -q
   uv run licmon probe --source <name>
   ```

6. Commit and push (`git add` only the changed source, test and fixture),
   then skill `run-now` with `-f source=<name>` and confirm `ok`.

If a source is gone for good, tell the owner and ask before removing it from
`src/licmon/sources/__init__.py`.
