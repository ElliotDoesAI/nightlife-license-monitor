---
name: package-for-client
description: Build a clean zip of this project to hand to the owner or a new computer, with no secrets, local state or lead data. Use when asked to "zip it up", "package it" or "send the folder".
---

# Package the project as a zip

The zip is built from **committed** files only, via a fresh clone, so
`.env.local`, `.neon`, `.venv`, `node_modules`, exports and anything
uncommitted cannot leak in. It keeps `.git` so the owner can pull updates.

1. Commit what should ship. `git status --short` should be empty (the
   script refuses otherwise unless `--allow-dirty`, and even then ships only
   committed files).
2. Build:

   ```bash
   scripts/package_for_client.sh                      # zip in ~/Desktop (or ~)
   scripts/package_for_client.sh --out /path/to/dir   # elsewhere
   scripts/package_for_client.sh --origin https://github.com/NEWOWNER/nightlife-license-monitor.git
   ```

   `--origin` sets the remote inside the zip (default: this folder's
   `origin`). After a GitHub transfer, the old URL redirects, but setting the
   new one is cleaner.
3. The script fails if the clone contains `.env*`, `.neon`, `*.csv` outside
   `tests/fixtures/`, or anything that looks like a real Postgres connection
   string with a password. It prints the zip path, size and file count.
4. Send the zip by a private channel. The owner unzips it and follows
   `ONBOARDING.md`.
