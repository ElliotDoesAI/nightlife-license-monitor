---
name: attio-sync
description: Set up the Attio "License Leads" list on Targets once, or push the day's Hot and A leads into Attio (dry run first). Use when the owner asks about Attio, wants leads in the CRM, asks what would go to Attio, or the "Sync to Attio" step failed.
---

# Attio: the License Leads list

The daily run calls `licmon attio-sync --write` after the email. It sends
only the day's **Hot and A** venues to Attio. Attio is the owner's internal
CRM: nothing here contacts a business. Ask the owner before any `--write`.

## How it fits in Attio

- Each venue is a record in the team's existing **Targets** object
  (`target_client`).
- It is also added to a list named **License Leads** (`license_leads`) that
  sits on Targets. All the lead details live on the list entry: Venue key,
  Priority, Score, Stage, Market, State, Address, Owner / company, Phone,
  License, Filing type, Filed on, First seen, Official record, Map, Google,
  Instagram (links are text: Attio has no link type), and the team's Status
  (New, Moved to Targets, Not a fit, Contacted).
- The Targets object itself is never changed: no fields are added to it.

Why a list and not its own object: the Attio plan is at its object limit
(`attio-setup` failed with `quota_exceeded` when it tried to make one).

## What the daily sync does

For each Hot and A venue, highest score first:

1. **Already in the list** (same Venue key): only its Stage, Score and
   Priority are updated. The team's Status is never touched.
2. **Not in the list yet:** if Targets already has a record with the same
   name (upper and lower case ignored), that record is reused. Otherwise a
   new Target is made with only three fields: the name, client type
   **Venue**, and status **Prespecting** (Attio's own spelling, not a typo
   to fix). Before the first new Target it checks those options still exist
   in Attio.
3. The venue is added to the list with all its details and Status **New**.

At most `ATTIO_DAILY_CAP` new Targets a day (default 25). Reused Targets and
updates do not count. Venues over the limit are skipped and stay in the
spreadsheet; Slack says how many. Logs show counts only.

## The API key

`ATTIO_API_KEY` is in `~/.env` on the owner's Mac. Load it without printing
it. The key needs these scopes (Attio, Workspace settings, Developers, the
integration, Scopes):

| Scope | Why |
|---|---|
| `list_entry:read-write` | add and update License Leads entries |
| `list_configuration:read` | read the list during sync |
| `record_permission:read-write` | find Targets by name and create new ones |
| `object_configuration:read` | read the Targets fields and options |
| `list_configuration:read-write` | only for the one-time `attio-setup` |

If `attio-setup --write` fails with `HTTP 403`, the key cannot create lists.
The owner makes one that can (same Developers page) and you load it as
`ATTIO_WRITE_API_KEY`, which wins over `ATTIO_API_KEY`.

```bash
set -a; source <(grep -E '^ATTIO_(WRITE_)?API_KEY=' ~/.env); set +a
```

## One-time setup (ask first)

```bash
uv run licmon attio-setup           # dry run: lists what it would create, changes nothing
uv run licmon attio-setup --write   # creates the list (owner's OK first)
```

It only creates new things: the list, its fields and their options. If
"License Leads" already exists it stops and changes nothing. It never adds
anything to Targets. The list is open to the whole workspace
(`full-access`) so the team can see it.

Then update `~/speakeasy-attio-crm/SCHEMA.md`: change the "Planned: License
Leads" section from "not yet created" to created, with the date.

## Daily sync

Needs skill `connect-database` first.

```bash
uv run licmon attio-sync                       # dry run, today (UTC): counts only
uv run licmon attio-sync --date 2026-10-01     # dry run for another day
uv run licmon attio-sync --write               # real write (owner's OK first)
```

With a key loaded, the dry run asks Attio (read only) which venues are
already in the list and which names already exist in Targets, so the counts
are exact. Run it twice to show the owner nothing is duplicated: the second
run adds 0 and updates the rest.

## Put the key on GitHub (ask first)

Pipe it from `~/.env` so it is never shown or typed into chat:

```bash
grep -E '^ATTIO_API_KEY=' ~/.env | cut -d= -f2- | tr -d '"' | gh secret set ATTIO_API_KEY --env production
gh variable set ATTIO_DAILY_CAP --env production --body 25        # optional
gh variable set ATTIO_LEADS_URL --env production --body "<License Leads list URL from the browser>"  # optional, Slack links to it
```

## Troubleshooting

Errors show the HTTP number and Attio's reason word, never lead details.

| Log says | Meaning / fix |
|---|---|
| `attio sync skipped (not configured)` | `ATTIO_API_KEY` secret missing. Set it as above. |
| `attio failed (HTTP 401 ...)` | Wrong or revoked key. Replace the secret. |
| `attio failed (HTTP 403 ...)` | The key lacks a scope in the table above. `billing_error` on setup means the plan does not allow that list access setting. |
| `attio failed (HTTP 400 quota_exceeded)` | The Attio plan is at a limit. Tell the owner; it needs a plan change or a cleanup in Attio. |
| `list license_leads not found; run licmon attio-setup` | Setup never ran. Do the one-time setup. |
| `list license_leads already exists` | Setup already ran. Nothing to do. If a setup stopped halfway, check the list's fields in Attio against the list above and add any missing one there by hand (ask the owner first). |
| `attio option Prespecting missing on target_client.status` (or `Venue` on `client_type`) | Someone renamed that option in Attio. Ask the owner which option new venues should get, then update `TARGET_STATUS` or `TARGET_TYPE` in `src/licmon/attio.py`. |
| `attio failed (HTTP 400 ...)` otherwise | A value Attio rejected, often a Stage or Priority option renamed in the list. Check the options match the list above. |
