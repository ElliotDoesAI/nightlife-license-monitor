---
name: tune-tiers
description: Change which filings count as leads, the tiers, the lead score weights, the Hot threshold, keywords, exclusions or target metros. Use when the owner says leads are too many, too few, the wrong kind, ranked wrong, too many or too few Hot, or wants a new city/metro in an existing state.
---

# Tune scoring, tiers and metros

Rules are deterministic word lists in two files:

- `src/licmon/qualify.py`: whether a filing qualifies (target metro,
  license category points, application type, routine renewals dropped) and
  which tier it gets. The owner sells event ticketing, table and VIP
  reservations and POS, so the tier is the venue kind, mostly from the
  business name (all in `venue_class`):
  - A (nightclubs, lounges and ticketed venues): `NIGHTCLUB_WORDS`,
    `TICKETED_WORDS` (comedy, stadium, arena, theater, concert, event
    center, rooftop, supper club...), a license key in `TICKETED_LICENSES`
    (nightclub, music venue, theater, sports venue, event center; each
    source sets these in `nightlife_license`), or `CONCESSIONAIRES` (Levy,
    Aramark, Delaware North...) with a ticketed word or
    `CONCESSION_VENUE_WORDS` (Field, Park, Center...) in the name.
  - B (bars and not-quite-ticketed venues): `BAR_VENUE_WORDS` /
    `BAR_VENUE_LICENSES`. `NOT_TICKETED` (cinema, movie, bowling, arcade,
    billiards...) keeps a name at B even with a ticketed word or license.
    A restaurant name (`RESTAURANT_WORDS`, `DROP_WORDS`) never reaches A:
    a lounge, ticketed word or ticketed license on it gives B.
  - C: everything else that qualifies (restaurants).
  `FOOD_BAR` stops "sushi bar" or "bar & grill" from counting as bars.
  `DROP_WORDS` (coffee, bakery, dessert...) and `CHAINS` (national chains,
  matched at the start of the name) remove a lead. Scores add
  license-category points, filing points (`APPLICATION_TYPE_POINTS`), and
  tier bonus (A 60 / B 30 / C 0). Add a word to the right list to move
  leads. A Chicago PPA license adds lead-score points but does not lift a
  bar to A. `ADULT_WORDS` (gentlemen's club, strip club, topless, bikini
  bar, adult cabaret...) sets the `adult` flag: tier and score stay, but it
  is never Hot, never sent to Attio and never named in Slack.
- **Lead score** (0 to 100, the Score column; ranks leads, does not decide
  whether something is a lead), also in `qualify.py`: `TIER_POINTS`
  (A 45 / B 25 / C 5), `NIGHTLIFE_LICENSE_POINTS` (highest one counts),
  `STAGE_POINTS` (Licensed 25 / Approved 20 / In review 10 / Received 5),
  `FILING_POINTS` (new or new location 10, change of owner 5), and the
  venue history change `SCORE_ADJUST` in `src/licmon/history.py` (New owner
  -10, Adding a permit -15; `RECENT_DAYS` is how long an ended license
  still counts, 730). After changing the history rules, run
  `uv run licmon requalify --history` (network). The How
  scoring works tab in the workbook is built from these, so it stays in
  step. Which license is "nightlife" and how a status maps to a stage live
  in each source's `nightlife_license` and `stage` methods
  (`src/licmon/sources/<file>.py`); Florida's 60-day window is
  `LICENSED_FRESH_DAYS` in `fl_abt.py`.
- **Hot** = tier A, not adult, with a score of at least `HOT_MIN_SCORE` (default 75).
  To change it without code:
  `gh variable set HOT_MIN_SCORE --env production --body 80`. Attio's daily
  cap is `ATTIO_DAILY_CAP` the same way (default 50), and the lowest score a
  B lead needs to go to Attio is `ATTIO_MIN_B_SCORE` (default 60).
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
   `tests/test_stage_score.py` (score, stage, Hot, per-source license keys)
   that pins the new behavior (synthetic names only). A new license key
   needs a line in `NIGHTLIFE_LICENSE_POINTS` (and `TICKETED_LICENSES` if it
   should make a venue A). Run the tests on the disposable
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
