---
name: review-leads
description: Mark leads as approved, rejected, contacted, snoozed or back to new, with an optional note. Use when the owner says "mark these as ...", "I called this one", "not interested", or "reopen".
---

# Record the owner's review decisions

1. Load the database (skill `connect-database`).
2. Get the record ids from the `Lead ID` column of the spreadsheet
   (space-separated). One venue can have several ids; update all of them.
   If the owner names a venue instead, find its ids:

   ```sql
   SELECT record_ids, legal_name, dba, address, queue_date
   FROM daily_leads
   WHERE dba ILIKE '%name%' OR legal_name ILIKE '%name%'
   ORDER BY queue_date DESC LIMIT 10;
   ```

   If several venues match, ask which one.
3. Update:

   ```bash
   uv run licmon review 1234 1235 --status approved --note "call next week"
   ```

   Statuses: `new` (reopen), `approved`, `rejected`, `contacted`, `snoozed`.
   `--note` is optional; without it the old note stays.
4. It prints `updated N record(s)`. N should equal the number of ids. If it
   says 0, the ids were wrong: look them up again.

Marking "contacted" only records what the owner did. This project never
contacts anyone.
