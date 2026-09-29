---
name: email-setup
description: Set up, change, preview or test the daily lead email (Gmail app password, sender, recipients). Use when the owner asks about the daily email, wants to change who gets it, wants to see what it looks like, or the email stopped arriving.
---

# Daily email: set up, preview, test

The daily run calls `licmon email` after collecting. It emails the owner's
own address(es) only, never a business. Ask the owner before any real send
and before changing recipients.

## Preview (sends nothing)

```bash
# needs skill connect-database first
uv run licmon email --preview ~/Desktop/email-preview            # today (UTC)
uv run licmon email --preview ~/Desktop/email-preview --date 2026-10-01
```

This writes `preview.html` (open it in a browser), `preview.txt`, the Excel
attachment and `message.eml` to that folder. Never write previews inside the
repo.

## Set up with Gmail

1. The owner makes an app password (ONBOARDING.md, step 4). It needs 2-Step
   Verification on the Google account, then
   myaccount.google.com/apppasswords.
2. The owner's own work address (Google Workspace) sends to itself, so it is
   both sender and recipient. These two secrets were set before handover;
   check with `gh secret list --env production`. Addresses are fine to say in
   chat but never write them into repo files (the repo may be public). The app
   password is never said in chat. If Google says app passwords are unavailable, the Workspace admin
   (probably Dylan) must allow 2-Step Verification for the account first.
3. Set the non-password values:

   ```bash
   gh secret set SMTP_USERNAME --env production --body "owner@company.com"
   gh secret set LEADS_EMAIL_TO --env production --body "owner@company.com"
   # optional, only if different from SMTP_USERNAME:
   gh secret set LEADS_EMAIL_FROM --env production --body "sender@gmail.com"
   ```

   Gmail needs no host or port settings (defaults: `smtp.gmail.com`, `587`).
   Another provider: `gh variable set SMTP_HOST --env production --body smtp.example.com`
   and `gh variable set SMTP_PORT --env production --body 465` if it only
   supports SSL.
4. The password: the owner adds it on GitHub in the browser, so it never
   passes through chat or a shell. Give these steps:
   repository page → **Settings** → **Environments** → **production** →
   **Add environment secret** → Name `SMTP_PASSWORD` → paste the 16-letter
   code (spaces are fine) → **Add secret**.
   Get the page URL with `gh repo view --json url -q .url` and append
   `/settings/environments`.
5. Check: `gh secret list --env production` shows `DATABASE_URL`,
   `SMTP_USERNAME`, `SMTP_PASSWORD`, `LEADS_EMAIL_TO` (values are never shown).

## Test send

With the owner's OK, run skill `run-now`. The log's "Email the owner" step
should say `email sent`. Ask the owner to check the inbox and spam folder.

## Troubleshooting

| Log says | Meaning / fix |
|---|---|
| `email skipped (not configured)` | `SMTP_PASSWORD` or `LEADS_EMAIL_TO` missing. Redo steps 3-4. |
| `email failed (SMTPAuthenticationError)` | Wrong or revoked app password, or `SMTP_USERNAME` is not the account that made it. Make a new app password and replace `SMTP_PASSWORD`. |
| `email failed (TimeoutError)` / connection errors | Host or port wrong. Gmail: unset `SMTP_HOST`/`SMTP_PORT` variables. |
| `email sent` but nothing arrived | Spam folder; or a typo in `LEADS_EMAIL_TO` (re-set it). |

Stop the email but keep collecting: `gh secret delete LEADS_EMAIL_TO --env production`
(ask first).
