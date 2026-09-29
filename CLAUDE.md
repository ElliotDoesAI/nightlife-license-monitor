# Operating guide for the owner's coding agent

You are helping the owner of this project run it. The owner is not a
developer. Talk in plain, short sentences, do the technical work yourself, and
ask before anything risky. The original builder is not maintaining it.

## What this is

A daily scraper that collects public liquor-license applications from official
government sources and turns them into a lead list of likely new or changing
bars, clubs, lounges, restaurants and taprooms in major nightlife metros.
Read `README.md` for the design and `nightlife_liquor_license_monitor_prd.md`
for the original requirements.

It runs by itself every day at 15:30 UTC on GitHub Actions
(`.github/workflows/daily.yml`) and writes to a private Neon Postgres database
(project `tiny-truth-43995411`, branch `production`). Nobody has to start it.

## Hard rules

1. **This repo is public (unless the owner made it private).** Never commit,
   print in a workflow, or upload as an artifact any lead data: names,
   addresses, phone numbers, CSV exports, database dumps, `.env*` files or
   connection strings. Workflow logs must stay counts-only.
2. **Never contact a business** (email, SMS, calls, social) from this project.
   Leads are for the owner to review by hand.
3. **Never paste the database password or connection string into chat.** Get
   it into an environment variable without echoing it (see below).
4. Do not bypass CAPTCHAs, logins or bot protection on any source. If a source
   blocks us, report it; do not work around it.
5. Ask the owner before deleting data, changing the database plan, adding paid
   services, or changing who receives the leads.

## Connecting to the database

```bash
# One-time on a new computer: install tools, sign in, link this folder.
npm i -g neon@latest && neon login
neon link --project-id tiny-truth-43995411 --branch production -y
curl -LsSf https://astral.sh/uv/install.sh | sh   # Python runner, if missing
uv sync

# Each session: load the connection string without printing it.
export DATABASE_URL="$(neon cs production --project-id tiny-truth-43995411 --ssl require)"
```

`neon link` also writes `.env.local` (gitignored). Never commit it.

## Everyday tasks

| Owner asks | Do this |
|---|---|
| "Show me today's leads" / "give me a spreadsheet" | `uv run licmon export --out ~/Desktop/leads-$(date +%F).csv` (one row per venue, today's UTC date). Tell the owner where the file is and summarize counts by metro and tier. Do not paste the whole list into chat unless asked. |
| "All leads I haven't reviewed" | `uv run licmon export --all --open --out ~/Desktop/open-leads.csv` |
| "Leads from a certain day" | `uv run licmon export --date 2026-10-01 --out ...` |
| "Mark these as approved / rejected / contacted / snoozed" | Find the `record_ids` column in the export, then `uv run licmon review <id> <id> --status approved --note "..."`. One venue can have several record ids; update all of them. `--status new` reopens a lead. |
| "One row per application, not per venue" | add `--per-record` to any export command. |
| "Nothing came in today?" | An empty export is normal on quiet days. Check `uv run licmon status`: if every source says `success`, it is working. |
| "Is it working?" | `uv run licmon status` (last run per source, queue size by day). Also `gh run list --workflow daily-collect -L 5`. |
| "Run it now" | `gh workflow run daily-collect`, wait ~10 s, then `gh run watch --exit-status $(gh run list --workflow daily-collect -L 1 --json databaseId -q ".[0].databaseId")`. |
| "Pause it" / "turn it back on" | `gh workflow disable daily-collect` / `gh workflow enable daily-collect` |
| "Only show Houston / only tier A" | Export, then filter the CSV, or query the `daily_leads` view with SQL (`review_queue` is one row per application). |

Tiers: **A** = strongest nightlife signal, **B** = good, **C** = weaker. Each
lead has a plain `qualify_reason` saying why it was picked.

## If something breaks

- **Red run / failure email from GitHub.** Open the run log
  (`gh run view <id> --log`). Each source logs one result line; a failed one
  says `FAILED` with the error type (no record data; details stay in the DB). Details are in the database:
  `SELECT source, started_at, error_type, error_detail FROM source_runs WHERE status='failed' ORDER BY started_at DESC LIMIT 5;`
  One broken source does not stop the others.
- **A source changed its format** (error `SourceSanityError` or a parse error).
  Fetch it with `uv run licmon probe --source <name>`, compare to the parser in
  `src/licmon/sources/<name>.py`, fix it, add or update the test fixture
  (synthetic data only, never real rows), run the tests, commit.
- **STORAGE ALARM in the log.** Neon Free stops saving new data at 512 MB. The
  run turns red at 400 MB. First keep fewer days of raw downloads:
  `gh variable set RAW_RETENTION_DAYS --body 7` (default 14; old ones are
  trimmed on the next run). If that is not enough, tell the owner the Neon
  plan needs an upgrade. Check size with `SELECT pg_size_pretty(pg_database_size(current_database()));`
- **Daily runs stopped.** GitHub disables schedules in public repos after 60
  days with no commits. The workflow's `keepalive` job prevents this by pushing
  an empty commit after 45 quiet days. If it happened anyway:
  `gh workflow enable daily-collect`.
- **After changing rules** in `src/licmon/qualify.py` or `src/licmon/metros.py`,
  run `uv run licmon requalify` so stored records get the new scores. Past
  daily queues are not rewritten; the change shows from the next run on.

## Handover checklist (do once, right after the repo moves to the owner)

1. `gh secret list --env production` must show `DATABASE_URL`. If it is
   missing, recreate it without echoing:
   `neon cs production --project-id tiny-truth-43995411 --ssl require | gh secret set DATABASE_URL --env production`
2. Make the owner the person who gets failure emails: GitHub sends scheduled
   run failures to whoever last enabled the workflow. Run
   `gh workflow disable daily-collect && gh workflow enable daily-collect` while
   signed in as the owner.
3. Run it once (see "Run it now" above) and confirm
   every source says `ok`.
4. Optional, recommended: make the repo private
   (`gh repo edit --visibility private --accept-visibility-change-consequences`).
   A ~1 minute daily job fits easily in GitHub Free's 2,000 private minutes a
   month, the 60-day schedule rule no longer applies, and run logs stop being
   public.

## Developing

Tests need a disposable Postgres (never the real database):

```bash
docker run -d --rm --name licmon-test-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=licmon_test -p 127.0.0.1:55432:5432 postgres:16-alpine
TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/licmon_test uv run pytest -q
```

To add a state or city, follow "Adding a source" in `README.md`: one new file
in `src/licmon/sources/`, register it, add metro counties, add a synthetic
test. Nothing else changes. CI runs the tests on pushes to `main` and on
pull requests. The manual `probe-sources` workflow checks that GitHub can reach
and parse every source without touching the database.

Optional secret `SOCRATA_APP_TOKEN` (free, from data.ny.gov / data.texas.gov
/ data.cityofchicago.org developer settings) raises open-data rate limits. Not
needed at current volumes.
