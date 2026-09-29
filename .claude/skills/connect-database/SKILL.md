---
name: connect-database
description: Load the private Neon database connection into this shell without printing it. Use before any licmon command that reads or writes leads (export, review, status, email, requalify) or any SQL query.
---

# Connect to the lead database safely

The connection string contains the database password. Never print it, paste
it into chat, write it into a tracked file, or put it in a command argument
that gets logged. All commands below are zsh-compatible (macOS default).

1. Check the tools exist: `command -v neon uv gh`. If `neon` is missing,
   install Node first, then the Neon CLI, then confirm it:
   `brew install node`, `npm i -g neon@latest`, `neon --help`
   (the `neon` npm package provides the `neon` binary with `cs`
   / `connection-string`, `login`, `link` and `me` subcommands).
   If `uv` is missing: `curl -LsSf https://astral.sh/uv/install.sh | sh`,
   then `uv sync` in the project folder.
2. Check sign-in: `neon me` (prints the account). If not signed in:
   `neon login` and ask the owner to click **Authorize** in the browser.
3. First time in this folder only:
   `neon link --project-id tiny-truth-43995411 --branch production -y`
   (writes `.env.local` and `.neon`, both gitignored; never commit them).
4. Load it (command substitution, so the value never prints):

   ```bash
   export DATABASE_URL="$(neon cs production --project-id tiny-truth-43995411 --ssl require)"
   test -n "$DATABASE_URL" && echo "DATABASE_URL loaded"
   ```

5. Verify: `uv run licmon status`. It prints only run counts, no lead data.

Each Claude Code Bash call may be a fresh shell, so `export` does not always
carry over. If a later command says `DATABASE_URL` is not set, re-run the
`export` line in the same command, e.g.:

```bash
export DATABASE_URL="$(neon cs production --project-id tiny-truth-43995411 --ssl require)" && uv run licmon status
```

Never use this database for tests. Tests use a disposable local Postgres
(see AGENTS.md, "Developing").
