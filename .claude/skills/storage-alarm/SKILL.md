---
name: storage-alarm
description: Handle the STORAGE ALARM or a growing database. Use when a run log says STORAGE ALARM, the run is red with no failed source, or the owner asks how full the database is.
---

# Database size and the storage alarm

Neon Free stops saving new data at 512 MB. The daily run turns red at 400 MB
(`STORAGE_ALARM_MB`) so there is time to act. Raw downloads are the main
growth; they are kept `RAW_RETENTION_DAYS` days (default 14).

1. Size (skill `connect-database`):

   ```sql
   SELECT pg_size_pretty(pg_database_size(current_database()));
   SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_catalog.pg_statio_user_tables
   ORDER BY pg_total_relation_size(relid) DESC LIMIT 5;
   ```

2. First fix, free and safe: keep fewer days of raw downloads.

   ```bash
   gh variable set RAW_RETENTION_DAYS --body 7
   ```

   The next run trims older ones (the latest good download per source is
   always kept). Check the size again after that run. Postgres may not hand
   space back at once; that is normal.
3. Still above ~400 MB: tell the owner the Neon plan needs an upgrade (a
   paid plan). Do not upgrade, delete records or drop tables without the
   owner's explicit OK.
4. Do not raise `STORAGE_ALARM_MB` above 450 on the free plan.
