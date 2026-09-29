---
name: add-source
description: Add a new state or city liquor-license source to the scraper. Use when the owner asks to cover a new state, city or metro.
---

# Add a source

Only official government data. No logins, CAPTCHAs or bot-protected pages,
and never disguise the scraper as a person. If the only access is blocked,
tell the owner and suggest a public-records request instead.

1. Research: find the agency's open data (Socrata/CKAN API, CSV/ZIP export,
   or a plain public HTML report). Prefer a list of **pending** applications.
   Note refresh schedule, fields, and whether it is a full list (removals
   mean something) or a rolling window. Check `robots.txt`.
2. Copy the closest existing connector as a template:
   - Socrata API: `src/licmon/sources/tx_tabc.py` (+ `socrata.py`)
   - CSV inside a ZIP: `ca_abc.py`
   - plain CSV: `fl_abt.py`
   - HTML report: `wa_lcb.py` or `chicago_pending.py`
3. New file `src/licmon/sources/<name>.py` with a `Source` subclass:
   `name` (never rename once live), `title`, `state`, `homepage`,
   `tracks_removals` (True for full lists, False for rolling windows),
   `min_records` (about half the normal count), and `material_fields` if the
   source repeats rows in different shapes. `fetch` returns raw bytes
   untouched; `parse` yields `Record`s with a `category` from
   `models.CATEGORIES` (map each license type deliberately).
   For the lead score, also override `stage(rec)` (map this source's status
   wording to Licensed / Approved / In review / Received; unmapped wording
   falls back to `stage.from_status`), `nightlife_license(rec)` (return keys
   of `qualify.NIGHTLIFE_LICENSE_POINTS`, such as `late_hours`, for the
   state's nightlife license types; add a new key there only if the state
   has a genuinely new kind) and, if old records would look new,
   `stage_counts(rec, today)` (see `fl_abt.py`). Both read normalized fields
   only, never `rec.raw`, because `licmon requalify` has no raw rows. The
   shared points table does not change per state.
4. Register it in `src/licmon/sources/__init__.py` and bump the source count
   in the registry test (`tests/test_socrata_sources.py`).
5. New state: add its metros and counties to `METRO_COUNTIES` in
   `src/licmon/metros.py`. Make sure the parser's county names match.
6. Test with a synthetic fixture (fake names/addresses) in `tests/fixtures/`
   and `tests/test_<name>.py`, no network. Add the new source's stage and
   nightlife-license cases to `tests/test_stage_score.py`. Run the full suite on the
   disposable database (AGENTS.md, "Developing").
7. `uv run licmon probe --source <name>`: record count, how many in target
   metros, category mix. Sanity-check a few parsed records against the
   official site yourself (do not paste them anywhere public).
8. Update the sources table in `README.md`. Commit, push, check CI
   (`gh run list --workflow ci -L 1`), then run the `probe-sources` workflow
   (`gh workflow run probe-sources`) and skill `run-now` for the new source.

The first run is a silent baseline: only applications dated in the last 14
days are queued. After that, every new or changed qualifying record is.
