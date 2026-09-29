---
name: handover-checklist
description: One-time setup after the repository is transferred to the owner, on the owner's computer. Use on first launch, when the owner pastes the ONBOARDING.md prompt, or on a new computer.
---

# Handover checklist

Do one step at a time. Tell the owner in plain words when they must click,
sign in or paste something. Never ask for a password in chat.

1. **Tools.** Check `command -v git gh node npm uv`. Install what is missing
   with the official installer for the owner's OS (GitHub CLI from
   cli.github.com, Node LTS from nodejs.org, uv via
   `curl -LsSf https://astral.sh/uv/install.sh | sh`). Ask before any
   system-wide install. Then `uv sync`.
2. **GitHub sign-in.** `gh auth status`; if needed `gh auth login` (GitHub.com,
   HTTPS, login with a web browser). Confirm the repo is theirs:
   `gh repo view --json nameWithOwner,visibility`. If the folder came as a
   zip, point it at their copy:
   `git remote set-url origin https://github.com/<owner>/nightlife-license-monitor.git`
   and `git fetch origin && git status` (should be up to date with
   `origin/main`).
3. **Neon.** Skill `connect-database` (install, `neon login`, `neon link`,
   load `DATABASE_URL`, `uv run licmon status`).
4. **Database secret.** `gh secret list --env production` must show
   `DATABASE_URL`. If missing, set it without echoing:

   ```bash
   neon cs production --project-id tiny-truth-43995411 --ssl require | gh secret set DATABASE_URL --env production
   ```

5. **Failure emails go to the owner.** GitHub emails scheduled-run failures
   to whoever last enabled the workflow:

   ```bash
   gh workflow disable daily-collect && gh workflow enable daily-collect
   ```

6. **Daily email.** Skill `email-setup` (Gmail app password, sender,
   recipients).
7. **First run.** Skill `run-now`. Every source should log `ok` and the email
   step `email sent`. Ask the owner to find the email (check spam once).
8. **Private repo (recommended, ask first).**

   ```bash
   gh repo edit --visibility private --accept-visibility-change-consequences
   ```

   Private: logs are no longer public and GitHub's 60-day schedule rule stops
   applying. The ~2 minute daily job fits in GitHub Free's 2,000 private
   minutes a month.
9. **Today's leads.** Skill `export-leads` to the Desktop, then summarize
   counts by metro and tier.

Finish by telling the owner what is set up and that the email will arrive
each morning around 15:30 UTC.
