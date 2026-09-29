---
name: pause-resume
description: Pause or restart the daily scraper and email. Use when the owner says "pause it", "stop the emails for a while", "turn it back on", or when GitHub disabled the schedule.
---

# Pause or resume the daily run

Pause (no collection, no email):

```bash
gh workflow disable daily-collect
```

Resume:

```bash
gh workflow enable daily-collect
gh workflow view daily-collect | head -5    # confirm "active"
```

Notes:

- Enabling makes the signed-in GitHub user the one who gets failure emails.
  Run it while signed in as the owner (`gh auth status`).
- Pending lists catch up on the next run. Rolling lists (Chicago 180 days,
  Washington 30 days) lose anything older than their window, so a pause
  longer than 30 days can miss some Washington leads.
- To stop only the email but keep collecting, delete the recipient secret:
  `gh secret delete LEADS_EMAIL_TO --env production`. Ask the owner first.
- GitHub disables schedules on public repos after 60 days without commits.
  The workflow's `keepalive` job prevents that. If it happened, resume as
  above. Making the repo private removes this rule.
