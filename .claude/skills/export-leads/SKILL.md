---
name: export-leads
description: Give the owner a spreadsheet of leads (today, a given day, all open, or filtered by metro/tier). Use when the owner asks to see leads, get a spreadsheet, or only certain cities or tiers.
---

# Export leads to a spreadsheet

Leads never go into the repo or GitHub logs. Write files to the owner's
Desktop (or another folder outside the repo) only.

1. Load the database (skill `connect-database`).
2. Pick the command. Dates are UTC; the daily run lands at 15:30 UTC.

   | Owner wants | Command |
   |---|---|
   | today's leads | `uv run licmon export --out ~/Desktop/leads-$(date -u +%F).xlsx` |
   | a certain day | `uv run licmon export --date 2026-10-01 --out ~/Desktop/leads-2026-10-01.xlsx` |
   | everything not yet reviewed | `uv run licmon export --all --open --out ~/Desktop/open-leads.xlsx` |
   | every lead ever queued | `uv run licmon export --all --out ~/Desktop/all-leads.xlsx` |
   | plain CSV instead of Excel | end the file name in `.csv` |
   | raw wide columns (troubleshooting) | `--full` or `--per-record` with a `.csv` name (CSV only) |

   The Excel file has one clean row per venue: Priority, Business name,
   Company / owner, Business type, Filing, Status, Filed on, Phone,
   Owner / applicant names, Address, City, State, ZIP, Market, Mailing
   address, License applied for, Map, Google and Instagram search links,
   Official record link, Lead ID. Frozen header, filters on, Priority
   colored (A green, B amber, C gray).

   If `~/Desktop` does not exist, use the home folder and say where it is.
   Open the result with `open <file>`.
3. The command prints the row count. Summarize for the owner: total, plus
   counts by market and priority. Do not paste the whole list into chat
   unless asked.
4. Filters (market, priority, state, date range): load rows with
   `licmon.leadsheet.load_rows(conn, day, open_only)`, filter them in a
   short Python snippet, and write them with
   `licmon.leadsheet.build_xlsx(rows)` so the clean layout stays. Or query
   the view:

   ```sql
   SELECT tier, legal_name, dba, address, city, metro, license_descriptions,
          qualify_reason, source_url, record_ids
   FROM daily_leads
   WHERE metro = 'Houston' AND tier = 'A'
     AND queue_date >= current_date - 7
   ORDER BY queue_date DESC, score DESC;
   ```

   Run SQL with `uv run python -c` and psycopg, or `psql "$DATABASE_URL"` if
   psql is installed. Write results to a file outside the repo.

Columns worth explaining: Priority (A strongest), Filing (new application,
change of owner, new location...), Map / Google / Instagram (search links to
find the phone and website by hand), Lead ID (use with skill
`review-leads`). Phone and owner names only appear where the state publishes
them (Washington); mailing addresses for California and Florida.

An empty file on a quiet day is normal. Check with skill `check-health`.
