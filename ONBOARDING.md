# Getting started

This folder is your nightlife lead finder. Every morning it reads public
liquor-license filings from official government websites and picks out the
ones that look like new or changing bars, clubs, lounges, restaurants and
taprooms in big nightlife cities. Then it emails you the list.

It already runs by itself on GitHub every day at 15:30 UTC (10:30 in Chicago,
8:30 in Los Angeles). You do not have to leave a computer on. Your leads are
kept in your own private Neon database.

You never need to type code. Claude Code does the technical steps. This page
tells you what to click and what to paste.

## What you need

1. A GitHub account (free). GitHub is where the daily job runs.
2. Your Neon account (the one this project already uses). Neon holds the
   leads.
3. Claude Code on your computer.
4. Your Google (Gmail) work email. The daily email is sent from your own
   address to yourself, so no one else's account is involved.

## Step 1: Accept the project on GitHub

You will get an email from GitHub about a repository transfer called
`nightlife-license-monitor`. Open it and click **Accept**. The project now
belongs to your GitHub account.

## Step 2: Put the folder on your computer

Unzip the folder you were sent into a place you will remember, like your
Documents folder. Keep the name `nightlife-license-monitor`.

## Step 3: Start Claude Code in the folder

Open a terminal in that folder and start Claude Code. Then paste this:

```
This folder is my liquor-license lead scraper. Read AGENTS.md and ONBOARDING.md first.
I'm not a developer, so explain things simply and do the technical steps for me.
Do the "handover-checklist" skill one step at a time, including the daily email setup,
and tell me each time I need to click, sign in or paste something.
When it's done, show me today's leads as a spreadsheet on my Desktop.
```

Claude Code will install a few free tools and ask you to sign in to GitHub and
to Neon in your browser. Each sign-in opens a page with a button like
**Authorize**. Click it.

## Step 4: Make a Gmail app password for the daily email

Google does not let programs use your normal password. You make a special
16-letter "app password" that only this project uses.

1. Go to myaccount.google.com and click **Security**. Make sure
   **2-Step Verification** is turned on. If it is off, turn it on first.
2. Go to myaccount.google.com/apppasswords.
3. In **App name**, type `Nightlife leads` and click **Create**.
4. Google shows a 16-letter code. Copy it.
5. When Claude Code asks for it, paste it into the **terminal prompt** it
   gives you, not into the chat. The code is hidden as you paste. That is
   normal.

If Google says app passwords are not available, your account is probably a
company account where the admin turned them off. Use a personal Gmail as the
sender instead, or ask your admin.

You can cancel the app password at any time on the same page. The email then
stops until you make a new one.

## Step 5: Check the first email

Claude Code will run the job once. A few minutes later you get an email with
the subject "Nightlife leads for ...". Check your spam folder the first time.
If it landed there, mark it "Not spam".

## Every day after that

The email arrives each morning. It is short: how many new leads came in,
how many are top priority, and which cities they are in. The leads themselves
are in the attached Excel file, one row per business, with the business name,
company, type of business, filing date, status, address, any phone number or
owner names the state publishes, and a "Map" link that opens the business on
Google Maps so you can find its phone and website. The email comes even on
quiet days, so if a morning email is missing, something needs a look.

To work with leads, open Claude Code in this folder and ask in plain words.
For example:

- "Show me today's leads as a spreadsheet."
- "Show me every lead I haven't reviewed yet."
- "Mark leads 1234 and 1235 as contacted." (The numbers are in the
  `Lead ID` column.)
- "Is the scraper working?"
- "Only show me Houston tier A leads from this week."
- "Pause the scraper." / "Turn it back on."
- "Send the daily email to my partner too."

Priority: **A** is nightclubs and lounges. **B** is obvious bars and event
venues, like taverns, pubs, taprooms, comedy clubs and event centers. **C** is
restaurants. Coffee shops, bakeries and big chains are left out. Start with
the A rows (green). If a lead is in the wrong tier, tell Claude Code; it can
adjust the rules.

## Good to know

- Nothing in this project ever contacts a business. The leads are only for
  you to review.
- Florida only publishes licenses after they are approved, so Florida leads
  are "newly licensed" and arrive a few weeks later than the other states.
- California leads have no filing date in the state's data. The date shown is
  the day the scraper first saw them, at most a day late.
- The free Neon plan holds a long time of data. If it ever gets close to full,
  the daily run turns red and Claude Code knows what to do.
- The GitHub project is public unless you make it private. Lead data is never
  stored there, only in your private database. Claude Code will offer to make
  it private during setup. That is recommended.
