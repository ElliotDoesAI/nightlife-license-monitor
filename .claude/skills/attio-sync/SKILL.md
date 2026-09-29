---
name: attio-sync
description: Set up the Attio "License Leads" object once, or push the day's Hot and A leads into Attio (dry run first). Use when the owner asks about Attio, wants leads in the CRM, asks what would go to Attio, or the "Sync to Attio" step failed.
---

# Attio: License Leads

The daily run calls `licmon attio-sync --write` after the email. It sends
only the day's **Hot and A** venues to a separate Attio object named
"License Leads" (api slug `license_leads`), so the rest of the CRM stays
clean. Attio is the owner's internal CRM: nothing here contacts a business.
Ask the owner before any `--write`.

## What it does

- Matches on the unique **Venue key**, so the same venue is never created
  twice. A venue that comes back gets its stage, score and details updated.
- Sets the team's **Status** field (New, Moved to Targets, Not a fit,
  Contacted) to New on create only. It never overwrites Status afterwards.
- Creates at most `ATTIO_DAILY_CAP` new records a day (default 25), highest
  score first. The rest stay in the spreadsheet and Slack says how many.
- Logs counts only: candidates, created, updated, over the daily cap.

## The API key

`ATTIO_API_KEY` is in `~/.env` on the owner's Mac. Load it without printing
it. The key needs these scopes (Attio → Workspace settings → Developers →
the integration → Scopes):

| Scope | Why |
|---|---|
| `record_permission:read-write` | create and update License Leads records |
| `object_configuration:read` | read the object and its attributes during sync |
| `object_configuration:read-write` | only for the one-time `attio-setup` |

If `attio-setup --write` fails with `HTTP 403`, the key cannot change the
workspace schema. The owner makes one that can (same Developers page) and
you load it as `ATTIO_WRITE_API_KEY`, which wins over `ATTIO_API_KEY`.

```bash
set -a; source <(grep -E '^ATTIO_(WRITE_)?API_KEY=' ~/.env); set +a
```

## One-time setup (ask first)

```bash
uv run licmon attio-setup           # dry run: lists the object and attributes, changes nothing
uv run licmon attio-setup --write   # creates them (owner's OK first)
```

It only creates new things. If "License Leads" already exists it stops and
changes nothing. It never touches any other object. Attributes: Venue,
Venue key (unique), Priority (Hot, A), Score, Stage (Licensed, Approved, In
review, Received), Market, State, Address, Owner / company, Phone, License,
Filing type, Filed on, First seen, Official record, Map, Google, Instagram
(links are text: Attio has no link type), and Status.

Then update `~/speakeasy-attio-crm/SCHEMA.md`: change the License Leads
section from "not yet created" to created, with the date.

## Daily sync

Needs skill `connect-database` first.

```bash
uv run licmon attio-sync                       # dry run, today (UTC): counts only
uv run licmon attio-sync --date 2026-10-01     # dry run for another day
uv run licmon attio-sync --write               # real write (owner's OK first)
```

With a key loaded, the dry run asks Attio (read only) which venues already
exist, so "would create" and "updated" are exact. Run it twice to show the
owner nothing is duplicated: the second run creates 0.

## Put the key on GitHub (ask first)

Pipe it from `~/.env` so it is never shown or typed into chat:

```bash
grep -E '^ATTIO_API_KEY=' ~/.env | cut -d= -f2- | tr -d '"' | gh secret set ATTIO_API_KEY --env production
gh variable set ATTIO_DAILY_CAP --env production --body 25        # optional
gh variable set ATTIO_LEADS_URL --env production --body "<License Leads page URL from the browser>"  # optional, Slack links to it
```

## Troubleshooting

| Log says | Meaning / fix |
|---|---|
| `attio sync skipped (not configured)` | `ATTIO_API_KEY` secret missing. Set it as above. |
| `attio failed (HTTP 401)` | Wrong or revoked key. Replace the secret. |
| `attio failed (HTTP 403)` | The key lacks a scope in the table above. |
| `object license_leads not found; run licmon attio-setup` | Setup never ran. Do the one-time setup. |
| `attio failed (HTTP 400)` | A value Attio rejected, often a Stage or Priority option that was renamed in Attio. Check the options match the list above. |
