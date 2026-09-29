# Operating guide for the owner's coding agent

You are helping the owner of this project run it. The owner is not a
developer. Talk in plain, short sentences, do the technical work yourself, and
ask before anything risky. The original builder is not maintaining it.

New computer or first day? Walk the owner through `ONBOARDING.md`.
Step-by-step recipes for every routine job are in `.claude/skills/`
(listed at the bottom of this file). Use them.

## What this is

A daily scraper that collects public liquor-license applications from official
government sources and turns them into a lead list of likely new or changing
bars, clubs, lounges, restaurants and taprooms in major nightlife metros.
Read `README.md` for the design and `nightlife_liquor_license_monitor_prd.md`
for the original requirements.

It runs by itself every day at 15:30 UTC on GitHub Actions
(`.github/workflows/daily.yml`, workflow name `daily-collect`). It writes to a
private Neon Postgres database (project `tiny-truth-43995411`, branch
`production`). When the email secrets are set, the same run then emails the
owner that day's leads with a spreadsheet attached. Nobody has to start it.

Sources: New York, Texas, Chicago (two lists), Washington and California
publish pending or new applications. Florida publishes no pending list, so its
leads are **newly issued licenses** (`application_type` = `NEW LICENSE`), a few
weeks later than the other states.

## Hard rules

1. **This repo is public (unless the owner made it private).** Never commit,
   print in a workflow, or upload as an artifact any lead data: names,
   addresses, phone numbers, spreadsheet exports, email previews, database dumps,
   `.env*` files or connection strings. Workflow logs must stay counts-only.
2. **Never contact a business** (email, SMS, calls, social) from this project.
   Leads are for the owner to review by hand. The daily email goes only to
   the owner's own address in `LEADS_EMAIL_TO`.
3. **Never paste the database password, connection string or email password
   into chat.** Load them into environment variables or GitHub secrets without
   echoing them (see below).
4. Do not bypass CAPTCHAs, logins or bot protection on any source. Do not
   disguise the scraper as a person or a browser. If a source blocks us,
   report it; do not work around it. (California's HTML daily report is
   behind bot protection. The official CSV export is used instead.)
5. Ask the owner before deleting data, changing the database plan, adding paid
   services, changing who receives the leads, or sending a test email.

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
| "Show me today's leads" / "give me a spreadsheet" | `uv run licmon export --out ~/Desktop/leads-$(date -u +%F).xlsx` (Excel, one clean row per venue, today's UTC date; `.csv` also works). Tell the owner where the file is and summarize counts by market and priority. Do not paste the whole list into chat unless asked. |
| "All leads I haven't reviewed" | `uv run licmon export --all --open --out ~/Desktop/open-leads.xlsx` |
| "Leads from a certain day" | `uv run licmon export --date 2026-10-01 --out ...` |
| "Mark these as approved / rejected / contacted / snoozed" | Find the `Lead ID` column in the spreadsheet, then `uv run licmon review <id> <id> --status approved --note "..."`. One venue can have several record ids; update all of them. `--status new` reopens a lead. |
| "One row per application" / "every column" | `--per-record` or `--full` with a `.csv` file name (raw, wide layout for troubleshooting). |
| "Show me the email" / "resend today's email" | Preview: `uv run licmon email --preview ~/Desktop/email-preview` (writes files, sends nothing). Send: only after the owner says yes, `uv run licmon email` with the SMTP variables set (skill `email-setup`). |
| "Nothing came in today?" | An empty list is normal on quiet days. Check `uv run licmon status`: if every source says `success`, it is working. |
| "Is it working?" | `uv run licmon status` (last run per source, queue size by day). Also `gh run list --workflow daily-collect -L 5`. |
| "Run it now" | `gh workflow run daily-collect`, wait ~10 s, then `gh run watch --exit-status $(gh run list --workflow daily-collect -L 1 --json databaseId -q ".[0].databaseId")`. This also sends the email if it is set up. |
| "Pause it" / "turn it back on" | `gh workflow disable daily-collect` / `gh workflow enable daily-collect` |
| "Only show Houston / only tier A" | Export, then filter the file (skill `export-leads`), or query the `daily_leads` view with SQL (`review_queue` is one row per application). |
| "Change who gets the email" | Ask first, then `gh secret set LEADS_EMAIL_TO --env production` (comma-separated addresses, typed at the prompt, not echoed). |

The owner sells event ticketing (Speakeasy), so the tier is the kind of venue:
**A** = nightclubs and lounges, **B** = obvious bars and event venues (tavern,
pub, taproom, brewery, comedy, live music, event center), **C** = restaurants.
Coffee shops, bakeries, dessert shops and national chains are dropped. The
business name decides most of it, because licenses rarely tell a bar from a
restaurant. Rules live in
`src/licmon/qualify.py`; target metros in `src/licmon/metros.py`.

## The daily email

After collecting, the workflow runs `licmon email`. It sends one short message
to `LEADS_EMAIL_TO`: how many new leads by priority and market, whether every
source ran, and the day's leads as an Excel attachment. The email body holds no
lead details; they are only in the attachment. It sends even on a day with no
leads (no attachment then), so a missing email means something is wrong.

The owner's own Google Workspace account sends the email to himself:
`SMTP_USERNAME` and `LEADS_EMAIL_TO` are both his work address (already set as
secrets; never write the address into this public repo), and `SMTP_PASSWORD`
is an app password he makes on his Google account.

The spreadsheet (`src/licmon/leadsheet.py`) has one row per venue: priority,
business name, company, business type, filing (new application, change of
owner...), status, filed-on date, phone and owner/applicant names (Washington
publishes these), address, market, mailing address (California, Florida),
license, a map-search link to find the phone and website by hand, the official
record link, and the Lead ID. Contact details come only from the official
records. Automatic lookups on other sites are out of scope (PRD).

Settings live in the GitHub `production` environment:

| Name | Kind | Value |
|---|---|---|
| `SMTP_USERNAME` | secret | the sending Gmail/Workspace address (Dylan's own) |
| `SMTP_PASSWORD` | secret | a Gmail **app password** (16 letters), not the normal password |
| `LEADS_EMAIL_TO` | secret | who receives it (comma-separated) |
| `LEADS_EMAIL_FROM` | secret, optional | defaults to `SMTP_USERNAME` |
| `SMTP_HOST` | variable, optional | default `smtp.gmail.com` |
| `SMTP_PORT` | variable, optional | default `587` (use `465` for SSL-only providers) |

If `SMTP_PASSWORD` or `LEADS_EMAIL_TO` is missing, the email step skips itself
and the run stays green. Setup steps are in the `email-setup` skill.

## If something breaks

- **Red run / failure email from GitHub.** Open the run log
  (`gh run view <id> --log`). Each source logs one result line; a failed one
  says `FAILED` with the error type (no record data; details stay in the DB):
  `SELECT source, started_at, error_type, error_detail FROM source_runs WHERE status='failed' ORDER BY started_at DESC LIMIT 5;`
  One broken source does not stop the others. See skill `fix-broken-source`.
- **The daily email did not arrive.** Check the run's "Email the owner" step.
  `email failed (SMTPAuthenticationError)` means the app password is wrong or
  was revoked: make a new one and reset `SMTP_PASSWORD`. Check spam once.
- **A source changed its format** (error `SourceSanityError` or a parse error).
  Fetch it with `uv run licmon probe --source <name>`, compare to the parser in
  `src/licmon/sources/<file>.py`, fix it, add or update the test fixture
  (synthetic data only, never real rows), run the tests, commit.
- **STORAGE ALARM in the log.** Neon Free stops saving new data at 512 MB. The
  run turns red at 400 MB. First keep fewer days of raw downloads:
  `gh variable set RAW_RETENTION_DAYS --body 7` (default 14;
  old ones are trimmed on the next run). If that is not enough, tell the owner
  the Neon plan needs an upgrade. Check size with
  `SELECT pg_size_pretty(pg_database_size(current_database()));`
- **Daily runs stopped.** GitHub disables schedules in public repos after 60
  days with no commits. The workflow's `keepalive` job prevents this by pushing
  an empty commit after 45 quiet days. If it happened anyway:
  `gh workflow enable daily-collect`.
- **After changing rules** in `src/licmon/qualify.py` or `src/licmon/metros.py`,
  run `uv run licmon requalify` so stored records get the new scores. Past
  daily queues are not rewritten; the change shows from the next run on.

## Handover checklist (do once, right after the repo moves to the owner)

Follow skill `handover-checklist`. In short:

1. `gh secret list --env production` must show `DATABASE_URL`. If it is
   missing, recreate it without echoing:
   `neon cs production --project-id tiny-truth-43995411 --ssl require | gh secret set DATABASE_URL --env production`
2. Make the owner the person who gets failure emails: GitHub sends scheduled
   run failures to whoever last enabled the workflow. Run
   `gh workflow disable daily-collect && gh workflow enable daily-collect` while
   signed in as the owner.
3. Set up the daily email (skill `email-setup`).
4. Run it once (see "Run it now") and confirm every source says `ok` and the
   email arrived.
5. Optional, recommended: make the repo private
   (`gh repo edit --visibility private --accept-visibility-change-consequences`).
   A ~2 minute daily job fits easily in GitHub Free's 2,000 private minutes a
   month, the 60-day schedule rule no longer applies, and run logs stop being
   public.

## Developing

Tests need a disposable Postgres (never the real database):

```bash
docker run -d --rm --name licmon-test-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=licmon_test -p 127.0.0.1:55432:5432 postgres:16-alpine
TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/licmon_test uv run pytest -q
```

To add a state or city, follow skill `add-source` (also "Adding a source" in
`README.md`): one new file in `src/licmon/sources/`, register it, add metro
counties, add a synthetic test. CI runs the tests on pushes to `main` and on
pull requests. The manual `probe-sources` workflow checks that GitHub can reach
and parse every source without touching the database.

Optional secret `SOCRATA_APP_TOKEN` (free, from data.ny.gov / data.texas.gov
/ data.cityofchicago.org developer settings) raises open-data rate limits. Not
needed at current volumes.

## Skills (`.claude/skills/<name>/SKILL.md`)

| Skill | Use when the owner asks to |
|---|---|
| `connect-database` | do anything that reads or writes leads (load `DATABASE_URL` safely) |
| `export-leads` | see leads, get a spreadsheet, filter by metro/tier/day |
| `review-leads` | mark leads approved, rejected, contacted, snoozed or new |
| `check-health` | know if it is working, or why nothing came in |
| `run-now` | run the collection right now |
| `pause-resume` | pause or restart the daily run |
| `email-setup` | set up, change, preview or test the daily email |
| `fix-broken-source` | fix a red run or a source that changed format |
| `add-source` | add a new state or city |
| `tune-tiers` | change what counts as a lead, the tiers or the target metros |
| `storage-alarm` | handle the STORAGE ALARM / database size |
| `handover-checklist` | finish the one-time setup after the repo transfer |
| `package-for-client` | build the zip to hand this project to someone |
