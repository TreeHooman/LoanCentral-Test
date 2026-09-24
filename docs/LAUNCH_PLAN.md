# LoanCentral 2.0 — Launch Plan (Reddit → code → the sub)

The technical steps are in [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) (the
"checklist"). This plan puts them in order with everything that happens **on
r/loancentral**: what to tell people, when, and the ready-to-post text.

**Launch date:** ______ (pick a quiet weekday morning/afternoon, not a Friday
night: if something goes wrong you want the next day free.)
**Launch window:** about 1 hour, done by you at the bot computer.

---

## The shape of it

| When | On Reddit | In the code / systems |
|---|---|---|
| **T-7 days** | Heads-up post (draft A), sticky it | Checklist "Before launch day" A–G done; lawyer has the Terms/Privacy |
| **T-3 days** | Mods briefed (draft E); lender flair locked down (checklist E) | Old bot still running as normal |
| **T-1 day** | Reminder comment on the heads-up post | Rehearse once more on this computer (optional) |
| **Launch, 0:00** | Maintenance post (draft B) + sub **Restricted** | Stop old bot → dump its DB |
| **0:10** | — | Load into Neon, rename typo, roles, Legacy (checklist 3–5) |
| **0:25** | — | Start bot + task; Render `REDDIT_SYNC_IN_DASHBOARD=true` (checklist 6, 8) |
| **0:30** | Private test thread (checklist 7) | Smoke test: `!login`, `!loan`/`!confirm`, `!fund`, `!paid_with_id`, dashboard |
| **0:50** | Sub back to Public; launch post (draft C), sticky it + FAQ comment (draft D); sidebar/wiki updated | Watch logs |
| **T+1 day** | Answer questions in the launch post | Check `--status`, sync failures, Neon usage |
| **T+7 days** | Unsticky the heads-up post; keep the launch post pinned for a month | Review "Known and left for after launch" |

---

## Before launch

### T-7: tell people it's coming

Post **draft A** and sticky it. The main points: a date, a short pause on the
day, and what to do about sign-in (nothing yet).

### T-3: get the mods and the subreddit ready

- **Brief the mods** (draft E), including how to answer the common questions.
- **Lender flair** (checklist E): mod-only template, users can't type their own
  flair. This matters more now: *the lender flair is what lets someone use lender
  commands.*
- **Bot account u/loancentral** stays a moderator with **flair** and **posts**
  permissions (it sets FUNDED / REPAID flair and edits its own comments).
- Prepare the **new sidebar / wiki text** (draft F) so it's a paste on the day.
- **Removed commands:** `$dispute` and `$mods` are gone in 2.0. Disputes and
  questions go to **modmail** or **loancentral08@gmail.com**. Update any wiki
  page or AutoModerator rule that mentions them.

### T-1: reminder

A short comment on the heads-up post: "Tomorrow at [time], about an hour of
maintenance." Optional: one more rehearsal on this computer.

---

## Launch day

### 0:00 — Pause the sub (Reddit)

1. Post **draft B** (maintenance notice) and sticky it.
2. Mod Tools → **Settings → Privacy & safety → Community type → Restricted**
   (people can still read and comment, only approved users can post).

**Why the pause matters:** the new bot only answers comments made *after* it
starts. Anything posted while neither bot is running is never processed. Draft
B asks people to hold their commands, and that is why the window is short.

### 0:00–0:50 — The switch (code)

Follow the checklist, launch day steps 1–8:

1. Stop the old bot (**first**, so two bots never answer the same post).
2. Dump its database on the bot computer.
3. Load into Neon: `python scripts/load_main_db.py backups\main_launch.dump --apply --target-host <Neon host>`
   (rehearsed on the June data: about 2 seconds, 551 loans / 166 users, all counts match).
4. Check `https://loancentral.net/health`.
5. Give roles (your admin account: `embarrassed-throat42`, two r's), set your
   admin key, grant Legacy (checklist 5: `bootstrap_roles.py --set-admin-key`).
6. Bot computer `.env`: `SUBREDDITS=loancentral`, Neon details,
   `REDDIT_SYNC_IN_BOT=true`. Install the bot task
   (`scripts\install_bot_task.ps1`), then check `python scripts\run_bot_forever.py --status`.
7. Render: `REDDIT_SYNC_IN_DASHBOARD=true`, and the four `REDDIT_…` values set to
   u/loancentral's login. Add the 30-minute backup sync task (checklist 8).

### 0:30 — Test it in the sub, still Restricted

Make a test post (you're approved, so you can post) with a second account of
yours as the borrower. Small amounts. Check each one gets the right reply:

- [ ] `!help` → command list
- [ ] `!login` → DM with a link → **create account → Sign in with Google** works
- [ ] `[REQ]` post → bot replies once with a request code
- [ ] `!fund REQ-XXXX` (from the lender account, with lender flair) → funded reply, post flair FUNDED within seconds
- [ ] `!loan 10 USD u/<borrower>` → offer; `!confirm` from the borrower → confirmed reply
- [ ] `!paid_with_id <id> 5 USD` then `!paid_with_id <id> 5 USD` again → both recorded (the second one used to be dropped)
- [ ] Dashboard: record a loan and mark it repaid → REPAID shows on Reddit within seconds
- [ ] `!logi u/<lender>` → shows the rank (e.g. Gold / Legacy)
- [ ] A lender's flair updates to "Verified Lender · <rank>" after their next repaid loan

Then mark the test loans **Refunded** on the dashboard (nothing is deleted;
refunded loans don't count toward anyone's history).

**If something fails and you can't fix it in ~15 minutes: roll back** (checklist
"If it goes wrong"). The old bot's database was never touched, so going back is
just starting the old bot again.

### 0:50 — Go live (Reddit)

1. Community type back to **Public**.
2. Remove the maintenance sticky. Post **draft C** and sticky it.
3. Add **draft D** as the first comment on it, and **distinguish + sticky** that
   comment.
4. Paste **draft F** into the sidebar and the wiki's commands page.

---

## After launch

**Day 1**
- Answer questions in the launch post. Most will be "how do I sign in?"
  (point to `!login`) and "why didn't the bot answer?" (usually a comment made
  during the pause: repost it).
- `python scripts\run_bot_forever.py --status` on the bot computer → running, healthy.
- `python scripts\reddit_sync_worker.py --failures` → anything that didn't reach Reddit.
- UptimeRobot shows loancentral.net up.

**Week 1**
- Neon dashboard → compute usage well under 100 hours/month.
- Collect the dashboard issues you and lenders find; fix them in batches.
- Unsticky the heads-up post.

**Old threads:** `[REQ]` posts made **before** launch have no request code (the
old bot didn't create them). For those, lenders use `!loan <amount> <currency>
u/<borrower>` and the borrower replies `!confirm`, the same as before. Draft D
says this.

---

## Drafts (Reddit markdown, ready to paste)

Replace `[date]` / `[time]` before posting. Times: say the timezone.

### Draft A: heads-up (T-7), sticky

> **Title:** LoanCentral 2.0 is coming on [date]
>
> Hi everyone,
>
> On **[date] at [time]** we're switching LoanCentral over to a new version of
> the bot and a new website: **https://loancentral.net**. The subreddit will be
> paused for about an hour while we move everything across.
>
> **What stays the same**
> - Every loan on record comes with us: history, repayments, unpaid marks.
> - Requests and loans still happen here on Reddit.
>
> **What's new**
> - **Your own dashboard** at loancentral.net: borrowers see their history and
>   what they owe; lenders see and manage every loan they've made.
> - **Sign in with your Reddit name:** comment `!login` and the bot DMs you a
>   link to set up your account (you'll connect a Google account to sign in).
> - **Ranks** for lenders and borrowers based on repaid loans: Iron, Bronze,
>   Silver, Gold, Platinum, Diamond.
> - Commands work with `!` as well as `$` (`!fund` = `$fund`).
>
> **What you need to do now:** nothing. Keep using the sub as normal until the
> switch. On the day, please don't post commands during the pause: the bot
> won't see them.
>
> Questions: reply here, modmail us, or email loancentral08@gmail.com.

### Draft B: maintenance notice (launch day), sticky

> **Title:** Maintenance now: LoanCentral 2.0 switch (about 1 hour)
>
> We're moving LoanCentral to its new version right now. For about an hour:
> - **New posts are paused.**
> - **Please don't post bot commands**: nothing is running to answer them,
>   and they won't be picked up afterwards. Post them again once we're back.
>
> Nothing on record is affected. We'll post here when it's done.

### Draft C: launch post (go-live), sticky

> **Title:** LoanCentral 2.0 is live: your dashboard, ranks, and how to sign in
>
> We're back, and every loan on record has come across.
>
> **1. Set up your account (borrowers and lenders)**
> 1. Comment `!login` on any post here.
> 2. Open the link the bot sends to your Reddit inbox (it works once, for 30 minutes).
> 3. Connect your Google account. From then on, sign in at
>    **https://loancentral.net** with Google.
> Lost access? Comment `!login` again.
>
> **2. Commands**
> *Everyone:* `!login` · `!stats u/name` · `!logi u/name` (a lender's record and rank) · `!help`
> *Lenders (Verified Lender flair):* `!fund REQ-XXXX` · `!loan 100 USD u/name` · `!paid_with_id ID 50 USD` · `!unpaid ID` · `!refunded ID`
> *Borrowers:* `!confirm` (accept a loan offer once you've received the money)
> `$` still works too.
>
> **3. Ranks**
> Your rank grows with repaid loans. Lenders: Bronze 25, Silver 50, Gold 100,
> Platinum 200, Diamond 500. Borrowers: Bronze 5, Silver 10, Gold 20, Platinum 40,
> Diamond 75. Lenders' flair shows their rank, and some of our founding lenders
> carry **Legacy**.
>
> **4. On the website**
> Borrowers: your history, what you owe, and due dates. Lenders: every loan
> you've made (from Reddit and the dashboard), payments, and what's due or unpaid.
> Loans recorded on the website show as FUNDED / REPAID here within seconds.
>
> **Gone:** `$dispute` and `$mods`. If a loan on your record is wrong, or you
> need a mod, send **modmail** or email **loancentral08@gmail.com**.
>
> LoanCentral keeps records only. It doesn't lend, hold or send money.
> [Terms](https://loancentral.net/terms) · [Privacy](https://loancentral.net/privacy)

### Draft D: pinned FAQ comment (on the launch post)

> **Quick answers**
>
> - **The bot didn't answer my command.** If you posted it during the
>   maintenance pause, post it again. Otherwise check the spelling (`!help`
>   lists them), and that lender commands come from an account with the
>   Verified Lender flair.
> - **I didn't get the `!login` message.** Check Reddit's chat *and* messages.
>   Links last 30 minutes. You can ask for up to 3 per hour.
> - **A request from before the switch has no REQ code.** Use
>   `!loan <amount> <currency> u/<borrower>`, and the borrower replies `!confirm`.
> - **My rank looks wrong.** Ranks count *repaid* loans under your Reddit name.
>   If some of your loans were recorded under a misspelled name, modmail us and
>   we'll merge them.
> - **Something's wrong with a loan on my record.** Modmail, or
>   loancentral08@gmail.com, with the loan ID.

### Draft E: mod briefing (modmail / mod chat, T-3)

> 2.0 goes live on [date] at [time]. What changes for us:
> - Mods and admins sign in at loancentral.net (same `!login` → Google as
>   everyone; your mod role is set in the database, not by flair).
> - **Lender flair now grants lender commands.** Only mods should ever assign
>   it. Removing it removes their lender commands.
> - `$dispute` and `$mods` are gone: disputes come to modmail. Check the loan on
>   the dashboard (Admin → Lenders / Search), and use the loan's history there.
> - Legacy Lender (founders) is granted from the dashboard: Admin → Lenders →
>   the lender → Grant Legacy Lender.
> - Common questions and answers are in the pinned FAQ comment on the launch post.

### Draft F: sidebar / wiki commands (paste into sidebar + wiki)

> **LoanCentral: https://loancentral.net**
> Your loan history, what you owe, and your rank.
>
> **New here?** Comment `!login` on any post. The bot DMs you a link to set up
> your account.
>
> **Commands** (`!` or `$`)
> - Everyone: `!login` · `!stats u/name` · `!logi u/name` · `!help`
> - Lenders (Verified Lender flair): `!fund REQ-XXXX` · `!loan 100 USD u/name` ·
>   `!paid_with_id ID 50 USD` · `!unpaid ID` · `!refunded ID`
> - Borrowers: `!confirm`
>
> Problems with a loan: modmail or loancentral08@gmail.com.
> LoanCentral keeps records only. It doesn't lend, hold or send money.

---

## Decisions still open

- [ ] Launch date and time.
- [ ] Ranks in lenders' flair: automatic from day one for lenders who already
      have the lender flair (it changes after their next repaid loan, or when
      Legacy is granted). Draft C mentions it. If you'd rather hold it back,
      say so before launch and I'll add a switch for it.
- [ ] Render Starter plan ($7/mo) later, if the free plan ever feels slow.
- [ ] Google sign-in end-to-end test before launch (kept for later).
- [ ] Logo (kept for later).
