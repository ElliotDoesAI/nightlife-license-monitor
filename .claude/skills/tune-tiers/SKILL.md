---
name: tune-tiers
description: Change which filings count as leads, the scoring and tiers, keywords, exclusions or target metros. Use when the owner says leads are too many, too few, the wrong kind, or wants a new city/metro in an existing state.
---

# Tune scoring, tiers and metros

Rules are deterministic and live in two files:

- `src/licmon/qualify.py`: points per license category, application type
  (new, relocation, ownership change beat renewals), name keywords (bar,
  lounge, pub...), exclusion words (market, gas, liquor store...), hard
  exclusions, and tier cut-offs (A >= 70, B 55-69, C 40-54, under 40 dropped).
- `src/licmon/metros.py`: which counties (or cities) make up each metro.

Steps:

1. Read both files fully. Restate the owner's wish as a concrete rule and
   confirm it with them in one sentence if it is ambiguous.
2. Before changing, measure (skill `connect-database`), e.g. how many of the
   last 7 days' leads a new rule would add or drop:

   ```sql
   SELECT metro, tier, count(*) FROM daily_leads
   WHERE queue_date >= current_date - 7 GROUP BY 1, 2 ORDER BY 1, 2;
   ```

3. Edit the rule. Add or update a case in `tests/test_rules.py` that pins the
   new behavior (synthetic names only). Run the tests on the disposable
   database (AGENTS.md, "Developing").
4. Re-score stored records:

   ```bash
   uv run licmon requalify
   ```

   Past daily queues are not rewritten. The change shows from the next run.
5. Commit and push. Tell the owner what changed and roughly how many more or
   fewer leads to expect per day.
