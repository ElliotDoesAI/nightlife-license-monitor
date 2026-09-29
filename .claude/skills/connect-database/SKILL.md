---
name: connect-database
description: Load the private Neon database connection into this shell without printing it. Use before any licmon command that reads or writes leads (export, review, status, email, requalify) or any SQL query.
---

# Connect to the lead database safely

The connection string contains the database password. Never print it, paste
it into chat, write it into a tracked file, or put it in a command argument
that gets logged.

1. Check the tools exist: `command -v neon uv gh`. If `neon` is missing:
   `npm i -g neon@latest` (needs Node). If `uv` is missing:
   `curl -LsSf https://astral.sh/uv/install.sh | sh`, then `uv sync`.
2. Check sign-in: `neon me` (prints the account). If not signed in:
   `neon login` and ask the owner to click **Authorize** in the browser.
3. First time in this folder only:
   `neon link --project-id tiny-truth-43995411 --branch production -y`
   (writes `.env.local` and `.neon`, both gitignored).
4. Load it:

   ```bash
   export DATABASE_URL="$(neon cs production --project-id tiny-truth-43995411 --ssl require)"
   test -n "$DATABASE_URL" && echo "DATABASE_URL loaded"
   ```

5. Verify: `uv run licmon status`. It prints only run counts, no lead data.

Each Bash call may be a fresh shell. If a later command says `DATABASE_URL`
is not set, prefix it with the `export` line in the same command.

Never use this database for tests. Tests use a disposable local Postgres
(see AGENTS.md, "Developing").
