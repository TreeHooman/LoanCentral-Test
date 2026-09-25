# LoanCentral 2.0 — Launch Plan (Reddit → code → the sub)

The technical steps are in [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) (the
"checklist"). This plan puts them in order with everything that happens **on
r/loancentral**: what to tell people, when, and the ready-to-post text.

**Launch date:** ______ (pick a quiet weekday morning/afternoon, not a Friday
night: if something goes wrong you want the next day free.)
**Launch window:** about 1 hour, done by you at the bot computer.

---

## Owner's notes for launch day (2026-09-25)

- **The newest database is on the hosted PC** (the bot computer). It must be
  brought over and loaded into Neon *before* anything goes live (checklist
  steps 2-3). The June copy in `data/imports/` is only for rehearsals.
- **Merge the misspellings of the owner's name** into **embarrassed-throat42
  (two r's)**: `embarassed-throat42` and `embarrassedthroat-42`. Required
  (checklist step 5).
- Mods: **u/left-associate3911**, **u/logistix1**; owner is admin. Legacy
  Lender: the same three.
- Post and pin **draft G** (the permanent "How LoanCentral works" guide).
- Restyle the subreddit (banner, colours, icon, sidebar widgets) with Claude
  guiding. Two ways to do it (owner picks; option 1 is the simplest):
  1. **Claude watches, you click.** With permission, Claude takes screenshots
     of your screen (computer use), sees where you are and tells you exactly
     what to click next. On the browser this is view-only: Claude can see it
     but not click it.
  2. **Claude clicks in your Chrome.** With the Claude in Chrome extension,
     Claude works in your own Chrome, where you're already logged into Reddit.
     It shows each change and waits for your OK before saving anything, since
     it changes a public page.
  Have the subreddit's mod tools open when starting. Use the new logo files
  (`api/static/img/logo-mark.png`, `logo-full.png`) and the site green
  `#2fdb5e` on black so the sub matches loancentral.net.

### Still to do before launch day

1. Test Google sign-in once on loancentral.net.
2. Do the flair test: set your flair to `Verified Lender · Gold`, check it sticks, then set it back.
3. Pick the launch date and time.
4. Post the heads-up 7 days before, brief the mods 3 days before, and post the reminder 1 day before.

## Reddit rules and API limits (checked 2026-09-25)

**What the code already does**
- Every Reddit request goes through one limiter: 80 per minute locally (Reddit
  allows 100 per minute per app, averaged over 10 minutes), and it also reads
  Reddit's own "requests left" counter and pauses before it runs out. The
  bot and the website share the same app, and both read that counter.
- The bot refuses to start with a placeholder user agent (Reddit throttles
  or blocks those).
- The bot touches the database only when a command or [REQ] post comes in, so
  Neon can sleep between; the website's /ping (UptimeRobot) never touches it.
- From [REQ] posts only the amount, currency, payment method and dates are
  kept, not the post text or location.
- New 2026-09-25: at most 10 bot commands per person per minute
  (`BOT_USER_COMMANDS_PER_MINUTE`), on top of ignoring exact double posts, so
  one account spamming `!stats u/...` can't hold up the bot for everyone.

**To do (owner), before launch**
1. **Register u/loancentral as an app with Reddit to get the [App] label.**
   Since 31 March 2026 Reddit tags approved automated accounts with [App] and
   may make unregistered accounts that behave like bots prove they're human,
   which would stop the bot. Apply through r/redditdev / Reddit's developer
   profile.
2. **Check the bot's API app is approved under the Responsible Builder
   Policy** (every app now needs approval; non-commercial moderator bots are
   free under 100 requests/min). Look at reddit.com/prefs/apps with the bot
   account; if Reddit has asked for a developer registration, complete it.
   LoanCentral is free and non-commercial: never sell or share Reddit data.
3. **Keep u/loancentral a moderator** of r/loancentral. Mods skip the
   subreddit's comment rate limits, which is what lets the bot answer every
   post and command without "you're doing that too much".

**Things to watch in the first week**
- **!login rush at launch.** Every `!login` sends a Reddit message. If Reddit
  says "doing that too much", the bot waits up to 5 minutes and retries, and
  commands queue up behind it. Expected to be brief; the supervisor only steps
  in after 15 minutes of silence.
- **Neon compute** (100 CU-hours/month on the free plan, suspends when used
  up). Estimate for this sub's activity: roughly 40-70 per month. Check the
  Neon dashboard on day 3 and day 7; if it's heading past ~80, move the sync
  worker from every 30 min to hourly, or upgrade Neon.
- **Render free plan**: 750 hours/month covers one always-on service (~730).
  Don't add a second free service to the same workspace.
- **Deleted posts/accounts**: Reddit asks apps to drop content users delete.
  LoanCentral keeps loan records (names, amounts, dates, thread links), not
  post text, which the Privacy Policy covers. If someone asks to be removed,
  handle it by email/modmail.

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
5. Post **draft G** (the permanent how-to guide), sticky it in slot 1, and link it from the sidebar.

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

### Draft G: "How LoanCentral works" guide (pin permanently)

Draft C announces 2.0 and comes down after a week or two. This one stays
pinned for good: it's where new people learn how the sub and the bot work.
Post it from the mod account, sticky it (slot 1), and link it in the sidebar.

> **Title:** How LoanCentral works: borrowing, lending and the bot (start here)
>
> LoanCentral keeps a public record of every loan made here. The bot,
> u/loancentral, writes each loan down and tracks it until it's repaid.
> **LoanCentral doesn't lend, hold or send money.** Lenders and borrowers deal
> with each other directly; we keep the record.
>
> Every command works with `!` or `$`.
>
> ---
>
> **Your account (everyone)**
>
> 1. Comment `!login` on any post here.
> 2. The bot sends you a link in your Reddit messages (it works once, for 30 minutes).
> 3. Connect your Google account. From then on, sign in at **https://loancentral.net** with Google.
>
> Lost your Google account? Comment `!login` again and connect a new one.
>
> ---
>
> **Borrowing**
>
> 1. Make a post whose title starts with **[REQ]**, for example:
>    `[REQ] ($150) (Toronto, ON, Canada) (Repay $180) (06/19) (PayPal)`
> 2. The bot replies with your loan history and a request code like **REQ-4F2K9Q**.
> 3. When a lender funds you, the bot records it and your post is marked **FUNDED**.
>    If the lender offers with `!loan` instead, reply **`!confirm`** once you've received the money.
> 4. See what you owe and when it's due at loancentral.net.
>
> ---
>
> **Lending** (needs the **Verified Lender** flair)
>
> To lend here, your Reddit account must meet the sub's requirements, including
> **at least 500 karma**. Ask the mods about the Verified Lender flair.
>
> - `!fund REQ-XXXX`: fund a request (the amount and currency come from the request)
> - `!loan 100 USD u/name`: offer a loan without a request code; the borrower replies `!confirm`
> - `!paid_with_id ID 50 USD`: record a repayment (the loan ID is in the bot's reply)
> - `!unpaid ID`: mark a loan unpaid
> - `!refunded ID`: cancel a loan
>
> Everything you record here also shows on your lender dashboard, and anything
> you record on the dashboard shows here as FUNDED / REPAID within seconds.
>
> ---
>
> **Checking someone out (everyone)**
>
> - `!logi u/name`: a lender's record and rank
> - `!stats u/name`: a Reddit account's age and activity
> - `!help`: every command
>
> ---
>
> **Ranks**
>
> Ranks grow with repaid loans.
>
> | Rank | Lender (repaid loans) | Borrower (repaid loans) |
> |---|---|---|
> | Iron | 1 | 1 |
> | Bronze | 25 | 5 |
> | Silver | 50 | 10 |
> | Gold | 100 | 20 |
> | Platinum | 200 | 40 |
> | Diamond | 500 | 75 |
>
> Lenders' flair shows their rank (for example "Verified Lender · Gold").
> **Legacy** marks our founding lenders.
>
> ---
>
> **Problems**
>
> A loan on your record is wrong, or you need a mod: send **modmail**, or email
> **loancentral08@gmail.com** with the loan ID.
>
> [Terms](https://loancentral.net/terms) · [Privacy](https://loancentral.net/privacy)

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
