# LoanCentral Next Feature Priorities

## Request-Code Funding Release Candidate

Status: implemented locally; not deployed. Last verification: 2026-09-08,
620 Python tests passed and desktop/mobile browser checks passed.

- Done: Reddit request replies include a request code and dashboard link.
- Done: code lookup fills the borrower, principal, currency, payment method,
  and thread; the lender reviews repayment terms before recording funding.
- Done: verified lender authorization, duplicate-funding protection, linked
  request/loan records, and transaction-level funding audit.
- Done: isolated offline demo with fake accounts and a new SQLite database.
- Confirmed: lenders record and update loans; borrowers do not confirm or approve
  the request-code funding action. Update the pinned procedure at launch.
- Pending: test and support the title formats actually used in the community.
- Pending: guarded EU staging, real login/account linking, PostgreSQL tests,
  backup restore drill, and deployment of the tested candidate.

See [feature behavior](REQUEST_CODE_FLOW.md),
[release plan](REQUEST_CODE_RELEASE.md), and
[community recovery discussion](COMMUNITY_RECOVERY.md).

## Near-Term Dashboard

- Done: mobile polish pass on lender, borrower, profile, and mod pages with phone-width checks.
- Done: reminder queue foundation for overdue, due today, due in 1-3 days, and missing due dates.
- Done: borrower active-loan checklist includes due date, amount owed, payment method, thread, and acknowledge status.
- Done: user profile improvements with repayment timeline, active loans, unpaid history, and shared lender/borrower context.
- CSV export filters by status/date range.
- Done: mod activity feed tab with auto-refresh while open.
- Pending: mod activity filters for funded, repaid, unpaid, disputed, banned, and notes.

## Bot And Reddit API-Safe Work

- Done: scheduled reminder dry-run job foundation that batches reminder checks without Reddit calls.
- Done: Reddit action queue for reminders, flair sync, and mod-confirmed bans without live Reddit calls.
- Pending: live test-subreddit reminder delivery after the shared-account staging setup is verified.
- Lender DM when a due date passes, with strict cooldowns.
- Bot confirmation comment after dashboard funding, only when a Reddit thread exists.
- Bot congratulations comment after full repayment, with opt-out/cooldown controls.
- `$extend` workflow for borrower extension requests and lender approval.
- Graceful handling for deleted/removed posts and missing authors in every command path.

## Trust And Moderation

- Done: dashboard lender verification application flow with mod approve/deny.
- Pending: Reddit flair update after lender verification approval, test-subreddit first.
- Done: approved lender verification queues a future Reddit flair sync action.
- Private mod notes and visible audit trail for every sensitive change.
- Ban log with issuer, reason, timestamp, and confirmation state.
- Manual loan correction flow with mandatory reason.
- Dispute workflow: borrower dispute, lender response, mod decision, audit note.

## Legal Guardrails

- Keep LoanCentral as a record-keeping and reputation tool.
- Do not show open borrower requests as a browsable lender marketplace.
- Keep funding decisions and negotiations on Reddit between users.
- Do not process payments or touch user funds.
- Keep public profile data factual: counts, statuses, dates, totals, verification state.

## Infrastructure

- Staging in LoanCentral EU using the existing bot account, separate test data,
  and distinct monitoring lists; exact subreddit and bot host still to confirm.
- Migration dry-run script for existing database upgrades.
- Deployment checklist with rollback steps.
- Structured app logs for API requests, bot actions, errors, and reminder jobs.
- Rate limits for dashboard APIs and Reddit action cooldowns.

## Live Reddit Switches

- Keep `REMINDER_REDDIT_ENABLED` unset/false until dry-run output is reviewed.
- Use a private test subreddit before any production Reddit comments or DMs.
- Keep auto-ban disabled until mod review flow is verified against test accounts.
- Keep Reddit flair sync disabled until OAuth/flair permissions are tested.
- Review queued Reddit actions in the mod dashboard before enabling any sender.
