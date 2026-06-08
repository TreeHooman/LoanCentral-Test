# LoanCentral — Project Vision, Roadmap & Legal Boundaries

---

## What LoanCentral Is

LoanCentral is a **record-keeping and loan management platform** for a Reddit lending community.
It has two parts that work together:

1. **The Reddit Bot** — monitors a subreddit for loan-related commands and posts.
   Runs 24/7. Reads posts, generates Request IDs, comments loan history summaries.

2. **The Dashboard** — a private web app where lenders track their loans, mods
   manage the community, and borrowers see what they owe.

Both talk to the same PostgreSQL database. The bot writes records, the dashboard
reads and manages them. They are always in sync.

---

## What Has Already Been Built

### Bot (fully offline-tested, 48 tests passing)
- `$confirm` — lender confirms a loan via Reddit comment
- `$paid_with_id` — lender records a repayment
- `$repaid` / `$unpaid` / `$refunded` — status commands
- `$help` / `$stats` / `$health` / `$loan` — info commands
- `$dispute` — borrower flags an issue
- Full service layer (all business logic separated from Reddit parsing)
- Offline test harness (tests run with no Reddit API or live database)
- Integrity checker (detects bad loan states, mismatched user totals)

### Dashboard (Flask web app)
- Reddit OAuth login (identity only, no posting permissions)
- Dev login bypass for testing (disabled in production)
- Role-based access: Mod / Lender / Borrower
- **Mod Dashboard** — all loans, search/filter by status, unpaid review queue,
  loan request queue, role management
- **Lender Dashboard** — their loans, stats, due date tracking, notes, file
  attachments, + New Loan button
- **Borrower Dashboard** — what they owe, full loan history, health score
- Full REST API backing all dashboard features
- Modals for: record payment, mark unpaid, mark refunded, new loan, notes/attachments
- Notification badge on unpaid review button (live count, refreshes every 60s)

### Loan Request System
- Bot generates a Request ID (e.g. REQ-0042) when it sees a [REQ] post that
  passes checks, saves key details to database
- Lender enters REQ-0042 on dashboard → form auto-fills: borrower, amount,
  currency, repay amount, repay date, payment method, thread link
- Lender reviews and hits Confirm — loan goes live in the database
- Repay amount is mandatory before save (flagged if not in post)

---

## What the Full Loan Flow Looks Like

```
1. BORROWER POSTS ON REDDIT
   Title format: [REQ] ($150) (#City, State, USA) (Repay $200) (06/19)
   AutoMod + HiveBot do their checks first.

2. BOT COMMENTS AUTOMATICALLY
   "Loan Request ID: REQ-0042
    u/borrower's loan history:
    — 3 loans total, 3 repaid"
   Request saved to DB as status = open. No loan exists yet.

3. LENDER AND BORROWER NEGOTIATE ON REDDIT
   They settle terms in that thread. Bot stays out of it completely.

4. TERMS AGREED — LENDER OPENS DASHBOARD
   Clicks "+ New Loan"
   Types REQ-0042 → clicks Look Up
   Form auto-fills from the saved request.
   If repay amount was missing from the post → field is blank and required.
   Lender reviews everything → clicks Confirm Loan.
   Loan is now live in DB as status = confirmed.

5. REPAYMENT TRACKED ON DASHBOARD
   Borrower pays → lender clicks Paid → records amount.
   Partial payment → status moves to partially_repaid.
   Borrower goes silent → lender clicks Unpaid → goes to mod review queue.

6. MOD REVIEWS UNPAID LOANS
   Mod sees the flagged loan in Unpaid Review tab.
   Investigates the Reddit thread, messages involved parties.
   If confirmed ghosted or scammed → clicks Confirm & Ban.
   Mod manually issues the Reddit ban (automated later when API keys arrive).

7. REDDIT COMMANDS STILL WORK
   $confirm, $paid_with_id etc. still write to the same DB.
   Dashboard and bot are always in sync.
   Legacy users who prefer Reddit commands are fully supported.
```

---

## What to Build Next (Priority Order)

### 1. Borrower Profile Page
When a lender or mod clicks a borrower's username anywhere on the dashboard,
it opens a dedicated profile page showing:
- Total loans, repaid count, unpaid count
- Repayment rate percentage
- Full loan history table
- All lenders they have borrowed from
- How long they have been on the subreddit (account age if available)
- Any notes mods have added about this borrower

**Why:** Lenders want to vet borrowers quickly before funding. This replaces
manually searching Reddit.

---

### 2. CSV Export
A button on the lender dashboard that downloads their full loan history as a
.csv spreadsheet. Columns: Loan ID, Borrower, Amount, Currency, Repaid,
Remaining, Status, Date Created, Repay Date, Thread Link.

**Why:** Some lenders want their own records for tax purposes or personal
tracking. Replaces the spreadsheets they currently maintain manually.

---

### 3. Repayment Reminder Bot Comment (needs API keys)
When a loan is approaching its repay date (e.g. 3 days before), the bot
automatically comments on the original Reddit thread:
"Hey u/borrower, friendly reminder that your loan of $150 from u/lender is
due on 06/19. Please reach out to your lender to confirm repayment."

Configurable: how many days before due date the reminder fires.
Mods can disable per-loan from the dashboard.

**Why:** Reduces ghosting. A gentle automated nudge before a loan goes overdue
is much better than waiting for a lender to manually flag unpaid.

---

### 4. Reddit Flair Check on OAuth Login (needs API keys)
When a user logs in via Reddit OAuth, the bot checks their flair on the
subreddit. If they have the verified lender flair → role assigned as lender
automatically. Mods are checked against the subreddit mod list.

This means role assignment is automatic and tied directly to Reddit flair,
not manually managed.

**Why:** Removes the manual step of a mod assigning roles on the dashboard
after someone gets their flair. Login and role are handled in one step.

---

### 5. Auto-Ban on Mod Confirm (needs API keys)
When a mod clicks Confirm & Ban in the Unpaid Review queue, the bot
automatically issues the Reddit ban on the subreddit.
Currently this is a manual step (mod has to go to Reddit and ban separately).

**Why:** Reduces the chance of a mod forgetting to issue the ban after
confirming in the dashboard. One click does both.

---

### 6. Lender Verification Application Flow
A lender-in-waiting fills out a form on the dashboard (or Reddit post).
Mods review the application and approve or deny from the mod dashboard.
On approval → role updated to lender + flair assigned via Reddit API.

**Why:** Currently flair is assigned manually by mods on Reddit. This gives
mods a proper queue and paper trail for who applied and when.

---

### 7. Dashboard Loan Feed (for mods)
A live feed on the mod dashboard showing recent activity:
loans funded, loans repaid, loans flagged unpaid — in reverse chronological
order, like a timeline. Refreshes automatically every 30 seconds.

**Why:** Gives mods situational awareness of the subreddit's lending activity
without having to filter through individual tables.

---

## Legal Boundaries — What LoanCentral Can and Cannot Do

### What LoanCentral IS (legal, no license needed)
- A **record-keeping tool** that logs loan agreements two parties already made
- A **community management tool** that helps mods track unpaid loans and issue bans
- A **tracking dashboard** that replaces spreadsheets
- An **information tool** that shows a borrower's loan history on request

LoanCentral is the equivalent of a shared Google Sheet that tracks loans.
The sheet is not a lender. It does not participate in the transaction.

### What LoanCentral is NOT and must NEVER become
- A **lending marketplace** — do not show open borrower requests to lenders
  as a browsable list that lenders pick from. That is matchmaking and requires
  a financial license in most jurisdictions.
- A **credit bureau** — do not sell or share loan history data with third parties.
- A **lender** — do not hold funds, move money, or take a percentage of loans.
- A **debt collector** — do not send legal threats, contact employers, or do
  anything beyond community bans for non-repayment.
- A **regulated financial platform** — do not advertise APR, approve or deny
  applications, or set interest rate limits.

### The Grey Areas to Watch
- **Repay amount tracking** — you store repay amount and loan amount, which
  means you are implicitly tracking interest. This is fine as a record but
  you must never calculate or suggest an interest rate to users.
- **Health score** — a borrower's health score based on repayment history is
  fine for community moderation. Do not present it as a credit score or use
  it to approve/deny access to lenders.
- **Predatory loans** — you will see loans where the repay amount is much
  higher than the amount borrowed. You are allowed to track these. You are
  not endorsing them. Add a disclaimer (see below).

### Required Disclaimer
Display this somewhere visible on the dashboard (footer or login page):

"LoanCentral is a record-keeping tool only. We do not facilitate, approve,
endorse, or participate in any loans. All lending agreements are made
independently between Reddit users. LoanCentral has no involvement in the
terms, repayment, or enforcement of any loan."

### Reddit-Specific Rules
- Bot must only use the OAuth scopes it needs (identity for login,
  read + submit for bot actions). Never request more permissions than needed.
- Bot must not post faster than Reddit's rate limits (1 request per 2 seconds
  for most endpoints, 60 requests per minute).
- Bot must identify itself in the user agent string.
- Do not scrape Reddit at scale. Only fetch posts the bot is actively
  processing.
- Test all bot changes against a private test subreddit before touching
  the live subreddit.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot | Python, PRAW (Reddit API wrapper) |
| Dashboard | Python, Flask |
| Database | PostgreSQL |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| Auth | Reddit OAuth2 (identity scope only) |
| Testing | Python unittest, offline fake DB/Reddit |
| Dev server | run_dev.py (Flask dev mode) |
| Hosting | TBD (currently local) |

---

## Rules for Development

1. Never run the bot against production Reddit credentials during development.
2. Never run tests against the production database.
3. Keep all .env files out of Git (they are in .gitignore).
4. Test all command logic offline before any Reddit API usage.
5. Use a test Reddit account and test subreddit only after offline tests pass.
6. Keep rollback possible before any production deployment.
7. The bot is tested at server downtime only — never during live subreddit hours.
