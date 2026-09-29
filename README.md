# Nightlife liquor-license lead monitor

Collects public liquor-license application records every day from official
sources, keeps the ones that look like new or changing bars, clubs, lounges,
restaurants and taprooms in major nightlife metros, and puts them in a review
queue. It emails the owner the day's list. It never contacts a business. See
`nightlife_liquor_license_monitor_prd.md`.

Owner: start with `ONBOARDING.md`. Coding agents: `AGENTS.md` is the operating
guide (`CLAUDE.md` imports it) and `.claude/skills/` holds a step-by-step
skill for each routine job.

**This repository is public. Lead data never goes in it.** Records, raw
snapshots, scores and review decisions live only in a private Postgres
database reached through the `DATABASE_URL` secret. Workflow logs print counts
per source, never names or addresses.

## Sources (one connector each, `src/licmon/sources/`)

| Source name | Official data | Kind |
|---|---|---|
| `ny_sla_pending` | NY SLA "Current SLA Pending Licenses", data.ny.gov `f8i8-k2gm` | full pending list, statewide |
| `tx_tabc_pending` | TABC "Pending Original ... Application(s)", data.texas.gov `mxm5-tdpj` | full pending list, statewide |
| `chicago_bacp_pending` | Chicago BACP "Liquor and Public Place of Amusement Applications" notice lists (liquor + amusement pages) | rolling ~6 weeks, earliest Chicago signal |
| `chicago_bacp_liquor` | Chicago "Business Licenses", data.cityofchicago.org `r5kz-chrr`, liquor/amusement codes, non-renewals | rolling 180 days |
| `wa_lcb_actions` | WSLCB "New License Applications, Approvals and Discontinuances", statewide report | rolling 30 days |
| `ca_abc_applications` | CA ABC Daily Data Export (CSV zip), application rows only | full list, statewide |
| `fl_abt_licenses` | FL DBPR ABT retail alcoholic beverage licensee extract `bd4006lic.csv` | full licensee list, statewide; leads are **newly issued** licenses (Florida publishes no pending list) |

The California HTML daily report is behind bot protection, so it is not used.
The official daily export carries the same applications. Per-record CA links
point at ABC's public license lookup page for a human to open.

## How a run works

1. `licmon run` fetches each source (retries with backoff, one polite client).
2. Raw bytes are saved gzip'd in `raw_snapshots` before any parsing, deduped
   by SHA-256. Bodies older than `RAW_RETENTION_DAYS` (default 14) are dropped,
   hashes and metadata kept; the latest successful snapshot per source is
   always kept.
3. Records are normalized to one shape and upserted by
   `(source, source_record_id)`. First seen, last seen and last changed are
   tracked. A change in status, name, DBA, address, license type, application
   type or application date is a *material change* and is recorded with the
   before/after values in `record_events`.
4. Pending-list sources mark records that drop off the list as removed.
   A parse below a source's `min_records` floor fails that source instead of
   marking everything removed.
5. `qualify.py` applies deterministic rules: target metro, license category,
   application type (new / relocation / ownership change beat renewals),
   name keywords, exclusion words. Each lead gets a score, a tier (A/B/C
   venue kind, defined in AGENTS.md) and a plain reason.
6. Qualified new or changed records are queued. A source's very first run is a
   silent baseline except for applications dated in the last 14 days.
7. A failing source is logged, stored with its traceback in `source_runs`, does
   not stop the others, and makes the workflow exit non-zero (red run + email).
8. `licmon email` sends the owner the day's `daily_leads`: counts by metro and
   priority, source health, and an Excel file of every lead (the body holds
   no lead details). It sends on empty days too (heartbeat) and skips itself when the SMTP
   secrets are not set. `licmon email --preview DIR` writes the message to
   files instead of sending.

## Review queue

* `daily_leads` view: one row per venue per day (several applications for the
  same premises are merged).
* `review_queue` view: one row per application.
* `records.review_status`: `new`, `approved`, `rejected`, `contacted`, `snoozed`.

On your own machine, with `DATABASE_URL` set:

```bash
uv run licmon status                       # last run per source, queue sizes
uv run licmon export --out today.xlsx      # today's leads (UTC date), clean sheet
uv run licmon export --all --open --out open.xlsx
uv run licmon review 123 456 --status approved --note "call next week"
uv run licmon email --preview ~/Desktop/email-preview   # see the daily email
uv run licmon requalify                    # after editing qualify.py / metros.py
```

Never run `export` inside GitHub Actions: its logs are public.

## The spreadsheet

`licmon export` builds one clean row per venue per day from the
`daily_leads` view: several applications for the same premises are merged
into one lead, and the Lead ID cell lists every record id. A file name ending
in `.xlsx` writes Excel, anything else writes the same clean sheet as CSV.

Columns: Priority, Business name, Company / owner, Business type, Filing,
Status, Filed on, Phone, Owner / applicant names, Address, City, State, ZIP,
Market, Mailing address, License applied for, Map, Google, Instagram,
Official record, Lead ID.

Contact details come only from the official records: Washington publishes a
phone number and applicant names, California and Florida publish a mailing
address. The Map, Google and Instagram columns are plain search links the
owner clicks by hand to find a phone number, website or social account.
Automatic lookups on other sites are out of scope (PRD).

## The daily email

After collecting, the workflow runs `licmon email`: one short counts-only
message (new leads by priority and market, whether every source ran) with
the day's spreadsheet attached. The body never holds lead details. It sends
even on days with no leads (no attachment then), so a missing email means
something is wrong. It skips itself when the email settings are missing and
the run stays green. Settings and troubleshooting live in AGENTS.md.

## Repo layout

```text
src/licmon/          pipeline, qualification, spreadsheet, email, CLI
src/licmon/sources/  one connector per official source
.github/workflows/  daily-collect (daily.yml), tests (ci.yml), probe (probe.yml)
tests/               deterministic tests with synthetic fixtures only
scripts/             package_for_client.sh builds the handover zip
.claude/skills/      step-by-step recipe per routine job (see AGENTS.md)
```

## Setup

1. Create a private Postgres database (any provider; free tiers are enough).
2. In the GitHub repo: Settings → Environments → `production` → add secret
   `DATABASE_URL`. Optional: `SOCRATA_APP_TOKEN` (raises open-data rate limits).
3. Email (optional): secrets `SMTP_USERNAME`, `SMTP_PASSWORD` (a Gmail app
   password), `LEADS_EMAIL_TO`, optional `LEADS_EMAIL_FROM`; variables
   `SMTP_HOST` / `SMTP_PORT` default to `smtp.gmail.com` / `587`.
4. Actions → `daily-collect` → Run workflow, once, to take the baseline.
5. It then runs daily at 15:30 UTC.

GitHub pauses scheduled workflows in public repos after 60 days without a
commit. The workflow's `keepalive` job pushes an empty commit after 45 quiet
days to prevent that. If it happens anyway, re-enable it from the Actions tab.

To hand the project over as a zip: `scripts/package_for_client.sh` (committed
files only, secrets and local state excluded).

## Development

```bash
uv sync
docker run -d --rm --name licmon-test-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=licmon_test -p 127.0.0.1:55432:5432 postgres:16-alpine
TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/licmon_test uv run pytest -q
uv run licmon probe          # live fetch + parse, no database, counts only
```

Tests use a throwaway Postgres in Docker (Docker Desktop on a Mac) plus
synthetic fixtures only. Never use the real database or commit real records.

### Adding a source

Write `src/licmon/sources/<name>.py` with a `Source` subclass (`fetch` returns
raw snapshots untouched, `parse` yields `Record`s with a `category`), register
it in `sources/__init__.py`, add metro counties/cities in `metros.py` if it is a
new state, and add a test with a synthetic fixture. Nothing else changes.
