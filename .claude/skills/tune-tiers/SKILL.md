---
name: tune-tiers
description: Change which filings count as leads, the tiers, the lead score weights, the Hot threshold, keywords, exclusions or target metros. Use when the owner says leads are too many, too few, the wrong kind, ranked wrong, too many or too few Hot, or wants a new city/metro in an existing state.
---

# Tune scoring, tiers and metros

Rules are deterministic word lists in two files:

- `src/licmon/qualify.py`: whether a filing qualifies (target metro,
  license category points, application type, routine renewals dropped) and
  which tier it gets. The owner sells event ticketing, so the tier is the
  venue kind, mostly from the business name: `NIGHTCLUB_WORDS` /
  `NIGHTCLUB_LICENSES` = A (nightclubs, lounges); `BAR_VENUE_WORDS` /
  `BAR_VENUE_LICENSES` = B (bars, event venues); everything else that
  qualifies = C (restaurants). `FOOD_BAR` and `RESTAURANT_WORDS` stop "sushi
  bar" or "bar & grill" from counting as bars. `DROP_WORDS` (coffee,
  bakery, dessert...) and `CHAINS` (national chains, matched at the start of
  the name) remove a lead. Scores add license-category points, filing points
  (`APPLICATION_TYPE_POINTS`), and tier bonus (A 60 / B 30 / C 0). Add a word
  to the right list to move leads. A Chicago PPA license on a bar or event
  name moves B to A (`PPA_NOT_NIGHTLIFE` keeps bowling alleys and theaters
  at B).
- **Lead score** (0 to 100, the Score column; ranks leads, does not decide
  whether something is a lead), also in `qualify.py`: `TIER_POINTS`
  (A 45 / B 25 / C 5), `NIGHTLIFE_LICENSE_POINTS` (highest one counts),
  `STAGE_POINTS` (Licensed 25 / Approved 20 / In review 10 / Received 5),
  `FILING_POINTS` (new or new location 10, change of owner 5). The How
  scoring works tab in the workbook is built from these, so it stays in
  step. Which license is "nightlife" and how a status maps to a stage live
  in each source's `nightlife_license` and `stage` methods
  (`src/licmon/sources/<file>.py`); Florida's 60-day window is
  `LICENSED_FRESH_DAYS` in `fl_abt.py`.
- **Hot** = tier A with a score of at least `HOT_MIN_SCORE` (default 75).
  To change it without code:
  `gh variable set HOT_MIN_SCORE --env production --body 80`. Attio's daily
  cap is `ATTIO_DAILY_CAP` the same way (default 25).
- `src/licmon/metros.py`: which counties (or cities) make up each metro.

Steps:

1. Read both files fully. Restate the owner's wish as a concrete rule and
   confirm it with them in one sentence if it is ambiguous.
2. Before changing, measure (skill `connect-database`), e.g. how many of the
   last 7 days' leads a new rule would add or drop:

   ```sql
   SELECT metro, tier, count(*) FROM daily_leads
   WHERE queue_date >= current_date - 7 GROUP BY 1, 2 ORDER BY 1, 2;
   -- score spread and how many are Hot
   SELECT tier, stage, lead_score, count(*), count(*) FILTER (WHERE hot) AS hot
   FROM daily_leads WHERE queue_date >= current_date - 7
   GROUP BY 1, 2, 3 ORDER BY 3 DESC;
   ```

3. Edit the rule. Add or update a case in `tests/test_rules.py` (tiers) or
   `tests/test_stage_score.py` (score, stage, Hot) that pins the new
   behavior (synthetic names only). Run the tests on the disposable
   database (AGENTS.md, "Developing").
4. Re-score stored records:

   ```bash
   uv run licmon requalify
   ```

   After changing `HOT_MIN_SCORE`, set the same value in this shell first
   (`export HOT_MIN_SCORE=80`) so stored records get the same Hot labels as
   the daily run. Past daily queues are not rewritten. The change shows from
   the next run.
5. Commit and push. Tell the owner what changed and roughly how many more or
   fewer leads to expect per day.
