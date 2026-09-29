---
name: handover-checklist
description: One-time setup after the repository is transferred to the owner, on the owner's Mac. Use on first launch, when the owner pastes the ONBOARDING.md prompt, or on a new computer.
---

# Handover checklist

The owner is Dylan, a non-developer on a Mac (macOS, zsh). Do one step at a
time. Tell him in plain words each time he must click, sign in or paste
something. Never ask for a password or connection string in chat.

1. **Tools.** Check `command -v git gh node npm uv claude`. Install what is
   missing with Homebrew (`brew install gh node uv`; git arrives with the
   Xcode Command Line Tools that Homebrew installs; Claude Code via
   `curl -fsSL https://claude.ai/install.sh | bash`, then reopen Terminal).
   Ask before any system-wide install. Then `uv sync` in the project folder.
2. **GitHub sign-in.** `gh auth status`; if needed `gh auth login`
   (GitHub.com, HTTPS, login with a web browser) and ask Dylan to click
   **Authorize**. Confirm the repo is his:
   `gh repo view --json nameWithOwner,visibility`. If the folder came as a
   zip, point it at his copy:
   `git remote set-url origin https://github.com/<owner>/nightlife-license-monitor.git`
   and `git fetch origin && git status` (should be up to date with
   `origin/main`).
3. **Neon.** Follow skill `connect-database` (`neon login`, `neon link`,
   load `DATABASE_URL`), then `uv run licmon status` (counts only).
4. **Secrets already set.** `gh secret list --env production` must show
   `DATABASE_URL`, `SMTP_USERNAME` and `LEADS_EMAIL_TO`. If `DATABASE_URL`
   is missing, set it without echoing:

   ```bash
   neon cs production --project-id tiny-truth-43995411 --ssl require | gh secret set DATABASE_URL --env production
   ```

   Never write the owner's email address into any repo file (public repo).
5. **Failure emails go to Dylan.** GitHub emails scheduled-run failures to
   whoever last enabled the workflow:

   ```bash
   gh workflow disable daily-collect && gh workflow enable daily-collect
   ```

6. **Daily email.** Follow skill `email-setup`. Only the `SMTP_PASSWORD`
   app password is left; Dylan adds it on GitHub's web page, never in chat.
7. **First run.** Follow skill `run-now`. Every source should log `ok` and
   the email step `email sent`. Ask Dylan to find the email (check spam
   once).
8. **Private repo (recommended, ask first).**

   ```bash
   gh repo edit --visibility private --accept-visibility-change-consequences
   ```

   Private: logs are no longer public and GitHub's 60-day schedule rule
   stops applying. The ~2 minute daily job fits in GitHub Free's 2,000
   private minutes a month.
9. **Today's leads.** Export to the Desktop and open it:

   ```bash
   uv run licmon export --out ~/Desktop/leads-$(date -u +%F).xlsx
   open ~/Desktop/leads-$(date -u +%F).xlsx
   ```

   Summarize counts by metro and tier. Do not paste the whole list into chat
   unless asked.

Finish by telling Dylan what is set up and that the email will arrive each
morning (the run is at 15:30 UTC).
